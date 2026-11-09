#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
platform="${PLATFORM:-linux/amd64}"
if [[ "$platform" != linux/amd64 ]]; then
  echo 'This project currently validates PLATFORM=linux/amd64.' >&2
  exit 1
fi
build_args=(--pull --platform "$platform" --tag "${IMAGE_NAME:-mongodb-compass}:${IMAGE_TAG:-local}")
exec docker build "${build_args[@]}" "$@" "$project_dir"
