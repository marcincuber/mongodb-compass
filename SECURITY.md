# Security policy

This project packages a shared Compass desktop for browser access. Review [Architecture](docs/architecture.md) and [Configuration](docs/configuration.md) before exposing it to other users or connecting it to sensitive data.

## Report a vulnerability

Use **Security → Report a vulnerability** on the GitHub repository if private vulnerability reporting is enabled. If it is unavailable, open an issue asking the maintainer for a private reporting channel without including vulnerability details. Do not disclose exploits, credentials, or private infrastructure information in a public issue.

Include the affected commit/image version, a sanitized description, reproduction steps, expected impact, and any suggested mitigation in the private report. Never send working database credentials, tokens, private keys, or database contents. There is no guaranteed response time or published support window.

For a vulnerability in an upstream component, use that component's disclosure process. Let this repository's maintainer know privately when its packaging or configuration is also affected.

## Deployment boundaries

- Each instance is one shared desktop. Anyone with its UI credentials can interact with the same Compass session and saved connections. Use separate deployments and credentials for separate users or trust boundaries.
- HTTP Basic authentication protects browser pages and WebSockets. Use HTTPS for browser traffic over a network; the container itself listens on HTTP port 6080. `/healthz` is intentionally public and returns a static response.
- The DocumentDB startup policy requires verified TLS for the generated connection. It does not constrain connections a user adds or edits inside Compass. Require TLS at the database as well.
- The desktop runs as UID/GID 10001. Electron uses `--no-sandbox` and a basic password store for container compatibility. Container isolation and access control are therefore significant parts of the deployment boundary.
- Saved Compass settings, exports, and persistent volumes can contain database credentials. Restrict access to them, including backups and snapshots. Kubernetes Secrets also require appropriate cluster access controls.
- Use a database account with only the permissions needed for the intended work. UI authentication does not limit database privileges or provide per-user application audit records.

## Updates and scanning

Use the latest reviewed project revision, rebuild with current base layers and OS updates, and scan the exact image you intend to publish. See [Security scanning and upgrades](docs/automation.md).

The scan gate fails on detected HIGH or CRITICAL vulnerabilities, including unfixed findings, and fails if a complete report cannot be validated. A passing result applies to that image, scanner coverage, vulnerability database, and time. It does not guarantee that the image is free from vulnerabilities.

The AWS CA bundle is fetched at build time. Rebuild without cache or mount a current trusted bundle when certificate updates are needed. Keep published tags immutable, retain the previous known working image for rollback, and verify live database connectivity after deployment.
