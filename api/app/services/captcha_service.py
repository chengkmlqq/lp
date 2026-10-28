"""图形验证码服务:生成验证码图片,答案存 Redis(broker 复用),登录时校验。"""
from __future__ import annotations

import base64
import io
import logging
import random
import string
import uuid

from PIL import Image, ImageDraw, ImageFont

from ..core.config import get_settings

logger = logging.getLogger(__name__)

CAPTCHA_TTL_SECONDS = 300          # 5 分钟有效
CAPTCHA_KEY_PREFIX = "lp:captcha"
CAPTCHA_LENGTH = 4
# 排除易混淆字符 (0/O, 1/I/L, 2/Z 等)
CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# 图形验证码开关参数 key(system_params 表): 显式设为 "false" 才关闭, 默认开启
CAPTCHA_ENABLED_PARAM_KEY = "auth.captcha.enabled"


def _get_param(db, key: str) -> str:
    """读取 system_params 参数值(与 sms_captcha_service 一致, 无值返回空串)。"""
    from ..services.system_param_service import get_system_param_by_key

    param = get_system_param_by_key(db, key)
    if param is None:
        return ""
    return param.param_value or ""


def is_captcha_enabled(db) -> bool:
    """图形验证码总开关: 参数缺失/非 "false" 一律视为开启, 显式 "false" 才关闭。"""
    return _get_param(db, CAPTCHA_ENABLED_PARAM_KEY).strip().lower() != "false"

WIDTH, HEIGHT = 120, 44


def _get_redis_client():
    """复用 celery broker redis 连接(与 task_log_service 一致)。"""
    import redis as redis_lib

    settings = get_settings()
    broker = settings.resolved_celery_broker_url
    if broker and broker.startswith("redis://"):
        return redis_lib.from_url(broker)
    return redis_lib.Redis(db=settings.task_log_redis_db)


def _captcha_key(captcha_id: str) -> str:
    return f"{CAPTCHA_KEY_PREFIX}:{captcha_id}"


def _load_font(size: int):
    """优先用系统字体,找不到则用 PIL 默认字体。"""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def generate_captcha() -> tuple[str, str]:
    """生成验证码,返回 (captcha_id, image_base64)。"""
    code = "".join(random.choices(CAPTCHA_CHARS, k=CAPTCHA_LENGTH))

    image = Image.new("RGB", (WIDTH, HEIGHT), color=(245, 248, 252))
    draw = ImageDraw.Draw(image)

    # 干扰线
    for _ in range(5):
        x0 = random.randint(0, WIDTH)
        y0 = random.randint(0, HEIGHT)
        x1 = random.randint(0, WIDTH)
        y1 = random.randint(0, HEIGHT)
        draw.line((x0, y0, x1, y1), fill=tuple(random.randint(120, 200) for _ in range(3)), width=1)

    # 噪点
    for _ in range(80):
        x = random.randint(0, WIDTH - 1)
        y = random.randint(0, HEIGHT - 1)
        draw.point((x, y), fill=tuple(random.randint(100, 200) for _ in range(3)))

    # 字符(带轻微旋转/位移)
    font = _load_font(28)
    char_x = 8
    for ch in code:
        # 每个字符随机颜色(深色系,保证可读)
        color = (random.randint(20, 80), random.randint(20, 80), random.randint(20, 80))
        dy = random.randint(-4, 4)
        draw.text((char_x, HEIGHT // 2 - 14 + dy), ch, font=font, fill=color)
        char_x += 26

    # 输出 base64
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    captcha_id = uuid.uuid4().hex
    try:
        client = _get_redis_client()
        client.setex(_captcha_key(captcha_id), CAPTCHA_TTL_SECONDS, code.lower())
    except Exception as exc:  # pragma: no cover - redis 故障时降级为不存,登录校验会失败并提示
        logger.warning("captcha redis set failed: %s", exc)

    return captcha_id, image_b64


def verify_captcha(captcha_id: str, code: str) -> bool:
    """校验验证码(大小写不敏感),校验后无论成败都删除(一次性)。"""
    if not captcha_id or not code:
        return False
    try:
        client = _get_redis_client()
        key = _captcha_key(captcha_id)
        stored = client.get(key)
        # 一次性:立即删除,防止重放
        client.delete(key)
        if stored is None:
            return False
        return stored.decode("utf-8", errors="ignore").lower() == code.strip().lower()
    except Exception as exc:  # pragma: no cover
        logger.warning("captcha redis verify failed: %s", exc)
        return False


def delete_captcha(captcha_id: str) -> None:
    """主动删除(登录失败重试时可选调用)。"""
    try:
        client = _get_redis_client()
        client.delete(_captcha_key(captcha_id))
    except Exception:
        pass
