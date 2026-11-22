#!/usr/bin/env bash
# ============================================================
# init.sh — 首次初始化（部署后、登录前执行）
#
# 背景（修复部署文档 P1 死循环）：
#   空库首次部署时 users 表为空，没有任何账号；而"初始化系统数据"
#   接口 /api/v1/admin/system/seed-defaults 需要登录 token，导致
#   "无账号→无法登录→无法播种→无账号"的死循环。
#   本脚本在 API 容器内直接调用 seed_defaults()，幂等，可重复执行。
#
# 用法（在部署目录执行）：
#   bash init.sh              # 播种管理员/菜单/角色/权限等（幂等）
#   bash init.sh --no-captcha # 播种并关闭图形验证码（便于自动化登录）
#
# 说明（LP-34 起）：系统语言由环境变量 APP_LANGUAGE（zh/en）控制，
#   不再写入 app.language 系统参数，故本脚本已移除该步骤。
# ============================================================
set -euo pipefail

cd "$(dirname "$0")" || exit 1
NO_CAPTCHA=0
[ "${1:-}" = "--no-captcha" ] && NO_CAPTCHA=1

# 解析 API 容器：优先按 compose 服务名查，回退到默认容器名
API_C="$(docker compose ps -q api 2>/dev/null | head -n1 || true)"
if [ -z "$API_C" ]; then
  API_C="lp-api-1"
fi

# 等待 API 容器就绪
echo "==> 等待 API 容器就绪（$API_C）..."
for i in $(seq 1 30); do
  if docker exec "$API_C" python3 -c "import app.main" >/dev/null 2>&1; then break; fi
  sleep 2
done
if ! docker exec "$API_C" python3 -c "import app.main" >/dev/null 2>&1; then
  echo "✗ API 容器未就绪，请先 docker compose up -d 并确认 api 容器正常"
  exit 1
fi

echo "==> 调用 seed_defaults() 初始化系统数据（幂等）..."
docker exec "$API_C" python3 -c '
from app.core.database import SessionLocal
from app.services.seed_service import seed_defaults
db = SessionLocal()
try:
    r = seed_defaults(db)
    s = r.summary
    print("admin_users created:", s.get("admin_users").created if s.get("admin_users") else "n/a")
    print("roles:", s.get("roles").created if s.get("roles") else "n/a")
    print("menus:", s.get("menus").created if s.get("menus") else "n/a")
    print("permissions:", s.get("permissions").created if s.get("permissions") else "n/a")
finally:
    db.close()
'

echo "==> 系统语言由环境变量 APP_LANGUAGE 控制（LP-34 起不再写 app.language 系统参数），跳过该步骤。"

if [ "$NO_CAPTCHA" -eq 1 ]; then
  echo "==> 关闭图形验证码（写入 system_params: auth.captcha.enabled=false）..."
  docker exec "$API_C" python3 -c '
from app.core.database import SessionLocal
from app.models.system_param import SystemParam
from sqlalchemy import select
db = SessionLocal()
try:
    key = "auth.captcha.enabled"
    p = db.scalar(select(SystemParam).where(SystemParam.param_key == key))
    if p is None:
        p = SystemParam(param_key=key, param_name="图形验证码开关", param_value="false")
        db.add(p)
    else:
        p.param_value = "false"
    db.commit()
    print("captcha disabled")
finally:
    db.close()
'
fi

echo ""
echo "✅ 初始化完成。"
echo "   管理员登录名（user_id）：admin"
echo "   密码：见 .env.prod 的 INITIAL_ADMIN_PASSWORD"
echo "   前端：http://<部署机IP>:3001/"
