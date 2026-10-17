#!/bin/sh
# Operate only the local administrative services with the existing core volumes.
set -eu
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo 'Missing .env; see docs/admin-workspace.md.' >&2
  exit 1
fi
if [ "$#" -ne 1 ]; then
  echo 'Usage: ./admin-local.sh {build|database|migrate|start|stop|status|logs|config|check}' >&2
  exit 2
fi
case "$1" in
  build) set -- build admin-api admin-web ;;
  database) set -- up -d --no-deps --wait --wait-timeout 90 postgres ;;
  migrate) set -- run --rm --no-deps database-migrations ;;
  start) set -- up -d --no-build --wait --wait-timeout 90 admin-web admin-sync ;;
  stop) set -- stop admin-web admin-api admin-sync ;;
  status) set -- ps postgres admin-api admin-sync admin-web ;;
  logs) set -- logs --tail=50 admin-api admin-sync admin-web ;;
  config) set -- config --quiet ;;
  check)
    port=$(docker port mirror-core-admin-web-1 8080/tcp | awk -F: '$1 == "127.0.0.1" {print $2}')
    if [ -z "$port" ]; then
      echo 'The administrative frontend has no active loopback port.' >&2
      exit 1
    fi
    exec python ../mirror-deploy/scripts/check_admin_lan.py --admin-url "http://127.0.0.1:$port"
    ;;
  *)
    echo 'Unknown operation. Use build, database, migrate, start, stop, status, logs, config or check.' >&2
    exit 2
    ;;
esac
exec docker compose --project-name mirror-core \
  --env-file .env -f docker-compose.yml --profile admin-lan "$@"
