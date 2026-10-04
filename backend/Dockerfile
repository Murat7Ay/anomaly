# syntax=docker/dockerfile:1.7
# Reproducible build: exact, hash-verified dependency versions from requirements.lock.
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock ./
RUN python -m venv /venv && /venv/bin/pip install --require-hashes -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN /venv/bin/pip install --no-deps .

FROM python:3.12-slim
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Europe/Istanbul
RUN useradd --system --uid 10001 app
WORKDIR /app
COPY --from=build /venv /venv
COPY alembic.ini ./
COPY alembic ./alembic
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1
CMD ["uvicorn", "loadguard.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
