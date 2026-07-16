#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [ ! -d "web/node_modules" ]; then
  echo "[web] Missing dependencies. Run: npm --prefix web install"
  exit 1
fi

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

if [ -x "${ROOT_DIR}/.venv/bin/python" ] && \
  "${ROOT_DIR}/.venv/bin/python" -c "import uvicorn" >/dev/null 2>&1; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif python3 -c "import uvicorn" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "[api] Missing dependency: uvicorn."
  echo "      Install with: python3 -m venv .venv && source .venv/bin/activate && python -m pip install -r api/requirements.txt"
  exit 1
fi

cleanup() {
  trap - INT TERM EXIT

  if [ -n "${WEB_PID:-}" ] && kill -0 "${WEB_PID}" 2>/dev/null; then
    kill "${WEB_PID}" 2>/dev/null || true
  fi

  if [ -n "${API_PID:-}" ] && kill -0 "${API_PID}" 2>/dev/null; then
    kill "${API_PID}" 2>/dev/null || true
  fi
}

trap cleanup INT TERM EXIT

echo "[api] Starting FastAPI at ${API_HOST:-0.0.0.0}:${API_PORT:-8000}"
"${PYTHON_BIN}" -m uvicorn api.app.main:app \
  --reload \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8000}" &
API_PID=$!

echo "[web] Starting Next.js on :3000"
npm --workspace web run dev &
WEB_PID=$!

wait -n "${API_PID}" "${WEB_PID}"
