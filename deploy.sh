#!/bin/sh
# Apply SQL + cross-store migrations before starting the new application release.
set -eu
cd "$(dirname "$0")"

docker-compose "$@" config --quiet
# Local Compose uses build contexts. Rebuild every service so Alembic includes
# the same release as the source mounted into API/workers/data-migrations.
docker-compose "$@" build --pull
# Old processes must not write while derived graph/files are being retired.
docker-compose "$@" stop api processing-worker processing-dispatcher pwa
docker-compose "$@" up -d --wait postgres arcadedb rabbitmq
for task in database-migrations arcadedb-schema data-migrations; do
  docker-compose "$@" up --no-deps --abort-on-container-exit --exit-code-from "$task" "$task"
done
# set -e leaves the application stopped if any migration failed.
docker-compose "$@" up -d
