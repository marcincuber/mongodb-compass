# Contributing

Contributions that make Compass easier to deploy, operate, and understand are welcome. You can help with documentation, bug reports, configuration examples, tests, or runtime changes. An AWS account is not required for most development.

Start with the [README](README.md), then use [Architecture](docs/architecture.md) to find the relevant code. Report vulnerabilities using the [security policy](SECURITY.md), rather than a public issue.

## Before you start

- Search existing issues and pull requests for related work.
- For a substantial behavior change, open an issue describing the problem and proposed approach before investing in an implementation.
- Keep each pull request focused on one problem. Small documentation corrections can go straight to a pull request.
- Check the [licensing status](README.md#licensing). This repository does not yet provide a project license or a contributor agreement; ask the maintainer to clarify terms if that affects your contribution.

## Development setup

Fork the repository on GitHub, clone your fork, and create a branch:

```sh
git clone https://github.com/YOUR_GITHUB_USERNAME/mongodb-compass.git
cd mongodb-compass
git switch -c describe-your-change
```

Run commands from the repository root. The runtime, helper scripts, and Python tests use the standard library; there is no Python dependency installation step.

| Tool | Used for |
| --- | --- |
| Python 3 | Runtime helpers and unit tests; CI runs Python 3.14 |
| Make, Bash, ShellCheck | Repository commands and shell validation |
| OpenSSL with `passwd -6` support | UI password hashing and temporary test certificates |
| Docker with Linux amd64 support | Image builds and desktop smoke tests |
| kubeconform | Kubernetes and Istio manifest validation |
| actionlint | GitHub Actions workflow validation |
| Docker Compose 2.30+ | Optional local Compose workflow |
| kubectl and AWS CLI v2 | Optional live Kubernetes and ECR checks |

On macOS, ensure `openssl` on your `PATH` supports `passwd -6`; some system-provided versions do not. Install the required tools using their upstream instructions or your package manager. CI's exact validation-tool versions and checksums are in [verify-image.yml](.github/workflows/verify-image.yml).

Keep local credentials in the gitignored `.env.runtime` or `secrets/` directory. Never place real endpoints or credentials in examples, test fixtures, screenshots, issue reports, or pull requests.

## Choose the right checks

| Change | Local validation |
| --- | --- |
| Documentation only | Check relative links and anchors, shell syntax, and commands against current scripts; run functional checks if instructions change |
| Python runtime, authentication, connection handling, or shell scripts | `make test`; build and run smoke tests for runtime changes |
| Dockerfile or bundled application/dependencies | `make test`, a fresh build, `make smoke-test`, and `make scan` |
| Kubernetes manifests | `make eks-validate`; smoke-test any changed runtime assumptions |
| GitHub Actions or security/upgrade tooling | `actionlint`, `make test`, and the affected build/scan path |

The full verification sequence is:

```sh
make test
make eks-validate
actionlint
./scripts/build.sh --pull --no-cache
make smoke-test
make scan
```

`make test` runs Python unit tests followed by ShellCheck. To run a focused test module while developing:

```sh
python3 -m unittest discover -s tests -p 'test_connection.py' -v
```

Schema validation downloads Kubernetes and Istio schemas. Builds and scans also need internet access. Smoke tests use temporary local containers, ports, and a settings volume; they exercise the real desktop without an AWS account or database. They do not verify live DocumentDB connectivity, EKS scheduling, or Istio routing. State any live checks you performed separately.

For a custom image name/tag, pass the same values to every image-related command:

```sh
IMAGE_NAME=mongodb-compass IMAGE_TAG=dev make build
IMAGE_NAME=mongodb-compass IMAGE_TAG=dev make smoke-test
IMAGE_NAME=mongodb-compass IMAGE_TAG=dev make scan
```

## Implementation guidelines

- Preserve `linux/amd64` as the supported image target unless you add and verify the complete build and test path for another architecture.
- Keep UI login and database credentials separate. Protect browser pages and WebSockets consistently.
- Preserve the DocumentDB TLS startup policy: TLS, CA validation, certificate verification, and hostname verification must remain mandatory across every supported configuration source.
- Keep examples compatible with non-root execution, a read-only root filesystem, dropped Linux capabilities, and graceful termination.
- Preserve one desktop per deployment. A probe should verify desktop infrastructure without making database availability a restart condition.
- Use placeholder credentials and hosts. Avoid printing secrets or adding them to process arguments.
- Add meaningful regression tests for behavior changes. Keep documentation and examples aligned with the final behavior.
- Keep dependency and Action references pinned. Explain security implications when changing dependencies, authentication, or container privileges.

## Compass and dependency upgrades

Prefer the [automated upgrade workflow](docs/automation.md). To inspect a release locally without editing files:

```sh
python3 scripts/upgrade_compass.py --version latest --check
```

To apply the verified release pins locally:

```sh
python3 scripts/upgrade_compass.py --version latest
```

Review the resulting version/checksum changes and run the full verification sequence. Fresh builds and scans are required even if a change only refreshes OS packages. A passing security gate means no HIGH or CRITICAL findings were detected within the scanner's coverage at that time; do not describe it as a guarantee that the image has no vulnerabilities.

## Pull requests

Explain the problem, resulting behavior, and checks you ran using the pull request template. Include sanitized screenshots only when they help explain a UI issue. Mention compatibility changes, deployment interruptions, configuration changes, and any checks you could not run.

For documentation changes, keep commands copyable from the repository root, mark placeholders clearly, and link to the existing configuration reference instead of duplicating every option. Never publish a sample vulnerability report as a permanent claim about image security.

Pull requests are reviewed and merged manually. CI does not publish images to ECR or deploy to a cluster. A successful local test or PR check does not authorize a contributor to change a shared environment.
