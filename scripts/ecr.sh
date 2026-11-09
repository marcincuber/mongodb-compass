#!/usr/bin/env bash
set -euo pipefail
action="${1:-push}"
if [[ "$action" != push && "$action" != create ]]; then
  echo 'Usage: scripts/ecr.sh [push|create]' >&2
  exit 1
fi
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [[ -z "$region" ]]; then region="$(aws configure get region || true)"; fi
: "${region:?Set AWS_REGION or configure an AWS CLI region}"
account="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
if [[ ! "$account" =~ ^[0-9]{12}$ ]]; then echo 'Invalid AWS_ACCOUNT_ID' >&2; exit 1; fi
repository="${ECR_REPOSITORY:-mongodb-compass}"
if [[ "$action" == create ]]; then
  exec aws ecr create-repository --region "$region" --repository-name "$repository" \
    --image-scanning-configuration scanOnPush=true --image-tag-mutability IMMUTABLE
fi
image="${IMAGE_NAME:-mongodb-compass}:${IMAGE_TAG:-local}"
architecture="$(docker image inspect "$image" --format '{{.Os}}/{{.Architecture}}')"
if [[ "$architecture" != linux/amd64 ]]; then
  echo 'Build a local linux/amd64 image with make build before publishing.' >&2
  exit 1
fi
# Use the returned URI so AWS partitions (including China) use the correct DNS suffix.
repository_uri="$(aws ecr describe-repositories --region "$region" --registry-id "$account" \
  --repository-names "$repository" --query 'repositories[0].repositoryUri' --output text)"
if [[ -z "$repository_uri" || "$repository_uri" == None || "$repository_uri" != */"$repository" ]]; then
  echo 'ECR repository not found. Create it with make ecr-create first.' >&2
  exit 1
fi
registry="${repository_uri%%/*}"
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"
remote_image="$repository_uri:${ECR_TAG:-${IMAGE_TAG:-local}}"
docker tag "$image" "$remote_image"
docker push "$remote_image"
printf 'Published %s\n' "$remote_image"
