from dataclasses import dataclass
from datetime import timedelta
import json

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..models.auth_session import AuthSession
from ..models.base import utcnow
from ..models.rbac import Role
from ..models.user import User
from ..schemas.auth import LoginRequest, RegisterRequest
from .audit_service import compose_audit_detail, write_audit_log
from .legacy_authz_service import (
    get_user_authorization,
    is_user_enabled,
)
from .user_service import get_user_by_email, get_user_by_id, get_user_by_username
from ..core.config import get_settings
from ..core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)

settings = get_settings()


@dataclass
class AuthResult:
    access_token: str
    expires_in: int
    refresh_token: str
    user: User


def register_user(
    db: Session,
    payload: RegisterRequest,
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthResult:
    email = payload.email.lower()

    duplicate = db.scalar(
        select(User.id).where(or_(User.email == email, User.username == payload.username))
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already exists",
        )

    role: Role | None = None
    try:
        role = db.scalar(select(Role).where(Role.code == "user"))
    except SQLAlchemyError:
        role = None

    user = User(
        email=email,
        username=payload.username,
        password_hash=hash_password(payload.password),
        status="ENABLED",
    )
    if role is not None:
        user.roles.append(role)
    db.add(user)
    db.commit()

    write_audit_log(
        db,
        action="auth.register",
        actor_user_id=user.id,
        detail=compose_audit_detail(
            f"user_id={user.id}",
            f"username={user.username}",
        ),
        output=json.dumps({"user_id": user.id, "username": user.username}),
    )
    db.commit()

    return issue_auth_result_for_user(
        db,
        user_id=user.id,
        user_agent=user_agent,
        ip_address=ip_address,
        action="auth.login_after_register",
    )


def login_user(
    db: Session,
    payload: LoginRequest,
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthResult:
    requested_user_id = payload.user_id.strip()
    user = get_user_by_id(db, requested_user_id)
    if not user:
        user = get_user_by_username(db, requested_user_id)

    # Check if user exists
    if not user:
        write_audit_log(
            db,
            action="auth.login_failed",
            actor_user_id=None,
            detail=compose_audit_detail(
                f"attempted_user_id={requested_user_id}",
                "reason=user_not_found",
            ),
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user_id or password",
        )

    # Check if account is locked
    now = utcnow()
    if user.failed_login_locked_until and user.failed_login_locked_until > now.replace(tzinfo=None):
        remaining_seconds = int((user.failed_login_locked_until - now.replace(tzinfo=None)).total_seconds())
        write_audit_log(
            db,
            action="auth.login_failed",
            actor_user_id=user.id,
            detail=compose_audit_detail(
                f"attempted_user_id={requested_user_id}",
                f"username={user.username}",
                "reason=account_locked",
                f"remaining_seconds={remaining_seconds}",
            ),
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is locked. Please try again in {remaining_seconds} seconds.",
        )

    # Verify password
    if not verify_password(payload.password, user.password_hash):
        # Increment failed login attempts
        user.failed_login_attempts += 1

        # Lock account if attempts >= 5
        if user.failed_login_attempts >= 5:
            user.failed_login_locked_until = now + timedelta(minutes=30)
            write_audit_log(
                db,
                action="auth.login_failed",
                actor_user_id=user.id,
                detail=compose_audit_detail(
                    f"attempted_user_id={requested_user_id}",
                    "reason=invalid_credentials",
                    f"failed_attempts={user.failed_login_attempts}",
                    "account_locked=true",
                    "lock_duration_minutes=30",
                ),
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Too many failed login attempts. Account locked for 30 minutes.",
            )

        write_audit_log(
            db,
            action="auth.login_failed",
            actor_user_id=user.id,
            detail=compose_audit_detail(
                f"attempted_user_id={requested_user_id}",
                "reason=invalid_credentials",
                f"failed_attempts={user.failed_login_attempts}",
            ),
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user_id or password",
        )

    if not is_user_enabled(user.status):
        write_audit_log(
            db,
            action="auth.login_failed",
            actor_user_id=user.id,
            detail=compose_audit_detail(
                f"attempted_user_id={requested_user_id}",
                f"username={user.username}",
                "reason=user_disabled",
            ),
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is disabled",
        )

    # Reset failed login attempts on successful login
    user.failed_login_attempts = 0
    user.failed_login_locked_until = None

    return issue_auth_result_for_user(
        db,
        user_id=user.id,
        user_agent=user_agent,
        ip_address=ip_address,
        action="auth.login",
    )


def refresh_user_session(
    db: Session,
    refresh_token: str | None,
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthResult:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )

    now = utcnow()
    token_hash = hash_token(refresh_token)
    session = db.scalar(
        select(AuthSession).where(
            and_(
                AuthSession.refresh_token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh session",
        )

    session.revoked_at = now
    write_audit_log(
        db,
        action="auth.refresh",
        actor_user_id=session.user_id,
        detail=compose_audit_detail(
            f"user_id={session.user_id}",
            "session_rotated=true",
        ),
        output=json.dumps({"user_id": session.user_id, "session_rotated": True}),
    )
    db.commit()

    return issue_auth_result_for_user(
        db,
        user_id=session.user_id,
        user_agent=user_agent,
        ip_address=ip_address,
        action="auth.refresh_issued",
    )


def logout_user_session(db: Session, refresh_token: str | None, *, user_id: str | None) -> None:
    if not refresh_token:
        return

    token_hash = hash_token(refresh_token)
    now = utcnow()
    session = db.scalar(
        select(AuthSession).where(
            and_(
                AuthSession.refresh_token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
            )
        )
    )
    if not session:
        return

    if user_id and session.user_id != user_id:
        return

    session.revoked_at = now
    write_audit_log(
        db,
        action="auth.logout",
        actor_user_id=session.user_id,
        detail=compose_audit_detail(
            f"user_id={session.user_id}",
            "session_revoked=true",
        ),
        output=json.dumps({"user_id": session.user_id, "session_revoked": True}),
    )
    db.commit()


def issue_auth_result_for_user(
    db: Session,
    *,
    user_id: str,
    user_agent: str | None,
    ip_address: str | None,
    action: str,
) -> AuthResult:
    user = get_user_by_id_with_rbac(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if not is_user_enabled(user.status):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is disabled",
        )

    refresh_token = create_refresh_token()
    refresh_expires_at = utcnow() + timedelta(days=settings.refresh_token_expire_days)

    db.add(
        AuthSession(
            user_id=user.id,
            refresh_token_hash=hash_token(refresh_token),
            user_agent=user_agent,
            ip_address=ip_address,
            expires_at=refresh_expires_at,
        )
    )

    user.last_login_at = utcnow()
    write_audit_log(
        db,
        action=action,
        actor_user_id=user.id,
        detail=compose_audit_detail(
            f"user_id={user.id}",
            f"username={user.username}",
            "access_token_issued=true",
        ),
        output=json.dumps({"user_id": user.id, "username": user.username, "access_token_issued": True}),
    )
    db.commit()

    user = get_user_by_id_with_rbac(db, user_id)
    authz = get_user_authorization(db, user.id)
    role_codes = sorted(authz.role_codes)
    permission_codes = sorted(authz.permission_codes)
    access_token, expires_in = create_access_token(
        user_id=user.id,
        role_codes=role_codes,
        permission_codes=permission_codes,
    )

    return AuthResult(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=refresh_token,
        user=user,
    )


def get_user_by_id_with_rbac(db: Session, user_id: str) -> User | None:
    from .user_service import get_user_by_id

    return get_user_by_id(db, user_id)
