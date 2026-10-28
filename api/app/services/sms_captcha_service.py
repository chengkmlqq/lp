"""短信验证码服务: 阿里云短信网关发送 + 校验, 开关/凭据由 system_params 表控制。

参数键(全部走 system_params 表, 无值即视为关闭/不可用):
- auth.sms_captcha.enabled         "true"/"false"  总开关, 默认 false(关闭)
- auth.sms_captcha.access_key_id    阿里云 AccessKey ID
- auth.sms_captcha.access_key_secret 阿里云 AccessKey Secret(建议 is_encrypted=True)
- auth.sms_captcha.sign_name        短信签名(如 "LP平台")
- auth.sms_captcha.template_code    短信模板 CODE(如 SMS_123456789)
- auth.sms_captcha.ttl_seconds      验证码有效期秒, 默认 300
- auth.sms_captcha.interval_seconds 发送间隔秒, 默认 60(防刷)

使用阿里云 Dysmsapi 的 HTTP JSON 接口(RPC 风格, 无需 SDK):
POST https://dysmsapi.aliyuncs.com/
参数: Action=SendSms&Version=2017-05-25&Format=JSON&...
签名: 阿里云 RPC 签名 v1 (HMAC-SHA1, AccessKeySecret + '&')
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import random
import time
import urllib.parse
from datetime import datetime, timezone

import httpx

from ..core.config import get_settings
from ..core.param_encryption import decrypt_value, is_encrypted_value

logger = logging.getLogger(__name__)

SMS_KEY_PREFIX = "lp:smscaptcha"
SMS_SEND_LOCK_PREFIX = "lp:smscaptcha:interval"
SMS_CODE_LENGTH = 6
DYSMSAPI_ENDPOINT = "https://dysmsapi.aliyuncs.com/"


class SmsCaptchaError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 参数读取(全部来自 system_params 表)
# ---------------------------------------------------------------------------
def _get_param(db, key: str) -> str:
    from ..services.system_param_service import get_system_param_by_key

    param = get_system_param_by_key(db, key)
    if param is None:
        return ""
    value = param.param_value or ""
    if is_encrypted_value(value):
        try:
            return decrypt_value(value)
        except Exception:
            logger.warning("sms captcha param decrypt failed: %s", key, exc_info=True)
            return ""
    return value


def is_sms_captcha_enabled(db) -> bool:
    return _get_param(db, "auth.sms_captcha.enabled").strip().lower() == "true"


def _get_redis_client():
    import redis as redis_lib

    settings = get_settings()
    broker = settings.resolved_celery_broker_url
    if broker and broker.startswith("redis://"):
        return redis_lib.from_url(broker)
    return redis_lib.Redis(db=settings.task_log_redis_db)


def _sms_key(phone: str) -> str:
    return f"{SMS_KEY_PREFIX}:{phone}"


def _interval_key(phone: str) -> str:
    return f"{SMS_SEND_LOCK_PREFIX}:{phone}"


# ---------------------------------------------------------------------------
# 阿里云 RPC 签名
# ---------------------------------------------------------------------------
def _rpc_sign(params: dict, access_key_secret: str) -> str:
    """阿里云 RPC 签名 v1 (HMAC-SHA1)。"""
    sorted_keys = sorted(params.keys())
    canonical = "&".join(
        f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(params[k]), safe='')}"
        for k in sorted_keys
    )
    string_to_sign = f"POST&%2F&{urllib.parse.quote(canonical, safe='')}"
    signature = base64.b64encode(
        hmac.new(
            (access_key_secret + "&").encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")
    return signature


def _send_sms(
    *,
    access_key_id: str,
    access_key_secret: str,
    sign_name: str,
    template_code: str,
    phone: str,
    code: str,
) -> None:
    """调用阿里云 Dysmsapi SendSms 发送验证码短信。"""
    params = {
        "Action": "SendSms",
        "Version": "2017-05-25",
        "Format": "JSON",
        "RegionId": "cn-hangzhou",
        "AccessKeyId": access_key_id,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": hashlib.md5(
            f"{time.time_ns()}{random.random()}".encode()
        ).hexdigest(),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "PhoneNumbers": phone,
        "SignName": sign_name,
        "TemplateCode": template_code,
        "TemplateParam": f'{{"code":"{code}"}}',
    }
    params["Signature"] = _rpc_sign(params, access_key_secret)

    resp = httpx.post(DYSMSAPI_ENDPOINT, data=params, timeout=10)
    data = resp.json()
    if data.get("Code") != "OK":
        raise SmsCaptchaError(
            f"短信发送失败: {data.get('Code')} {data.get('Message', '')}".strip()
        )


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def send_sms_captcha(db, phone: str) -> dict:
    """发送短信验证码到指定手机号。返回 {interval, ttl} 或抛 SmsCaptchaError。"""
    if not is_sms_captcha_enabled(db):
        raise SmsCaptchaError("短信验证码未启用")

    access_key_id = _get_param(db, "auth.sms_captcha.access_key_id")
    access_key_secret = _get_param(db, "auth.sms_captcha.access_key_secret")
    sign_name = _get_param(db, "auth.sms_captcha.sign_name")
    template_code = _get_param(db, "auth.sms_captcha.template_code")
    if not (access_key_id and access_key_secret and sign_name and template_code):
        raise SmsCaptchaError("短信网关参数未配置完整")

    try:
        ttl = int(_get_param(db, "auth.sms_captcha.ttl_seconds") or 300)
    except ValueError:
        ttl = 300
    try:
        interval = int(_get_param(db, "auth.sms_captcha.interval_seconds") or 60)
    except ValueError:
        interval = 60

    client = _get_redis_client()

    # 发送频率限制
    if client.exists(_interval_key(phone)):
        raise SmsCaptchaError("发送过于频繁,请稍后再试")

    code = "".join(random.choices("0123456789", k=SMS_CODE_LENGTH))

    # 先发短信,成功后再写 Redis(避免写库成功但发送失败)
    _send_sms(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        sign_name=sign_name,
        template_code=template_code,
        phone=phone,
        code=code,
    )

    client.setex(_sms_key(phone), ttl, code)
    client.setex(_interval_key(phone), interval, "1")
    return {"interval_seconds": interval, "ttl_seconds": ttl}


def verify_sms_captcha(db, phone: str, code: str) -> bool:
    """校验短信验证码(一次性), 校验后无论成败都删除。"""
    if not phone or not code:
        return False
    try:
        client = _get_redis_client()
        key = _sms_key(phone)
        stored = client.get(key)
        client.delete(key)
        if stored is None:
            return False
        return stored.decode("utf-8", errors="ignore") == code.strip()
    except Exception as exc:  # pragma: no cover
        logger.warning("sms captcha verify failed: %s", exc)
        return False