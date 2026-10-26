# Lighty backend
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/srv/data \
    RUNTIME_DIR=/srv/runtime

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
# Bundled copy of the dataset; a volume mounted at /srv/data takes precedence.
COPY data /srv/data

RUN useradd --create-home --uid 10001 lighty \
    && mkdir -p /srv/runtime \
    && chown -R lighty:lighty /srv
USER lighty

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
