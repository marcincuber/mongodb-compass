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


if __name__ == "__main__":
    unittest.main()
