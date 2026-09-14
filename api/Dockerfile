# API 镜像：一级基础镜像（无 wine）+ 后端服务代码。
# wine 相关执行全部下沉到 worker（celery 任务），api 仅保留路由与任务分发。
ARG REGISTRY=crpi-u265r07n4blchcqo.cn-shanghai.personal.cr.aliyuncs.com
ARG REGISTRY_NAMESPACE=ck-registry
FROM ${REGISTRY}/${REGISTRY_NAMESPACE}/fquiz-base:latest

WORKDIR /app

# Static assets (tpbig.exe, etc.) are volume-mounted at runtime
# from deploy/pro-deploy/data/app/wine/

# Entrypoint: ensures tpbig.exe is available in runtime volume
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# 静态引擎文件（tpbig.exe + 各电压 EGM 引擎 rjtzl_egm*.exe）随镜像分发，
# 容器启动时由 entrypoint 拷到运行时卷（/app/data/wine/ATP/）。
COPY static/wine /app/static/wine

COPY app ./app
# 录波 PDF 提取器（extract_fault_report.py）及其依赖清单：镜像内需与 app 同级存在，
# 否则 /extract-wave 与判别任务会报「录波 PDF 提取器不存在」。
COPY 录波 ./录波

EXPOSE 8000
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--ws", "wsproto", "--workers", "2"]
