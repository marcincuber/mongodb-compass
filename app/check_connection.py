"""Check the configured database from a container/pod without exposing credentials."""

import json
import os
import re
import subprocess
import sys

from connection import ConfigurationError
from server import runtime_config

CHECK = r'''
const {createRequire} = require('node:module');
const {MongoClient} = createRequire('/opt/compass-web/node_modules/compass-web/package.json')('mongodb');
(async () => {
  let input = '';
  for await (const part of process.stdin) input += part;
  const {connectionString} = JSON.parse(input);
  const client = new MongoClient(connectionString, {serverSelectionTimeoutMS: 10000, connectTimeoutMS: 5000});
  try {
    await client.connect();
    await client.db('admin').command({ping: 1});
    console.log(JSON.stringify({ok: true}));
  } finally { await client.close(); }
})().catch(error => {
  console.log(JSON.stringify({ok: false, error: error.name}));
  process.exitCode = 1;
});
'''


def main():
    try:
        config = runtime_config(os.environ)
        if not config['connectionString']:
            raise ConfigurationError('Set MONGODB_HOST or MONGODB_URI to check a database connection')
        result = subprocess.run(['node', '-e', CHECK], input=json.dumps({'connectionString': config['connectionString']}),
                                text=True, capture_output=True, timeout=25)
        response = json.loads(result.stdout)
        if not isinstance(response, dict):
            raise ValueError('Invalid database check response')
        if result.returncode == 0 and response.get('ok') is True:
            print('Database ping succeeded using the configured connection and TLS settings.')
            return 0
        error = response.get('error', '')
        error = error if isinstance(error, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,80}', error) else 'ConnectionError'
        print(f'Database ping failed ({error}). Check endpoint/DNS, routing, security groups, credentials, and certificates.', file=sys.stderr)
    except ConfigurationError as error:
        print(f'Configuration error: {error}', file=sys.stderr)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print('Database check could not complete. Check the runtime and database network access.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
