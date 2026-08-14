#!/usr/bin/env bash
#
# Start the terminal client.
#
#   ./entrypoints/chat.sh
#   ./entrypoints/chat.sh --url http://hiro:8080/v1 --raw
#
# Environment (see .env.example):
#   BAYMAX_URL      base url of the hiro API, including /v1
#   BAYMAX_MODEL    model name to request
#   BAYMAX_API_KEY  bearer token
#
# Any extra arguments are passed straight through to the client.

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

# exec so the client owns the terminal and ctrl-c reaches it directly.
exec "${RUNNER[@]}" python -m cli "$@"
