from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from desktop import stop_processes


class DesktopShutdownTests(unittest.TestCase):
    def start(self, script, directory):
        return subprocess.Popen([sys.executable, "-c", script, str(directory)], start_new_session=True)

    def wait_ready(self, processes, files):
        deadline = time.monotonic() + 5
        while not all(filename.exists() for filename in files):
            self.assertTrue(all(process.poll() is None for process in processes))
            self.assertLess(time.monotonic(), deadline, "Child process did not become ready")
            time.sleep(0.01)

    def test_compass_saves_before_display_stops(self):
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
            processes = [("Xvfb", display), ("Compass", compass)]
            try:
                self.wait_ready([compass, display], [root / "compass-ready", root / "display-ready"])
                stop_processes(processes, compass_timeout=2, infrastructure_timeout=2)
                self.assertEqual((root / "display-stopped").read_text(), "True")
                self.assertEqual(compass.returncode, 0)
                self.assertEqual(display.returncode, 0)
            finally:
                stop_processes(processes, compass_timeout=0.1, infrastructure_timeout=0.1)

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
                stop_processes([("Compass", process)], compass_timeout=0.1)
                self.assertEqual(process.returncode, -signal.SIGKILL)
                stop_processes([("Compass", process)])  # Already exited; safe to reap again.
            finally:
                stop_processes([("Compass", process)], compass_timeout=0.1)


if __name__ == "__main__":
    unittest.main()
