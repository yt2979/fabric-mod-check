FROM ghcr.io/astral-sh/uv:0.11.21 AS uv
FROM python:3.13-slim

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOST=0.0.0.0 \
    PORT=8080 \
    SESSION_DB=/tmp/fabric-mod-check.sqlite3

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY app.py catalog.py research.py index.html ./
COPY static/ static/
COPY data/catalog.json data/examples.json data/
USER 65532:65532
CMD ["/app/.venv/bin/python", "app.py"]
