# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

FROM python-base AS requirements-exporter

COPY pyproject.toml README.md ./
COPY scripts/export_container_requirements.py ./scripts/export_container_requirements.py

RUN python scripts/export_container_requirements.py core > /tmp/requirements-core.txt \
    && python scripts/export_container_requirements.py container-dev > /tmp/requirements-container-dev.txt \
    && python scripts/export_container_requirements.py ingestion > /tmp/requirements-ingestion.txt

FROM python-base AS core-deps

COPY --from=requirements-exporter /tmp/requirements-core.txt /tmp/requirements-core.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements-core.txt

FROM core-deps AS worker-deps

COPY --from=requirements-exporter /tmp/requirements-ingestion.txt /tmp/requirements-ingestion.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -s /tmp/requirements-ingestion.txt ]; then pip install -r /tmp/requirements-ingestion.txt; fi

FROM core-deps AS api-dev-deps

COPY --from=requirements-exporter /tmp/requirements-container-dev.txt /tmp/requirements-container-dev.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -s /tmp/requirements-container-dev.txt ]; then pip install -r /tmp/requirements-container-dev.txt; fi

FROM worker-deps AS worker-dev-deps

COPY --from=requirements-exporter /tmp/requirements-container-dev.txt /tmp/requirements-container-dev.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -s /tmp/requirements-container-dev.txt ]; then pip install -r /tmp/requirements-container-dev.txt; fi

FROM python-base AS app-builder

COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
COPY infra/docker ./infra/docker

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "setuptools>=82.0.0" wheel \
    && pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/dist .

FROM core-deps AS api-runtime

RUN addgroup --system app && adduser --system --ingroup app --home /home/app app

ENV HOME=/home/app \
    XDG_CACHE_HOME=/home/app/.cache \
    HF_HOME=/home/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/home/app/.cache/huggingface/transformers

COPY --from=app-builder /tmp/dist /tmp/dist
COPY scripts ./scripts
COPY infra/docker ./infra/docker

RUN pip install --no-deps /tmp/dist/*.whl \
    && mkdir -p /home/app/.cache/huggingface/transformers \
    && chmod +x /app/infra/docker/api-start.sh /app/infra/docker/worker-start.sh \
    && chown -R app:app /app /home/app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "scripts/healthcheck_api.py"]

CMD ["sh", "/app/infra/docker/api-start.sh"]

FROM worker-deps AS worker-runtime

RUN addgroup --system app && adduser --system --ingroup app --home /home/app app

ENV HOME=/home/app \
    XDG_CACHE_HOME=/home/app/.cache \
    HF_HOME=/home/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/home/app/.cache/huggingface/transformers

COPY --from=app-builder /tmp/dist /tmp/dist
COPY scripts ./scripts
COPY infra/docker ./infra/docker

RUN pip install --no-deps /tmp/dist/*.whl \
    && mkdir -p /home/app/.cache/huggingface/transformers \
    && chmod +x /app/infra/docker/api-start.sh /app/infra/docker/worker-start.sh \
    && chown -R app:app /app /home/app

USER app

EXPOSE 9100

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "scripts/healthcheck_worker.py"]

CMD ["sh", "/app/infra/docker/worker-start.sh"]

FROM api-dev-deps AS api-dev-runtime

RUN addgroup --system app && adduser --system --ingroup app --home /home/app app

ENV HOME=/home/app \
    XDG_CACHE_HOME=/home/app/.cache \
    HF_HOME=/home/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/home/app/.cache/huggingface/transformers

COPY --from=app-builder /tmp/dist /tmp/dist
COPY scripts ./scripts
COPY infra/docker ./infra/docker

RUN pip install --no-deps /tmp/dist/*.whl \
    && mkdir -p /home/app/.cache/huggingface/transformers \
    && chmod +x /app/infra/docker/api-start.sh /app/infra/docker/worker-start.sh /app/infra/docker/api-dev-start.sh /app/infra/docker/worker-dev-start.sh \
    && chown -R app:app /app /home/app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "scripts/healthcheck_api.py"]

CMD ["sh", "/app/infra/docker/api-dev-start.sh"]

FROM worker-dev-deps AS worker-dev-runtime

RUN addgroup --system app && adduser --system --ingroup app --home /home/app app

ENV HOME=/home/app \
    XDG_CACHE_HOME=/home/app/.cache \
    HF_HOME=/home/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/home/app/.cache/huggingface/transformers

COPY --from=app-builder /tmp/dist /tmp/dist
COPY scripts ./scripts
COPY infra/docker ./infra/docker

RUN pip install --no-deps /tmp/dist/*.whl \
    && mkdir -p /home/app/.cache/huggingface/transformers \
    && chmod +x /app/infra/docker/api-start.sh /app/infra/docker/worker-start.sh /app/infra/docker/api-dev-start.sh /app/infra/docker/worker-dev-start.sh \
    && chown -R app:app /app /home/app

USER app

EXPOSE 9100

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "scripts/healthcheck_worker.py"]

CMD ["sh", "/app/infra/docker/worker-dev-start.sh"]

FROM worker-runtime AS production-default
