#!/usr/bin/env bash
# ============================================================
# check-credentials.sh — LP 部署凭据一致性校验
#
# 背景：曾因某容器 MINIO_SECRET_KEY 使用占位符/旧值，导致
#       S3 上传 SignatureDoesNotMatch。本脚本在部署前后执行，
#       对比依赖容器的实际环境变量与 .env.prod，杜绝"改了一个
#       忘了另一个"的凭据漂移。
#
# 用法：
#   bash check-credentials.sh            # 检查所有依赖容器
#   bash check-credentials.sh --fix-hint # 失败时输出排查提示
# ============================================================
set -uo pipefail

cd "$(dirname "$0")" || exit 1

ENV_FILE=".env.prod"
if [ ! -f "$ENV_FILE" ]; then
  echo "✗ 未找到 $ENV_FILE（请在 deploy/pro-deploy 目录下执行）"
  exit 2
fi

# --- 从 .env.prod 读取期望值（兼容 CRLF 与引号） ---
get_env() {
  grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r' | tr -d '"'
}

EXPECT_MINIO_ACCESS_KEY="$(get_env MINIO_ACCESS_KEY)"
EXPECT_MINIO_SECRET_KEY="$(get_env MINIO_SECRET_KEY)"
EXPECT_REDIS_PASSWORD="$(get_env REDIS_PASSWORD)"
EXPECT_MINIO_BUCKET="$(get_env MINIO_BUCKET)"
EXPECT_MINIO_ENDPOINT="$(get_env MINIO_ENDPOINT)"

if [ -z "$EXPECT_MINIO_SECRET_KEY" ] || [ -z "$EXPECT_REDIS_PASSWORD" ]; then
  echo "✗ $ENV_FILE 中缺少 MINIO_SECRET_KEY / REDIS_PASSWORD，请先检查配置"
  exit 2
fi

FAIL=0

# --- 检查单个容器的环境变量 ---
check_container() {
  local container="$1"
  local desc="$2"
  shift 2

  if ! docker inspect "$container" >/dev/null 2>&1; then
    echo "… $container（$desc）：容器不存在，跳过"
    return
  fi

  local env
  env="$(docker inspect "$container" --format '{{range .Config.Env}}{{println .}}{{end}}')"

  local name val
  while [ $# -gt 0 ]; do
    name="$1"
    val="$2"
    shift 2
    if ! echo "$env" | grep -Fqx "$name=$val"; then
      local actual
      actual="$(echo "$env" | grep -E "^$name=" | head -1 | cut -d= -f2- || true)"
      echo "✗ $container（$desc）：$name 不一致"
      echo "    期望: $val"
      echo "    实际: ${actual:-<未设置>}"
      FAIL=1
    fi
  done
}

echo "== 检查 MinIO 凭据 =="
for c in lp-api-1 lp-celery-worker-1 lp-celery-beat-1; do
  check_container "$c" "MinIO 凭据" \
    MINIO_ACCESS_KEY "$EXPECT_MINIO_ACCESS_KEY" \
    MINIO_SECRET_KEY "$EXPECT_MINIO_SECRET_KEY" \
    MINIO_BUCKET "$EXPECT_MINIO_BUCKET" \
    MINIO_ENDPOINT "$EXPECT_MINIO_ENDPOINT"
done

echo "== 检查 Redis 密码（broker URL 内嵌） =="
for c in lp-api-1 lp-celery-worker-1 lp-celery-beat-1 lp-ctb-worker-1 lp-flower-1; do
  check_container "$c" "Redis broker URL" \
    CELERY_BROKER_URL "redis://:${EXPECT_REDIS_PASSWORD}@redis:6379/0"
done

echo "== 检查 MinIO 实际可用性 =="
if docker exec lp-api-1 python3 -c "
import boto3, os
s3 = boto3.client('s3',
    endpoint_url='${EXPECT_MINIO_ENDPOINT}',
    aws_access_key_id='${EXPECT_MINIO_ACCESS_KEY}',
    aws_secret_access_key='${EXPECT_MINIO_SECRET_KEY}',
    region_name='us-east-1',
    config=__import__('botocore').config.Config(signature_version='s3v4'))
s3.list_buckets()
" >/dev/null 2>&1; then
  echo "✓ MinIO 凭据可用（list_buckets 成功）"
else
  echo "✗ MinIO 凭据不可用（请检查 MinIO 容器实际 root 凭据与 .env.prod 是否一致）"
  FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
  echo ""
  echo "✅ 全部凭据一致，可以部署"
  exit 0
else
  echo ""
  echo "❌ 存在凭据不一致！请修正后重新部署："
  echo "   1. 编辑 .env.prod 统一凭据"
  echo "   2. 重新创建受影响容器：docker compose up -d api celery-worker celery-beat"
  echo "   3. 重新运行本脚本验证"
  exit 1
fi
