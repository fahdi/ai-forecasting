#!/usr/bin/env bash
# Production deploy for /opt/ai-forecasting (RUNBOOK §1).
# Pulls main, rebuilds the changed services with the git SHA baked in, and
# waits for health. Usage (on the VPS):
#   scripts/deploy_prod.sh [services...]   # default: api dashboard
set -euo pipefail
cd "$(dirname "$0")/.."

SERVICES=("${@:-api dashboard}")
[ $# -gt 0 ] && SERVICES=("$@") || SERVICES=(api dashboard)

git pull --quiet origin main
export GIT_SHA="$(git rev-parse --short HEAD)"

# Refuse to ship a commit CI did not pass. Stdlib only, so the VPS system
# python3 is enough. Override with ALLOW_RED_CI=1 when you must.
python3 scripts/ci_gate.py --sha "$(git rev-parse HEAD)"

echo "deploying ${SERVICES[*]} at ${GIT_SHA}"

docker compose -f docker-compose.prod.yml build "${SERVICES[@]}"
docker compose -f docker-compose.prod.yml up -d "${SERVICES[@]}"

for i in $(seq 1 30); do
  status=$(docker compose -f docker-compose.prod.yml ps api --format '{{.Status}}')
  case "$status" in *healthy*) break;; esac
  sleep 2
done

# Only the api image bakes GIT_SHA, so its reported SHA proves nothing about a
# deploy that left api alone. Checking it anyway produced a DEPLOY MISMATCH on
# a successful `deploy_prod.sh dashboard`, and a deploy tool that cries wolf
# gets ignored.
deployed_api=false
for service in "${SERVICES[@]}"; do
  [ "$service" = "api" ] && deployed_api=true
done

if [ "$deployed_api" = true ]; then
  live_sha=$(docker compose -f docker-compose.prod.yml exec -T api python -c \
    "from app.core.config import settings; print(settings.GIT_SHA)")
  echo "live api git_sha: ${live_sha}"
  if [ "$live_sha" != "$GIT_SHA" ]; then
    echo "DEPLOY MISMATCH: built ${GIT_SHA} but api reports ${live_sha}" >&2
    exit 1
  fi
else
  echo "skipping live-SHA verification: api not among deployed services (${SERVICES[*]}); only the api image carries GIT_SHA"
fi
echo "deploy ok"
