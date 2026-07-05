FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY services/agent/requirements.txt ./requirements.txt
COPY services/img-proc-mcp/requirements.txt /tmp/img-proc-requirements.txt
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -r /tmp/img-proc-requirements.txt \
    && addgroup --system app \
    && adduser --system --ingroup app app

COPY services/agent/*.py ./
COPY services/img-proc-mcp/img_proc_app.py /img-proc-mcp/img_proc_app.py

RUN chown -R app:app /app /img-proc-mcp

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
