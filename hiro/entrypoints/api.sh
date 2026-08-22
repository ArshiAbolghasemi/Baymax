#!/usr/bin/env bash
#
# Start the FastAPI application.
#
#   ./entrypoints/api.sh                 # serve on 0.0.0.0:8080
#   API_RELOAD=true ./entrypoints/api.sh # auto-reload for development
#   ./entrypoints/api.sh --timeout-keep-alive 30   # extra uvicorn flags
#
# Environment:
#   API_HOST        bind address                      (default 0.0.0.0)
#   API_PORT        bind port                         (default 8080)
#   API_WORKERS     uvicorn worker processes          (default 1)
#   API_RELOAD      true to auto-reload on change     (default false)
#   RUN_MIGRATIONS  apply migrations before serving   (default true)
#   LOG_LEVEL       app + uvicorn log level           (default INFO)
#
# Port 8080 by default because 8000/8001 belong to the vLLM containers.

set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if [ "${USE_UV:-auto}" != "false" ] && command -v uv >/dev/null 2>&1 && [ -f pyproject.toml ]; then
  RUNNER=(uv run)
else
  RUNNER=()
fi

log() { printf '%s [api] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%S)" "$*" >&2; }

for name in DATABASE_URL CELERY_BROKER_URL EMBEDDING_BASE_URL EMBEDDING_MODEL QDRANT_URL; do
  if [ -z "${!name:-}" ]; then
    log "ERROR: missing required environment variable $name (see .env.example)"
    exit 1
  fi
done

: "${API_HOST:=0.0.0.0}"
: "${API_PORT:=8080}"
: "${API_WORKERS:=1}"
: "${API_RELOAD:=false}"
: "${RUN_MIGRATIONS:=true}"
: "${LOG_LEVEL:=INFO}"

# Applies only revisions the database has not recorded yet, and serialises
# against the worker doing the same thing via an advisory lock.
if [ "$RUN_MIGRATIONS" = "true" ]; then
  ./entrypoints/migrate.sh
else
  log "RUN_MIGRATIONS=false, skipping migrations"
fi

args=(
  uvicorn hiro.api.app:app
  --host "$API_HOST"
  --port "$API_PORT"
  # Trust X-Forwarded-* so request logs and generated URLs are right behind an
  # ingress or reverse proxy.
  --proxy-headers
  --log-level "$(echo "$LOG_LEVEL" | tr '[:upper:]' '[:lower:]')"
)

if [ "$API_RELOAD" = "true" ]; then
  # --reload and --workers are mutually exclusive; reload implies one process.
  args+=(--reload)
  log "starting on ${API_HOST}:${API_PORT} (reload)"
else
  args+=(--workers "$API_WORKERS")
  log "starting on ${API_HOST}:${API_PORT} (workers=${API_WORKERS})"
fi

# exec so uvicorn is PID 1 and receives SIGTERM directly.
exec "${RUNNER[@]}" "${args[@]}" "$@"
