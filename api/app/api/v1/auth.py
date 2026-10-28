from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.database import get_db
from ...core.dependencies import CurrentUser, get_current_user
from ...schemas.auth import (
    AuthTokenResponse,
    CaptchaResponse,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    SmsCaptchaSendRequest,
    SmsCaptchaSendResponse,
)
from ...schemas.user import UserPublic
from ...services.auth_service import (
    AuthResult,
    login_user,
    logout_user_session,
    refresh_user_session,
    register_user,
)
from ...services.captcha_service import generate_captcha, verify_captcha
from ...services.sms_captcha_service import (
    SmsCaptchaError,
    is_sms_captcha_enabled,
    send_sms_captcha,
    verify_sms_captcha,
)
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
def get_captcha(db: Session = Depends(get_db)) -> CaptchaResponse:
    """获取登录图形验证码(captcha_id + base64 PNG 图片)。"""
    captcha_id, image_base64 = generate_captcha()
    return CaptchaResponse(
        captcha_id=captcha_id,
        image_base64=image_base64,
        expires_in=300,
        sms_captcha_enabled=is_sms_captcha_enabled(db),
    )


@router.post("/sms-captcha/send", response_model=SmsCaptchaSendResponse)
def send_sms_captcha_endpoint(
    payload: SmsCaptchaSendRequest,
    db: Session = Depends(get_db),
) -> SmsCaptchaSendResponse:
    """发送短信验证码: 必须先通过图形验证码(防刷), 发到指定手机号。"""
    if not verify_captcha(payload.captcha_id, payload.captcha_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期,请刷新后重试",
        )
    try:
        result = send_sms_captcha(db, payload.phone)
    except SmsCaptchaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SmsCaptchaSendResponse(
        message="短信验证码已发送",
        interval_seconds=result["interval_seconds"],
        ttl_seconds=result["ttl_seconds"],
    )


@router.post("/login", response_model=AuthTokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    sms_enabled = is_sms_captcha_enabled(db)
    if sms_enabled:
        # 短信开关开启: 登录必须通过短信验证码(图形码在发送短信时已校验)
        if not payload.sms_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请输入短信验证码",
            )
        # 需要用户手机号: 先用 user_id 定位用户, 取绑定手机号校验
        from ...services.user_service import get_user_by_id, get_user_by_username

        requested_user_id = payload.user_id.strip()
        user = get_user_by_id(db, requested_user_id) or get_user_by_username(db, requested_user_id)
        if not user or not user.phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该账号未绑定手机号,无法使用短信验证码登录",
            )
        if not verify_sms_captcha(db, user.phone, payload.sms_code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="短信验证码错误或已过期,请重新获取",
            )
    else:
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
