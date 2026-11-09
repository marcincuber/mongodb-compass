# Configuration reference

Return to the [local quick start](../README.md#run-locally) or [Kubernetes guide](../k8s/README.md).

Application variables can be passed through Docker `-e NAME=value`, an env file, or a Kubernetes Secret/ConfigMap. Set credentials in a Secret; put nonsecret connection settings in a ConfigMap. Changes take effect when the container starts. Compose host settings are listed separately at the end.

## Choose a connection method

| Method | Set | When to use it |
| --- | --- | --- |
| Manual setup in Compass | UI credentials only; leave database/SSH variables unset | Explore or enter a connection in the desktop |
| Individual variables | `MONGODB_HOST` plus the required credentials/options | Straightforward MongoDB or DocumentDB configuration |
| Full connection URI | `MONGODB_URI` plus any intentional overrides | Reuse an existing connection string |
| Existing Compass export | `COMPASS_CONNECTION_FILE` with no database/SSH variables | Import a profile in the generic MongoDB mode |

For DocumentDB, also set `CONNECTION_TYPE=documentdb`; this selects mandatory verified TLS and the cluster defaults described [below](#documentdb). A complete inline Docker example is in the [README](../README.md#connect-to-amazon-documentdb). Start env-file configurations from [.env.example](../.env.example) or [.env.documentdb.example](../.env.documentdb.example).

## UI login and desktop

| Variable | Meaning |
| --- | --- |
| `UI_USERNAME`, `UI_PASSWORD` | Required HTTP Basic login for browser pages and WebSockets |
| `UI_USERNAME_FILE`, `UI_PASSWORD_FILE` | Read UI credentials from mounted files instead |
| `VNC_PASSWORD` | Optional second VNC login; 6–8 printable ASCII characters |
| `DESKTOP_WIDTH`, `DESKTOP_HEIGHT` | Default `1440` × `900`; each dimension accepts 640–7680 |

The username cannot contain `:`; UI credentials cannot contain control characters. The UI password has no VNC eight-character limit. The gateway stores a salted SHA-512 password hash in a private temporary file. Missing UI credentials stop startup.

Only `/healthz` is public, returning static `ok` text. Health probes check that endpoint, internal noVNC, and the VNC handshake; they bypass outbound proxy settings. Database connectivity errors appear inside Compass and do not restart the pod.

The desktop runs as UID/GID 10001. Electron uses `--no-sandbox` for container compatibility and a basic password store. Saved settings may contain database credentials, so protect settings volumes. Raw VNC and internal noVNC listen only on loopback. Browser HTTPS must terminate at your ingress/proxy; the included Istio example does this.

WebSocket ping frames are sent every 30 seconds to keep idle desktop connections active through proxies. Compass receives up to 10 seconds to exit before its display and gateway processes stop; remaining processes get a further 5 seconds. Kubernetes grants a 30-second termination period.

## Database connection

Set `MONGODB_URI` or `MONGODB_HOST`. To configure connections manually in Compass, omit all `MONGODB_*` and `SSH_*` variables and use `CONNECTION_TYPE=mongodb`.

| Variable | Meaning / default |
| --- | --- |
| `CONNECTION_TYPE` | `mongodb` (default) or `documentdb` preset |
| `COMPASS_CONNECTION_NAME` | Connection display name |
| `MONGODB_URI` | Full `mongodb://` or `mongodb+srv://` URI |
| `MONGODB_HOST` | Host, bracketed IPv6, or comma-separated seeds with optional ports |
| `MONGODB_PORT` | Override the port for one non-SRV host |
| `MONGODB_SCHEME` | Override with `mongodb` or `mongodb+srv` |
| `MONGODB_DATABASE` | Override the URI database name |
| `MONGODB_USERNAME`, `MONGODB_PASSWORD` | Override URI credentials; raw values are encoded automatically |
| `MONGODB_AUTH_SOURCE` | `authSource` |
| `MONGODB_AUTH_MECHANISM` | E.g. `SCRAM-SHA-256`, `MONGODB-X509`, `MONGODB-AWS` |
| `MONGODB_AUTH_MECHANISM_PROPERTIES` | Authentication mechanism properties |
| `MONGODB_REPLICA_SET`, `MONGODB_READ_PREFERENCE` | Replica set and read preference |
| `MONGODB_RETRY_WRITES`, `MONGODB_DIRECT_CONNECTION` | Boolean driver options |
| `MONGODB_TLS` | `true` / `false`; must be `true` in the DocumentDB profile |
| `MONGODB_TLS_INSECURE` | Must be `false` or unset for DocumentDB |
| `MONGODB_TLS_CA_FILE` | CA file path inside the container |
| `MONGODB_TLS_CERTIFICATE_KEY_FILE` | Client certificate/private key PEM path |
| `MONGODB_TLS_CERTIFICATE_KEY_FILE_PASSWORD` | Client key password |
| `MONGODB_TLS_ALLOW_INVALID_CERTIFICATES`, `MONGODB_TLS_ALLOW_INVALID_HOSTNAMES` | Must be `false` or unset for DocumentDB; verification overrides are available only in the generic MongoDB profile |
| `MONGODB_SERVER_SELECTION_TIMEOUT_MS`, `MONGODB_CONNECT_TIMEOUT_MS` | Driver timeouts |
| `MONGODB_OPTIONS` | JSON object for extra URI options; arrays represent repeated options |

Precedence: URI → missing DocumentDB defaults → `MONGODB_OPTIONS` → individual nonempty variables. Empty values are ignored. Remove the example host/port/auth-source variables when you want a full URI to supply those values.

DocumentDB TLS requirements are checked before overrides and after merging; precedence cannot hide an insecure TLS option. Duplicate JSON option keys are rejected; use arrays for supported repeated options.

```dotenv
MONGODB_URI=mongodb+srv://cluster.example.mongodb.net/application
MONGODB_USERNAME=my-user
MONGODB_PASSWORD=my-raw-password
MONGODB_OPTIONS={"appName":"Compass Docker","serverSelectionTimeoutMS":10000}
```

Env file values are literal, without surrounding shell quotes or `$` escaping. Shell `-e` values should be quoted as needed. A URI containing credentials must percent-encode them; separate username/password variables are encoded by the wrapper.

The wrapper creates a private temporary [Compass connection import file](https://www.mongodb.com/docs/compass/connect/connect-from-the-command-line/), keeping database credentials out of process arguments. Further [URI options](https://www.mongodb.com/docs/manual/reference/connection-string-options/) must be supported by Compass's bundled driver and your database.

## DocumentDB

`CONNECTION_TYPE=documentdb` fills missing settings with TLS, `/opt/certs/global-bundle.pem`, `replicaSet=rs0`, `readPreference=secondaryPreferred`, `retryWrites=false`, and `authSource=admin`. These follow the [AWS connection examples](https://docs.aws.amazon.com/documentdb/latest/devguide/connect_programmatically.html). Use the cluster endpoint and database credentials from your existing cluster.

TLS fails closed in this profile: `tls=false` / `ssl=false`, `tlsInsecure=true`, and disabled certificate or hostname verification stop startup. This applies to URI options, JSON options, and individual environment variables, including unsafe values that a later option would otherwise override. Safe SSL aliases are normalized to TLS; the emitted connection always enables certificate and hostname verification.

The effective CA file must be readable and parse as PEM/X.509 with at least one currently valid CA certificate. Missing, malformed, unreadable, or wholly expired/not-yet-valid CA bundles stop startup. The bundled AWS CA is checked the same way as a mounted replacement. These are local startup checks; the driver validates the actual server certificate and hostname when connecting.

This policy covers the startup-generated connection. Enable required TLS on the DocumentDB cluster too: it does not restrict connections added or edited manually in Compass. Existing Compass exports cannot be used with `CONNECTION_TYPE=documentdb`, because their connection settings cannot be guaranteed by this policy; use `MONGODB_URI` or `MONGODB_HOST` for this profile.

The pod/container needs VPC routing, DNS, and security-group access to TCP 27017. ECR stores the image; it does not provide database access. DocumentDB implements a compatible subset of MongoDB, so some Compass features may differ.

For DocumentDB 8.0, point at an existing 8.0 cluster; no client variable sets the server engine version. Retryable writes can be enabled explicitly on [8.0.2 and later](https://docs.aws.amazon.com/documentdb/latest/devguide/retryable-writes.html); the default remains false for compatibility.

The AWS CA bundle is downloaded when building the image. Refresh it with a no-cache build or mount a current bundle and set `MONGODB_TLS_CA_FILE`:

```sh
docker build --no-cache --platform linux/amd64 -t mongodb-compass:local .
```

For [IAM database authentication](https://docs.aws.amazon.com/documentdb/latest/devguide/iam-identity-auth.html), configure the cluster and a supported workload identity, set `MONGODB_AUTH_MECHANISM=MONGODB-AWS`, and remove static database credentials. The preset uses `authSource=$external` for AWS/X509 authentication. Standard AWS credential variables, mounted profiles, and supported workload providers are passed to Compass. Kubernetes examples use database passwords; customize their service account if using a workload role.

For a single forwarded endpoint, `MONGODB_DIRECT_CONNECTION=true` removes only the preset replica set unless you explicitly supplied one. Preserve the real endpoint hostname for TLS verification.

## Mounted secrets and files

These variables support a `_FILE` alternative:

- `UI_USERNAME`, `UI_PASSWORD`, `VNC_PASSWORD`
- `MONGODB_URI`, `MONGODB_USERNAME`, `MONGODB_PASSWORD`, `MONGODB_TLS_CERTIFICATE_KEY_FILE_PASSWORD`
- `SSH_USERNAME`, `SSH_PASSWORD`, `SSH_IDENTITY_PASSPHRASE`
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`
- `COMPASS_CONNECTION_PASSPHRASE`

Set the value or its `_FILE` alternative, not both. Trailing line endings are removed; spaces are preserved. Files must be readable by UID/GID 10001.

For example, mount `./secrets` read-only at `/run/secrets` and use:

```dotenv
UI_USERNAME_FILE=/run/secrets/ui_username
UI_PASSWORD_FILE=/run/secrets/ui_password
MONGODB_PASSWORD_FILE=/run/secrets/database_password
```

With Kubernetes, use a Secret volume with `defaultMode: 0440`, `readOnly: true`, and the examples' `fsGroup: 10001`. Use container paths for CA files, SSH keys, and Compass exports. The provided manifests instead use `envFrom.secretRef`, so Secret keys such as `UI_USERNAME` and `UI_PASSWORD` become environment variables directly. See [Kubernetes Secret configuration](../k8s/README.md#ui-and-database-secrets) for both approaches.

Treat environment values, mounted secrets, saved profiles, and exports as sensitive. Inline Docker values may also be retained in shell history or visible to users with Docker access. Use your platform's secret management controls for shared deployments, and [restart after rotation](operations.md#rotate-credentials-and-change-configuration).

## SSH and existing Compass exports

| Variable | Meaning |
| --- | --- |
| `SSH_HOST`, `SSH_PORT`, `SSH_USERNAME` | Compass SSH tunnel; default port 22 |
| `SSH_PASSWORD` | Optional SSH password |
| `SSH_IDENTITY_FILE`, `SSH_IDENTITY_PASSPHRASE` | Mounted private key and passphrase |
| `COMPASS_CONNECTION_FILE` | Mounted Compass connection export in the generic MongoDB profile; omit `MONGODB_*` / `SSH_*` variables |
| `COMPASS_CONNECTION_ID` | Optional connection to open from that export |
| `COMPASS_CONNECTION_PASSPHRASE` | Encrypted export passphrase; upstream Compass requires it as a command argument |

## Compose settings

| Variable | Default |
| --- | --- |
| `IMAGE_NAME`, `IMAGE_TAG` | `mongodb-compass`, `local` |
| `COMPASS_ENV_FILE` | `.env.runtime` |
| `BIND_ADDRESS`, `WEB_PORT` | `127.0.0.1`, `6080` |

These control Compose on the host. The other variables above configure the application inside the container.
