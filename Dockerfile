# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is reused until requirements.txt changes.
# The cache mount keeps downloaded wheels between local rebuilds without baking them into the image.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY alembic.ini entrypoint.sh ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY app ./app
COPY static ./static
RUN chmod +x entrypoint.sh \
    && useradd --create-home --uid 10001 ezt \
    && mkdir -p /app/data && chown -R ezt /app/data
USER ezt

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

ENTRYPOINT ["./entrypoint.sh"]
CMD ["web"]
