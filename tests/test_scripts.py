"""Exercise build/publishing commands without a Docker daemon or AWS account."""

import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUB = r'''
import json, os, sys
tool = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps([tool, *args]) + "\n")
if tool == "aws":
    if args[:2] == ["sts", "get-caller-identity"]:
        print("123456789012")
    elif args[:2] == ["ecr", "describe-repositories"]:
        if os.environ.get("MOCK_MISSING_REPO"):
            sys.exit(1)
        print("123456789012.dkr.ecr.eu-west-2.amazonaws.com/team/compass")
    elif args[:2] == ["ecr", "get-login-password"]:
        if os.environ.get("MOCK_AUTH_FAILURE"):
            sys.exit(1)
        print("mock-token")
elif args[:2] == ["image", "inspect"]:
    if os.environ.get("MOCK_MISSING_IMAGE"):
        sys.exit(1)
    print(os.environ.get("MOCK_ARCH", "linux/amd64"))
elif args[:1] == ["login"]:
    if sys.stdin.read().strip() != "mock-token":
        sys.exit(1)
elif tool == "kubectl" and args[:1] == ["apply"] and os.environ.get("MOCK_APPLY_FAILURE"):
    sys.exit(1)
'''


class ScriptTests(unittest.TestCase):
    def run_command(self, command, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls.jsonl"
            for tool in ("aws", "docker", "kubectl"):
                executable = Path(directory) / tool
                executable.write_text(f"#!{sys.executable}\n" + STUB)
                executable.chmod(0o755)
            env = {"PATH": directory + os.pathsep + os.defpath,
                   "CALL_LOG": str(log), "AWS_REGION": "eu-west-2",
                   "ECR_REPOSITORY": "team/compass", "ECR_TAG": "release-1", **overrides}
            result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    def run_script(self, script, *args, **overrides):
        return self.run_command(["/bin/bash", str(ROOT / "scripts" / script), *args], **overrides)

    def test_build_defaults_and_path(self):
        result, calls = self.run_script("build.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [["docker", "build", "--platform", "linux/amd64", "--tag",
                                 "mongodb-compass:local", str(ROOT)]])

    def test_build_rejects_arm_and_unverified_version(self):
        for env in ({"PLATFORM": "linux/arm64"}, {"COMPASS_VERSION": "1.2.3"}):
            result, calls = self.run_script("build.sh", **env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])

    def test_build_version_and_checksum(self):
        result, calls = self.run_script("build.sh", COMPASS_VERSION="1.2.3", COMPASS_SHA256="abc")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COMPASS_VERSION=1.2.3", calls[0])
        self.assertIn("COMPASS_SHA256=abc", calls[0])

    def test_publish_existing_image(self):
        result, calls = self.run_script("ecr.sh", "push")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call[:3] == ["docker", "login", "--username"] for call in calls))
        self.assertEqual(calls[-2], ["docker", "tag", "mongodb-compass:local",
                                   "123456789012.dkr.ecr.eu-west-2.amazonaws.com/team/compass:release-1"])
        self.assertEqual(calls[-1][:2], ["docker", "push"])
        self.assertFalse(any("create-repository" in call for call in calls))
        self.assertNotIn("mock-token", result.stdout + result.stderr)

    def test_failures_never_push(self):
        for env in ({"MOCK_MISSING_IMAGE": "1"}, {"MOCK_ARCH": "linux/arm64"},
                    {"MOCK_MISSING_REPO": "1"}, {"MOCK_AUTH_FAILURE": "1"}):
            with self.subTest(env=env):
                result, calls = self.run_script("ecr.sh", "push", **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[:2] == ["docker", "push"] for call in calls))

    def test_explicit_repository_creation(self):
        result, calls = self.run_script("ecr.sh", "create", AWS_ACCOUNT_ID="123456789012")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ["aws", "ecr", "create-repository"])
        self.assertIn("IMMUTABLE", calls[0])
        self.assertIn("scanOnPush=true", calls[0])

    def test_deploy_reloads_secret_and_configmap_values(self):
        result, calls = self.run_command([shutil.which("make"), "eks-deploy", "K8S_EXAMPLE=/tmp/edited compass.yaml"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            ["kubectl", "apply", "-f", "/tmp/edited compass.yaml"],
            ["kubectl", "-n", "mongodb-compass", "rollout", "restart", "deployment/mongodb-compass"],
            ["kubectl", "-n", "mongodb-compass", "rollout", "status", "deployment/mongodb-compass", "--timeout=300s"],
        ])

    def test_failed_apply_does_not_restart_running_desktop(self):
        result, calls = self.run_command([shutil.which("make"), "eks-deploy"], MOCK_APPLY_FAILURE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [["kubectl", "apply", "-f", "secrets/compass.yaml"]])


if __name__ == "__main__":
    unittest.main()
