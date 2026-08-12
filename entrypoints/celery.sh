#!/usr/bin/env bash
#
# Start a Celery worker.
#
#   ./entrypoints/celery.sh                      # prefork worker, 2 processes
#   CELERY_CONCURRENCY=8 ./entrypoints/celery.sh
#   ./entrypoints/celery.sh --without-gossip     # extra celery flags
#
# Environment:
#   CELERY_CONCURRENCY  worker processes                 (default 2)
#   CELERY_POOL         prefork | solo | threads         (default prefork)
#   CELERY_QUEUES       comma-separated queues to consume(default celery)
#   CELERY_HOSTNAME     worker node name                 (default worker@%h)
#   RUN_MIGRATIONS      apply migrations before starting (default true)
#   LOG_LEVEL           log level                        (default INFO)
#
# Concurrency is deliberately low: each task holds a database connection and
# calls vLLM, so the useful ceiling is set by the GPU, not by CPU count.

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

log() { printf '%s [celery] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%S)" "$*" >&2; }

for name in DATABASE_URL CELERY_BROKER_URL EMBEDDING_BASE_URL EMBEDDING_MODEL QDRANT_URL; do
  if [ -z "${!name:-}" ]; then
    log "ERROR: missing required environment variable $name (see .env.example)"
    exit 1
  fi
done

: "${CELERY_CONCURRENCY:=2}"
: "${CELERY_POOL:=prefork}"
: "${CELERY_QUEUES:=celery}"
: "${CELERY_HOSTNAME:=worker@%h}"
: "${RUN_MIGRATIONS:=true}"
: "${LOG_LEVEL:=INFO}"

# Applies only revisions the database has not recorded yet, and serialises
# against the API doing the same thing via an advisory lock.
if [ "$RUN_MIGRATIONS" = "true" ]; then
  ./entrypoints/migrate.sh
else
  log "RUN_MIGRATIONS=false, skipping migrations"
fi

log "starting pool=${CELERY_POOL} concurrency=${CELERY_CONCURRENCY} queues=${CELERY_QUEUES}"

# exec so celery is PID 1 and its warm-shutdown handler gets SIGTERM directly —
# with task_acks_late, an interrupted task is redelivered rather than lost.
exec "${RUNNER[@]}" celery \
  --app baymax.celery.app:celery_app \
  worker \
  --pool "$CELERY_POOL" \
  --concurrency "$CELERY_CONCURRENCY" \
  --queues "$CELERY_QUEUES" \
  --hostname "$CELERY_HOSTNAME" \
  --loglevel "$(echo "$LOG_LEVEL" | tr '[:upper:]' '[:lower:]')" \
  "$@"
