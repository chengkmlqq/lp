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
# MATLAB Runtime（Wine）幂等安装（仅 fquiz-matlab-worker 镜像）
#
# 方案 2：构建镜像仅携带 mcr.zip（未解压，/opt/mcr-stage/mcr.zip）。
# - 解压：部署机由 GitHub Actions 完成（见 workflow "解压 MCR" 步骤），
#   解压到外部持久卷（挂载到 /opt/mcr-stage，无 .unpacked 标记时执行）。
# - Wine 安装：本脚本在容器首启时执行，安装到外部持久卷挂载的 /root/.wine，
#   写 .installed 标记；重复发布/容器重建因标记存在而跳过（幂等）。
# 普通 api/worker 镜像无 /opt/mcr-stage/mcr.zip，脚本直接跳过。
# ============================================================
if [ -f /opt/mcr-stage/mcr.zip ]; then
    echo "entrypoint: 检测到 MCR zip，开始幂等安装 MATLAB Runtime（首选官方源，失败回退 84）..."

    export WINEDLLOVERRIDES="winemenubuilder.exe=d"
    export WINEPREFIX="${WINEPREFIX:-/root/.wine}"
    UNPACKED_MARKER="/opt/mcr-stage/.unpacked"
    INSTALLED_MARKER="${WINEPREFIX}/drive_c/MATLAB_Runtime-installed"

    # 1) 解压（若部署机未解压或因任何原因缺标记，则此处补上）
    if [ ! -f "${UNPACKED_MARKER}" ]; then
        echo "entrypoint: 解压 MCR zip 到 /opt/mcr-stage ..."
        mkdir -p /opt/mcr-stage
        cd /opt/mcr-stage
        if unzip -q -o /opt/mcr-stage/mcr.zip; then
            touch "${UNPACKED_MARKER}"
            echo "entrypoint: 解压完成"
        else
            echo "entrypoint: 警告 - MCR zip 解压失败，尝试继续（可能不完整）"
        fi
    else
        echo "entrypoint: MCR 已解压过（.unpacked 存在），跳过解压"
    fi

    # 2) Wine 安装（幂等：有标记则跳过）
    if [ ! -f "${INSTALLED_MARKER}" ]; then
        echo "entrypoint: 开始 Wine 静默安装 MATLAB Runtime（WINEPREFIX=${WINEPREFIX}）..."
        mkdir -p "${WINEPREFIX}"

        if ! command -v xvfb-run >/dev/null 2>&1; then
            echo "entrypoint: 未找到 xvfb-run，跳过 Runtime 安装（将降级到 Python 规则）"
        else
            cat > /tmp/mcr_input.txt <<EOF
destinationFolder=C:\MATLAB_Runtime
two=no
agreeToLicense=yes
mode=silent
EOF
            SETUP="$(find /opt/mcr-stage -maxdepth 2 -iname 'setup.exe' | head -1)"
            if [ -z "${SETUP}" ]; then
                echo "entrypoint: 未找到 setup.exe，尝试直接运行（可能在子目录）"
                SETUP="/opt/mcr-stage/setup.exe"
            fi
            echo "entrypoint: 安装器 = ${SETUP}"
            timeout 120 xvfb-run -a wineboot --init || true
            timeout 900 xvfb-run -a wine "${SETUP}" -inputfile /tmp/mcr_input.txt || \
            timeout 900 xvfb-run -a wine "${SETUP}" -silent -verbose -inputfile /tmp/mcr_input.txt || true
            touch "${INSTALLED_MARKER}" 2>/dev/null || true
            echo "entrypoint: MATLAB Runtime 安装流程结束"
            rm -f /tmp/mcr_input.txt || true
        fi
    else
        echo "entrypoint: MATLAB Runtime 已安装（.installed 存在），跳过安装"
    fi

    # 3) 释放解压后的中间文件（保留 mcr.zip 供后续重建复用；删掉已展开的目录以省空间）
    #    注意：不删 mcr.zip 本身，避免将来需要重装时又要重新下载。
    echo "entrypoint: 保留 /opt/mcr-stage/mcr.zip（供复用），清理展开目录..."
    find /opt/mcr-stage -mindepth 1 -maxdepth 1 ! -name 'mcr.zip' ! -name '.unpacked' -exec rm -rf {} + 2>/dev/null || true
fi

# Execute the main container command
exec "$@"
