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

# --- mytpbig.exe (Wine 引擎入口, atp_engine_executable/atp_tpbig_executable 默认值均指向它) ---
# ATP 官方 atpmingw 编译版(与 tpbig.exe 是两个不同程序, 不能互相替代), 必须随镜像分发,
# 否则新环境部署时外部/legacy ATP 路径都会报 "ATP engine executable not found"。
if [ -f "${STATIC_ROOT}/ATP/mytpbig.exe" ]; then
    mkdir -p "${DATA_ROOT}/ATP"
    if [ ! -f "${DATA_ROOT}/ATP/mytpbig.exe" ] || ! cmp -s "${STATIC_ROOT}/ATP/mytpbig.exe" "${DATA_ROOT}/ATP/mytpbig.exe"; then
        cp "${STATIC_ROOT}/ATP/mytpbig.exe" "${DATA_ROOT}/ATP/mytpbig.exe"
        echo "entrypoint: initialized ${DATA_ROOT}/ATP/mytpbig.exe"
    fi
fi

# --- rjtzl.exe (绕击 EGM 单塔引擎, atp_rjtzl_executable 默认值) ---
# 与 tpbig/mytpbig 同理随镜像分发; 缺失时 legacy_atp_adapter 报 "rjtzl.exe不存在"。
if [ -f "${STATIC_ROOT}/ATP/rjtzl.exe" ]; then
    mkdir -p "${DATA_ROOT}/ATP"
    if [ ! -f "${DATA_ROOT}/ATP/rjtzl.exe" ] || ! cmp -s "${STATIC_ROOT}/ATP/rjtzl.exe" "${DATA_ROOT}/ATP/rjtzl.exe"; then
        cp "${STATIC_ROOT}/ATP/rjtzl.exe" "${DATA_ROOT}/ATP/rjtzl.exe"
        echo "entrypoint: initialized ${DATA_ROOT}/ATP/rjtzl.exe"
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

# --- LCC 引擎配置文件（startup/graphics/listsize/templates） ---
# LCC（Line Constants Calculator）启动必需：缺失时 ATP 报
# "Attempt to connect disk file startup has failed. Halt in RFUNL1" 且产不出 .pch。
# 与 tpbig/EGM 同理，镜像带一份（/app/static/wine/ATP/），启动时幂等拷到运行时卷。
for F in startup graphics graphics.aux graphics.std listsize.big; do
    SRC_F="${STATIC_ROOT}/ATP/${F}"
    DST_F="${DATA_ROOT}/ATP/${F}"
    if [ -f "${SRC_F}" ] && { [ ! -f "${DST_F}" ] || ! cmp -s "${SRC_F}" "${DST_F}"; }; then
        cp "${SRC_F}" "${DST_F}"
        echo "entrypoint: initialized ${DST_F}"
    fi
done
for A in halfhigh.aux halfwide.aux higher80.aux higher93.aux quarter.aux sixteen.aux thirty2.aux; do
    SRC_F="${STATIC_ROOT}/ATP/${A}"
    DST_F="${DATA_ROOT}/ATP/${A}"
    if [ -f "${SRC_F}" ] && { [ ! -f "${DST_F}" ] || ! cmp -s "${SRC_F}" "${DST_F}"; }; then
        cp "${SRC_F}" "${DST_F}"
        echo "entrypoint: initialized ${DST_F}"
    fi
done
# 参数模板目录（fanji/raoji1 等）：防雷计算 .dat 生成时从模板读取，随镜像分发。
if [ -d "${STATIC_ROOT}/ATP/templates" ]; then
    mkdir -p "${DATA_ROOT}/ATP/templates"
    cp -rn "${STATIC_ROOT}/ATP/templates/." "${DATA_ROOT}/ATP/templates/"
    echo "entrypoint: initialized templates"
fi

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
