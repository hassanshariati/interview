#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] || { echo '.env missing: run python3 scripts/generate_env.py --admin-email YOUR_EMAIL' >&2; exit 1; }
chmod 600 .env
docker compose config --quiet
# --wait confirms db, API, and container nginx are healthy (Docker Compose v2).
docker compose up -d --build --wait --wait-timeout 180
docker compose ps
proxy_address="$(docker compose port proxy 8080 | head -n 1)"
[[ -n "$proxy_address" ]] || { echo "Proxy port is not published" >&2; exit 1; }
curl --fail --silent --show-error "http://${proxy_address}/api/v1/health"
printf '\n'
