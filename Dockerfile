# VeriTrack AI API — one image for the web service (and Celery workers).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=2

WORKDIR /srv
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# rapidocr pulls the GUI build of OpenCV; swap it for the headless one
RUN pip install -r requirements.txt \
 && pip uninstall -y opencv-python \
 && pip install --force-reinstall --no-deps "opencv-python-headless>=4.10"

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN useradd --create-home --uid 10001 veritrack \
 && mkdir -p /srv/storage-data \
 && chown -R veritrack /srv/storage-data \
 && chmod +x /usr/local/bin/entrypoint.sh
USER veritrack

ENV LOCAL_STORAGE_ROOT=/srv/storage-data PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health',timeout=4)"

ENTRYPOINT ["entrypoint.sh"]
CMD ["web"]
