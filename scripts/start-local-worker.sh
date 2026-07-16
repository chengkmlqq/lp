# 本地 Worker 启动脚本
# 连到 84 环境的 Redis 和 PostgreSQL，不启动本地依赖服务
#
# 用法：
#   bash scripts/start-local-worker.sh          # 构建镜像并启动
#   bash scripts/start-local-worker.sh --no-build  # 跳过构建直接用已有镜像
#   bash scripts/start-local-worker.sh --stop      # 停止容器

set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="deploy/local-worker/compose.yml"
PROJECT_NAME="lp-local-worker"

# 84 环境连接信息
REDIS_HOST="223.109.142.84"
REDIS_PORT="6339"
REDIS_PASSWORD="4rfvVFR$"
PG_HOST="223.109.142.84"
PG_PORT="5413"
PG_USER="lp"
PG_PASSWORD="7ujmMJU&"
PG_DB="lp"

stop() {
  echo "🛑 停止本地 Worker..."
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down
  echo "✅ 已停止"
  exit 0
}

# 处理参数
if [ "${1:-}" = "--stop" ]; then stop; fi

mkdir -p deploy/local-worker/data/app/celery

# 构建 API 镜像（如果本地没有）
if [ "${1:-}" != "--no-build" ]; then
  echo "🔨 构建 API 镜像..."
  docker build -t lp-api:local -f api/Dockerfile api/
fi

# 生成 compose 文件
cat > "$COMPOSE_FILE" << YAML
services:
  celery-worker:
    image: lp-api:local
    container_name: ${PROJECT_NAME}-celery-worker
    command:
      - celery
      - -A
      - app.core.celery_app.celery_app
      - worker
      - --loglevel=INFO
      - --concurrency=2
      - --queues=default,celery
    environment:
      # 连到 84 的 PostgreSQL
      DB_HOST: ${PG_HOST}
      DB_PORT: ${PG_PORT}
      DB_NAME: ${PG_DB}
      DB_USERNAME: ${PG_USER}
      DB_PASSWORD: ${PG_PASSWORD}
      DB_SCHEMA: public
      DATABASE_URL: postgresql+psycopg://${PG_USER}:${PG_PASSWORD}@${PG_HOST}:${PG_PORT}/${PG_DB}

      # 连到 84 的 Redis
      CELERY_BROKER_URL: redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/0
      CELERY_RESULT_BACKEND: redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/1
      CELERY_TIMEZONE: Asia/Shanghai

      # 需要的最小配置
      DB_SCHEMA: public
      JWT_SECRET_KEY: ${JWT_SECRET_KEY:-local-dev-secret-key-change-in-production}
      MINIO_ENABLED: "false"
      MINIO_ENDPOINT: http://${PG_HOST}:9000
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY:-minioadmin}
      MINIO_BUCKET: lp
      MINIO_REGION: us-east-1
      WINE_BINARY_PATH: wine
      WINE_ALLOWED_ROOT: /app/data/wine
      WINE_DEFAULT_TIMEOUT_SECONDS: 300
      WINE_MAX_TIMEOUT_SECONDS: 1800
      FLOWER_API_BASE_URL: http://${PG_HOST}:5555
      FLOWER_API_TIMEOUT_SECONDS: 10
    volumes:
      - ./data/app:/app/data
    restart: unless-stopped
YAML

echo "🚀 启动本地 Worker（连到 84 环境）..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d
echo "✅ Worker 已启动！"
echo ""
echo "📋 查看日志： docker compose -p ${PROJECT_NAME} -f ${COMPOSE_FILE} logs -f"
echo "🛑 停止 Worker： bash $0 --stop"
