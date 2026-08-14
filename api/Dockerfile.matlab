# fquiz-matlab-worker image: fquiz-wine-base-64 + Windows MATLAB Runtime zip (unpacked on deploy host)
# MATLAB Runtime R2026a zip is fetched at build time from the official MathWorks URL first,
# with server nginx (DL_BASE) as fallback. The zip is NOT unpacked during build (avoids blowing
# the GitHub runner disk). Unpacking + Wine install happen on the deploy host, written to an
# external persistent volume (idempotent, see workflow + entrypoint).
#
# waveform_engine_v2.exe is NOT baked into the image; it is provided via an external volume
# mounted at /app/matlab-wave, so exe changes require no image rebuild.

ARG REGISTRY=crpi-u265r07n4blchcqo.cn-shanghai.personal.cr.aliyuncs.com
ARG REGISTRY_NAMESPACE=ck-registry
FROM ${REGISTRY}/${REGISTRY_NAMESPACE}/fquiz-wine-base-64:latest

ARG APT_MIRROR=""
ARG DL_BASE="http://223.109.142.84/downloads"
ARG MCR_OFFICIAL_URL="https://ssd.mathworks.cn/supportfiles/downloads/R2026a/Release/0/deployment_files/installer/complete/win64/MATLAB_Runtime_R2026a_win64.zip"

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

# Download the MCR zip only (NOT unpacked here). Unpacking happens on the deploy host.
ARG MCR_ZIP=""
RUN set -eux; \
    if [ -z "${MCR_ZIP}" ]; then \
        mcr_url="${MCR_OFFICIAL_URL:-${DL_BASE}/MATLAB_Runtime_R2026a_win64.zip}"; \
        echo "Downloading MCR zip, official first: ${mcr_url}"; \
        if ! curl -fSL --retry 3 --retry-delay 5 -o /tmp/mcr.zip "${mcr_url}"; then \
            echo "Official source failed, falling back to ${DL_BASE}"; \
            curl -fSL --retry 5 --retry-delay 5 -o /tmp/mcr.zip "${DL_BASE}/MATLAB_Runtime_R2026a_win64.zip"; \
        fi; \
    else \
        echo "Using prebuilt MCR_ZIP"; \
    fi; \
    mkdir -p /opt/mcr-stage && mv /tmp/mcr.zip /opt/mcr-stage/mcr.zip && ls -la /opt/mcr-stage/

# exe is not baked in; it lives on an external volume mounted at /app/matlab-wave.
RUN mkdir -p /app/matlab-wave

WORKDIR /app
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY app ./app

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["celery", "-A", "app.core.celery_app.celery_app", "worker", "-Q", "matlab-diagnostics", "--loglevel=info"]
