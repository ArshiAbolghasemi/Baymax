#!/usr/bin/env bash
#
# Create a migration from the difference between the models and the database.
#
#   ./entrypoints/makemigrations.sh "add answer source column"
#   EMPTY=true ./entrypoints/makemigrations.sh "backfill answer language"
#
# Autogenerate compares baymax's models against the database the DATABASE_URL
# points at, so that database must already be at head — run migrate.sh first.
# Set EMPTY=true for a hand-written migration (data backfills, index rebuilds),
# which autogenerate cannot infer.
#
# Always read the generated file before committing it. Autogenerate does not
# detect table or column renames (it emits a drop plus an add, which loses
# data), and it cannot see CHECK constraints or server-side defaults it did not
# create.

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

if [ $# -lt 1 ]; then
  echo "usage: $0 \"short description of the change\"" >&2
  exit 1
fi

MESSAGE="$1"

if [ "${EMPTY:-false}" = "true" ]; then
  "${RUNNER[@]}" alembic revision -m "$MESSAGE"
else
  "${RUNNER[@]}" alembic revision --autogenerate -m "$MESSAGE"
fi

printf '\n%s [makemigrations] review the file above, then apply it with ./entrypoints/migrate.sh\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%S)" >&2
