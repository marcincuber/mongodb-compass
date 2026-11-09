"""Supervise browser-native Compass and the authenticated HTTP gateway."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qsl, urlsplit
from connection import ConfigurationError, build_connection, secret
from ui_auth import configure_ui


def runtime_config(env):
    if any(value for key, value in env.items() if key.startswith(('SSH_', 'COMPASS_CONNECTION_FILE', 'COMPASS_CONNECTION_ID', 'COMPASS_CONNECTION_PASSPHRASE'))):
        raise ConfigurationError('Desktop exports and built-in SSH tunnels are not supported; use a reachable database endpoint')
    connection = build_connection(env)
    uri = connection['connectionOptions']['connectionString'] if connection else ''
    options = {key.lower(): value for key, value in parse_qsl(urlsplit(uri).query)}
    if options.get('authmechanism', '').upper() == 'MONGODB-AWS':
        raise ConfigurationError('IAM database authentication is not supported by this browser client; use database credentials')
    insecure = options.get('tlsinsecure') == 'true'
    return {
        'connectionString': uri,
        'name': env.get('COMPASS_CONNECTION_NAME') or 'MongoDB Compass',
        'documentdb': env.get('CONNECTION_TYPE', 'mongodb').lower() == 'documentdb',
        'editable': env.get('CONNECTION_TYPE', 'mongodb').lower() != 'documentdb',
        'storagePassword': secret(env, 'COMPASS_CONNECTIONS_PASSWORD'),
        'tls': {
            'caFile': options.get('tlscafile'),
            'certificateKeyFile': options.get('tlscertificatekeyfile'),
            'password': options.get('tlscertificatekeyfilepassword'),
            'allowInvalidCertificates': insecure or options.get('tlsallowinvalidcertificates') == 'true',
            'allowInvalidHostnames': insecure or options.get('tlsallowinvalidhostnames') == 'true',
        },
    }


def stop_processes(processes, application_timeout=10, gateway_timeout=3):
    for name, process in reversed(processes):
        if process.poll() is not None:
            continue
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=application_timeout if name == 'Compass Web' else gateway_timeout)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def main():
    os.umask(0o077)
    stopping = False
    processes = []
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    env = {key: value for key, value in os.environ.items() if not key.startswith('CW_')}
    config = runtime_config(env)
    Path(env['XDG_CONFIG_HOME']).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='compass-', dir='/tmp') as runtime:
        filename = Path(runtime) / 'connection.json'
        filename.write_text(json.dumps(config))
        filename.chmod(0o600)
        gateway = configure_ui(env, runtime)
        env['COMPASS_RUNTIME_CONFIG'] = str(filename)
        env = {key: value for key, value in env.items()
               if not key.startswith(('UI_', 'MONGODB_', 'COMPASS_CONNECTIONS_PASSWORD'))}
        try:
            for name, command in [('HTTP gateway', gateway), ('Compass Web', ['node', '/opt/compass-container/web.cjs'])]:
                processes.append((name, subprocess.Popen(command, env=env, start_new_session=True)))
            print('Compass browser UI: http://localhost:6080', flush=True)
            while not stopping:
                for name, process in processes:
                    if process.poll() is not None:
                        print(f'{name} exited; stopping the application', file=sys.stderr)
                        return 1
                time.sleep(0.25)
            return 0
        finally:
            stop_processes(processes)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ConfigurationError as error:
        print(f'Configuration error: {error}', file=sys.stderr)
        sys.exit(2)
