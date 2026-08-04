ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=300
ARG PIP_RETRIES=20

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT}
ENV PIP_RETRIES=${PIP_RETRIES}

# Keep daocloud mirror for apt/pip (internal mirrors work from GitHub runners too)
RUN sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list 2>/dev/null; \
    dpkg --add-architecture i386 \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libexpat1 \
        wine \
        wine32:i386 \
        gdal-bin \
        libgdal-dev \
        fonts-noto-cjk \
        g++ \
        gcc \
    && command -v wine >/dev/null \
    && dpkg-query -W -f='${Status}' wine32:i386 | grep -q "install ok installed" \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --retries "${PIP_RETRIES}" --timeout "${PIP_DEFAULT_TIMEOUT}" -i "${PIP_INDEX_URL}" -r requirements.txt

# Install GDAL Python bindings matching system GDAL version
RUN GDAL_VERSION=$(gdal-config --version) \
    && pip install --no-cache-dir GDAL==${GDAL_VERSION} \
    && apt-get purge -y --auto-remove g++ gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -c "import rasterio; print('rasterio ready:', rasterio.__version__)"
RUN python -c "from osgeo import gdal; print('GDAL ready:', gdal.__version__)"
RUN command -v gdal2tiles.py && echo "gdal2tiles.py available"

# Verify CJK fonts installed so matplotlib can render Chinese labels (LP-223)
RUN python -c "from matplotlib import font_manager; names=[f.name for f in font_manager.fontManager.ttflist if 'CJK' in f.name or 'Noto' in f.name]; print('CJK fonts:', sorted(set(names))); assert any('CJK' in n for n in names), 'No CJK font found'"

# Static assets (tpbig.exe, etc.) are volume-mounted at runtime
# from deploy/pro-deploy/data/app/wine/

# Entrypoint: ensures tpbig.exe is available in runtime volume
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

COPY app ./app

EXPOSE 8000
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--ws", "wsproto", "--workers", "2"]
