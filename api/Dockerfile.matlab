# fquiz-matlab-worker image: fquiz-wine-base-64 + diagnosis worker (MATLAB via Wine)
#
# 方案 A: the image does NOT carry the MATLAB Runtime (avoids GitHub runner disk limits).
# The MCR zip is downloaded + unpacked idempotently on the deploy host by the GitHub Actions
# deploy job (see workflow "解压 MCR"), then installed once via Wine into an external volume.
# waveform_engine_v2.exe is NOT baked in either; it lives on an external volume mounted at
# /app/matlab-wave, so exe/Runtime changes need no image rebuild.

ARG REGISTRY=crpi-u265r07n4blchcqo.cn-shanghai.personal.cr.aliyuncs.com
ARG REGISTRY_NAMESPACE=ck-registry
FROM ${REGISTRY}/${REGISTRY_NAMESPACE}/fquiz-wine-base-64:latest

ARG APT_MIRROR=""
RUN if [ -n "${APT_MIRROR}" ]; then \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i "s/deb.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list 2>/dev/null; \
    fi; \
    apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
     xvfb \
     xauth \
 && rm -rf /var/lib/apt/lists/*

# exe is provided via an external volume mounted at /app/matlab-wave.
RUN mkdir -p /app/matlab-wave

WORKDIR /app
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY app ./app

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["celery", "-A", "app.core.celery_app.celery_app", "worker", "-Q", "matlab-diagnostics", "--loglevel=info"]
