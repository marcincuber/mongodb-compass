# Build and publish to ECR

Return to the [README](../README.md) or continue to [Kubernetes](../k8s/README.md).

## Build and verify

Docker must be running. The validated target is `linux/amd64`:

```sh
make build
# Equivalent:
docker build --pull --platform linux/amd64 -t mongodb-compass:local .
make smoke-test
make scan
```

The build installs the browser package from `web/package.json` and its integrity-locked dependency tree. The package version is fixed for this application release. `make build` uses `scripts/build.sh`, defaults to Linux amd64, and pulls current base images. BuildKit caches npm downloads for repeated builds; application dependencies remain locked.

For the complete local verification sequence, run `make verify`; required tools are listed in [Contributing](../CONTRIBUTING.md#development-setup).

To refresh base layers, OS packages, and the build-time AWS CA bundle:

```sh
./scripts/build.sh --no-cache
make smoke-test
make scan
```

Use the same `IMAGE_NAME`/`IMAGE_TAG` for the build, smoke test, scan, Compose run, and push.

## Publish when needed

Requirements: AWS CLI v2, configured credentials, a region, and ECR push permissions. Authenticate first, for example with `aws sso login --profile my-profile`.

```sh
export AWS_PROFILE=my-profile
export AWS_REGION=eu-west-2
export ECR_REPOSITORY=mongodb-compass

# Once, only if the repository does not exist:
make ecr-create

make build
make smoke-test
make scan
ECR_TAG=0.5.2-1 make push
```

`make ecr-create` creates a repository with immutable tags and scan-on-push. `make push` checks that the local image is Linux amd64, resolves the repository, authenticates Docker with `--password-stdin`, tags the image, and pushes. It does not build or create a repository implicitly. ECR scanning does not replace this project's HIGH/CRITICAL gate.

Copy the printed image URI into your private manifest. Example tags use `BROWSER_PACKAGE_VERSION-BUILD_REVISION`; `0.5.2` identifies Compass Web, not official desktop Compass. Immutable tags cannot be overwritten. If pinning a digest, use the registry digest after pushing, not a local image config ID.

| Setting | Default |
| --- | --- |
| `IMAGE_NAME` / `IMAGE_TAG` | `mongodb-compass` / `local` |
| `PLATFORM` | `linux/amd64` |
| `ECR_REPOSITORY` | `mongodb-compass` |
| `ECR_TAG` | Local tag; set a release tag explicitly |
| `AWS_REGION` | `AWS_DEFAULT_REGION`, then AWS CLI configuration |
| `AWS_ACCOUNT_ID` | STS caller account; override for an existing cross-account registry |

Record the source revision, published image reference, and scan report. Publishing alone does not update running workloads. EKS image-pull permissions, publishing credentials, and database credentials are separate. See [AWS's ECR CLI guide](https://docs.aws.amazon.com/AmazonECR/latest/userguide/getting-started-cli.html).
