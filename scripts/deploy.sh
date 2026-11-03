#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] || { echo '.env missing: run python3 scripts/generate_env.py --admin-email YOUR_EMAIL' >&2; exit 1; }
chmod 600 .env
docker compose config --quiet
# --wait confirms db, API, and container nginx are healthy (Docker Compose v2).
docker compose up -d --build --wait --wait-timeout 180
docker compose ps
curl --fail --silent --show-error http://127.0.0.1:"${APP_BIND_PORT:-18080}"/api/v1/health
printf '\n'
