# fquiz-matlab-worker 镜像：fquiz-wine-base-64（含 64 位 wine）+ Windows MATLAB Runtime + 判别系统
# 用途：跑 MATLAB 行波判别任务（判别系统 v1.0 的 waveform_engine_v2.exe，经 Wine 调用 Windows Runtime）。
#
# 决策背景（LP-316）：
# - 判别系统采用 Windows mcc 编译产物 waveform_engine_v2.exe（R2026a，含模型 CTF），
#   为 64 位 PE，故必须在 64 位 wine（libwine:amd64 + wine64）下经 Wine 调用；
#   运行时必需 Windows MATLAB Runtime（R2026a）。
# - 64 位 wine 独立为 fquiz-wine-base-64 基础镜像（与 32 位 fquiz-wine-base 分开），
#   本镜像基于它构建。
# - Runtime zip 与 exe 均由部署机 84 nginx 提供下载（方案 A），CI 构建时拉取。
#
# 队列：本镜像以 celery worker 形式消费 matlab-diagnostics 队列（见 CMD），
# 保证判别任务只落到本镜像（普通 celery-worker 不消费该队列）。
#
ARG REGISTRY=crpi-u265r07n4blchcqo.cn-shanghai.personal.cr.aliyuncs.com
ARG REGISTRY_NAMESPACE=ck-registry
FROM ${REGISTRY}/${REGISTRY_NAMESPACE}/fquiz-wine-base-64:latest

# apt 源镜像（海外 CI 默认官方源）
ARG APT_MIRROR=""
# 下载源基础地址（方案 A：部署机 84 nginx 静态目录）．CI 用 build-args 注入。
ARG DL_BASE="http://223.109.142.84/downloads"
# 各产物下载 URL（默认可被覆盖，用 DL_BASE 拼接）
ARG MCR_DOWNLOAD_URL="${DL_BASE}/MATLAB_Runtime_R2026a_win64.zip"
ARG WAVE_ENGINE_URL="${DL_BASE}/waveform_engine_v2.exe"

# 安装 unzip（解压 MCR zip）与 xvfb（Wine GUI 安装器需虚拟显示）
RUN if [ -n "${APT_MIRROR}" ]; then \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list 2>/dev/null; \
    fi; \
    apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        unzip \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/mcr-stage

# ── 下载并解压 Windows MATLAB Runtime R2026a（zip 约 5.77GB，解压约 12GB） ──
# 安装不在构建时进行（需 Wine 运行时环境），而是由 docker-entrypoint.sh 首次启动时
# 经 Wine 静默安装到 WINEPREFIX（/root/.wine/drive_c/MATLAB_Runtime）。
# 构建时仅下载解压到 /opt/mcr-stage，运行时装完即删，控制镜像体积。
ARG MCR_ZIP=""
RUN set -eux; \
    if [ -z "${MCR_ZIP}" ]; then \
        echo "MCR_ZIP 未设置（默认从 ${MCR_DOWNLOAD_URL} 下载）"; \
        curl -fSL --retry 5 --retry-delay 5 -o /tmp/mcr.zip "${MCR_DOWNLOAD_URL}"; \
    else \
        echo "使用预置 MCR_ZIP"; \
    fi; \
    mkdir -p /opt/mcr-stage && cd /opt/mcr-stage && unzip -q /tmp/mcr.zip; \
    rm -f /tmp/mcr.zip

# ── 下载判别系统编译产物 waveform_engine_v2.exe（含模型 CTF，R2026a） ──
# 放置到 /app/matlab-wave/waveform_engine_v2.exe（与 fault_diagnosis_service 约定一致）。
RUN set -eux; \
    mkdir -p /app/matlab-wave; \
    if [ -n "${WAVE_ENGINE_URL}" ]; then \
        curl -fSL --retry 3 -o /app/matlab-wave/waveform_engine_v2.exe "${WAVE_ENGINE_URL}"; \
    else \
        echo "WAVE_ENGINE_URL 为空，跳过 exe 下载（运行时需挂载）"; \
    fi; \
    ls -la /app/matlab-wave/

# ── 业务代码 + 入口 ──
WORKDIR /app
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY app ./app

# 首次启动时经 Wine 静默安装 Runtime（见 docker-entrypoint.sh，含 WINEPREFIX 初始化）。
# 本镜像固定消费 matlab-diagnostics 队列。
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["celery", "-A", "app.core.celery_app.celery_app", "worker", "-Q", "matlab-diagnostics", "--loglevel=info"]
