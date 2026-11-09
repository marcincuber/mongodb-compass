from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from connection import ConfigurationError
from server import runtime_config, stop_processes


class WebShutdownTests(unittest.TestCase):
    def start(self, script, directory):
        return subprocess.Popen([sys.executable, "-c", script, str(directory)], start_new_session=True)

    def wait_ready(self, processes, files):
        deadline = time.monotonic() + 5
        while not all(filename.exists() for filename in files):
            self.assertTrue(all(process.poll() is None for process in processes))
            self.assertLess(time.monotonic(), deadline, "Child process did not become ready")
            time.sleep(0.01)

    def test_application_stops_before_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            compass = self.start('''
from pathlib import Path
import signal, sys, time
root = Path(sys.argv[1])
def stop(*args):
    time.sleep(0.1)
    (root / "saved").write_text("profile flushed")
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
(root / "compass-ready").touch()
while True: signal.pause()
''', root)
            display = self.start('''
from pathlib import Path
import signal, sys
root = Path(sys.argv[1])
def stop(*args):
    (root / "display-stopped").write_text(str((root / "saved").exists()))
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
(root / "display-ready").touch()
while True: signal.pause()
''', root)
            processes = [("HTTP gateway", display), ("Compass Web", compass)]
            try:
                self.wait_ready([compass, display], [root / "compass-ready", root / "display-ready"])
                stop_processes(processes, application_timeout=2, gateway_timeout=2)
                self.assertEqual((root / "display-stopped").read_text(), "True")
                self.assertEqual(compass.returncode, 0)
                self.assertEqual(display.returncode, 0)
            finally:
                stop_processes(processes, application_timeout=0.1, gateway_timeout=0.1)

    def test_unresponsive_process_is_killed_within_shutdown_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            process = self.start('''
from pathlib import Path
import signal, sys
signal.signal(signal.SIGTERM, signal.SIG_IGN)
(Path(sys.argv[1]) / "ready").touch()
while True: signal.pause()
''', directory)
            try:
                self.wait_ready([process], [Path(directory) / "ready"])
                stop_processes([("Compass Web", process)], application_timeout=0.1)
                self.assertEqual(process.returncode, -signal.SIGKILL)
                stop_processes([("Compass Web", process)])  # Already exited; safe to reap again.
            finally:
                stop_processes([("Compass Web", process)], application_timeout=0.1)


class RuntimeConfigTests(unittest.TestCase):
    def test_manual_connections_and_storage_secret(self):
        with tempfile.NamedTemporaryFile(mode="w") as password:
            password.write("storage-secret\n")
            password.flush()
            config = runtime_config({"COMPASS_CONNECTIONS_PASSWORD_FILE": password.name})
            self.assertTrue(config["editable"])
            self.assertEqual(config["storagePassword"], "storage-secret")

    def test_generic_connections_allow_manual_additions(self):
        config = runtime_config({"MONGODB_HOST": "localhost", "MONGODB_TLS": "false"})
        self.assertTrue(config["editable"])
        self.assertIn("tls=false", config["connectionString"])

    def test_unsupported_desktop_configuration_is_rejected(self):
        for env in ({"SSH_HOST": "bastion"}, {"COMPASS_CONNECTION_FILE": "/tmp/export.json"},
                    {"MONGODB_URI": "mongodb://db/?authMechanism=MONGODB-AWS"}):
            with self.subTest(env=env), self.assertRaises(ConfigurationError):
                runtime_config(env)


if __name__ == "__main__":
    unittest.main()
