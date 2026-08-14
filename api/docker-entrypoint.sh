#!/bin/bash
set -e

# ============================================================
# fquiz API Docker Entrypoint
# Ensures static assets (tpbig.exe) are available at runtime
# locations, even when the /app/data volume is a fresh bind mount.
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

# ============================================================
# MATLAB Runtime（Wine）首启静默安装（仅 fquiz-matlab-worker 镜像）
# 标记：仅 matlab-worker 镜像内存在 /opt/mcr-stage（解压后的 MCR 安装包）。
# 普通 api/worker 镜像无此目录，脚本直接跳过，不影响现有行为。
# ============================================================
if [ -d /opt/mcr-stage ] && [ ! -f /root/.wine/drive_c/MATLAB_Runtime-installed ]; then
    echo "entrypoint: 检测到 /opt/mcr-stage，开始经 Wine 静默安装 MATLAB Runtime..."
    mkdir -p /root/.wine

    # 无头环境：初始化 Wine 前缀（wineboot）
    export WINEDLLOVERRIDES="winemenubuilder.exe=d"
    export WINEPREFIX="/root/.wine"
    if ! command -v xvfb-run >/dev/null 2>&1; then
        echo "entrypoint: 未找到 xvfb-run，跳过 Runtime 安装（将降级到 Python 规则）"
    else
        # 生成静默安装输入文件：安装到 Wine 的 C:\MATLAB_Runtime
        cat > /tmp/mcr_input.txt <<EOF
destinationFolder=C:\MATLAB_Runtime
two=no
agreeToLicense=yes
mode=silent
EOF
        # 定位安装器：解压包内含 setup.exe
        SETUP="$(find /opt/mcr-stage -maxdepth 2 -iname 'setup.exe' | head -1)"
        if [ -z "${SETUP}" ]; then
            echo "entrypoint: 未找到 setup.exe，尝试直接运行（可能在子目录）"
            SETUP="/opt/mcr-stage/setup.exe"
        fi
        echo "entrypoint: 安装器 = ${SETUP}"
        # Wine 首次初始化（timeout 防止 headless 卡住）
        timeout 120 xvfb-run -a wineboot --init || true
        # 静默安装（经 Wine 执行 Windows setup.exe）
        timeout 900 xvfb-run -a wine "${SETUP}" -inputfile /tmp/mcr_input.txt || \
        timeout 900 xvfb-run -a wine "${SETUP}" -silent -verbose -inputfile /tmp/mcr_input.txt || true
        # 安装完成标记（无论成功与否，避免每次重启重试）
        touch /root/.wine/drive_c/MATLAB_Runtime-installed 2>/dev/null || true
        echo "entrypoint: MATLAB Runtime 安装流程结束"
        # 释放解压临时空间
        rm -rf /opt/mcr-stage /tmp/mcr_input.txt || true
    fi
fi

# Execute the main container command
exec "$@"
