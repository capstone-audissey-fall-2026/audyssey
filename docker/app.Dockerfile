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
# Run as an unprivileged user; jobs are written under /app/work (named volume). Created
# before src/ so that no RUN follows the src/ COPY.
RUN useradd --create-home --uid 10001 app && mkdir -p /app/work/jobs && chown -R app:app /app/work
# Dependencies first (only pyproject.toml and uv.lock), then src/ and the built web UI as
# COPY --link layers with no RUN after them: a code or UI change rebuilds only its own
# layer and never reinstalls (or, with a registry cache, downloads) the venv.
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_HTTP_TIMEOUT=600
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    for i in 1 2 3; do \
      uv sync --locked --no-dev --no-install-project --extra ui --extra llm && exit 0; \
      echo "uv sync attempt $i failed, retrying"; sleep 10; \
    done; exit 1
# The editable install (a .pth pointing at /app/src) only needs the metadata files and an
# importable package, so an empty skeleton stands in; the real src/ is copied on top below.
RUN mkdir -p src/audyssey && touch src/audyssey/__init__.py README.md
RUN --mount=type=cache,target=/root/.cache/uv \
    for i in 1 2 3; do \
      uv sync --locked --no-dev --extra ui --extra llm && exit 0; \
      echo "uv sync attempt $i failed, retrying"; sleep 10; \
    done; exit 1
COPY --link src/ src/
COPY --link --from=frontend /app/src/audyssey/webui src/audyssey/webui
ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8600
CMD ["audyssey", "serve", "--host", "0.0.0.0", "--port", "8600"]
