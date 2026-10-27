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


class CaptchaResponse(BaseModel):
    captcha_id: str
    image_base64: str
    expires_in: int


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class MessageResponse(BaseModel):
    message: str
