# MongoDB Compass Web UI

Run a browser-native MongoDB administration UI in your own Docker image, locally or on Kubernetes/AWS EKS. Open **http://localhost:6080** to browse collections, run queries, and build aggregation pipelines against MongoDB or Amazon DocumentDB.

This initial release builds [Compass Web 0.5.2](https://www.npmjs.com/package/compass-web/v/0.5.2), a community browser port of Compass, into an Ubuntu 26.04 image with Node.js and an authenticated Nginx gateway. It does not install the official desktop application, Electron, VNC/noVNC, or an X display server. It does not use a third-party Compass Docker image. The browser port has its own release cycle and feature set; its version is not a desktop Compass version.

The validated image target is **linux/amd64**. Intel/AMD Linux nodes run it directly; Apple Silicon uses Docker Desktop's amd64 emulation. No database server is included in the UI image.

## Documentation

| Task | Guide |
| --- | --- |
| Run MongoDB and the UI together | [Local test script](#run-mongodb-and-the-ui-together) |
| Build/run the UI alone | [Docker quick start](#run-locally) |
| Configure credentials, TLS, or mounted secrets | [Configuration](docs/configuration.md) |
| Connect to DocumentDB | [DocumentDB](#connect-to-amazon-documentdb) |
| Publish your image to ECR | [Publishing](docs/publishing.md) |
| Deploy on EKS, with optional storage or Istio | [Kubernetes](k8s/README.md) |
| Troubleshoot or rotate secrets | [Operations](docs/operations.md) |
| Understand build verification and security scans | [Automation](docs/automation.md) |
| Understand the runtime or contribute | [Architecture](docs/architecture.md), [Contributing](CONTRIBUTING.md) |
| Report a vulnerability | [Security](SECURITY.md) |

## Run MongoDB and the UI together

Start Docker Desktop on macOS or Docker Engine on Linux. From the repository directory:

```sh
bash ./test-script.sh
```

Wait for **Compass is ready**, then open **http://localhost:6080** and log in as `admin` with password `admin`. Select `mongodb-local:27017` in the sidebar and click **Connect**. These defaults are for local testing. To set your own passwords when initializing the database:

```sh
DB_PASSWORD='replace-with-a-database-password' \
UI_PASSWORD='replace-with-a-ui-password' bash ./test-script.sh
```

The script builds `mongodb-compass:local` from this repository, starts/reuses `mongodb-local` on the `compass-local` network, and recreates `mongodb-compass` from the freshly built image. It preserves database data in `mongodb-local-data` and settings in `mongodb-compass-config`. Existing MongoDB passwords are not reset by changing `DB_PASSWORD`.

Browser access is bound to `127.0.0.1:6080`; MongoDB is bound to `127.0.0.1:27017`. The local database uses authentication without TLS. Re-running the script interrupts UI sessions while replacing the UI container.

Optionally set `COMPASS_CONNECTIONS_PASSWORD` to a separate stable password when invoking the script to retain manually added connections in the settings volume.

## Run locally

Requirements: Docker, Git to clone the repository, and internet access for build dependencies. Make and AWS credentials are not needed.

```sh
git clone https://github.com/marcincuber/mongodb-compass.git
cd mongodb-compass
docker build --pull --platform linux/amd64 -t mongodb-compass:local .
docker run -d --name mongodb-compass --platform linux/amd64 \
  -p 127.0.0.1:6080:6080 \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  -e UI_USERNAME=admin \
  -e UI_PASSWORD='replace-with-a-strong-password' \
  mongodb-compass:local
```

Open <http://localhost:6080>. Select a configured connection and click **Connect**, or add a connection if none is configured. To supply one at startup, add these options before the image name:

```sh
-e MONGODB_HOST=host.docker.internal \
-e MONGODB_PORT=27017 \
-e MONGODB_USERNAME='database-user' \
-e MONGODB_PASSWORD='database-password' \
-e MONGODB_AUTH_SOURCE=admin
```

Docker Desktop provides `host.docker.internal` for a database on your Mac. On Linux, also add `--add-host=host.docker.internal:host-gateway`; the database must listen on an address reachable from the Docker bridge. For another container on a shared network, use its container name. `localhost` in a database URI refers to the UI container.

Stop and remove an existing UI container before reusing its name. For browser access over a network, terminate HTTPS at your ingress/reverse proxy; Basic authentication alone does not encrypt HTTP traffic.

## Connect to Amazon DocumentDB

After building, start the UI with your existing cluster endpoint and database credentials:

```sh
docker run -d --name mongodb-compass --platform linux/amd64 \
  -p 127.0.0.1:6080:6080 \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  -e UI_USERNAME=admin \
  -e UI_PASSWORD='replace-with-a-strong-ui-password' \
  -e CONNECTION_TYPE=documentdb \
  -e MONGODB_HOST='your-cluster.cluster-xxxxxxxxxxxx.eu-west-2.docdb.amazonaws.com' \
  -e MONGODB_USERNAME='database-user' \
  -e MONGODB_PASSWORD='database-password' \
  -e MONGODB_TLS=true \
  -e MONGODB_TLS_INSECURE=false \
  -e MONGODB_TLS_ALLOW_INVALID_CERTIFICATES=false \
  -e MONGODB_TLS_ALLOW_INVALID_HOSTNAMES=false \
  -e MONGODB_TLS_CA_FILE=/opt/certs/global-bundle.pem \
  mongodb-compass:local
```

The preset supplies `authSource=admin`, `replicaSet=rs0`, `readPreference=secondaryPreferred`, and `retryWrites=false`. TLS, a valid readable CA bundle, certificate verification, and hostname verification are mandatory. The server enforces verified TLS on browser database sockets too, and disables editing connections in this profile.

The container needs VPC routing, DNS, and security-group access to TCP 27017. AWS credentials alone do not establish network access. For DocumentDB 8.0, use an existing 8.0 cluster; the client cannot select its engine version. After deploying on EKS, run `make eks-check` to verify the configured database connection from the pod. See [configuration and limitations](docs/configuration.md#documentdb), or the [EKS/Istio examples](k8s/README.md).

## Use an env file or Compose

```sh
cp .env.example .env.runtime
chmod 600 .env.runtime
# Edit UI credentials and database settings before starting.
docker run -d --name mongodb-compass --platform linux/amd64 \
  --env-file .env.runtime -p 127.0.0.1:6080:6080 \
  --cap-drop=ALL --security-opt=no-new-privileges:true mongodb-compass:local
```

For DocumentDB, copy `.env.documentdb.example` instead. Env-file values are literal: omit shell quotes and do not escape `$`.

With Make and Docker Compose 2.30+:

```sh
make build
make up
make logs
make down
```

Compose retains its settings volume. Browser preferences are stored in the browser; manually added server-side connections survive replacement only when `COMPASS_CONNECTIONS_PASSWORD` is configured with a settings volume. Environment-defined connections are recreated at startup. See [storage configuration](docs/configuration.md#connection-storage).

## Validate and contribute

```sh
make build   # Build the Linux amd64 image; fetch current base images
make verify  # Unit tests, Kubernetes schemas, build, smoke tests, vulnerability scan
```

`make verify` requires Python 3, Node.js, OpenSSL, ShellCheck, kubeconform, and Docker. See [development setup](CONTRIBUTING.md#development-setup) for details. Individual checks remain available as `make test`, `make eks-validate`, `make smoke-test`, and `make scan`.

Smoke tests use temporary containers/networks, MongoDB 8.0, and generated test certificates. They verify authenticated database traffic through the browser transport and TLS failures without AWS access. Live EKS, Istio, and DocumentDB connectivity must still be verified in your environment.

Read [Contributing](CONTRIBUTING.md) for development setup and pull requests. Use [issue templates](https://github.com/marcincuber/mongodb-compass/issues/new/choose) for bugs and feature requests, and [Security](SECURITY.md) for private vulnerability reports.

## Licensing and upstream components

This repository does not yet include a project license. Ask the maintainer to clarify reuse terms. The browser package and bundled components retain their upstream terms and license files. This project is not an official MongoDB container product and does not confer MongoDB or AWS support.
