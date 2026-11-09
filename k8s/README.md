# Kubernetes deployment

Return to the [README](../README.md). For runtime settings use [Configuration](../docs/configuration.md); for upgrades and diagnostics use [Operations](../docs/operations.md).

These are four standalone manifests for an existing Linux amd64 cluster. Each includes a Namespace, UI credential Secret, connection ConfigMap, one Compass Deployment, and a ClusterIP Service.

| Example | Database connection | Settings | Browser access |
| --- | --- | --- | --- |
| [DocumentDB TLS](examples/documentdb-tls.yaml) | DocumentDB TLS with database credentials | Temporary | Port-forward |
| [MongoDB without TLS](examples/mongodb-no-tls.yaml) | MongoDB; database credentials optional | Temporary | Port-forward |
| [Persistent settings](examples/mongodb-persistent.yaml) | MongoDB without TLS | 5Gi encrypted EBS | Port-forward |
| [DocumentDB 8.0 + Istio](examples/documentdb-v8-istio.yaml) | Existing DocumentDB 8.0 cluster with TLS | Temporary | HTTPS Gateway + VirtualService |

All require UI Basic authentication. Database TLS and browser HTTPS are separate connections. No example creates a database, EKS cluster, or Istio installation. For runtime variables and mounted credential files, see [configuration](../docs/configuration.md).

Both DocumentDB examples explicitly require verified TLS:

```yaml
  CONNECTION_TYPE: documentdb
  MONGODB_TLS: "true"
  MONGODB_TLS_INSECURE: "false"
  MONGODB_TLS_ALLOW_INVALID_CERTIFICATES: "false"
  MONGODB_TLS_ALLOW_INVALID_HOSTNAMES: "false"
  MONGODB_TLS_CA_FILE: /opt/certs/global-bundle.pem
```

The startup policy rejects insecure TLS settings from the URI, JSON options, or environment—even if a later setting would override them. The CA file must be readable PEM with a currently valid CA certificate. The driver then verifies the server certificate and endpoint hostname on connection. See [the TLS policy](../docs/configuration.md#documentdb) for details.

Build and publish an image from the current repository before relying on this enforcement; editing YAML alone does not add the policy to an older image. The image references in the examples are placeholders for your published image. The generic MongoDB examples continue to support connections without TLS.

## 1. Prepare

You need `kubectl` access, a [published image](../docs/publishing.md), and amd64 node capacity. On EKS, nodes need [ECR pull permissions](https://docs.aws.amazon.com/AmazonECR/latest/userguide/ECR_on_EKS.html). Pods need DNS, routing, security-group access, and any required NetworkPolicy allowance to reach the database.

From the repository root, copy one example to the gitignored working file:

```sh
mkdir -p secrets
cp k8s/examples/documentdb-tls.yaml secrets/compass.yaml
chmod 600 secrets/compass.yaml
```

Edit `secrets/compass.yaml`:

- Replace the Deployment's image with your ECR URI and tag/digest.
- Set `UI_USERNAME` and `UI_PASSWORD` in the Secret.
- Set `MONGODB_HOST` in the ConfigMap to your database endpoint.
- Fill in database username/password for DocumentDB or an authenticated MongoDB server. Leave them empty for an unauthenticated MongoDB server.

Choose one example at a time: all use namespace `mongodb-compass` and the same Deployment/Service names. Settings reset on pod replacement except in the persistent example.

## 2. Deploy and open

```sh
make eks-deploy
make eks-port-forward
```

Open <http://localhost:6080/vnc.html?autoconnect=true&resize=remote>, enter the UI credentials, and click **Start** in a new Compass profile. Keep the port-forward running.

`make eks-deploy` applies `secrets/compass.yaml`, restarts the desktop to load Secret/ConfigMap changes, and waits for rollout. Each deployment interrupts the current shared session. No image rebuild is needed for configuration changes. To use a different working file:

```sh
K8S_EXAMPLE=secrets/my-compass.yaml make eks-deploy
```

If using `kubectl` directly, configuration changes need an explicit restart:

```sh
kubectl apply -f secrets/compass.yaml
kubectl -n mongodb-compass rollout restart deployment/mongodb-compass
kubectl -n mongodb-compass rollout status deployment/mongodb-compass --timeout=300s
```

Keep `replicas: 1` for one shared desktop. Separate users who need independent sessions need separate deployments and Secrets. The application reads credentials through `envFrom.secretRef`; your secret controller can manage the same named Secret.

## UI and database secrets

Every example defines an Opaque Secret named `mongodb-compass-secrets` containing `UI_USERNAME`, `UI_PASSWORD`, and the database credentials. The Deployment imports it with:

```yaml
envFrom:
  - configMapRef:
      name: mongodb-compass-config
  - secretRef:
      name: mongodb-compass-secrets
```

There is no image rebuild when credentials change. Apply the edited working manifest with `make eks-deploy`, or restart after an external secret controller updates the Secret. If your controller owns this Secret, remove its Secret document from the working manifest so `kubectl apply` does not overwrite it. Keep real credentials out of the committed examples; a Kubernetes Secret is not a reason to commit its plaintext YAML.

For mounted credential files, use the supported `_FILE` variables instead and ensure UID/GID 10001 can read the volume. Set either a value or its file alternative, not both. See [mounted secrets](../docs/configuration.md#mounted-secrets-and-files).

## Runtime and resource expectations

The examples request 500m CPU, 1Gi memory, and 1Gi ephemeral storage per desktop, with limits of 2 CPU, 3Gi memory, and 3Gi ephemeral storage. They also mount a memory-backed `/dev/shm` with a 1Gi size limit. Size limits do not preallocate that memory; its actual use contributes to the container's memory consumption. Adjust resources after observing your workload, especially large result sets or exports.

All examples use `Recreate` updates and a 30-second termination period. Replacements interrupt browser sessions. Persistent storage is optional; the temporary mounts are needed because the image filesystem is read-only. Keep the writable home, `/tmp`, and shared-memory mounts even when you do not need a PVC.

Startup probes allow up to roughly three minutes for the desktop to initialize. Readiness and liveness check browser infrastructure rather than the database. Successful rollout must be followed by a live connection check inside Compass.

## Persistent settings

Only `mongodb-persistent.yaml` provisions storage. Its 5Gi PVC mounts `/home/compass/.config`; the rest of home/cache, `/tmp`, and shared memory stay temporary. Settings may contain saved database credentials.

Standard EKS needs the [EBS CSI driver and its IAM permissions](https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html). For Auto Mode, change the StorageClass provisioner to `ebs.csi.eks.amazonaws.com` and add `eks.amazonaws.com/compute-type: auto` to the pod's `nodeSelector`, following [AWS's storage guidance](https://docs.aws.amazon.com/eks/latest/userguide/create-storage-class.html).

To use an existing StorageClass, remove the StorageClass document and change the PVC's `storageClassName` before applying. A bound claim's storage class cannot be changed in place. EBS constrains later scheduling to the volume's Availability Zone.

Updates use `Recreate`, and Compass exits before its display stops so it can save preferences. The class uses `Retain`: deleting the PVC leaves its EBS volume for deliberate cleanup. Switching to a temporary example detaches the PVC without deleting it. For persistent DocumentDB settings, copy the DocumentDB ConfigMap/Secret values into this example.

## DocumentDB 8.0 through Istio

Start from `documentdb-v8-istio.yaml` when creating your working file. In addition to the normal settings:

1. Point `MONGODB_HOST` at an existing instance-based DocumentDB 8.0 cluster. Client configuration cannot set the server engine version.
2. Replace `compass.example.com` in the Gateway and VirtualService with your browser hostname.
3. Match the Gateway selector to your existing ingress workload's labels.
4. Use the ingress workload's namespace for the Gateway and certificate Secret. The example assumes `istio-system`; update the VirtualService's `gateways` reference if different.
5. Supply a trusted certificate/private key for that hostname.

With an installed Istio ingress Service exposing ports 80/443:

```sh
kubectl -n istio-system create secret tls mongodb-compass-ui-tls \
  --cert=./certs/compass.crt --key=./certs/compass.key \
  --dry-run=client -o yaml | kubectl apply -f -
make eks-deploy
kubectl -n istio-system get service istio-ingressgateway
```

Use your actual ingress Service name. Point the browser hostname's DNS record at its load balancer, then open `https://YOUR_HOST/vnc.html?autoconnect=true&resize=remote`. No port-forward is needed.

The [Gateway](https://istio.io/latest/docs/tasks/traffic-management/ingress/secure-ingress/) redirects HTTP to HTTPS and terminates browser TLS. The VirtualService forwards UI and WebSocket paths unchanged with `timeout: 0s`. The app sends WebSocket pings every 30 seconds; [proxy idle timeouts](https://www.envoyproxy.io/docs/envoy/latest/faq/configuration/timeouts) and maximum connection lifetimes remain controlled by your ingress.

The app pod disables sidecar injection. The ingress-to-app hop is HTTP inside the cluster, so gateway traffic policy must allow it. Compass independently uses TLS and the included AWS CA bundle for DocumentDB. Retryable writes remain disabled for compatibility across 8.0 releases; [8.0.2+ supports enabling them](https://docs.aws.amazon.com/documentdb/latest/devguide/retryable-writes.html).

To reuse a shared Istio Gateway, remove the Gateway document and reference your existing HTTPS Gateway in the VirtualService. When switching to another example, separately remove any unused Gateway/VirtualService; applying another manifest does not prune them.

## Operate and validate

```sh
make eks-status
make eks-restart
kubectl -n mongodb-compass logs deployment/mongodb-compass --tail=100
kubectl -n mongodb-compass get events --sort-by=.lastTimestamp
make eks-validate
```

Validation checks every example, including Istio resources, against downloaded schemas without contacting a live cluster. The deployment uses a non-root user, read-only root filesystem, writable temporary mounts, resource limits, and a 30-second termination period.

Probes check the public static `/healthz` response and internal noVNC/VNC services, bypassing outbound proxies. Database failures appear in Compass rather than causing restart loops. Kubernetes is responsible for restarting the container if a supervised desktop process exits.

| Symptom | Check |
| --- | --- |
| `ImagePullBackOff` | Image/tag, ECR permissions, registry connectivity |
| `Pending` | amd64 capacity; for persistence, PVC/CSI events, node taints, and volume zone |
| `CrashLoopBackOff` | Container logs, UI credentials, file permissions, memory |
| HTTP 401 | UI username/password; `/healthz` stays public |
| UI works but database times out | Endpoint, DNS/routes, security groups, database authentication |
| Istio 404/503 or TLS error | Hostname, Gateway selector, Service destination, certificate namespace, gateway traffic policy |

Live EKS, Istio, and database access need verification in the target environment; schema and local Docker tests cannot verify those external resources. For configuration rotation, rollback, and storage cleanup, follow the [operations guide](../docs/operations.md).
