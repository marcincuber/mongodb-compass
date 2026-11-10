"""Opt-in browser runtime, authentication, database protocol, TLS and persistence checks."""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get('IMAGE_NAME', 'mongodb-compass') + ':' + os.environ.get('IMAGE_TAG', 'local')
USERNAME = 'smoke-operator'
PASSWORD = 'smoke-long-pa$$word:with / punctuation!'
DB_PASSWORD = 'database-p@ss word/$!'


def docker(*args, **kwargs):
    return subprocess.run(['docker', *args], capture_output=True, text=True, check=True, **kwargs).stdout.strip()


def request(port, path='/', credentials=None, method='GET', data=None, websocket=False):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    headers = {}
    if credentials:
        headers['Authorization'] = 'Basic ' + base64.b64encode(credentials.encode()).decode()
    key = base64.b64encode(os.urandom(16)).decode()
    if websocket:
        headers.update({'Upgrade': 'websocket', 'Connection': 'Upgrade', 'Sec-WebSocket-Version': '13', 'Sec-WebSocket-Key': key})
    if data is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(data)
    try:
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        if response.status == 101:
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            assert response.getheader('Sec-WebSocket-Accept') == expected
            body = b''
        else:
            body = response.read()
        return response.status, body
    finally:
        connection.close()


def start_web(name, env=None, mounts=(), network=None, file_mode=False):
    args = ['run', '-d', '--platform', 'linux/amd64', '--name', name, '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--user=10001:10001',
            '--tmpfs', '/tmp:rw,nosuid,nodev,uid=10001,gid=10001,mode=1777',
            '--tmpfs', '/home/compass:rw,nosuid,nodev,uid=10001,gid=10001,mode=0700',
            '-p', '127.0.0.1::6080']
    if network:
        args += ['--network', network]
    for mount in mounts:
        args += ['--mount', mount]
    values = {'UI_USERNAME': USERNAME, 'UI_PASSWORD': PASSWORD, **(env or {})}
    for key, value in values.items():
        args += ['-e', key + '=' + value]
    docker(*args, IMAGE)
    return wait_ready(name)


def wait_ready(name):
    port = int(docker('port', name, '6080/tcp').rsplit(':', 1)[1])
    deadline = time.monotonic() + 45
    while True:
        try:
            if request(port, '/api/version', USERNAME + ':' + PASSWORD)[0] == 200:
                docker('exec', name, 'python3', '/opt/compass-container/healthcheck.py')
                return port
        except (OSError, http.client.HTTPException, subprocess.CalledProcessError):
            pass
        if time.monotonic() >= deadline:
            logs = subprocess.run(['docker', 'logs', '--tail', '25', name], capture_output=True, text=True)
            print(logs.stdout + logs.stderr)
            raise AssertionError('Browser server did not become ready')
        time.sleep(0.5)


def remove(name):
    subprocess.run(['docker', 'rm', '-f', '-v', name], capture_output=True)


def stop(name):
    docker('stop', '--timeout', '20', name)
    assert docker('inspect', '--format', '{{.State.ExitCode}}', name) == '0'


def wait_mongodb_ready(database, web, timeout=120):
    """Wait for authenticated network access after the image's init/restart cycle."""
    deadline = time.monotonic() + timeout
    last_check = 'Database connection has not succeeded yet.'
    print('Waiting for the MongoDB fixture and authenticated database access...', flush=True)
    while True:
        state = json.loads(docker('inspect', '--format', '{{json .State}}', database))
        if not state['Running'] or state.get('Paused'):
            reason = 'MongoDB fixture stopped before becoming ready'
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            reason = f'MongoDB did not initialize within {timeout} seconds'
            break
        try:
            # Use the application's driver, credentials and Docker-network endpoint.
            # The image's temporary localhost-only initialization server is not ready.
            result = subprocess.run(['docker', 'exec', web, 'python3',
                                     '/opt/compass-container/check_connection.py'],
                                    capture_output=True, text=True, timeout=min(30, remaining))
            if result.returncode == 0:
                assert 'Database ping succeeded' in result.stdout, result.stdout
                print(result.stdout.strip(), flush=True)
                return
            last_check = result.stderr.strip() or result.stdout.strip() or f'Connection check exited {result.returncode}'
        except subprocess.TimeoutExpired:
            last_check = 'Database connection check timed out.'
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(2, remaining))
    print(f'{reason}. Container state: {json.dumps(state)}', flush=True)
    print(last_check, flush=True)
    logs = subprocess.run(['docker', 'logs', '--tail', '60', database], capture_output=True, text=True, timeout=10)
    print(logs.stdout + logs.stderr, flush=True)
    raise AssertionError(reason)


def test_browser():
    name = 'compass-browser-smoke-' + uuid.uuid4().hex[:10]
    try:
        port = start_web(name, {'HTTP_PROXY': 'http://127.0.0.1:9', 'NO_PROXY': ''})
        credentials = USERNAME + ':' + PASSWORD
        for path, websocket in (('/', False), ('/api/version', False), ('/compass.js', False), ('/mongo', True)):
            for login in (None, USERNAME + ':wrong-password', USERNAME + ':' + PASSWORD[:8]):
                assert request(port, path, login, websocket=websocket)[0] == 401
            status, _ = request(port, path, credentials, websocket=websocket)
            assert status == (101 if websocket else 200), (path, status)
        _, page = request(port, '/', credentials)
        assert b'<html' in page.lower() and b'compass' in page.lower()
        docker('exec', name, 'python3', '-c',
               'import os,shutil; assert os.getuid()==10001; assert not any(shutil.which(x) for x in ["Xvfb","x11vnc","websockify","mongodb-compass"]); assert not os.path.exists("/opt/compass-container/desktop.py")')
        docker('kill', '--signal=KILL', name)
        docker('start', name)
        wait_ready(name)
        stop(name)
        print('Native HTML, API/static/WebSocket authentication, non-root read-only runtime and forced restart passed.')
    finally:
        remove(name)


def test_files_and_persistence():
    volume = 'compass-web-settings-' + uuid.uuid4().hex[:10]
    docker('volume', 'create', volume)
    try:
        with tempfile.TemporaryDirectory(prefix='compass-web-secrets-') as directory:
            Path(directory).chmod(0o755)
            for key, value in (('username', USERNAME), ('password', PASSWORD)):
                file = Path(directory) / key
                file.write_text(value + '\n')
                file.chmod(0o644)  # Dummy test credentials, readable by the container UID.
            for attempt in range(2):
                name = 'compass-files-smoke-' + uuid.uuid4().hex[:10]
                try:
                    port = start_web(name, {'UI_USERNAME': '', 'UI_PASSWORD': '',
                        'UI_USERNAME_FILE': '/run/test-secrets/username', 'UI_PASSWORD_FILE': '/run/test-secrets/password',
                        'COMPASS_CONNECTIONS_PASSWORD': 'separate-storage-secret'}, mounts=(
                            f'type=bind,src={directory},dst=/run/test-secrets,readonly',
                            f'type=volume,src={volume},dst=/home/compass/.config'))
                    credentials = USERNAME + ':' + PASSWORD
                    if attempt == 0:
                        value = {'id': 'persisted', 'connectionOptions': {'connectionString': 'mongodb://user:private-storage-password@db.invalid/'}}
                        assert request(port, '/api/connection-info', credentials, 'POST', value)[0] == 200
                    status, data = request(port, '/api/connection-info', credentials)
                    assert status == 200 and b'persisted' in data
                    docker('exec', name, 'python3', '-c',
                           'from pathlib import Path; p=list(Path.home().joinpath(".config").glob("connections-*.json")); assert p; assert all("private-storage-password" not in x.read_text() for x in p)')
                    stop(name)
                finally:
                    remove(name)
        print('Mounted UI secrets and encrypted connection persistence across container replacement passed.')
    finally:
        subprocess.run(['docker', 'volume', 'rm', volume], capture_output=True)


def test_mongodb_transport():
    prefix = 'compass-wire-' + uuid.uuid4().hex[:10]
    network, database, web = prefix, prefix + '-db', prefix + '-web'
    try:
        docker('network', 'create', network)
        # MongoDB's rseq regression test uses this to disable TCMalloc per-CPU
        # caches on kernels affected by SERVER-121912. Keep it fixture-local.
        # https://github.com/mongodb/mongo/blob/r8.0.32/jstests/noPassthrough/rseq_linux_compatibility/rseq_kernel_compatibility_check.js
        docker('run', '-d', '--name', database, '--network', network, '--network-alias', 'mongo-smoke',
               '-e', 'GLIBC_TUNABLES=glibc.pthread.rseq=1',
               '-e', 'MONGO_INITDB_ROOT_USERNAME=smoke-user', '-e', 'MONGO_INITDB_ROOT_PASSWORD=' + DB_PASSWORD, 'mongo:8.0')
        start_web(web, {'MONGODB_HOST': 'mongo-smoke', 'MONGODB_USERNAME': 'smoke-user',
                       'MONGODB_PASSWORD': DB_PASSWORD, 'MONGODB_AUTH_SOURCE': 'admin', 'MONGODB_TLS': 'false'}, network=network)
        wait_mongodb_ready(database, web)
        output = docker('exec', '-i', '-w', '/opt/compass-web', '-e', 'SMOKE_UI_PASSWORD=' + PASSWORD,
                        '-e', 'SMOKE_DB_PASSWORD=' + DB_PASSWORD, web, 'node', input=(ROOT / 'tests/smoke_wire.cjs').read_text())
        print(output)
        stop(web)
    finally:
        remove(web)
        remove(database)
        subprocess.run(['docker', 'network', 'rm', network], capture_output=True)


def test_documentdb_tls():
    prefix = 'compass-tls-' + uuid.uuid4().hex[:10]
    network, backend, web = prefix, prefix + '-tls', prefix + '-web'
    with tempfile.TemporaryDirectory(prefix='compass-tls-fixture-') as directory:
        root = Path(directory)
        root.chmod(0o755)
        def openssl(*args):
            subprocess.run(['openssl', *args], cwd=root, check=True, capture_output=True)
        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=Test CA',
                '-addext', 'basicConstraints=critical,CA:TRUE', '-keyout', 'ca.key', '-out', 'ca.pem')
        openssl('req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=tls-good', '-keyout', 'server.key', '-out', 'server.csr')
        (root / 'extensions').write_text('subjectAltName=DNS:tls-good\n')
        openssl('x509', '-req', '-in', 'server.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial',
                '-days', '2', '-extfile', 'extensions', '-out', 'server.crt')
        openssl('req', '-newkey', 'rsa:2048', '-passout', 'pass:fixture-client-password', '-subj', '/CN=Test Client',
                '-keyout', 'client.key', '-out', 'client.csr')
        openssl('x509', '-req', '-in', 'client.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial',
                '-days', '2', '-out', 'client.crt')
        (root / 'client.pem').write_bytes((root / 'client.key').read_bytes() + (root / 'client.crt').read_bytes())
        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=Other CA',
                '-addext', 'basicConstraints=critical,CA:TRUE', '-keyout', 'other.key', '-out', 'other.pem')
        for path in root.iterdir():
            path.chmod(0o644)  # Ephemeral test material only.
        echo = '''import socket,ssl,threading
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/certs/server.crt','/certs/server.key')
context.load_verify_locations('/certs/ca.pem')
context.verify_mode=ssl.CERT_REQUIRED
def serve(connection):
    try:
        with context.wrap_socket(connection,server_side=True) as secure:
            while data:=secure.recv(65536): secure.sendall(data)
    except (OSError,ssl.SSLError): connection.close()
with socket.create_server(('0.0.0.0',27017)) as server:
    while True:
        connection,_=server.accept()
        threading.Thread(target=serve,args=(connection,),daemon=True).start()
'''
        try:
            docker('network', 'create', network)
            docker('run', '-d', '--platform', 'linux/amd64', '--name', backend, '--network', network, '--network-alias', 'tls-good', '--network-alias', 'tls-wrong',
                   '--mount', f'type=bind,src={directory},dst=/certs,readonly', '--entrypoint', 'python3', IMAGE, '-u', '-c', echo)
            port = start_web(web, {'CONNECTION_TYPE': 'documentdb', 'MONGODB_HOST': 'tls-good', 'MONGODB_TLS_CA_FILE': '/certs/ca.pem',
                                   'MONGODB_TLS_CERTIFICATE_KEY_FILE': '/certs/client.pem',
                                   'MONGODB_TLS_CERTIFICATE_KEY_FILE_PASSWORD': 'fixture-client-password'},
                            mounts=(f'type=bind,src={directory},dst=/certs,readonly',), network=network)
            _, connections = request(port, '/api/connection-info', USERNAME + ':' + PASSWORD)
            assert b'tlsCAFile' not in connections and b'/certs' not in connections and b'fixture-client-password' not in connections
            assert request(port, '/api/connection-info', USERNAME + ':' + PASSWORD, 'POST',
                           {'id': 'unsafe', 'connectionOptions': {'connectionString': 'mongodb://tls-good/?tls=false'}})[0] == 400
            print(docker('exec', '-i', '-w', '/opt/compass-web', '-e', 'SMOKE_UI_PASSWORD=' + PASSWORD,
                         web, 'node', input=(ROOT / 'tests/smoke_tls.cjs').read_text()))
            stop(web)
            remove(web)
            start_web(web, {'CONNECTION_TYPE': 'documentdb', 'MONGODB_HOST': 'tls-good', 'MONGODB_TLS_CA_FILE': '/certs/other.pem'},
                      mounts=(f'type=bind,src={directory},dst=/certs,readonly',), network=network)
            print(docker('exec', '-i', '-w', '/opt/compass-web', '-e', 'SMOKE_UI_PASSWORD=' + PASSWORD,
                         '-e', 'SMOKE_UNTRUSTED_ONLY=true', web, 'node', input=(ROOT / 'tests/smoke_tls.cjs').read_text()))
            stop(web)
        finally:
            remove(web)
            remove(backend)
            subprocess.run(['docker', 'network', 'rm', network], capture_output=True)


if __name__ == '__main__':
    missing = subprocess.run(['docker', 'run', '--rm', '--platform', 'linux/amd64', '-e', 'UI_USERNAME=' + USERNAME, IMAGE], capture_output=True, text=True)
    assert missing.returncode == 2 and 'UI_USERNAME and UI_PASSWORD are required' in missing.stderr
    rejected = subprocess.run(['docker', 'run', '--rm', '--platform', 'linux/amd64', '-e', 'CONNECTION_TYPE=documentdb',
                               '-e', 'MONGODB_HOST=db.invalid', '-e', 'MONGODB_TLS=false', IMAGE], capture_output=True, text=True)
    assert rejected.returncode == 2 and 'DocumentDB requires TLS' in rejected.stderr
    test_browser()
    test_files_and_persistence()
    test_mongodb_transport()
    test_documentdb_tls()
