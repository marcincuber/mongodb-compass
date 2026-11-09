"""Opt-in Docker tests for the desktop, authentication, probes, and persistent settings."""

import base64
import hashlib
import http.client
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

IMAGE = os.environ.get("IMAGE_NAME", "mongodb-compass") + ":" + os.environ.get("IMAGE_TAG", "local")
USERNAME = "smoke-operator"
PASSWORD = 'smoke-long-pa$$word:with / punctuation!'


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True, **kwargs).stdout.strip()


def test_documentdb_tls_policy():
    check = r'''
import os, sys, tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
sys.path.insert(0, "/opt/compass-container")
from connection import ConfigurationError, build_connection
assert os.getuid() == 10001
base = {"CONNECTION_TYPE": "documentdb", "MONGODB_HOST": "example.invalid"}
safe = build_connection(base)
options = dict(parse_qsl(urlsplit(safe["connectionOptions"]["connectionString"]).query))
assert options["tls"] == "true"
assert options["tlsAllowInvalidCertificates"] == options["tlsAllowInvalidHostnames"] == "false"
assert options["tlsCAFile"] == "/opt/certs/global-bundle.pem"
cases = [{"MONGODB_TLS": "false"}, {"MONGODB_TLS_INSECURE": "true"},
         {"MONGODB_TLS_ALLOW_INVALID_CERTIFICATES": "true"},
         {"MONGODB_TLS_ALLOW_INVALID_HOSTNAMES": "true"},
         {"MONGODB_URI": "mongodb://db/?ssl=false", "MONGODB_TLS": "true"},
         {"MONGODB_OPTIONS": '{"tlsInsecure":true}'},
         {"MONGODB_OPTIONS": '{"tls":false,"tls":true}'}]
def rejected(env):
    try: build_connection({**base, **env})
    except ConfigurationError: return
    raise AssertionError("Unsafe DocumentDB configuration was accepted")
for env in cases: rejected(env)
with tempfile.TemporaryDirectory() as directory:
    ca = Path(directory) / "ca.pem"
    ca.write_text("not a certificate")
    rejected({"MONGODB_TLS_CA_FILE": str(ca)})
    ca.write_bytes(Path("/opt/certs/global-bundle.pem").read_bytes())
    ca.chmod(0)
    rejected({"MONGODB_TLS_CA_FILE": str(ca)})
    ca.chmod(0o600)
'''
    docker("run", "--rm", "--platform", "linux/amd64", "--entrypoint", "python3", IMAGE, "-c", check)
    invalid = subprocess.run(["docker", "run", "--rm", "--platform", "linux/amd64",
                              "--env", "CONNECTION_TYPE=documentdb", "--env", "MONGODB_HOST=example.invalid",
                              "--env", "MONGODB_TLS=false", IMAGE], capture_output=True, text=True)
    assert invalid.returncode == 2 and "DocumentDB requires TLS" in invalid.stderr
    print("DocumentDB TLS policy, real AWS CA parsing, unreadable CA rejection, and startup failure passed.")


def probe(port, path, credentials=None, websocket=False):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {}
    if credentials:
        headers["Authorization"] = "Basic " + base64.b64encode(credentials.encode()).decode()
    key = base64.b64encode(os.urandom(16)).decode()
    if websocket:
        headers.update({"Upgrade": "websocket", "Connection": "Upgrade",
                        "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": key,
                        "Sec-WebSocket-Protocol": "binary"})
    response = None
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status == 101:
            expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            assert response.getheader("Sec-WebSocket-Accept") == expected
            frame = response.fp.read(2)
            assert len(frame) == 2 and frame[0] & 15 == 2, "Expected a binary VNC WebSocket frame"
            length = frame[1] & 127
            assert 0 < length < 126
            assert response.fp.read(length).startswith(b"RFB "), "VNC handshake missing"
        else:
            response.read()
        return response.status, response.getheader("WWW-Authenticate")
    finally:
        if response:
            response.close()
        connection.close()


def test_gateway(file_mode, settings_volume=None, expect_settings=False):
    name = "compass-ui-smoke-" + uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix="compass-ui-secrets-") as directory:
        args = ["run", "--detach", "--platform", "linux/amd64", "--name", name,
                "--read-only", "--user=10001:10001", "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true", "--shm-size=1g", "--memory=3g", "--cpus=2",
                "--tmpfs", "/tmp:rw,nosuid,nodev,uid=10001,gid=10001,mode=1777",
                "--tmpfs", "/home/compass:rw,nosuid,nodev,uid=10001,gid=10001,mode=0700",
                "--publish", "127.0.0.1::6080"]
        if settings_volume:
            args += ["--mount", f"type=volume,src={settings_volume},dst=/home/compass/.config"]
        for variable, value in (("UI_USERNAME", USERNAME), ("UI_PASSWORD", PASSWORD)):
            if file_mode:
                filename = Path(directory) / variable
                filename.write_text(value + "\n")
                filename.chmod(0o644)  # Dummy test credentials, readable by the container UID.
                target = "/run/secrets/" + variable
                args += ["--mount", f"type=bind,src={filename},dst={target},readonly",
                         "--env", variable + "_FILE=" + target]
            else:
                args += ["--env", variable + "=" + value]
        if file_mode:
            # Local probes must work without relying on the user's NO_PROXY configuration.
            args += ["--env", "HTTP_PROXY=http://127.0.0.1:9", "--env", "NO_PROXY="]
        try:
            docker(*args, IMAGE)
            port = int(docker("port", name, "6080/tcp").rsplit(":", 1)[1])
            deadline = time.monotonic() + 45
            while True:
                try:
                    if (probe(port, "/healthz")[0] == 200 and
                            probe(port, "/vnc.html", USERNAME + ":" + PASSWORD)[0] == 200):
                        windows = docker("exec", name, "xwininfo", "-root", "-tree")
                        if '"MongoDB Compass"' in windows:
                            break
                except (OSError, http.client.HTTPException):
                    pass
                if time.monotonic() >= deadline:
                    raise AssertionError("Compass window and browser gateway did not become ready")
                time.sleep(0.5)
            for websocket, path in ((False, "/vnc.html"), (True, "/websockify")):
                for credentials in (None, USERNAME + ":wrong-password", USERNAME + ":" + PASSWORD[:8],
                                    "wrong-user:" + PASSWORD):
                    status, challenge = probe(port, path, credentials, websocket)
                    assert status == 401 and challenge.startswith("Basic "), (path, status)
                status = probe(port, path, USERNAME + ":" + PASSWORD, websocket)[0]
                assert status == (101 if websocket else 200), (path, status)
            docker("exec", name, "python3", "/opt/compass-container/healthcheck.py")
            if settings_volume:
                if expect_settings:
                    docker("exec", name, "python3", "-c",
                           'from pathlib import Path; assert (Path.home()/".config/smoke-persistence").read_text() == "saved"')
                else:
                    docker("exec", name, "python3", "-c",
                           'from pathlib import Path; (Path.home()/".config/smoke-persistence").write_text("saved")')
            docker("stop", "--timeout", "15", name)
            assert docker("inspect", name, "--format", "{{.State.ExitCode}}") == "0"
            print(f"Compass window, UI authentication, WebSockets, health and shutdown passed ({'Secret files with HTTP_PROXY' if file_mode else 'environment'}).")
            if expect_settings:
                print("Settings survived container replacement and Compass reopened its existing profile.")
        except Exception:
            logs = subprocess.run(["docker", "logs", "--tail", "30", name], capture_output=True, text=True)
            print(logs.stdout + logs.stderr)
            raise
        finally:
            subprocess.run(["docker", "rm", "--force", name], capture_output=True)


if __name__ == "__main__":
    missing = subprocess.run(["docker", "run", "--rm", "--platform", "linux/amd64",
                              "--env", "UI_USERNAME=" + USERNAME, IMAGE], capture_output=True, text=True)
    assert missing.returncode == 2 and "UI_USERNAME and UI_PASSWORD are required" in missing.stderr
    print("Missing UI credentials fail closed.")
    test_documentdb_tls_policy()
    test_gateway(file_mode=False)
    volume = "compass-settings-smoke-" + uuid.uuid4().hex[:10]
    try:
        docker("volume", "create", volume)
        test_gateway(file_mode=True, settings_volume=volume)
        test_gateway(file_mode=True, settings_volume=volume, expect_settings=True)
    finally:
        subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
