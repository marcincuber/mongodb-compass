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
elif args[:2] == ["network", "inspect"]:
    sys.exit(0 if os.environ.get("MOCK_LOCAL_EXISTS") else 1)
elif args[:2] == ["container", "inspect"]:
    if not os.environ.get("MOCK_LOCAL_EXISTS"):
        sys.exit(1)
    if "--format" in args:
        template = args[args.index("--format") + 1]
        if ".Mounts" in template:
            if not os.environ.get("MOCK_UNMOUNTED_PROFILE"):
                print("mongodb-compass-config")
        elif ".State.Running" in template:
            print("false")
        elif not os.environ.get("MOCK_LOCAL_DETACHED"):
            print("connected")
elif args[:1] == ["cp"] and os.environ.get("MOCK_CP_FAILURE"):
    sys.exit(1)
elif args[:1] == ["exec"] and os.environ.get("MOCK_UI_EXITED"):
    sys.exit(1)
elif args[:1] == ["info"] and os.environ.get("MOCK_DOCKER_UNAVAILABLE"):
    sys.exit(1)
elif args[:1] == ["build"] and os.environ.get("MOCK_BUILD_FAILURE"):
    sys.exit(1)
elif args[:3] == ["network", "create", "compass-local"] and os.environ.get("MOCK_NETWORK_FAILURE"):
    sys.exit(1)
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
        self.assertEqual(calls, [["docker", "build", "--pull", "--platform", "linux/amd64", "--tag",
                                 "mongodb-compass:local", str(ROOT)]])

    def test_build_rejects_unsupported_architecture(self):
        result, calls = self.run_script("build.sh", PLATFORM="linux/arm64")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

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

    def test_local_stack_creates_missing_resources(self):
        result, calls = self.run_command(["/bin/bash", str(ROOT / "test-script.sh")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["docker", "network", "create", "compass-local"], calls)
        runs = [call for call in calls if call[:2] == ["docker", "run"]]
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0][-1], "mongo:8.0")
        self.assertIn("mongodb-local-data:/data/db", runs[0])
        self.assertIn("mongodb-compass", runs[1])
        self.assertIn("127.0.0.1:6080:6080", runs[1])
        self.assertIn("MONGODB_HOST=mongodb-local", runs[1])
        self.assertNotIn("--shm-size=1g", runs[1])
        self.assertEqual(runs[1][-1], "mongodb-compass:local")
        self.assertIn(["docker", "build", "--pull", "--platform", "linux/amd64", "--tag",
                       "mongodb-compass:local", str(ROOT)], calls)
        self.assertFalse(any("mongodb-compass-web" in call or
                             any("haohanyang/compass-web" in arg for arg in call) for call in calls))
        self.assertIn("http://localhost:6080", result.stdout)
        self.assertIn(["docker", "exec", "mongodb-compass", "python3", "/opt/compass-container/healthcheck.py"], calls)
        self.assertIn("type=volume,src=mongodb-compass-config,dst=/home/compass/.config", runs[1])

    def test_local_stack_builds_and_runs_same_custom_image_tag(self):
        result, calls = self.run_command(["/bin/bash", str(ROOT / "test-script.sh")],
                                         IMAGE_NAME="my-compass", IMAGE_TAG="dev")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["docker", "build", "--pull", "--platform", "linux/amd64", "--tag", "my-compass:dev", str(ROOT)], calls)
        runs = [call for call in calls if call[:2] == ["docker", "run"]]
        self.assertEqual(runs[1][-1], "my-compass:dev")

    def test_local_stack_preserves_raw_credentials_for_project_image(self):
        password = 'p@ss word/$!?:#%'
        result, calls = self.run_command(["/bin/bash", str(ROOT / "test-script.sh")],
                                         DB_PASSWORD=password, UI_PASSWORD="ui-password")
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = [call for call in calls if call[:2] == ["docker", "run"]]
        self.assertIn("MONGO_INITDB_ROOT_PASSWORD=" + password, runs[0])
        self.assertIn("MONGODB_PASSWORD=" + password, runs[1])
        self.assertIn("UI_PASSWORD=ui-password", runs[1])
        self.assertNotIn(password, result.stdout + result.stderr)

    def test_local_stack_replaces_ui_and_preserves_database_and_settings(self):
        result, calls = self.run_command(["/bin/bash", str(ROOT / "test-script.sh")], MOCK_LOCAL_EXISTS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["docker", "start", "mongodb-local"], calls)
        self.assertIn(["docker", "stop", "--timeout", "20", "mongodb-compass"], calls)
        self.assertIn(["docker", "rm", "mongodb-compass"], calls)
        self.assertFalse(any("mongodb-compass-web" in call for call in calls))
        runs = [call for call in calls if call[:2] == ["docker", "run"]]
        self.assertEqual(len(runs), 1)
        self.assertIn("type=volume,src=mongodb-compass-config,dst=/home/compass/.config", runs[0])
        self.assertFalse(any(call[:3] in (["docker", "rm", "mongodb-local"], ["docker", "stop", "mongodb-local"],
                                        ["docker", "network", "create"], ["docker", "volume", "rm"])
                             for call in calls))

    def test_local_stack_preserves_settings_before_replacing_container(self):
        result, calls = self.run_command(["/bin/bash", str(ROOT / "test-script.sh")],
                                         MOCK_LOCAL_EXISTS="1", MOCK_UNMOUNTED_PROFILE="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        copy_call = ["docker", "cp", "mongodb-compass:/home/compass/.config/.", "-"]
        self.assertIn(copy_call, calls)
        self.assertLess(calls.index(copy_call), calls.index(["docker", "rm", "mongodb-compass"]))
        self.assertTrue(any(call[:2] == ["docker", "run"] and "--entrypoint" in call and "python3" in call and
                            any('archive.extractall("/settings", filter="data")' in arg for arg in call) for call in calls))

    def test_local_stack_keeps_container_when_profile_copy_fails(self):
        result, calls = self.run_command(["/bin/bash", str(ROOT / "test-script.sh")],
                                         MOCK_LOCAL_EXISTS="1", MOCK_UNMOUNTED_PROFILE="1", MOCK_CP_FAILURE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(["docker", "rm", "mongodb-compass"], calls)

    def test_local_stack_reports_failure_instead_of_ready_when_ui_exits(self):
        result, calls = self.run_command(["/bin/bash", str(ROOT / "test-script.sh")], MOCK_UI_EXITED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Compass is ready", result.stdout)
        self.assertIn("did not become ready", result.stderr)
        self.assertIn(["docker", "logs", "--tail", "40", "mongodb-compass"], calls)

    def test_local_stack_reconnects_existing_containers(self):
        result, calls = self.run_command(["/bin/bash", str(ROOT / "test-script.sh")],
                                         MOCK_LOCAL_EXISTS="1", MOCK_LOCAL_DETACHED="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["docker", "network", "connect", "compass-local", "mongodb-local"], calls)
        self.assertTrue(any(call[:2] == ["docker", "run"] and "compass-local" in call for call in calls))

    def test_local_stack_stops_after_docker_build_or_network_failure(self):
        for env in ({"MOCK_DOCKER_UNAVAILABLE": "1"}, {"MOCK_BUILD_FAILURE": "1"}, {"MOCK_NETWORK_FAILURE": "1"}):
            with self.subTest(env=env):
                result, calls = self.run_command(["/bin/bash", str(ROOT / "test-script.sh")], **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[:2] == ["docker", "run"] or call[1:2] == ["volume"] for call in calls))


if __name__ == "__main__":
    unittest.main()
