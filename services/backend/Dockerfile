# Build context is the repo root (the image also needs data/reference and data/golden).
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH DATA_DIR=/app/data PYTHONUNBUFFERED=1

WORKDIR /app/backend
COPY services/backend/pyproject.toml services/backend/uv.lock services/backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/backend/ ./
RUN uv sync --frozen --no-dev
COPY data/ /app/data/

RUN useradd --uid 1000 app && chown -R app /app
USER app
EXPOSE 8000
ENTRYPOINT ["backend"]
CMD ["api"]
