# fquiz-matlab-worker image: fquiz-wine-base-64 + Windows MATLAB Runtime + diagnosis worker
# MATLAB Runtime is fetched from the official MathWorks URL first, with 84 nginx as fallback.

ARG REGISTRY=crpi-u265r07n4blchcqo.cn-shanghai.personal.cr.aliyuncs.com
ARG REGISTRY_NAMESPACE=ck-registry
FROM ${REGISTRY}/${REGISTRY_NAMESPACE}/fquiz-wine-base-64:latest

ARG APT_MIRROR=""
ARG DL_BASE="http://223.109.142.84/downloads"
ARG MCR_OFFICIAL_URL="https://ssd.mathworks.cn/supportfiles/downloads/R2026a/Release/0/deployment_files/installer/complete/win64/MATLAB_Runtime_R2026a_win64.zip"
ARG WAVE_ENGINE_URL="${DL_BASE}/waveform_engine_v2.exe"

RUN if [ -n "${APT_MIRROR}" ]; then \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list 2>/dev/null; \
    fi; \
    apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        curl \
        unzip \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/mcr-stage

ARG MCR_ZIP=""
RUN set -eux; \
    if [ -z "${MCR_ZIP}" ]; then \
        mcr_url="${MCR_OFFICIAL_URL:-${DL_BASE}/MATLAB_Runtime_R2026a_win64.zip}"; \
        echo "MCR_ZIP not set, trying official source first: ${mcr_url}"; \
        if ! curl -fSL --retry 3 --retry-delay 5 -o /tmp/mcr.zip "${mcr_url}"; then \
            echo "Official source failed, falling back to 84: ${DL_BASE}"; \
            curl -fSL --retry 5 --retry-delay 5 -o /tmp/mcr.zip "${DL_BASE}/MATLAB_Runtime_R2026a_win64.zip"; \
        fi; \
    else \
        echo "Using prebuilt MCR_ZIP"; \
    fi; \
    mkdir -p /opt/mcr-stage && cd /opt/mcr-stage && unzip -q /tmp/mcr.zip; \
    rm -f /tmp/mcr.zip

RUN set -eux; \
    mkdir -p /app/matlab-wave; \
    if [ -n "${WAVE_ENGINE_URL}" ]; then \
        curl -fSL --retry 3 -o /app/matlab-wave/waveform_engine_v2.exe "${WAVE_ENGINE_URL}"; \
    else \
        echo "WAVE_ENGINE_URL is empty, skipping exe download"; \
    fi; \
    ls -la /app/matlab-wave/

WORKDIR /app
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY app ./app

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["celery", "-A", "app.core.celery_app.celery_app", "worker", "-Q", "matlab-diagnostics", "--loglevel=info"]
