# Container verification and security scanning

Return to the [README](../README.md), [publishing guide](publishing.md), or [contributor guide](../CONTRIBUTING.md).

## Workflow

**Container security** runs on pull requests, pushes to `main`, daily at 06:23 UTC, and manually through **Actions → Container security → Run workflow**.

It calls [verify-image.yml](../.github/workflows/verify-image.yml) to validate the checked-out source:

1. Run Python and Node.js tests, ShellCheck, and workflow syntax checks.
2. Validate Kubernetes and Istio examples against their schemas.
3. Build a fresh Linux amd64 image with `--pull --no-cache`.
4. Run browser/API authentication, MongoDB transport, TLS/client-certificate, secret-file, and persistence checks.
5. Scan the exact built image and enforce the HIGH/CRITICAL gate.
6. Upload security reports, including reports from failed scans.

The workflow creates a verification image. Publishing to ECR and deploying to Kubernetes are separate steps in the [publishing](publishing.md) and [Kubernetes](../k8s/README.md) guides. Scheduled runs use the default branch and may start later than requested.

The MongoDB smoke fixture has up to 120 seconds to complete its initialization and restart. Readiness requires an authenticated ping from the application container through the Docker network. Each check has a timeout; an exited fixture fails immediately. Initialization failures print the container state, last connection-check result, and recent database logs before cleanup.

## Read the security result

Open a workflow run's **Summary**. A complete validated scan reports its image config ID, pinned scanner, timestamp, and severity counts:

- **PASS: 0 HIGH and 0 CRITICAL vulnerabilities detected** requires a matching image report and package inventory.
- HIGH/CRITICAL findings fail the job, including unfixed findings.
- Scanner errors, missing inventory, or mismatched image reports fail; they cannot produce a clean result.
- Other severities remain visible without blocking this gate.

Download the `security-reports-...` artifact for Markdown, JSON, text, and SARIF reports. Reports are retained for 30 days, including failed scans. SARIF is downloadable; publishing it to GitHub code scanning is not required.

Trivy 0.76.2 is pinned by digest and scans an archive of the exact image, including OS and discoverable Node.js packages. It receives no Docker socket. No ignore list or unfixed-finding exclusion is used. A passing result is specific to the image, scan time, and scanner coverage. Dependencies embedded in frontend bundles may not be identifiable, so the report is not a guarantee that the application has no vulnerabilities.

## Run locally

For the complete sequence (tests, schemas, build, container smoke tests, and scan):

```sh
make verify
```

See [Contributing](../CONTRIBUTING.md#development-setup) for required tools. To scan an image you already built, use `make scan`.

Read `reports/security/summary.md` and `trivy.txt`. Reports and `.cache/trivy` are gitignored. The command exits nonzero for HIGH/CRITICAL findings or scanning errors. There are no automatic exemptions.

To build with freshly fetched base images, OS packages, and the AWS CA bundle before scanning:

```sh
./scripts/build.sh --no-cache
make smoke-test
make scan
```

## Repository setup

- Commit and push the workflows to your default branch and enable GitHub Actions.
- Adjust the `main` push trigger if your default branch has a different name.
- Require the verification check through repository rulesets or branch protection.
- The workflows use read-only repository permissions. No AWS credentials or permission to create pull requests are required.
- Action references and Trivy use immutable pins. The application uses its npm integrity lock; fresh CI builds fetch the moving `node:24` tag with `--pull`.
