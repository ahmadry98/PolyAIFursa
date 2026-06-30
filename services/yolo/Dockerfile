FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV YOLO_CONFIG_DIR=/tmp/ultralytics

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY torch-requirements.txt requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r torch-requirements.txt \
    && pip install -r requirements.txt \
    && addgroup --system app \
    && adduser --system --ingroup app app

COPY app.py .
COPY database.py .
COPY models.py .
COPY repositories.py .
COPY s3_utils.py .

RUN mkdir -p uploads/original uploads/predicted /tmp/ultralytics \
    && chown -R app:app /app /tmp/ultralytics

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
