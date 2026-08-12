#!/usr/bin/env bash
#
# Apply database migrations.
#
#   ./entrypoints/migrate.sh              # upgrade to the latest revision
#   ./entrypoints/migrate.sh <revision>   # upgrade/downgrade to a specific one
#
# Only revisions not already recorded in the alembic_version table are run, so
# this is safe to call on every boot — which is exactly what api.sh and
# celery.sh do. Concurrent callers serialise on a Postgres advisory lock taken
# in migrations/env.py, so the API and the worker starting together is fine.

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

TARGET="${1:-head}"

printf '%s [migrate] upgrading database to %s\n' "$(date -u +%Y-%m-%dT%H:%M:%S)" "$TARGET" >&2
"${RUNNER[@]}" alembic upgrade "$TARGET"
printf '%s [migrate] done\n' "$(date -u +%Y-%m-%dT%H:%M:%S)" >&2
