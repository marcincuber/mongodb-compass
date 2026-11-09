"""Configure the authenticated HTTP/WebSocket gateway without exposing passwords in argv."""

import os
from pathlib import Path
import subprocess

from connection import ConfigurationError, secret


def configure_ui(env, runtime):
    username = secret(env, "UI_USERNAME")
    password = secret(env, "UI_PASSWORD")
    if not username or not password:
        raise ConfigurationError("UI_USERNAME and UI_PASSWORD are required (or use their _FILE alternatives)")
    if ":" in username or any(ord(char) < 32 or ord(char) == 127 for char in username + password):
        raise ConfigurationError("UI_USERNAME cannot contain ':'; UI credentials cannot contain control characters")
    try:
        result = subprocess.run(["openssl", "passwd", "-6", "-stdin"],
                                input=password.encode("utf-8") + b"\n",
                                capture_output=True, check=True)
        password_hash = result.stdout.decode("ascii").strip()
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        raise ConfigurationError("Could not configure UI password hashing") from None
    if not password_hash.startswith("$6$"):
        raise ConfigurationError("Could not configure UI password hashing")
    runtime = Path(runtime)
    files = {
        "htpasswd": username + ":" + password_hash + "\n",
        "nginx.conf": Path(__file__).with_name("nginx.conf").read_text().replace("@RUNTIME@", str(runtime)),
    }
    for name, content in files.items():
        descriptor = os.open(runtime / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
    return ["nginx", "-p", str(runtime) + "/", "-c", str(runtime / "nginx.conf"), "-g", "daemon off;"]
