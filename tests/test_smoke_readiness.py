"""Regression checks for MongoDB initialization races in the container smoke suite."""
import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch

import smoke_ui


class MongoDBReadinessTests(unittest.TestCase):
    running = json.dumps({'Running': True, 'Status': 'running', 'ExitCode': 0})

    def test_retries_initialization_and_authentication_until_network_ping_succeeds(self):
        checks = [subprocess.CompletedProcess([], 1, '', 'Database ping failed (MongoServerSelectionError).'),
                  subprocess.CompletedProcess([], 1, '', 'Database ping failed (MongoServerError).'),
                  subprocess.CompletedProcess([], 0, 'Database ping succeeded using configured TLS.\n', '')]
        with patch('smoke_ui.docker', return_value=self.running), \
                patch('smoke_ui.subprocess.run', side_effect=checks) as run, \
                patch('smoke_ui.time.monotonic', side_effect=[0, 0, 31, 31, 62, 62]), \
                patch('smoke_ui.time.sleep'), contextlib.redirect_stdout(io.StringIO()):
            smoke_ui.wait_mongodb_ready('database', 'web')
        self.assertEqual(run.call_count, 3)
        self.assertTrue(all('/opt/compass-container/check_connection.py' in call.args[0] for call in run.call_args_list))
        self.assertTrue(all(call.kwargs['timeout'] <= 30 for call in run.call_args_list))

    def test_exited_fixture_fails_immediately_with_state_and_logs(self):
        state = json.dumps({'Running': False, 'Status': 'exited', 'ExitCode': 132, 'OOMKilled': False})
        output = io.StringIO()
        with patch('smoke_ui.docker', return_value=state), \
                patch('smoke_ui.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', 'CPU feature unavailable')) as run, \
                patch('smoke_ui.time.sleep') as sleep, contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(AssertionError, 'fixture stopped'):
                smoke_ui.wait_mongodb_ready('database', 'web')
        self.assertIn('132', output.getvalue())
        self.assertIn('CPU feature unavailable', output.getvalue())
        self.assertEqual(run.call_args.args[0], ['docker', 'logs', '--tail', '60', 'database'])
        sleep.assert_not_called()

    def test_hanging_check_respects_deadline_and_reports_failure(self):
        output = io.StringIO()
        logs = subprocess.CompletedProcess([], 0, 'fixture still initializing', '')
        with patch('smoke_ui.docker', return_value=self.running), \
                patch('smoke_ui.time.monotonic', side_effect=[0, 0, 5, 5]), \
                patch('smoke_ui.time.sleep') as sleep, \
                patch('smoke_ui.subprocess.run', side_effect=[subprocess.TimeoutExpired(['docker'], 5), logs]) as run, \
                contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(AssertionError, 'within 5 seconds'):
                smoke_ui.wait_mongodb_ready('database', 'web', timeout=5)
        self.assertEqual(run.call_args_list[0].kwargs['timeout'], 5)
        self.assertIn('connection check timed out', output.getvalue())
        self.assertIn('fixture still initializing', output.getvalue())
        sleep.assert_not_called()
