from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from connection import ConfigurationError
from ui_auth import configure_ui


class UIAuthTests(unittest.TestCase):
    def test_credentials_required_and_control_characters_rejected(self):
        cases = [{}, {"UI_USERNAME": "admin"}, {"UI_PASSWORD": "secret"},
                 {"UI_USERNAME": "bad:name", "UI_PASSWORD": "secret"},
                 {"UI_USERNAME": "admin\nother", "UI_PASSWORD": "secret"},
                 {"UI_USERNAME": "admin", "UI_PASSWORD": "first\nsecond"},
                 {"UI_USERNAME": "admin", "UI_PASSWORD": "null\0byte"}]
        with tempfile.TemporaryDirectory() as runtime:
            for env in cases:
                with self.subTest(keys=list(env)), self.assertRaises(ConfigurationError):
                    configure_ui(env, runtime)

    def test_hashed_credentials_and_private_files(self):
        password = 'a long password with : / $ ! " and spaces'
        with tempfile.TemporaryDirectory() as runtime:
            command = configure_ui({"UI_USERNAME": "operator", "UI_PASSWORD": password}, runtime)
            authfile = Path(runtime) / "htpasswd"
            self.assertTrue(authfile.read_text().startswith("operator:$6$"))
            self.assertNotIn(password, authfile.read_text())
            self.assertNotIn(password, " ".join(command))
            self.assertEqual(authfile.stat().st_mode & 0o777, 0o600)
            self.assertEqual((Path(runtime) / "nginx.conf").stat().st_mode & 0o777, 0o600)
            self.assertNotIn("@RUNTIME@", (Path(runtime) / "nginx.conf").read_text())

    def test_credentials_from_mounted_files(self):
        with tempfile.TemporaryDirectory() as runtime:
            username_file = Path(runtime) / "username"
            password_file = Path(runtime) / "password"
            username_file.write_text("operator\n")
            password_file.write_text("a long password\n")
            configure_ui({"UI_USERNAME_FILE": str(username_file), "UI_PASSWORD_FILE": str(password_file)}, runtime)
            self.assertTrue((Path(runtime) / "htpasswd").read_text().startswith("operator:$6$"))
            with self.assertRaises(ConfigurationError):
                configure_ui({"UI_USERNAME": "operator", "UI_USERNAME_FILE": str(username_file),
                              "UI_PASSWORD": "password"}, runtime)

    def test_hashing_error_is_safe_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as runtime, patch("ui_auth.subprocess.run", side_effect=OSError):
            with self.assertRaises(ConfigurationError) as error:
                configure_ui({"UI_USERNAME": "operator", "UI_PASSWORD": "private-secret"}, runtime)
            self.assertNotIn("private-secret", str(error.exception))
            self.assertFalse((Path(runtime) / "htpasswd").exists())


if __name__ == "__main__":
    unittest.main()
