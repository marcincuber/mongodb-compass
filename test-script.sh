#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Local development defaults. Override these when first creating the containers.
# Existing MongoDB credentials are not changed. Compass reloads these on each run.
DB_PASSWORD="${DB_PASSWORD:-admin}"
UI_PASSWORD="${UI_PASSWORD:-admin}"
storage_password="${COMPASS_CONNECTIONS_PASSWORD:-}"
compass_image="${IMAGE_NAME:-mongodb-compass}:${IMAGE_TAG:-local}"

# Fail immediately if Docker is unavailable, before checking existing resources.
docker info > /dev/null

# Build the Compass UI only from this repository's Dockerfile.
"$project_dir/scripts/build.sh"

# Create a shared network and persistent database storage.
if ! docker network inspect compass-local > /dev/null 2>&1; then
  docker network create compass-local
fi
docker volume create mongodb-local-data > /dev/null
docker volume create mongodb-compass-config > /dev/null

ensure_network() {
  local attached
  attached="$(docker container inspect --format \
    '{{if index .NetworkSettings.Networks "compass-local"}}connected{{end}}' "$1")"
  if [[ "$attached" != connected ]]; then
    docker network connect compass-local "$1"
  fi
}

# Start MongoDB 8.0.
if docker container inspect mongodb-local > /dev/null 2>&1; then
  ensure_network mongodb-local
  docker start mongodb-local
  echo 'Reusing mongodb-local with its existing database credentials.'
else
  docker run -d \
    --name mongodb-local \
    --network compass-local \
    -p 127.0.0.1:27017:27017 \
    -v mongodb-local-data:/data/db \
    -e MONGO_INITDB_ROOT_USERNAME=localadmin \
    -e MONGO_INITDB_ROOT_PASSWORD="$DB_PASSWORD" \
    mongo:8.0
fi

# Always run the image just built, with the requested port and credentials.
# Preserve existing settings before replacing the local UI container.
if docker container inspect mongodb-compass > /dev/null 2>&1; then
  docker stop --timeout 20 mongodb-compass > /dev/null
  settings_volume="$(docker container inspect --format \
    '{{range .Mounts}}{{if eq .Destination "/home/compass/.config"}}{{.Name}}{{end}}{{end}}' mongodb-compass)"
  if [[ "$settings_volume" != mongodb-compass-config ]]; then
    docker cp mongodb-compass:/home/compass/.config/. - | \
      docker run --rm -i --platform linux/amd64 --user 0:0 --network none \
        --mount type=volume,src=mongodb-compass-config,dst=/settings \
        --entrypoint python3 "$compass_image" -c '
import os
import sys
import tarfile

with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
    archive.extractall("/settings", filter="data")
for parent, directories, files in os.walk("/settings"):
    os.chown(parent, 10001, 10001, follow_symlinks=False)
    for name in directories + files:
        os.chown(os.path.join(parent, name), 10001, 10001, follow_symlinks=False)
'
  fi
  docker rm mongodb-compass > /dev/null
fi
docker run -d \
    --name mongodb-compass \
    --platform linux/amd64 \
    --network compass-local \
    -p 127.0.0.1:6080:6080 \
    --cap-drop=ALL \
    --security-opt=no-new-privileges:true \
    --mount type=volume,src=mongodb-compass-config,dst=/home/compass/.config \
    -e UI_USERNAME=admin \
    -e UI_PASSWORD="$UI_PASSWORD" \
    -e COMPASS_CONNECTIONS_PASSWORD="$storage_password" \
    -e CONNECTION_TYPE=mongodb \
    -e COMPASS_CONNECTION_NAME='Local MongoDB' \
    -e MONGODB_HOST=mongodb-local \
    -e MONGODB_PORT=27017 \
    -e MONGODB_USERNAME=localadmin \
    -e MONGODB_PASSWORD="$DB_PASSWORD" \
    -e MONGODB_AUTH_SOURCE=admin \
    -e MONGODB_TLS=false \
    "$compass_image"

echo 'Waiting for the Compass browser application to become ready...'
deadline=$((SECONDS + 120))
while ! docker exec mongodb-compass python3 /opt/compass-container/healthcheck.py > /dev/null 2>&1; do
  if [[ "$(docker container inspect --format '{{.State.Running}}' mongodb-compass)" != true ]] || (( SECONDS >= deadline )); then
    docker logs --tail 40 mongodb-compass >&2
    echo 'Compass did not become ready. Review the container logs above.' >&2
    exit 1
  fi
  sleep 2
done

echo 'Compass is ready: http://localhost:6080 (UI username: admin).'
echo 'Use UI_PASSWORD to log in; the local default is admin.'
echo 'Select mongodb-local:27017 in the browser sidebar and click Connect.'
echo 'MongoDB data and Compass settings are preserved in named Docker volumes.'
