# Security scanning and Compass upgrades

Return to the [README](../README.md), [publishing guide](publishing.md), or [contributor guide](../CONTRIBUTING.md).

## Workflows

| Workflow in the Actions tab | When it runs | Result |
| --- | --- | --- |
| **Container security** | Pull requests, pushes to `main`, daily at 06:23 UTC, or **Run workflow** | Tests, fresh image build, vulnerability report, and HIGH/CRITICAL gate |
| **Upgrade Compass** | Mondays at 05:41 UTC, or **Run workflow** | Resolve a stable release, run the same checks, then open/update an upgrade PR if needed |

Both use the [shared verification workflow](../.github/workflows/verify-image.yml). Daily rebuilding catches new vulnerability disclosures and refreshes Ubuntu security packages even when repository code has not changed. GitHub schedules run on the default branch and may start later than their requested time.

The workflows build temporary verification images. They do not publish a public image, push to ECR, update a running deployment, or rotate its CA bundle. Operators must publish and deploy a reviewed image separately.

## Read the security result

Open a workflow run and read its **Summary**. The scan reports the exact image config ID, pinned scanner, report timestamp, and severity counts:

- **PASS: 0 HIGH and 0 CRITICAL vulnerabilities detected** appears only after a complete, validated scan of that image.
- Any HIGH or CRITICAL finding fails the job, including findings without an available fix.
- Scanner errors, missing package inventory, or a mismatched image report fail the job; they cannot produce a clean result.
- MEDIUM, LOW, and UNKNOWN findings remain visible but do not block this gate.

Download the `security-reports-...` artifact for `summary.md`, the complete `trivy.json`, the HIGH/CRITICAL text report, and SARIF. Reports are retained for 30 days, including failed scans. SARIF is an artifact and can be imported into your reporting tooling; no paid GitHub code-scanning feature is required to read the job summary or artifacts.

The scanner is Trivy 0.76.2, pinned by image digest. It scans an archive of the built image with current vulnerability data, OS packages, and discoverable language packages. It does not receive the Docker socket, and no ignore list or unfixed-vulnerability exclusion is used. A passing scan means no known HIGH/CRITICAL findings were detected in that scanner's coverage at that time; it does not prove the absence of unknown or undiscoverable vulnerabilities, including dependencies hidden in bundled application archives.

## Run a scan locally

Docker and Python 3 are required. The scanner and vulnerability database are downloaded automatically:

```sh
make build
make scan
```

Read `reports/security/summary.md` or `trivy.txt`. The command exits 1 for blocking findings and nonzero for scan errors. Reports and the `.cache/trivy` database cache are gitignored.

To rebuild with fresh base layers and OS updates first:

```sh
./scripts/build.sh --pull --no-cache
make scan
```

Resolve findings by rebuilding with available OS fixes or upgrading Compass. If an upstream fix is not available, the gate stays red. There are no automatic exemptions.

## Trigger a Compass upgrade

1. Open **Actions → Upgrade Compass → Run workflow**.
2. Leave `compass_version` as `latest`, or enter a stable version such as `1.53.2`.
3. Read the tests and scan summary. If a newer version passes, review the generated PR.

The upgrade helper reads the [official Compass release API](https://api.github.com/repos/mongodb-js/compass/releases/latest), requires the stable Linux amd64 installer and its published SHA-256 digest, and rejects prereleases, downgrades, missing digests, and changed checksums for an already pinned version. The Docker build independently verifies the downloaded installer against that digest.

The pipeline runs workflow linting, unit tests, ShellCheck, Kubernetes/Istio schema validation, a fresh amd64 image build, real GUI/authentication/Secret-file/persistence smoke tests, and the vulnerability gate. Checks run even if Compass is already current. Tests are executed before creating the PR, so validation does not depend on a second PR-triggered workflow.

An upgrade PR changes `Dockerfile` version/checksum pins, the README release link, publishing tag examples, and Kubernetes image tags. The PR job rechecks that the official checksum still matches the tested candidate. One branch, `automation/upgrade-compass`, is reused. PRs are never auto-merged; no workflow pushes to ECR or deploys to Kubernetes.

## Enable and maintain

- Commit and push these files to the repository's default branch, with GitHub Actions enabled. The push trigger currently names `main`; adjust it if your default branch differs.
- In **Settings → Actions → General → Workflow permissions**, enable **Allow GitHub Actions to create and approve pull requests** for upgrade PR creation. The workflow grants write permissions only to the PR job; validation jobs have read-only repository access.
- Configure branch protection/rulesets to require the container verification check before merging.
- GitHub may require approval of PR workflow runs created using `GITHUB_TOKEN`; see [GitHub's workflow triggering rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow). The upgrade run already validates the candidate before opening its PR.
- Action references use full commit SHAs; scanner references use a full image digest. Review and update these pins and validation-tool checksums when upgrading the automation tools.

You can inspect or apply the same release update locally:

```sh
python3 scripts/upgrade_compass.py --version latest --check
python3 scripts/upgrade_compass.py --version latest
```

After merging an upgrade, [build and publish](publishing.md) its new image tag before changing a live deployment.
