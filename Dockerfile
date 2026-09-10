FROM python:3.12-slim

WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libgomp1 libxcb1 libsm6 libxext6 libxrender1 libgl1 libglib2.0-0t64 \
    tesseract-ocr && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]