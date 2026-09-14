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

# --- EGM 引擎（各电压的 rjtzl_egm*.exe）：绕击跳闸率计算用 ---
# 与 tpbig.exe 同理：镜像里带（/app/static/wine/ATP/<v>/<v>egm/），启动时拷到运行时卷。
for V in 35 66 110 220 330 500 750 800 1000; do
    SRC_EGM="${STATIC_ROOT}/ATP/${V}/${V}egm"
    [ -d "${SRC_EGM}" ] || continue
    mkdir -p "${DATA_ROOT}/ATP/${V}/${V}egm"
    for F in "${SRC_EGM}"/*.exe; do
        [ -f "$F" ] || continue
        BN="${F##*/}"
        if [ ! -f "${DATA_ROOT}/ATP/${V}/${V}egm/${BN}" ] || ! cmp -s "$F" "${DATA_ROOT}/ATP/${V}/${V}egm/${BN}"; then
            cp "$F" "${DATA_ROOT}/ATP/${V}/${V}egm/${BN}"
        fi
    done
    echo "entrypoint: initialized ${DATA_ROOT}/ATP/${V}/${V}egm/*.exe"
done

# --- Wine 初始化 (celery-worker) ---
# tobix/pywine:3.10 镜像已自带完整的 wineboot --init 配置在 /opt/wineprefix
# 直接使用，不再重复初始化
if command -v wine >/dev/null 2>&1; then
    export WINEPREFIX=/opt/wineprefix
    export XDG_RUNTIME_DIR=/tmp
    export WINEDLLOVERRIDES=winemenubuilder.exe=d
    mkdir -p /tmp/.xdg /opt/wineprefix/dosdevices
    rm -f /opt/wineprefix/dosdevices/d:
    ln -sf /app/data/wine/ATP /opt/wineprefix/dosdevices/d:
    echo "entrypoint: Wine prefix=${WINEPREFIX}, d: -> /app/data/wine/ATP"
fi

# Execute the main container command
exec "$@"
