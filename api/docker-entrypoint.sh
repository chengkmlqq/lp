#!/bin/bash
set -e

# ============================================================
# fquiz API Docker Entrypoint
# ============================================================

STATIC_ROOT="/app/static/wine"
DATA_ROOT="/app/data/wine"

# --- tpbig.exe (Legacy ATP path: wine_allowed_root/ATP/tpbig.exe) ---
if [ -f "${STATIC_ROOT}/ATP/tpbig.exe" ]; then
    mkdir -p "${DATA_ROOT}/ATP"
    if [ ! -f "${DATA_ROOT}/ATP/tpbig.exe" ] || ! cmp -s "${STATIC_ROOT}/ATP/tpbig.exe" "${DATA_ROOT}/ATP/tpbig.exe"; then
        cp "${STATIC_ROOT}/ATP/tpbig.exe" "${DATA_ROOT}/ATP/tpbig.exe"
        echo "entrypoint: initialized ${DATA_ROOT}/ATP/tpbig.exe"
    fi
fi

# --- tpbig.exe (atp-storage path: used by atp_engine_executable) ---
if [ -f "${STATIC_ROOT}/atp/tpbig.exe" ]; then
    mkdir -p "${DATA_ROOT}/atp"
    if [ ! -f "${DATA_ROOT}/atp/tpbig.exe" ] || ! cmp -s "${STATIC_ROOT}/atp/tpbig.exe" "${DATA_ROOT}/atp/tpbig.exe"; then
        cp "${STATIC_ROOT}/atp/tpbig.exe" "${DATA_ROOT}/atp/tpbig.exe"
        echo "entrypoint: initialized ${DATA_ROOT}/atp/tpbig.exe"
    fi
fi

# --- tpbig.exe (atp-models storage: atp_storage_root) ---
if [ -f "${STATIC_ROOT}/ATP/tpbig.exe" ]; then
    mkdir -p "${DATA_ROOT}/atp-models"
    if [ ! -f "${DATA_ROOT}/atp-models/tpbig.exe" ] || ! cmp -s "${STATIC_ROOT}/ATP/tpbig.exe" "${DATA_ROOT}/atp-models/tpbig.exe"; then
        cp "${STATIC_ROOT}/ATP/tpbig.exe" "${DATA_ROOT}/atp-models/tpbig.exe"
        echo "entrypoint: initialized ${DATA_ROOT}/atp-models/tpbig.exe"
    fi
fi

# --- Wine 初始化 (celery-worker) ---
if command -v wine >/dev/null 2>&1; then
    export WINEPREFIX=/root/.wine
    export WINEARCH=win32
    export XDG_RUNTIME_DIR=/tmp/.xdg
    mkdir -p /tmp/.xdg /root/.wine/dosdevices
    rm -f /root/.wine/dosdevices/d:
    ln -sf /app/data/wine/ATP /root/.wine/dosdevices/d:
    if [ ! -d /root/.wine/drive_c ]; then
        echo "entrypoint: 初始化 Wine 配置..."
        timeout 300 wine wineboot --init || echo "entrypoint: wineboot --init 失败，继续启动..."
    fi
fi

# Execute the main container command
exec "$@"
