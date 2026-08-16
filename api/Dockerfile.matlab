# fquiz-matlab-worker image: Linux 版 MATLAB Runtime + 判别 celery worker
#
# 方案 B（Linux 原生）：镜像在构建时下载并安装 Linux 版 MATLAB Runtime
# （glnxa64），判别引擎为 Linux mcc 编译产物（RunWaveAnalysisModule），
# 直接执行、无需 Wine。彻底移除 Wine 链路（xauth/wine32/prefix 等全部不再需要）。
#
# - MCR：构建期从 MathWorks 官方源下载 R2026a glnxa64 安装包，静默安装到 /opt/mcr
# - 引擎：外部卷挂载到 /app/matlab-wave（含 RunWaveAnalysisModule），引擎/模型改动无需重建镜像
# - 队列：matlab-diagnostics（判别任务专用）

ARG REGISTRY=crpi-u265r07n4blchcqo.cn-shanghai.personal.cr.aliyuncs.com
ARG REGISTRY_NAMESPACE=ck-registry
FROM ${REGISTRY}/${REGISTRY_NAMESPACE}/fquiz-base:latest

ARG APT_MIRROR=""
ARG MCR_VERSION=R2026a
ARG MCR_DOWNLOAD_URL=https://ssd.mathworks.com/supportfiles/downloads/R2026a/Release/0/deployment_files/installer/complete/glnxa64/MATLAB_Runtime_R2026a_glnxa64.zip

# 1) MCR 运行所需的系统库（X11/解压工具）
RUN if [ -n "${APT_MIRROR}" ]; then \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list 2>/dev/null; \
    fi; \
    apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        unzip \
        curl \
        libxt6 \
        libxmu6 \
        libice6 \
        libsm6 \
        libxrender1 \
        libxrandr2 \
        libxfixes3 \
        libxcursor1 \
        libxinerama1 \
        libxft2 \
        libxi6 \
    && rm -rf /var/lib/apt/lists/*

# 2) 下载并静默安装 Linux 版 MATLAB Runtime
RUN mkdir -p /mcr-install \
    && curl -fsSL --retry 5 --retry-delay 5 -o /tmp/MCR.zip "${MCR_DOWNLOAD_URL}" \
    && unzip -q /tmp/MCR.zip -d /mcr-install \
    && find /mcr-install -maxdepth 1 -iname "*install*" -type f -exec chmod +x {} \; \
    && /mcr-install/install -mode silent -agreeToLicense yes -destinationFolder /opt/mcr \
    && rm -rf /tmp/MCR.zip /mcr-install

# 3) MCR 运行环境变量
ENV MCR_MASTER_PATH=/opt/mcr/${MCR_VERSION}
ENV LD_LIBRARY_PATH=${MCR_MASTER_PATH}/runtime/glnxa64:${MCR_MASTER_PATH}/bin/glnxa64:${MCR_MASTER_PATH}/sys/os/glnxa64:${LD_LIBRARY_PATH}
ENV XAPPLRESDIR=/etc/X11/app-defaults

# 4) Linux 编译的判别引擎：外部卷挂载到 /app/matlab-wave（含 RunWaveAnalysisModule）
RUN mkdir -p /app/matlab-wave

WORKDIR /app
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY app ./app

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["celery", "-A", "app.core.celery_app.celery_app", "worker", "-Q", "matlab-diagnostics", "--loglevel=info"]