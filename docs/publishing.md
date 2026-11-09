# Build and publish to ECR

Return to the [README](../README.md) or continue to [Kubernetes deployment](../k8s/README.md).

## Build

Docker must be running. All builds target `linux/amd64`:

```sh
make build
# Equivalent:
docker build --platform linux/amd64 -t mongodb-compass:local .
```

To upgrade Compass, obtain the version and SHA-256 for the Linux amd64 package from its [official release](https://github.com/mongodb-js/compass/releases), then supply both:

```sh
COMPASS_VERSION=VERSION COMPASS_SHA256=SHA256 IMAGE_TAG=VERSION make build
```

Update both defaults in `Dockerfile` for a permanent upgrade. After building a custom tag, use the same `IMAGE_TAG` with Compose or publishing.

The [weekly/manual upgrade workflow](automation.md) can update these pins and run tests automatically. Container scans include unfixed findings and block HIGH/CRITICAL vulnerabilities. The Dockerfile updates installed Ubuntu packages during a fresh build; use `./scripts/build.sh --pull --no-cache` to refresh an existing local build's OS packages.

## Publish when needed

Requirements: AWS CLI v2, configured AWS credentials, an AWS region, and ECR push permissions. Authenticate first, for example with `aws sso login --profile my-profile`.

Build, test, and scan the same local image before publishing. Neither `make push` nor ECR's scan-on-push replaces the local HIGH/CRITICAL gate. The commands below also require Python 3 for smoke tests/scanning.

```sh
export AWS_PROFILE=my-profile
export AWS_REGION=eu-west-2
export ECR_REPOSITORY=mongodb-compass

# Once, only when the repository does not exist:
make ecr-create

make build
make smoke-test
make scan
# Choose a new tag for every image change.
ECR_TAG=1.53.2-6 make push
```

`make ecr-create` creates a repository in the authenticated account with immutable tags and scan-on-push. `make push` checks the existing local image is Linux amd64, finds the ECR repository, logs Docker in using `--password-stdin`, tags the image, and pushes it. It does not build or create a repository implicitly.

Copy the printed image URI into your Kubernetes manifest. Existing tags in an immutable repository cannot be overwritten: increment the suffix after changes to the base image, runtime, or dependencies.

The tag convention in these examples is `COMPASS_VERSION-BUILD_REVISION`: the Compass version identifies the upstream desktop, and the suffix identifies a packaging rebuild. Use a new suffix for OS fixes, runtime changes, or a refreshed CA bundle even when Compass itself has not changed. For deployments pinned by digest, use the pushed registry digest rather than a local image config ID.

Before deploying, record the published image reference, source revision, and scan report. Keep the previous image available for [rollback](operations.md#update-or-roll-back-an-image). Publishing does not update a running Kubernetes deployment.

| Setting | Default |
| --- | --- |
| `IMAGE_NAME` / `IMAGE_TAG` | `mongodb-compass` / `local` |
| `PLATFORM` | `linux/amd64` only |
| `ECR_REPOSITORY` | `mongodb-compass` |
| `ECR_TAG` | Local image tag; set a release tag explicitly |
| `AWS_REGION` | `AWS_DEFAULT_REGION`, then AWS CLI configuration |
| `AWS_ACCOUNT_ID` | Current account from STS; override for an existing cross-account registry |

The node role used by EKS to pull the image is separate from the credentials used to publish it and from any database authentication role. Cross-account repositories need the appropriate repository policy.

For the required ECR authentication/upload actions and CLI workflow, see [AWS's ECR guide](https://docs.aws.amazon.com/AmazonECR/latest/userguide/getting-started-cli.html). No AWS credentials are embedded in the image.
