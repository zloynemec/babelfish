FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# CPU wheels avoid pulling CUDA libraries onto hive.
RUN python -m pip install 'torch>=2.1,<3' --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install .

FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/data \
    XDG_DATA_HOME=/data/share \
    XDG_CONFIG_HOME=/data/config \
    XDG_CACHE_HOME=/data/.cache \
    HF_HOME=/data/.cache/huggingface \
    MARIAN_MODELS_DIR=/data/marian \
    ARGOS_DEVICE_TYPE=cpu

LABEL org.opencontainers.image.title="BabelFish" \
      org.opencontainers.image.source="https://github.com/zloynemec/babelfish"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 babelfish \
    && useradd --uid 10001 --gid 10001 --home-dir /data --no-create-home \
        --shell /usr/sbin/nologin babelfish \
    && install -d -o 10001 -g 10001 -m 0700 /data

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY scripts/install_argos_model.py scripts/install_marian_model.py ./scripts/

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).close()"]

CMD ["uvicorn", "translation_service.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
