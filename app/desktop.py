"""Run and supervise a single-user Compass desktop, with graceful shutdown."""

import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from connection import ConfigurationError, compass_arguments, secret
from ui_auth import configure_ui


def signal_process_group(process, signum):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass  # It exited between poll() and killpg().


def wait_or_kill(process, timeout):
    try:
        process.wait(timeout=max(0, timeout))
    except subprocess.TimeoutExpired:
        signal_process_group(process, signal.SIGKILL)
        process.wait()


def stop_processes(processes, compass_timeout=10, infrastructure_timeout=5):
    # Keep X11, D-Bus, and browser connections available while Compass saves its profile.
    for name, process in processes:
        if name == "Compass":
            signal_process_group(process, signal.SIGTERM)
            wait_or_kill(process, compass_timeout)
    others = [process for name, process in reversed(processes) if name != "Compass"]
    for process in others:
        signal_process_group(process, signal.SIGTERM)
    deadline = time.monotonic() + infrastructure_timeout
    for process in others:
        wait_or_kill(process, deadline - time.monotonic())


def main():
    os.umask(0o077)
    processes = []
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    env = dict(os.environ)
    password = secret(env, "VNC_PASSWORD")
    if password and (not 6 <= len(password) <= 8 or not password.isascii() or not password.isprintable()):
        raise ConfigurationError("Optional VNC_PASSWORD must contain 6-8 printable ASCII characters")
    width, height = env.get("DESKTOP_WIDTH", "1440"), env.get("DESKTOP_HEIGHT", "900")
    if not all(re.fullmatch(r"[0-9]{3,4}", v) and 640 <= int(v) <= 7680 for v in (width, height)):
        raise ConfigurationError("DESKTOP_WIDTH and DESKTOP_HEIGHT must be between 640 and 7680")
    # Support AWS secrets from mounted files as well as standard driver credential providers.
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        value = secret(env, name)
        if value:
            env[name] = value
    Path(env["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="compass-", dir="/tmp") as runtime:
        env["XDG_RUNTIME_DIR"] = runtime
        args = compass_arguments(env, runtime)
        gateway_command = configure_ui(env, runtime)
        if password:
            password_file = Path(runtime) / "vnc-password"
            password_file.write_text(password + "\n")
            vnc_auth = ["-passwdfile", str(password_file)]
        else:
            # Raw VNC is loopback-only; the public HTTP/WebSocket gateway requires UI login.
            vnc_auth = ["-nopw"]
        for name in ("UI_USERNAME", "UI_PASSWORD", "UI_USERNAME_FILE", "UI_PASSWORD_FILE",
                     "VNC_PASSWORD", "VNC_PASSWORD_FILE"):
            env.pop(name, None)

        def start(name, command):
            process = subprocess.Popen(command, env=env, start_new_session=True)
            processes.append((name, process))
            return process

        try:
            start("Xvfb", ["Xvfb", env["DISPLAY"], "-screen", "0", f"{width}x{height}x24",
                           "-nolisten", "tcp", "-ac"])
            for _ in range(100):
                if stopping:
                    return 0
                if processes[0][1].poll() is not None:
                    raise ConfigurationError("Xvfb exited before the desktop was ready")
                probe = subprocess.run(["xdpyinfo", "-display", env["DISPLAY"]], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if probe.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise ConfigurationError("Xvfb did not become ready")
            start("window manager", ["openbox"])
            start("VNC", ["x11vnc", "-display", env["DISPLAY"], "-rfbport", "5900",
                          "-localhost", "-forever", "-shared", "-noxdamage",
                          *vnc_auth, "-quiet"])
            start("WebSocket proxy", ["websockify", "--web=/usr/share/novnc", "--heartbeat=30",
                                      "127.0.0.1:6081", "127.0.0.1:5900"])
            start("authenticated browser gateway", gateway_command)
            # Chromium's sandbox requires kernel privileges unavailable in ordinary Docker containers.
            # The image runs as uid 10001 with all Linux capabilities dropped by Compose.
            start("Compass", ["dbus-run-session", "--", "mongodb-compass", "--no-sandbox",
                              "--disable-gpu", "--ignore-additional-command-line-flags",
                              "--password-store=basic", *args])
            print("Compass browser UI: http://localhost:6080/vnc.html?autoconnect=true&resize=remote", flush=True)
            while not stopping:
                for name, process in processes:
                    if process.poll() is not None:
                        print(f"{name} exited; stopping the desktop", file=sys.stderr)
                        return 1
                time.sleep(0.25)
            return 0
        finally:
            stop_processes(processes)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        sys.exit(2)
