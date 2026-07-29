from __future__ import annotations

import asyncio
import json
import logging
import os
from uuid import uuid4

from sqlalchemy import and_, bindparam, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, object_session

from ..models.auth_session import AuthSession
from ..models.base import utcnow
from ..models.user import User
from ..schemas.user import (
    UserCreateRequest,
    UserListResponse,
    UserPasswordResetRequest,
    UserPublic,
    UserRoleUpdateRequest,
    UserUpdateRequest,
)
from ..core.security import hash_password
from .audit_service import compose_audit_detail, describe_changed_fields, summarize_values, write_audit_log
from .legacy_authz_service import (
    UserAuthorization,
    get_user_authorization,
    is_user_enabled,
    normalize_user_status,
)
from .push_service import publish_topic, publish_to_user
from .ws_manager import ws_connection_manager

logger = logging.getLogger(__name__)


def _user_with_rbac_stmt():
    return select(User)


def list_users(
    db: Session,
    *,
    limit: int,
    offset: int,
    keyword: str | None = None,
    status: str | None = None,
) -> UserListResponse:
    conditions = []
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        conditions.append(
            or_(
                User.id.ilike(like),
                User.email.ilike(like),
                User.username.ilike(like),
            )
        )
    normalized_status = (status or "").strip().lower()
    if normalized_status in {"active", "enabled"}:
        conditions.append(User.status.in_(["active", "ACTIVE", "ENABLED"]))
    elif normalized_status == "disabled":
        conditions.append(User.status.in_(["disabled", "DISABLED", "INACTIVE"]))

    total_stmt = select(func.count()).select_from(User)
    if conditions:
        total_stmt = total_stmt.where(*conditions)
    total = db.scalar(total_stmt) or 0

    stmt = _user_with_rbac_stmt().order_by(User.created_at.desc())
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.offset(offset).limit(limit)
    users = db.execute(stmt).unique().scalars().all()
    return UserListResponse(items=[serialize_user(user) for user in users], total=total)


def get_user_by_id(db: Session, user_id: str) -> User | None:
    stmt = _user_with_rbac_stmt().where(User.id == user_id)
    return db.execute(stmt).unique().scalar_one_or_none()


def get_user_by_email(db: Session, email: str) -> User | None:
    stmt = _user_with_rbac_stmt().where(User.email == email)
    return db.execute(stmt).unique().scalar_one_or_none()


def get_user_by_username(db: Session, username: str) -> User | None:
    stmt = _user_with_rbac_stmt().where(User.username == username)
    return db.execute(stmt).unique().scalar_one_or_none()


class UserCreateError(Exception):
    pass


class UserDuplicateError(UserCreateError):
    pass


class UserRoleAssignmentError(UserCreateError):
    pass


def create_user(
    db: Session,
    payload: UserCreateRequest,
    *,
    actor_user_id: str | None,
) -> UserPublic:
    user_id = payload.user_id.strip()

    # Build conditions for duplicate check
    conditions = [User.id == user_id, User.username == payload.username]
    if payload.email:
        conditions.append(User.email == payload.email.lower())

    duplicate = db.scalar(
        select(User.id).where(or_(*conditions))
    )
    if duplicate:
        raise UserDuplicateError("User id/email/username already exists")

    user = User(
        id=user_id,
        email=payload.email.lower() if payload.email else None,
        username=payload.username,
        password_hash=hash_password(payload.password),
        status="ENABLED",
    )

    try:
        db.add(user)
        db.flush()
        _assign_legacy_roles(db, user_id, [])
        write_audit_log(
            db,
            action="user.create",
            actor_user_id=actor_user_id,
            detail=compose_audit_detail(
                f"target_user_id={user.id}",
                f"target_username={user.username}",
                f"target_status={user.status}",
            ),
            output=json.dumps({"user_id": user.id, "username": user.username, "status": user.status}),
        )
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        error_msg = str(e).lower()
        if "role" in error_msg or "default" in error_msg:
            raise UserRoleAssignmentError("Default role not configured or role assignment failed")
        raise UserCreateError("User creation failed")

    created = get_user_by_id(db, user_id)
    if created:
        queue_user_auth_refresh(created)
        _fire_and_forget(
            publish_topic(
                "admin.users",
                name="users.changed",
                payload={"action": "created", "user_id": created.id},
                requires_refetch=["/api/v1/users"],
                dedupe_key=f"users:created:{created.id}",
            )
        )
    return serialize_user(created)


def delete_user(db: Session, user_id: str, *, actor_user_id: str | None) -> bool:
    user = get_user_by_id(db, user_id)
    if not user:
        return False

    target_username = user.username
    avatar_path = user.avatar_path  # Save before delete
    try:
        # Delete active sessions first with ORM sync to avoid StaleDataError.
        # No need to revoke-then-delete; ON DELETE CASCADE will handle any
        # remaining rows when the user row is removed.
        sessions = db.execute(
            select(AuthSession).where(AuthSession.user_id == user_id)
        ).scalars().all()
        for session in sessions:
            db.delete(session)
        db.flush()
        write_audit_log(
            db,
            action="user.delete",
            actor_user_id=actor_user_id,
            detail=compose_audit_detail(
                f"target_user_id={user_id}",
                f"target_username={target_username}",
            ),
            output=json.dumps({"user_id": user_id, "username": target_username}),
        )
        db.delete(user)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to delete user %s", user_id)
        raise

    # Clean up avatar file
    if avatar_path:
        avatar_filepath = os.path.join("/app/data/avatars", avatar_path)
        try:
            if os.path.exists(avatar_filepath):
                os.remove(avatar_filepath)
        except OSError:
            pass

    _fire_and_forget(
        publish_topic(
            "admin.users",
            name="users.changed",
            payload={"action": "deleted", "user_id": user_id},
            requires_refetch=["/api/v1/users"],
            dedupe_key=f"users:deleted:{user_id}",
        )
    )
    return True


def reset_user_password(
    db: Session,
    user_id: str,
    payload: UserPasswordResetRequest,
    *,
    actor_user_id: str | None,
) -> UserPublic | None:
    user = get_user_by_id(db, user_id)
    if not user:
        return None

    try:
        user.password_hash = hash_password(payload.new_password)
        revoke_active_sessions_for_user(db, user_id)
        write_audit_log(
            db,
            action="user.password.reset",
            actor_user_id=actor_user_id,
            detail=compose_audit_detail(
                f"target_user_id={user.id}",
                f"target_username={user.username}",
                "password_updated=true",
                "sessions_revoked=true",
            ),
            output=json.dumps({"user_id": user.id, "username": user.username, "password_updated": True, "sessions_revoked": True}),
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return None

    updated = get_user_by_id(db, user_id)
    if updated:
        _fire_and_forget(
            publish_to_user(
                updated.id,
                topic="auth",
                name="auth.password_reset",
                payload={"user_id": updated.id},
                requires_refetch=["/api/v1/auth/me"],
                dedupe_key=f"auth:password_reset:{updated.id}",
            )
        )
        _fire_and_forget(
            publish_topic(
                "admin.users",
                name="users.changed",
                payload={"action": "password_reset", "user_id": updated.id},
                requires_refetch=["/api/v1/users"],
                dedupe_key=f"users:password_reset:{updated.id}",
            )
        )
    return serialize_user(updated) if updated else None


def update_user(
    db: Session,
    user_id: str,
    payload: UserUpdateRequest,
    *,
    actor_user_id: str | None,
) -> UserPublic | None:
    user = get_user_by_id(db, user_id)
    if not user:
        return None

    changed_fields: list[str] = []
    previous_status = user.status

    # Handle new_user_id (user ID change)
    if payload.new_user_id is not None:
        next_user_id = payload.new_user_id.strip()
        if next_user_id and next_user_id != user.id:
            # Check uniqueness against other users
            existing = get_user_by_id(db, next_user_id)
            if existing:
                return None
            user.id = next_user_id
            changed_fields.append("user_id")
            # If the actor is changing their own user ID, update actor_user_id
            # so the audit log write succeeds (the old id no longer exists
            # after the UPDATE + ON UPDATE CASCADE flushes).
            if actor_user_id is not None and actor_user_id == user_id:
                actor_user_id = next_user_id

    if payload.email is not None:
        next_email = payload.email.strip().lower()
        if not next_email:
            return None
        if next_email != user.email:
            duplicate = db.scalar(
                select(User.id).where(User.email == next_email, User.id != user.id)
            )
            if duplicate:
                return None
            user.email = next_email
            changed_fields.append("email")

    if payload.username is not None:
        next_username = payload.username.strip()
        if not next_username:
            return None
        if next_username != user.username:
            duplicate = db.scalar(
                select(User.id).where(User.username == next_username, User.id != user.id)
            )
            if duplicate:
                return None
            user.username = next_username
            changed_fields.append("username")

    status_changed = False
    if payload.status:
        next_status = _to_storage_user_status(payload.status)
        if next_status != user.status:
            user.status = next_status
            status_changed = True
            changed_fields.append("status")

    if not changed_fields:
        return serialize_user(user)

    try:
        write_audit_log(
            db,
            action="user.update",
            actor_user_id=actor_user_id,
            detail=compose_audit_detail(
                f"target_user_id={user.id}",
                f"target_username={user.username}",
                describe_changed_fields(changed_fields),
                (
                    f"status_transition={previous_status}->{user.status}"
                    if status_changed
                    else None
                ),
            ),
            output=json.dumps({
                "user_id": user.id,
                "username": user.username,
                "changed_fields": changed_fields,
                "status_transition": f"{previous_status}->{user.status}" if status_changed else None,
            }),
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return None

    # Use the ORM object directly (its id may have changed due to new_user_id)
    queue_user_auth_refresh(user, status_changed=status_changed)
    _fire_and_forget(
        publish_topic(
            "admin.users",
            name="users.changed",
            payload={"action": "updated", "user_id": user.id},
            requires_refetch=["/api/v1/users"],
            dedupe_key=f"users:updated:{user.id}",
        )
    )
    _fire_and_forget(
        publish_to_user(
            user.id,
            topic="auth",
            name="auth.profile_changed",
            payload={"user_id": user.id, "status": user.status},
            requires_refetch=["/api/v1/auth/me"],
            dedupe_key=f"auth:profile_changed:{user.id}:{user.status}",
        )
    )
    return serialize_user(user)


def set_user_roles(
    db: Session,
    user_id: str,
    payload: UserRoleUpdateRequest,
    *,
    actor_user_id: str | None,
) -> UserPublic | None:
    user = get_user_by_id(db, user_id)
    if not user:
        return None

    role_codes = sorted(set(code.strip() for code in payload.role_codes if code.strip()))
    if not role_codes:
        return None
    if not _role_ids_exist(db, role_codes):
        return None

    if not _replace_legacy_user_roles(db, user_id, role_codes):
        return None
    updated = get_user_by_id(db, user_id)
    if updated:
        authz = get_user_authorization(db, updated.id)
        try:
            write_audit_log(
                db,
                action="user.roles.replace",
                actor_user_id=actor_user_id,
                detail=compose_audit_detail(
                    f"target_user_id={updated.id}",
                    f"target_username={updated.username}",
                    f"role_codes={summarize_values(sorted(authz.role_codes))}",
                ),
                output=json.dumps({
                    "user_id": updated.id,
                    "username": updated.username,
                    "role_codes": sorted(authz.role_codes),
                }),
            )
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            return None
        queue_user_auth_refresh(updated)
        _fire_and_forget(
            publish_topic(
                "admin.users",
                name="users.changed",
                payload={"action": "roles_updated", "user_id": updated.id, "role_codes": sorted(authz.role_codes)},
                requires_refetch=["/api/v1/users"],
                dedupe_key=f"users:roles_updated:{updated.id}",
            )
        )
        _fire_and_forget(
            publish_to_user(
                updated.id,
                topic="auth",
                name="auth.permission_changed",
                payload={"user_id": updated.id, "role_codes": sorted(authz.role_codes)},
                requires_refetch=["/api/v1/auth/me", "/api/v1/admin/me/menus"],
                dedupe_key=f"auth:permission_changed:{updated.id}",
            )
        )
    return serialize_user(updated)


def serialize_user(user: User | None) -> UserPublic:
    if user is None:
        msg = "User is required"
        raise ValueError(msg)

    authz = _resolve_authz_for_user(user)
    avatar_url = f"/api/v1/users/{user.id}/avatar" if user.avatar_path else None
    return UserPublic(
        id=user.id,
        email=user.email or "",
        username=user.username,
        status=normalize_user_status(user.status),
        role_codes=sorted(authz.role_codes),
        permission_codes=sorted(authz.permission_codes),
        created_at=user.created_at or utcnow(),
        last_login_at=user.last_login_at,
        avatar_url=avatar_url,
    )


def queue_user_auth_refresh(user: User, *, status_changed: bool = False) -> None:
    authz = _resolve_authz_for_user(user)
    _fire_and_forget(
        ws_connection_manager.refresh_user_authorization(
            user.id,
            role_codes=authz.role_codes,
            permission_codes=authz.permission_codes,
        )
    )
    if status_changed and not is_user_enabled(user.status):
        revoke_active_sessions_for_user_by_id(user.id)
        _fire_and_forget(
            ws_connection_manager.disconnect_user(
                user.id,
                code=4403,
                reason="user_not_allowed",
            )
        )


def queue_users_auth_refresh(db: Session, user_ids: list[str]) -> None:
    normalized = sorted(set(user_ids))
    if not normalized:
        return
    users = db.execute(_user_with_rbac_stmt().where(User.id.in_(normalized))).unique().scalars().all()
    for user in users:
        queue_user_auth_refresh(user)


def revoke_active_sessions_for_user(db: Session, user_id: str) -> None:
    now = utcnow()
    sessions = db.execute(
        select(AuthSession).where(
            and_(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    if not sessions:
        return
    for session in sessions:
        session.revoked_at = now
    db.flush()  # Ensure session revocations are persisted


def revoke_active_sessions_for_user_by_id(user_id: str) -> None:
    from ..core.database import SessionLocal

    with SessionLocal() as session:
        revoke_active_sessions_for_user(session, user_id)
        session.commit()


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return
    loop.create_task(coro)


def _resolve_authz_for_user(user: User) -> UserAuthorization:
    session = object_session(user)
    if session is None:
        return UserAuthorization(role_codes=set(), permission_codes=set())
    return get_user_authorization(session, user.id)


def _to_storage_user_status(raw_status: str) -> str:
    return "ENABLED" if normalize_user_status(raw_status) == "active" else "DISABLED"


def _role_ids_exist(db: Session, role_ids: list[str]) -> bool:
    stmt = text(
        "SELECT code FROM roles WHERE code IN :role_ids"
    ).bindparams(bindparam("role_ids", expanding=True))
    try:
        existing = {str(row[0]) for row in db.execute(stmt, {"role_ids": role_ids}).all()}
    except SQLAlchemyError:
        return False
    return set(role_ids).issubset(existing)


def _replace_legacy_user_roles(db: Session, user_id: str, role_codes: list[str]) -> bool:
    try:
        db.execute(text("DELETE FROM user_roles WHERE user_id = :user_id"), {"user_id": user_id})

        # Get role IDs from role codes
        role_id_stmt = text(
            "SELECT id FROM roles WHERE code IN :role_codes"
        ).bindparams(bindparam("role_codes", expanding=True))
        role_ids = [row[0] for row in db.execute(role_id_stmt, {"role_codes": role_codes}).all()]

        if not role_ids:
            return False

        insert_stmt = text(
            """
            INSERT INTO user_roles (user_id, role_id)
            VALUES (:user_id, :role_id)
            """
        )
        for role_id in role_ids:
            db.execute(
                insert_stmt,
                {
                    "user_id": user_id,
                    "role_id": role_id,
                },
            )
        db.flush()
    except SQLAlchemyError:
        return False
    return True


def _assign_legacy_roles(db: Session, user_id: str, role_ids: list[str]) -> None:
    normalized = sorted(set(role_id.strip() for role_id in role_ids if role_id.strip()))
    # Keep create-user path backward compatible: if no explicit role given, try legacy "user".
    if not normalized:
        try:
            exists = db.scalar(text("SELECT code FROM roles WHERE code = 'user' LIMIT 1"))
            if exists:
                normalized = ["user"]
        except SQLAlchemyError:
            return
    if not normalized:
        return
    _replace_legacy_user_roles(db, user_id, normalized)
