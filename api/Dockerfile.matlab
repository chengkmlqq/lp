# fquiz-matlab-worker image: Linux 版 MATLAB Runtime + 判别 celery worker
#
# 方案 B（Linux 原生）：基于 fquiz-mcr-base（fquiz-base + Linux 版 MATLAB
# Runtime R2023a glnxa64，低频更新、服务器构建推送）。判别引擎为 Linux mcc
# 编译产物（RunWaveAnalysisModule），直接执行、无需 Wine。
#
# - MCR：来自 fquiz-mcr-base 基础镜像（构建期安装，见 api/Dockerfile.mcrbase）
# - 引擎：外部卷挂载到 /app/matlab-wave（含 RunWaveAnalysisModule），引擎/模型改动无需重建镜像
# - 队列：matlab-diagnostics（判别任务专用）

ARG REGISTRY=crpi-u265r07n4blchcqo.cn-shanghai.personal.cr.aliyuncs.com
ARG REGISTRY_NAMESPACE=ck-registry
FROM ${REGISTRY}/${REGISTRY_NAMESPACE}/fquiz-mcr-base:r2023a

# Linux 编译的判别引擎：外部卷挂载到 /app/matlab-wave（含 RunWaveAnalysisModule）
RUN mkdir -p /app/matlab-wave

WORKDIR /app
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY app ./app

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["celery", "-A", "app.core.celery_app.celery_app", "worker", "-Q", "matlab-diagnostics", "--loglevel=info"]