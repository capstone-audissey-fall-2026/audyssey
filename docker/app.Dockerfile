# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# vite.config.ts writes to ../src/audyssey/webui, i.e. /app/src/audyssey/webui
RUN npm run build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv
# Debian mirrors sometimes drop connections; retry each file and the whole install.
RUN for i in 1 2 3; do \
      apt-get update && apt-get install -y -o Acquire::Retries=5 --no-install-recommends ffmpeg \
      && rm -rf /var/lib/apt/lists/* && exit 0; \
      echo "apt attempt $i failed, retrying"; sleep 15; \
    done; exit 1
WORKDIR /app
# Dependencies first (only pyproject.toml and uv.lock), then src/ and the built web UI,
# so a code or UI change does not reinstall the venv.
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_HTTP_TIMEOUT=600
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    for i in 1 2 3; do \
      uv sync --locked --no-dev --no-install-project --extra ui --extra llm && exit 0; \
      echo "uv sync attempt $i failed, retrying"; sleep 10; \
    done; exit 1
COPY README.md ./
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/uv \
    for i in 1 2 3; do \
      uv sync --locked --no-dev --extra ui --extra llm && exit 0; \
      echo "uv sync attempt $i failed, retrying"; sleep 10; \
    done; exit 1
# After the sync: the editable install reads src/, and a web change then only adds this layer.
COPY --from=frontend /app/src/audyssey/webui src/audyssey/webui
ENV PATH="/app/.venv/bin:$PATH"
# Run as an unprivileged user; jobs are written under /app/work (named volume).
RUN useradd --create-home --uid 10001 app && mkdir -p /app/work/jobs && chown -R app:app /app/work
USER app
EXPOSE 8600
CMD ["audyssey", "serve", "--host", "0.0.0.0", "--port", "8600"]
