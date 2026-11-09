import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import check_connection


class ConnectionCheckTests(unittest.TestCase):
    def invoke(self, env, result=None, error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict('os.environ', env, clear=True), \
                patch('check_connection.subprocess.run', return_value=result, side_effect=error) as run, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = check_connection.main()
        return status, stdout.getvalue() + stderr.getvalue(), run

    def test_authenticated_uri_uses_stdin_and_success_requires_ping(self):
        uri = 'mongodb://user:secret@database:27017/?authSource=admin'
        result = subprocess.CompletedProcess([], 0, '{"ok":true}', '')
        status, output, run = self.invoke({'MONGODB_URI': uri}, result)
        self.assertEqual(status, 0, output)
        self.assertIn('ping succeeded', output)
        args, kwargs = run.call_args
        self.assertNotIn(uri, ' '.join(args[0]))
        self.assertEqual(json.loads(kwargs['input'])['connectionString'], uri)
        self.assertEqual(kwargs['timeout'], 25)
        self.assertNotIn('secret', output)

    def test_missing_connection_and_insecure_documentdb_do_not_connect(self):
        for env in ({}, {'CONNECTION_TYPE': 'documentdb', 'MONGODB_HOST': 'database', 'MONGODB_TLS': 'false'}):
            with self.subTest(env=env):
                status, output, run = self.invoke(env)
                self.assertEqual(status, 1)
                self.assertIn('Configuration error', output)
                run.assert_not_called()

    def test_driver_error_details_cannot_expose_credentials(self):
        for error in ('MongoServerSelectionError', 'mongodb://user:secret@database'):
            with self.subTest(error=error):
                result = subprocess.CompletedProcess([], 1, json.dumps({'ok': False, 'error': error}), 'secret')
                status, output, _ = self.invoke({'MONGODB_HOST': 'database'}, result)
                self.assertEqual(status, 1)
                self.assertIn('Database ping failed', output)
                self.assertNotIn('secret', output)

    def test_timeout_or_invalid_output_is_a_failure_without_details(self):
        for response in ('not json: secret', '[]', '{"ok":true}'):
            with self.subTest(response=response):
                status, output, _ = self.invoke({'MONGODB_HOST': 'database'},
                    subprocess.CompletedProcess([], 1, response, 'secret'))
                self.assertEqual(status, 1)
                self.assertNotIn('secret', output)
        status, output, _ = self.invoke({'MONGODB_HOST': 'database'},
            error=subprocess.TimeoutExpired(['node'], 25, output='secret'))
        self.assertEqual(status, 1)
        self.assertNotIn('secret', output)
