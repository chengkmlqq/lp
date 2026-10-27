from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.database import get_db
from ...core.dependencies import CurrentUser, get_current_user
from ...schemas.auth import AuthTokenResponse, CaptchaResponse, LoginRequest, MessageResponse, RegisterRequest
from ...schemas.user import UserPublic
from ...services.auth_service import (
    AuthResult,
    login_user,
    logout_user_session,
    refresh_user_session,
    register_user,
)
from ...services.captcha_service import generate_captcha, verify_captcha
from ...services.user_service import serialize_user

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _is_secure_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto:
        return forwarded_proto.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def _refresh_cookie_secure(request: Request) -> bool:
    if not settings.refresh_cookie_secure:
        return False
    return _is_secure_request(request)


def _set_refresh_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        httponly=True,
        secure=_refresh_cookie_secure(request),
        samesite=settings.refresh_cookie_samesite,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path="/",
    )


def _clear_refresh_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/",
        httponly=True,
        secure=_refresh_cookie_secure(request),
        samesite=settings.refresh_cookie_samesite,
    )


def _set_access_token_cookie(request: Request, response: Response, token: str, expires_in: int) -> None:
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=_refresh_cookie_secure(request),
        samesite=settings.refresh_cookie_samesite,
        max_age=expires_in,
        path="/",
    )


def _clear_access_token_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(
        key="access_token",
        path="/",
        httponly=True,
        secure=_refresh_cookie_secure(request),
        samesite=settings.refresh_cookie_samesite,
    )


def _to_auth_response(result: AuthResult) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=serialize_user(result.user),
    )


@router.post("/register", response_model=AuthTokenResponse)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    result = register_user(
        db,
        payload,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    _set_refresh_cookie(request, response, result.refresh_token)
    _set_access_token_cookie(request, response, result.access_token, result.expires_in)
    return _to_auth_response(result)


@router.get("/captcha", response_model=CaptchaResponse)
def get_captcha() -> CaptchaResponse:
    """获取登录图形验证码(captcha_id + base64 PNG 图片)。"""
    captcha_id, image_base64 = generate_captcha()
    return CaptchaResponse(
        captcha_id=captcha_id,
        image_base64=image_base64,
        expires_in=300,
    )


@router.post("/login", response_model=AuthTokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    # 图形验证码人机校验(LP 登录安全增强):校验失败直接 400,不泄露账号信息
    if not verify_captcha(payload.captcha_id, payload.captcha_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期,请刷新后重试",
        )
    result = login_user(
        db,
        payload,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    _set_refresh_cookie(request, response, result.refresh_token)
    _set_access_token_cookie(request, response, result.access_token, result.expires_in)
    return _to_auth_response(result)


@router.post("/refresh", response_model=AuthTokenResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    result = refresh_user_session(
        db,
        request.cookies.get(settings.refresh_cookie_name),
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    _set_refresh_cookie(request, response, result.refresh_token)
    _set_access_token_cookie(request, response, result.access_token, result.expires_in)
    return _to_auth_response(result)


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MessageResponse:
    logout_user_session(
        db,
        request.cookies.get(settings.refresh_cookie_name),
        user_id=None,
    )
    _clear_access_token_cookie(request, response)
    _clear_refresh_cookie(request, response)
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserPublic)
def me(current_user: CurrentUser = Depends(get_current_user)) -> UserPublic:
    return serialize_user(current_user.user)
