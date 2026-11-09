import socket
import urllib.request

# Probes target pod-local services even when the workload configures an outbound proxy.
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for url in ("http://127.0.0.1:6080/healthz", "http://127.0.0.1:6081/vnc.html"):
    with opener.open(url, timeout=1) as response:
        if response.status != 200:
            raise SystemExit(1)
with socket.create_connection(("127.0.0.1", 5900), timeout=1) as connection:
    connection.settimeout(1)
    if not connection.makefile("rb").read(12).startswith(b"RFB "):
        raise SystemExit(1)
