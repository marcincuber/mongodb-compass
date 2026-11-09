# Operations and troubleshooting

Return to the [README](../README.md), [Kubernetes guide](../k8s/README.md), or [configuration reference](configuration.md).

Run commands from the repository root. Replace container names, namespaces, and image references if you customized them. Sanitize diagnostic output before sharing it: logs and screenshots can contain endpoint names, usernames, connection details, or database contents.

## Check a local container

```sh
docker ps -a --filter name=mongodb-compass
docker logs --tail 100 mongodb-compass
docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' mongodb-compass
docker exec mongodb-compass python3 /opt/compass-container/healthcheck.py
```

The explicit health check exits zero when the browser infrastructure is available. It does not test the database. The public `/healthz` endpoint returns static text, so its HTTP 200 response alone is not proof that Compass or the database is ready.

For Compose, use `docker compose ps` and `make logs`. The local browser URL is <http://localhost:6080/vnc.html?autoconnect=true&resize=remote>.

## Check a Kubernetes deployment

Confirm your context before applying changes:

```sh
kubectl config current-context
make eks-status
kubectl -n mongodb-compass rollout status deployment/mongodb-compass --timeout=300s
kubectl -n mongodb-compass logs deployment/mongodb-compass --tail=100
kubectl -n mongodb-compass get events --sort-by=.lastTimestamp
```

If a pod has restarted, use its name to inspect the previous container logs:

```sh
kubectl -n mongodb-compass logs POD_NAME --previous --tail=100
kubectl -n mongodb-compass describe pod POD_NAME
```

Successful rollout means the desktop probes passed. Open the UI and verify that the intended connection succeeds and can perform the operations allowed by its database account.

## Common problems

| Symptom | Likely cause and next step |
| --- | --- |
| Build rejects the architecture | Use `--platform linux/amd64`; Apple Silicon needs amd64 emulation and EKS needs amd64 node capacity |
| Docker reports a container-name conflict | Stop and remove the earlier `mongodb-compass` container before creating another |
| Missing UI credentials or startup exits immediately | Supply both UI credentials, or both `_FILE` alternatives; read the configuration error in logs |
| HTTP 401 or a repeated browser login prompt | Verify UI credentials and restart after rotation; the UI login is separate from the database account |
| Browser opens but the desktop cannot connect | Ensure the proxy forwards `/websockify`, supports WebSocket upgrades, and preserves the URL paths |
| Remote browser session disconnects | Check ingress/load-balancer idle timeouts and connection lifetime limits; WebSocket pings run every 30 seconds |
| Host database cannot be reached from Docker | Use `host.docker.internal`; Linux needs the host-gateway mapping and a database listener reachable from the Docker bridge |
| DocumentDB connection times out | Check cluster endpoint, VPC routing, DNS, TCP 27017, security groups, and any NetworkPolicy; AWS login alone does not establish network access |
| DocumentDB TLS configuration is rejected at startup | Remove insecure options from every source, including URI/JSON settings; a later safe override does not hide an unsafe value |
| CA validation fails at startup | Check the mounted container path, UID 10001 read permissions, PEM contents, certificate validity dates, and system clock |
| Server certificate or hostname verification fails on connection | Use the real cluster endpoint and a current trusted CA bundle; do not bypass verification to work around a DNS/tunnel problem |
| Pod is `ImagePullBackOff` | Verify the image exists, ECR pull permissions, and registry network access |
| Pod stays `Pending` | Check amd64 node capacity, scheduling constraints, and PVC/CSI events if using storage |
| Pod restarts or reports `OOMKilled` | Inspect previous logs and pod status; adjust resources for the workload and account for the memory-backed `/dev/shm` volume |
| Settings disappear after redeployment | Use the persistent example or a settings volume; temporary Kubernetes settings are lost on pod replacement |
| Istio returns 404/503 or a browser TLS error | Check hostname, Gateway selector/reference, Service destination, certificate Secret namespace, and ingress-to-app traffic policy |

## Rotate credentials and change configuration

The wrapper reads configuration at process startup. Updating a Secret, env file, or mounted secret file does not reconfigure the running desktop automatically. Restarting interrupts the shared session; coordinate active work first.

For direct Docker runs, stop the container with time to save preferences, remove it, and repeat your `docker run` command with the updated configuration:

```sh
docker stop --time 20 mongodb-compass
docker rm mongodb-compass
```

Without a mounted settings volume, removing the container also removes its saved settings. For Compose, edit `.env.runtime` and force recreation to load its new values:

```sh
docker compose up -d --force-recreate compass
```

For the Kubernetes examples, edit the Secret/ConfigMap in your private working manifest and run:

```sh
make eks-deploy
```

If an external controller owns the Secret, let it update the Secret and then run `make eks-restart`. Remove the Secret document from your working manifest before using that controller so a later apply does not overwrite its values.

After a UI credential rotation, browsers may cache the old HTTP Basic credentials. Use a fresh browser session when verifying the new login. Separately update or remove any old database credentials saved within Compass profiles; a wrapper restart is not a guarantee that all saved copies have been erased.

## Update or roll back an image

1. Review the change and run the relevant [contributor checks](../CONTRIBUTING.md#choose-the-right-checks).
2. Build a fresh image, smoke-test it, and scan that exact image. Review the timestamp and findings rather than relying on a previous report.
3. [Publish a new immutable image tag](publishing.md). Retain the previous image reference.
4. Update the image reference in your private Kubernetes manifest and run `make eks-deploy`.
5. Verify browser login, desktop behavior, and live database connectivity after rollout.

To roll back, restore the previous image reference in that manifest and deploy again. Image rollback does not restore settings or undo database changes. If settings are persistent, preserve a suitable backup before an upgrade; compatibility with a newer Compass profile is not guaranteed when returning to an older version.

The automated upgrade workflow opens a reviewed candidate PR; it does not publish images or deploy them. Scheduled security scans also do not update images already running in a cluster.

## Persistent settings and cleanup

Persistent storage is optional and stores the client profile, not the database itself. Saved connections, exports, and settings may contain credentials. Protect backups with the same access controls as the original volume, and avoid copying a live profile while Compass is writing it.

Compose's `make down` keeps its settings volume. `docker compose down --volumes` deletes it and its saved settings. Direct Docker containers without a settings mount lose preferences when removed.

In the EKS persistent example, the StorageClass uses `Retain`. Deleting the PVC leaves the underlying EBS volume for deliberate cleanup. EBS snapshots and retained volumes may continue to contain credentials and incur storage costs. Review PVC, PV, and snapshot ownership before deleting shared resources.

Applying another Kubernetes example does not remove resources created by the previous one. Remove unused Istio routes, Gateway resources, and storage separately when changing deployment styles. Avoid deleting the whole namespace if it contains resources you need to keep.

## Ask for help

Use the [bug report form](https://github.com/marcincuber/mongodb-compass/issues/new/choose) with the image tag/commit, host architecture, deployment method, reproduction steps, and sanitized logs. State whether the issue is in browser access, desktop startup, or database connectivity. See [Security](../SECURITY.md) for private vulnerability reporting.
