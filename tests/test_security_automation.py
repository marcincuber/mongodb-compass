import copy
import importlib.util
import json
import hashlib
import io
import os
import subprocess
from pathlib import Path
import tempfile
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = script("scan_report")
upgrade = script("upgrade_compass")
IMAGE_ID = "sha256:" + "1" * 64


class ScanPolicyTests(unittest.TestCase):
    def report(self, vulnerabilities=None):
        return {"SchemaVersion": 2, "ArtifactType": "container_image", "Metadata": {"ImageID": IMAGE_ID},
                "Results": [{"Class": "os-pkgs", "Packages": [{"Name": "openssl"}], "Vulnerabilities": vulnerabilities}]}

    def test_clean_report_requires_real_package_inventory(self):
        counts, blocking = scan.inspect_report(self.report(), IMAGE_ID)
        self.assertEqual(counts["HIGH"], 0)
        self.assertEqual(counts["CRITICAL"], 0)
        self.assertEqual(blocking, [])
        summary = scan.render_summary(counts, blocking, "example:tag", IMAGE_ID, "scanner@sha256:123")
        self.assertIn("PASS: 0 HIGH and 0 CRITICAL", summary)

    def test_unfixed_high_and_critical_findings_block(self):
        findings = [{"Severity": "HIGH", "VulnerabilityID": "CVE-HIGH", "FixedVersion": ""},
                    {"Severity": "CRITICAL", "VulnerabilityID": "CVE-CRITICAL", "FixedVersion": "2"},
                    {"Severity": "MEDIUM", "VulnerabilityID": "CVE-MEDIUM"}]
        counts, blocking = scan.inspect_report(self.report(findings), IMAGE_ID)
        self.assertEqual((counts["HIGH"], counts["CRITICAL"], len(blocking)), (1, 1, 2))
        summary = scan.render_summary(counts, blocking, "example:tag", IMAGE_ID, "scanner")
        self.assertIn("FAIL: 1 HIGH and 1 CRITICAL", summary)
        self.assertNotIn("PASS:", summary)

    def test_partial_or_wrong_image_reports_cannot_pass(self):
        cases = [{}, {"SchemaVersion": 2}, self.report()]
        cases[2]["Metadata"]["ImageID"] = "other-image"
        for report in cases:
            with self.subTest(report=report), self.assertRaises(ValueError):
                scan.inspect_report(report, IMAGE_ID)
        report = self.report()
        report["Results"][0]["Packages"] = []
        with self.assertRaises(ValueError):
            scan.inspect_report(report, IMAGE_ID)

    def test_unrecognized_severity_cannot_silently_pass(self):
        with self.assertRaises(ValueError):
            scan.inspect_report(self.report([{"Severity": "NEW-SEVERITY"}]), IMAGE_ID)

    def test_image_id_comes_from_saved_config_not_platform_index(self):
        config = b'{"architecture":"amd64","os":"linux"}'
        manifest = json.dumps([{"Config": "config.json"}]).encode()
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "image.tar"
            with tarfile.open(filename, "w") as archive:
                for name, data in (("manifest.json", manifest), ("config.json", config)):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            self.assertEqual(scan.archive_image_id(filename), "sha256:" + hashlib.sha256(config).hexdigest())

    def test_scan_command_errors_produce_error_report_not_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "docker"
            executable.write_text("#!/bin/sh\nexit 2\n")
            executable.chmod(0o755)
            reports = root / "reports"
            summary = root / "job-summary.md"
            env = {**os.environ, "PATH": directory + os.pathsep + os.defpath,
                   "REPORT_DIR": str(reports), "GITHUB_STEP_SUMMARY": str(summary)}
            result = subprocess.run(["/bin/bash", str(ROOT / "scripts/scan-image.sh")],
                                    env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            for filename in (reports / "summary.md", summary):
                self.assertIn("ERROR", filename.read_text())
                self.assertNotIn("PASS:", filename.read_text())


class CompassUpgradeTests(unittest.TestCase):
    def release(self, version="1.54.0", checksum="b" * 64):
        name = f"mongodb-compass_{version}_amd64.deb"
        return {"tag_name": "v" + version, "draft": False, "prerelease": False, "assets": [{
            "name": name, "digest": "sha256:" + checksum,
            "browser_download_url": f"https://github.com/mongodb-js/compass/releases/download/v{version}/{name}",
        }]}

    def setup_root(self, directory):
        root = Path(directory)
        (root / "docs").mkdir()
        (root / "k8s/examples").mkdir(parents=True)
        (root / "Dockerfile").write_text("FROM ubuntu:26.04\nARG COMPASS_VERSION=1.53.2\nARG COMPASS_SHA256=" + "a" * 64 + "\n")
        (root / "README.md").write_text("[Compass 1.53.2](https://github.com/mongodb-js/compass/releases/tag/v1.53.2)\n")
        (root / "docs/publishing.md").write_text("ECR_TAG=1.53.2-4 make push\n")
        (root / "k8s/examples/example.yaml").write_text("image: example/mongodb-compass:1.53.2-4\n")
        return root

    def test_upgrade_updates_installer_docs_and_kubernetes_examples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            pin = upgrade.resolve(root, self.release())
            upgrade.update_files(root, pin)
            self.assertEqual(upgrade.pinned_release(root), ("1.54.0", "b" * 64))
            self.assertIn("Compass 1.54.0", (root / "README.md").read_text())
            self.assertIn("v1.54.0", (root / "README.md").read_text())
            self.assertIn("ECR_TAG=1.54.0-1", (root / "docs/publishing.md").read_text())
            self.assertIn(":1.54.0-1", (root / "k8s/examples/example.yaml").read_text())

    def test_same_release_is_noop_but_changed_checksum_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            original = (root / "Dockerfile").read_text()
            pin = upgrade.resolve(root, self.release("1.53.2", "a" * 64))
            self.assertFalse(pin["changed"])
            upgrade.update_files(root, pin)
            self.assertEqual((root / "Dockerfile").read_text(), original)
            with self.assertRaises(ValueError):
                upgrade.resolve(root, self.release("1.53.2"))

    def test_missing_digest_wrong_asset_and_unstable_releases_rejected(self):
        release = self.release()
        cases = []
        for key, value in (("draft", True), ("prerelease", True), ("tag_name", "v1.54.0-beta.1"), ("assets", [])):
            case = copy.deepcopy(release)
            case[key] = value
            cases.append(case)
        for key, value in (("digest", None), ("digest", "sha256:bad"), ("browser_download_url", "https://example.com/installer.deb")):
            case = copy.deepcopy(release)
            case["assets"][0][key] = value
            cases.append(case)
        for release in cases:
            with self.subTest(release=release), self.assertRaises(ValueError):
                upgrade.release_pin(release)

    def test_downgrades_and_changed_tested_checksum_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.setup_root(directory)
            with self.assertRaises(ValueError):
                upgrade.resolve(root, self.release("1.52.0"))
            with self.assertRaises(ValueError):
                upgrade.resolve(root, self.release(), expected_sha256="c" * 64)


if __name__ == "__main__":
    unittest.main()
