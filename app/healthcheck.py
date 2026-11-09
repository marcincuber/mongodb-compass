import json
import urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open('http://127.0.0.1:6080/healthz', timeout=1) as response:
    if response.status != 200 or response.read().strip() != b'ok':
        raise SystemExit(1)
with opener.open('http://127.0.0.1:6081/healthz', timeout=1) as response:
    if response.status != 200 or json.load(response).get('status') != 'ok':
        raise SystemExit(1)
