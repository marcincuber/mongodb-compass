#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
platform="${PLATFORM:-linux/amd64}"
if [[ "$platform" != linux/amd64 ]]; then
  echo 'The official Compass Linux package requires PLATFORM=linux/amd64.' >&2
  exit 1
fi
build_args=(--platform "$platform" --tag "${IMAGE_NAME:-mongodb-compass}:${IMAGE_TAG:-local}")
if [[ -n "${COMPASS_VERSION:-}" || -n "${COMPASS_SHA256:-}" ]]; then
  : "${COMPASS_VERSION:?Set COMPASS_VERSION and COMPASS_SHA256 together}"
  : "${COMPASS_SHA256:?Set COMPASS_VERSION and COMPASS_SHA256 together}"
  build_args+=(--build-arg "COMPASS_VERSION=$COMPASS_VERSION" --build-arg "COMPASS_SHA256=$COMPASS_SHA256")
fi
exec docker build "${build_args[@]}" "$@" "$project_dir"
