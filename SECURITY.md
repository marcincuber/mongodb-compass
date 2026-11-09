# Security policy

This project packages a shared browser-native database administration UI. Review [Architecture](docs/architecture.md) and [Configuration](docs/configuration.md) before connecting it to sensitive data or exposing it to other users.

## Report a vulnerability

Use **Security → Report a vulnerability** on GitHub if private reporting is enabled. Otherwise, open an issue asking for a private reporting channel without vulnerability details. Do not post exploits or secrets publicly.

Provide the affected image/revision, sanitized reproduction steps, impact, and any suggested mitigation privately. Do not send working credentials, tokens, private keys, or database contents. There is no guaranteed response time or published support window. Report upstream component issues through their disclosure process too when appropriate.

## Deployment boundaries

- HTTP Basic authentication protects browser pages, APIs, and database WebSockets. Use HTTPS for network browser access. The container publishes HTTP on 6080; the Node.js backend is loopback-only on 6081.
- Authenticated users share server connection configuration and database privileges. The browser driver receives connection strings, including database credentials. Deploy separate instances and Secrets for separate trust boundaries. UI authentication is not a per-user database role or audit system.
- The DocumentDB profile rejects unsafe startup settings and forces server-owned verified TLS for browser database sockets. Browser-supplied insecure flags and replacement trust material are ignored. Connection editing and the embedded shell are disabled for that profile. Require TLS at the database too.
- Browser WebSockets with a different Origin host are rejected. Authorized users can access database endpoints reachable by the application; use routing, security groups, NetworkPolicy, and least-privilege database accounts to bound that access.
- The application runs as UID/GID 10001 and supports a read-only image filesystem, dropped capabilities, and temporary writable mounts. There is no Electron sandbox exception or desktop display service.
- Connection storage, runtime configuration, browser sessions, Secrets, backups, and exported results are sensitive. Optional server-side connection storage encrypts connection strings using a separate storage password; retain its salt file and password with protected backups.
- `/healthz` is intentionally public and static. It does not report database availability or expose application data.

## Dependencies and verification

The browser package and transitive dependencies are integrity-locked. Builds disable npm install scripts and apply reviewed integration hooks; source drift fails the build. Upstream notices ship with the runtime. Review [licensing and upstream components](README.md#licensing-and-upstream-components).

Build and scan the exact image being published. The gate blocks detected HIGH/CRITICAL vulnerabilities, including unfixed ones, and fails on incomplete scans. It does not prove the absence of unknown vulnerabilities or cover every dependency embedded in frontend bundles. See [Automation](docs/automation.md).

The AWS CA bundle is fetched at build time. Use a current trusted bundle and immutable published image tags. Protect settings backups with the same access controls as the original volume.
