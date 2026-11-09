# Operations and troubleshooting

Return to the [README](../README.md), [Kubernetes guide](../k8s/README.md), or [configuration reference](configuration.md).

Run commands from the repository root. Replace container names, namespaces, and image references if you customized them. Sanitize diagnostic output before sharing it: logs and screenshots can contain endpoint names, usernames, connection details, or database contents.

## Check a local container

```sh
docker ps -a --filter name=mongodb-compass
docker logs --tail 100 mongodb-compass
docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' mongodb-compass
docker exec mongodb-compass python3 /opt/compass-container/healthcheck.py
# Optional: requires a database connection configured through environment variables.
docker exec mongodb-compass python3 /opt/compass-container/check_connection.py
```

The explicit health check exits zero when the browser infrastructure is available. It does not test the database. The public `/healthz` endpoint returns static text, so its HTTP 200 response alone is not proof that Compass or the database is ready.

For Compose, use `docker compose ps` and `make logs`. The local browser URL is <http://localhost:6080>; it serves the native browser application.

## Check a Kubernetes deployment

Confirm your context before applying changes:

```sh
kubectl config current-context
make eks-status
make eks-check
kubectl -n mongodb-compass rollout status deployment/mongodb-compass --timeout=300s
kubectl -n mongodb-compass logs deployment/mongodb-compass --tail=100
kubectl -n mongodb-compass get events --sort-by=.lastTimestamp
```

If a pod has restarted, use its name to inspect the previous container logs:

```sh
kubectl -n mongodb-compass logs POD_NAME --previous --tail=100
kubectl -n mongodb-compass describe pod POD_NAME
```

Successful rollout means the application probes passed. `make eks-check` separately uses the configured database connection to run an authenticated ping from the pod, including CA and hostname verification for DocumentDB. It exits nonzero on failure and omits raw driver errors and credentials. Then open the UI and verify the operations your database account needs. The check does not inspect manually added browser connections.

## Common problems

| Symptom | Likely cause and next step |
| --- | --- |
| Build rejects the architecture | Use `--platform linux/amd64`; Apple Silicon needs amd64 emulation and EKS needs amd64 node capacity |
| Docker reports a container-name conflict | Stop and remove the earlier `mongodb-compass` container before creating another |
| Missing UI credentials or startup exits immediately | Supply both UI credentials, or both `_FILE` alternatives; read the configuration error in logs |
| HTTP 401 or a repeated browser login prompt | Verify UI credentials and restart after rotation; the UI login is separate from the database account |
| Browser opens but the application cannot connect | Ensure the proxy forwards `/mongo`, supports WebSocket upgrades, and preserves the URL paths |
| Remote browser session disconnects | Check ingress/load-balancer idle timeouts and connection lifetime limits; WebSocket pings run every 30 seconds |
| Host database cannot be reached from Docker | Use `host.docker.internal`; Linux needs the host-gateway mapping and a database listener reachable from the Docker bridge |
| DocumentDB connection times out | Check cluster endpoint, VPC routing, DNS, TCP 27017, security groups, and any NetworkPolicy; AWS login alone does not establish network access |
| DocumentDB TLS configuration is rejected at startup | Remove insecure options from every source, including URI/JSON settings; a later safe override does not hide an unsafe value |
| CA validation fails at startup | Check the mounted container path, UID 10001 read permissions, PEM contents, certificate validity dates, and system clock |
| Server certificate or hostname verification fails on connection | Use the real cluster endpoint and a current trusted CA bundle; do not bypass verification to work around a DNS/tunnel problem |
| Pod is `ImagePullBackOff` | Verify the image exists, ECR pull permissions, and registry network access |
| Pod stays `Pending` | Check amd64 node capacity, scheduling constraints, and PVC/CSI events if using storage |
| Pod restarts or reports `OOMKilled` | Inspect previous logs and pod status; adjust resources for the workload |
| Settings disappear after redeployment | Use the persistent example or a settings volume; temporary Kubernetes settings are lost on pod replacement |
| Istio returns 404/503 or a browser TLS error | Check hostname, Gateway selector/reference, Service destination, certificate Secret namespace, and ingress-to-app traffic policy |

## Rotate credentials and change configuration

The wrapper reads configuration at process startup. Updating a Secret, env file, or mounted secret file does not reconfigure the running application automatically. Restarting interrupts the shared session; coordinate active work first.

For direct Docker runs, stop the server gracefully, remove it, and repeat your `docker run` command with the updated configuration:

```sh
docker stop --time 20 mongodb-compass
docker rm mongodb-compass
```

Without a settings volume, removing the container removes any encrypted connection store. Browser preferences remain in browser storage. For Compose, edit `.env.runtime` and force recreation to load its new values:

```sh
docker compose up -d --force-recreate compass
```

For the Kubernetes examples, edit the Secret/ConfigMap in your private working manifest and run:

```sh
make eks-deploy
```

If an external controller owns the Secret, let it update the Secret and then run `make eks-restart`. Remove the Secret document from your working manifest before using that controller so a later apply does not overwrite its values.

After a UI credential rotation, browsers may cache the old HTTP Basic credentials. Use a fresh browser session when verifying the new login. Separately update or remove any old database credentials saved within Compass profiles; a wrapper restart is not a guarantee that all saved copies have been erased.

## Persistent settings and cleanup

Persistent storage is optional and retains encrypted server-side connection files, not database data. Enable it with a separate stable `COMPASS_CONNECTIONS_PASSWORD`. Saved connections, exports, and settings may contain credentials. Protect backups with the same access controls as the original volume, and avoid copying encrypted connection files while the server is writing them.

Compose's `make down` keeps its settings volume. `docker compose down --volumes` deletes it and its saved settings. Browser preferences remain in browser storage; unpersisted server connections are lost on replacement.

In the EKS persistent example, the StorageClass uses `Retain`. Deleting the PVC leaves the underlying EBS volume for deliberate cleanup. EBS snapshots and retained volumes may continue to contain credentials and incur storage costs. Review PVC, PV, and snapshot ownership before deleting shared resources.

Applying another Kubernetes example does not remove resources created by the previous one. Remove unused Istio routes, Gateway resources, and storage separately when changing deployment styles. Avoid deleting the whole namespace if it contains resources you need to keep.

## Ask for help

Use the [bug report form](https://github.com/marcincuber/mongodb-compass/issues/new/choose) with the image tag/commit, host architecture, deployment method, reproduction steps, and sanitized logs. State whether the issue is in browser access, application startup, or database connectivity. See [Security](../SECURITY.md) for private vulnerability reporting.
