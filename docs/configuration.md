# Configuration reference

Return to the [README](../README.md) or [Kubernetes guide](../k8s/README.md).

Pass application variables with Docker `-e`, an env file, or a Kubernetes Secret/ConfigMap. Use Secrets for credentials and ConfigMaps for nonsecret connection settings. Values are read at startup; restart/recreate after changes.

## UI login

| Variable | Meaning |
| --- | --- |
| `UI_USERNAME`, `UI_PASSWORD` | Required HTTP Basic login for all browser pages, APIs, and WebSockets |
| `UI_USERNAME_FILE`, `UI_PASSWORD_FILE` | Mounted-file alternatives |
| `COMPASS_CONNECTION_NAME` | Application display label |

The username cannot contain `:`. UI credentials cannot contain control characters. Missing credentials stop startup. Nginx stores a salted SHA-512 password hash in a private temporary file and removes the Authorization header before proxying. The backend listens only on container loopback port 6081; only authenticated port 6080 is published.

`/healthz` is public and returns static `ok` text. Health probes check that endpoint and the internal application's health response, bypassing outbound proxies. They do not test the database or restart pods because a database is unavailable.

The server runs as UID/GID 10001. Browser HTTPS terminates at your ingress/proxy. UI credentials grant access to a shared set of server connections, not an independent identity or database role. Authenticated users receive connection strings, including database credentials, for the browser database driver. Only share an instance within one trust boundary.

## Database connection

Set `MONGODB_URI` or `MONGODB_HOST`. With neither set, the generic MongoDB profile opens an empty connection editor. Environment-defined connections are recreated at startup. Generic MongoDB permits additional connections; DocumentDB disables editing and requires the validated environment connection.

| Variable | Meaning / default |
| --- | --- |
| `CONNECTION_TYPE` | `mongodb` (default) or `documentdb` |
| `MONGODB_URI` | Full `mongodb://` or `mongodb+srv://` URI |
| `MONGODB_HOST` | Host, bracketed IPv6, or comma-separated seeds with optional ports |
| `MONGODB_PORT` | Override port for one non-SRV host |
| `MONGODB_SCHEME` | Override `mongodb` / `mongodb+srv` |
| `MONGODB_DATABASE` | Override URI database |
| `MONGODB_USERNAME`, `MONGODB_PASSWORD` | Raw credentials, percent-encoded by the wrapper |
| `MONGODB_AUTH_SOURCE`, `MONGODB_AUTH_MECHANISM` | Driver authentication options |
| `MONGODB_AUTH_MECHANISM_PROPERTIES` | Driver authentication mechanism properties |
| `MONGODB_REPLICA_SET`, `MONGODB_READ_PREFERENCE` | Replica set and read preference |
| `MONGODB_RETRY_WRITES`, `MONGODB_DIRECT_CONNECTION` | Boolean driver options |
| `MONGODB_TLS` | `true` / `false`; mandatory `true` for DocumentDB |
| `MONGODB_TLS_CA_FILE` | Server CA bundle path inside the container |
| `MONGODB_TLS_CERTIFICATE_KEY_FILE` | Combined client certificate/private key PEM path |
| `MONGODB_TLS_CERTIFICATE_KEY_FILE_PASSWORD` | Optional encrypted client key password |
| `MONGODB_TLS_INSECURE` | Must be `false` or unset for DocumentDB |
| `MONGODB_TLS_ALLOW_INVALID_CERTIFICATES`, `MONGODB_TLS_ALLOW_INVALID_HOSTNAMES` | Must be `false` or unset for DocumentDB |
| `MONGODB_SERVER_SELECTION_TIMEOUT_MS`, `MONGODB_CONNECT_TIMEOUT_MS` | Driver timeouts |
| `MONGODB_OPTIONS` | JSON object for additional supported URI options; arrays represent repeated options |

Precedence: URI → missing DocumentDB defaults → JSON options → individual nonempty variables. Empty values are ignored. Remove example host/port/auth-source settings when a complete URI should supply them. Duplicate JSON option keys are rejected.

```dotenv
MONGODB_URI=mongodb+srv://cluster.example.mongodb.net/application
MONGODB_USERNAME=my-user
MONGODB_PASSWORD=my-raw-password
MONGODB_OPTIONS={"appName":"Compass UI","serverSelectionTimeoutMS":10000}
```

In env files, omit surrounding shell quotes and `$` escaping. For shell `-e` values, quote as needed. A URI with embedded credentials must already percent-encode them.

## DocumentDB

`CONNECTION_TYPE=documentdb` supplies TLS, `/opt/certs/global-bundle.pem`, `replicaSet=rs0`, `readPreference=secondaryPreferred`, `retryWrites=false`, and `authSource=admin`. Use an existing cluster's endpoint and database credentials, with network access from the container to that endpoint.

The startup policy rejects `tls=false`, `ssl=false`, `tlsInsecure=true`, disabled certificate/hostname verification, and invalid CA bundles. It checks URI, JSON, and environment values before overrides and after merging, so a later safe option cannot hide an insecure input. A CA file must be readable PEM/X.509 with at least one currently valid CA certificate.

The browser-to-server database WebSocket uses a server-owned TLS policy: browser-supplied insecure flags, CA replacements, key material, and hostname overrides are ignored. DocumentDB database sockets always use TLS 1.2 or newer, the configured trusted CA, and the actual destination hostname for certificate verification. Client certificate/private-key files, including encrypted keys, are loaded on the server and removed from connection strings returned to the browser. Connection editing and the embedded shell are disabled for this profile. Require TLS on the database cluster too.

Use the real endpoint hostname. The container needs VPC routing, DNS, TCP 27017 access, and security-group/NetworkPolicy allowances. Do not disable verification to work around a tunnel or DNS error. For a single forwarded endpoint, `MONGODB_DIRECT_CONNECTION=true` removes the preset replica set unless explicitly provided.

For DocumentDB 8.0, the client connects to your existing 8.0 cluster. `retryWrites=false` remains the compatibility default; server features vary by engine release. DocumentDB supports a subset of MongoDB APIs, so browser features may differ. Validate the operations you need against the target cluster.

The AWS CA bundle is downloaded at image build time. Rebuild without cache or mount a current trusted bundle and set `MONGODB_TLS_CA_FILE` when it needs refreshing. AWS's [connection guidance](https://docs.aws.amazon.com/documentdb/latest/devguide/connect_programmatically.html) describes cluster networking and certificate use.

## Mounted secrets and files

These variables accept `_FILE` alternatives:

- `UI_USERNAME`, `UI_PASSWORD`
- `MONGODB_URI`, `MONGODB_USERNAME`, `MONGODB_PASSWORD`, `MONGODB_TLS_CERTIFICATE_KEY_FILE_PASSWORD`
- `COMPASS_CONNECTIONS_PASSWORD`

Set the value or its file alternative, not both. Trailing line endings are removed; other spaces are preserved. Files and parent directories must be readable by UID/GID 10001. CA/key paths refer to container paths.

```dotenv
UI_USERNAME_FILE=/run/secrets/ui_username
UI_PASSWORD_FILE=/run/secrets/ui_password
MONGODB_PASSWORD_FILE=/run/secrets/database_password
```

Kubernetes examples import Secret keys through `envFrom.secretRef`. For Secret-file mounts, use `defaultMode: 0440`, read-only mounts, and `fsGroup: 10001`. See [Kubernetes Secrets](../k8s/README.md#credentials-and-rotation).

The wrapper writes a private startup JSON file and passes its path to Node.js. Database credentials are not placed in process arguments. Environment values, saved profiles, browser sessions, and API responses are still sensitive to users with host/container/UI access.

## Connection storage

Generic MongoDB connections added through the UI stay in memory unless `COMPASS_CONNECTIONS_PASSWORD` (or `_FILE`) is set. With this separate stable password, the server encrypts saved connection strings into `/home/compass/.config/connections-*.json`, with a companion salt file. Mount that directory to retain them across replacement. Browser preferences such as theme remain in browser storage.

Changing the storage password selects a different store; it does not re-encrypt the existing one. Back up both files, keep the original password available, and treat the volume and backups as sensitive. UI password rotation is independent of the storage password. Environment-defined connections do not require persistent storage.

## Supported features

The browser port has a different feature set from desktop Compass. Desktop export files, built-in SSH tunnels, IAM database authentication, and the embedded shell are not supported by this container. Use a reachable database endpoint and database credentials. Unsupported SSH/export/IAM configuration fails clearly at startup.

Raw upstream `CW_*` environment variables are ignored so they cannot override port binding, authentication, or the server-owned DocumentDB policy.

## Compose settings

| Variable | Default |
| --- | --- |
| `IMAGE_NAME`, `IMAGE_TAG` | `mongodb-compass`, `local` |
| `COMPASS_ENV_FILE` | `.env.runtime` |
| `BIND_ADDRESS`, `WEB_PORT` | `127.0.0.1`, `6080` |

These affect Compose on the host. Other variables configure the application inside the container.
