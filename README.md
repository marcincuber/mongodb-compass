# MongoDB Compass UI for Docker and Kubernetes

Access the MongoDB Compass desktop from a browser, with container builds, authenticated access, and deployment examples for Kubernetes and AWS EKS. Connect to an existing MongoDB or Amazon DocumentDB cluster, including DocumentDB 8.0 with verified TLS.

**This is an independent project.** It packages the official Compass desktop application with a virtual display and noVNC browser access. The container and deployment examples are maintained by this repository; they are not an official MongoDB container product. No database server is included.

The image uses Ubuntu 26.04 and pins [Compass 1.53.2](https://github.com/mongodb-js/compass/releases/tag/v1.53.2) with installer checksum verification. It targets **linux/amd64**. Apple Silicon uses Docker Desktop's amd64 emulation; Linux servers and Kubernetes nodes need x86_64 CPUs.

Each container provides **one shared desktop**. Everyone using the same instance sees the same session and connections. Use separate deployments for independent users or trust boundaries.

## Documentation

| Task | Guide |
| --- | --- |
| Build and run on Mac or Linux | [Local quick start](#run-locally) |
| Set UI/database credentials, TLS, or mounted secrets | [Configuration](docs/configuration.md) |
| Connect to DocumentDB with verified TLS | [DocumentDB quick start](#connect-to-amazon-documentdb) |
| Build and push to ECR | [Publishing](docs/publishing.md) |
| Deploy with Kubernetes, EBS, or Istio | [Kubernetes](k8s/README.md) |
| Rotate credentials, update, or troubleshoot | [Operations](docs/operations.md) |
| Container vulnerability reports and automated Compass upgrades | [GitHub Actions](docs/automation.md) |
| Understand the runtime and repository | [Architecture](docs/architecture.md) |
| Report a bug, improve docs, or submit code | [Contributing](CONTRIBUTING.md) |
| Report a vulnerability privately | [Security policy](SECURITY.md) |

## Run locally

Requirements: Docker Desktop on macOS or Docker Engine on Linux, Git to clone the repository, and network access to download the base image, packages, Compass installer, and AWS CA bundle. Make and AWS credentials are not needed for this quick start.

```sh
git clone https://github.com/marcincuber/mongodb-compass.git
cd mongodb-compass
docker build --platform linux/amd64 -t mongodb-compass:local .
docker run -d --name mongodb-compass --platform linux/amd64 \
  -p 127.0.0.1:6080:6080 --shm-size=1g \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  -e UI_USERNAME=admin \
  -e UI_PASSWORD='replace-with-a-strong-password' \
  mongodb-compass:local
```

These commands work on both Apple Silicon/Intel Macs and Linux amd64. They use no env file and open Compass for manual connection setup. Replace the UI password before running.

Open <http://localhost:6080/vnc.html?autoconnect=true&resize=remote>, enter the UI username/password, and click **Start** in Compass.

The published port is bound to your computer's loopback address. Use HTTPS at an ingress or reverse proxy for remote browser access: HTTP Basic authentication alone does not encrypt traffic.

To connect automatically, add database options before the final image name, for example:

```sh
-e MONGODB_HOST=host.docker.internal \
-e MONGODB_PORT=27017 \
-e MONGODB_USERNAME='database-user' \
-e MONGODB_PASSWORD='database-password' \
-e MONGODB_AUTH_SOURCE=admin
```

Omit the database username/password for an unauthenticated server. For a remote database, replace the host. For a full URI or DocumentDB, see [connection configuration](docs/configuration.md).

**Mac:** Docker Desktop provides `host.docker.internal` for databases running on the Mac.

**Linux:** add `--add-host=host.docker.internal:host-gateway` before the image name when using a database on the Linux host. That database must listen on an address reachable from the Docker bridge, rather than only the host's `127.0.0.1`.

For a database in another container, add `--network NETWORK_NAME` and use its container/service name. `localhost` inside Compass refers to the Compass container.

## Connect to Amazon DocumentDB

After building the image, run it with your cluster endpoint and credentials. This is a complete example without an env file; stop and remove any previous container with the same name first.

```sh
docker run -d --name mongodb-compass --platform linux/amd64 \
  -p 127.0.0.1:6080:6080 --shm-size=1g \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  -e UI_USERNAME=admin \
  -e UI_PASSWORD='replace-with-a-strong-ui-password' \
  -e CONNECTION_TYPE=documentdb \
  -e MONGODB_HOST='your-cluster.cluster-xxxxxxxxxxxx.eu-west-2.docdb.amazonaws.com' \
  -e MONGODB_USERNAME='your-database-user' \
  -e MONGODB_PASSWORD='your-database-password' \
  -e MONGODB_TLS=true \
  -e MONGODB_TLS_INSECURE=false \
  -e MONGODB_TLS_ALLOW_INVALID_CERTIFICATES=false \
  -e MONGODB_TLS_ALLOW_INVALID_HOSTNAMES=false \
  -e MONGODB_TLS_CA_FILE=/opt/certs/global-bundle.pem \
  mongodb-compass:local
```

Open the same browser URL as above. Your container needs a network path to the cluster's VPC, DNS resolution, and database access on TCP 27017. A local Docker container does not gain private AWS network access from AWS credentials alone.

The DocumentDB preset supplies `authSource=admin`, `replicaSet=rs0`, `readPreference=secondaryPreferred`, and `retryWrites=false`. It refuses disabled TLS or certificate/hostname verification and validates the CA bundle before launching. This policy covers the generated startup connection; users can still edit connections inside Compass. See [DocumentDB configuration](docs/configuration.md#documentdb) for IAM authentication, custom CA bundles, and compatibility details.

For EKS, use the [DocumentDB TLS or DocumentDB 8.0 + Istio example](k8s/README.md). Browser HTTPS and database TLS secure separate network connections.

## Use an env file or Compose

Instead of the inline `-e` options, prepare an env file:

```sh
cp .env.example .env.runtime
chmod 600 .env.runtime
# Edit the UI credentials and database connection.
docker run -d --name mongodb-compass --platform linux/amd64 \
  --env-file .env.runtime -p 127.0.0.1:6080:6080 --shm-size=1g \
  --cap-drop=ALL --security-opt=no-new-privileges:true mongodb-compass:local
```

For DocumentDB, start from `.env.documentdb.example`. Env file values are literal: omit shell quotes and do not escape `$`. Linux host databases need the extra `--add-host` option above.

For Compose, install Docker Compose 2.30+ and Make, prepare `.env.runtime`, then run:

```sh
make build
make up
make logs
make down
```

Compose preserves settings in its `compass-config` volume. On Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the Compose service when using a host database.

## Logs, updates, and cleanup

```sh
docker logs -f mongodb-compass
docker stop --time 20 mongodb-compass
docker rm mongodb-compass
```

Direct Docker runs keep settings until the container is removed. Recreate the container to load changed environment variables; rebuild first if the image changed. Remove a previous container before reusing its name. With Compose, `make up` applies environment changes, while `docker compose down --volumes` deletes saved settings.

If Docker runs on a remote Linux server, tunnel its browser port:

```sh
ssh -N -L 6080:127.0.0.1:6080 user@linux-host
```

Then use the same localhost browser URL. For browser access over a network, use HTTPS through your ingress or reverse proxy. UI credentials and database credentials are separate, and all viewers of a container share one desktop.

## Kubernetes and publishing

Choose a [standalone Kubernetes example](k8s/README.md): DocumentDB with TLS, MongoDB without TLS, persistent settings, or DocumentDB 8.0 through Istio. UI credentials come from a Kubernetes Secret in every example.

The DocumentDB startup profile requires TLS with certificate and hostname verification, validates the CA bundle, and rejects insecure overrides. See the [DocumentDB TLS policy](docs/configuration.md#documentdb).

Follow the [ECR publishing guide](docs/publishing.md) before setting the image in your chosen manifest. Apply configuration changes with `make eks-deploy`; it restarts the desktop to reload Secret/ConfigMap values.

## Validate changes

For development prerequisites and the checks relevant to each kind of change, see [Contributing](CONTRIBUTING.md).

```sh
make test          # Python 3, Make, OpenSSL with passwd -6, and ShellCheck
make eks-validate  # kubeconform; Kubernetes and Istio schemas are downloaded
make build
make smoke-test    # Docker: real desktop, UI auth, WebSockets, secrets, probes, and shutdown
make scan          # Pinned Trivy scanner; fails on HIGH or CRITICAL findings
```

Smoke tests create and remove temporary containers and a settings volume without an AWS account or database. They check profile persistence across container replacement, a read-only root filesystem, and non-root execution like the Kubernetes examples. Live EKS scheduling, Istio routing, and database connectivity must be verified in the target environment.

GitHub Actions runs these checks on PRs, pushes, and a daily schedule. A separate weekly/manual workflow validates official Compass upgrades and opens a PR only after tests and the scan gate pass. See [automation setup and reports](docs/automation.md).

## Contribute and get help

Documentation improvements, reproducible bug reports, tests, and deployment fixes are welcome. Read [Contributing](CONTRIBUTING.md) before opening a pull request, or use the repository's [issue templates](https://github.com/marcincuber/mongodb-compass/issues/new/choose). Remove credentials, connection strings containing passwords, and private infrastructure details from reports. For vulnerabilities, follow [Security](SECURITY.md).

## Licensing

This repository does not currently include a project license. Do not assume permission to redistribute or reuse its code; ask the maintainer to clarify licensing before doing so. MongoDB Compass and the other bundled components retain their respective upstream license terms. This repository does not replace those terms or confer MongoDB or AWS support.
