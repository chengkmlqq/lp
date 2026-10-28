from pydantic import BaseModel, EmailStr, Field

from .user import UserPublic


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    # 图形验证码(登录人机验证,LP 新增)
    captcha_id: str = Field(default="", max_length=64)
    captcha_code: str = Field(default="", max_length=16)
    # 短信验证码(短信开关开启时必填,关闭时忽略)
    sms_code: str = Field(default="", max_length=16)


class CaptchaResponse(BaseModel):
    captcha_id: str
    image_base64: str
    expires_in: int
    # 短信验证码开关状态: 前端据此决定是否展示短信验证码输入
    sms_captcha_enabled: bool = False


class SmsCaptchaSendRequest(BaseModel):
    # 发送短信验证码: 先通过图形验证码(防刷), 手机号为目标接收号码
    captcha_id: str = Field(min_length=1, max_length=64)
    captcha_code: str = Field(min_length=1, max_length=16)
    phone: str = Field(min_length=6, max_length=20)


class SmsCaptchaSendResponse(BaseModel):
    message: str
    interval_seconds: int
    ttl_seconds: int


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class MessageResponse(BaseModel):
    message: str
