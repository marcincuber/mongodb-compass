"""Fail closed on incomplete scans; report exact HIGH/CRITICAL finding counts."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import sys
import tarfile

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")


def archive_image_id(filename):
    # Docker Desktop/containerd may expose an index digest as .Id. Trivy identifies
    # the image by its config digest, so derive it from the exact saved archive.
    with tarfile.open(filename) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        if not isinstance(manifest, list) or len(manifest) != 1:
            raise ValueError("Expected one image in the scan archive")
        config = archive.extractfile(manifest[0]["Config"]).read()
    return "sha256:" + hashlib.sha256(config).hexdigest()


def inspect_report(report, expected_image_id):
    if report.get("SchemaVersion") != 2 or report.get("ArtifactType") != "container_image":
        raise ValueError("Expected a Trivy schema v2 container image report")
    if report.get("Metadata", {}).get("ImageID") != expected_image_id:
        raise ValueError("Scan report does not match the requested image ID")
    results = report.get("Results")
    if not isinstance(results, list) or not any(
        isinstance(result, dict) and result.get("Class") == "os-pkgs" and result.get("Packages")
        for result in results
    ):
        raise ValueError("No operating-system package inventory was scanned")
    counts = Counter({severity: 0 for severity in SEVERITIES})
    blocking = []
    for result in results:
        for vulnerability in result.get("Vulnerabilities") or []:
            severity = vulnerability.get("Severity")
            if severity not in counts:
                raise ValueError("Report contains an unrecognized vulnerability severity")
            counts[severity] += 1
            if severity in {"HIGH", "CRITICAL"}:
                blocking.append(vulnerability)
    return counts, blocking


def cell(value):
    return str(value or "—").replace("|", "\\|").replace("\n", " ").replace("`", "'")


def render_summary(counts, blocking, image, image_id, scanner):
    passed = not blocking
    outcome = ("PASS: 0 HIGH and 0 CRITICAL vulnerabilities detected." if passed else
               f"FAIL: {counts['HIGH']} HIGH and {counts['CRITICAL']} CRITICAL findings.")
    lines = ["# Container vulnerability scan", "", f"**{outcome}**", "",
             f"Image: `{image}`", f"Image ID: `{image_id}`", f"Scanner: `{scanner}`",
             f"Report generated: {datetime.now(timezone.utc).isoformat()}", "",
             "| Severity | Findings |", "| --- | ---: |"]
    lines.extend(f"| {severity} | {counts[severity]} |" for severity in SEVERITIES)
    lines.extend(["", "Includes fixed and unfixed findings. No ignore list or severity exceptions are applied.",
                  "Counts represent package findings, which may include the same CVE in multiple packages.", ""])
    if blocking:
        lines += ["## HIGH / CRITICAL findings", "", "| Severity | ID | Package | Installed | Fixed |",
                  "| --- | --- | --- | --- | --- |"]
        ordered = sorted(blocking, key=lambda item: (SEVERITIES.index(item["Severity"]), item.get("VulnerabilityID", "")))
        for item in ordered[:50]:
            lines.append("| " + " | ".join(cell(item.get(key)) for key in
                         ("Severity", "VulnerabilityID", "PkgName", "InstalledVersion", "FixedVersion")) + " |")
        if len(ordered) > 50:
            lines += ["", f"Showing 50 of {len(ordered)} blocking findings; see the complete JSON/text reports."]
    lines += ["", "Download the security report artifact for JSON, text, and SARIF details.",
              "A passing scan covers vulnerabilities known to this scanner/database at scan time, not unknown vulnerabilities.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--scanner", required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.input.read_text())
        counts, blocking = inspect_report(report, args.image_id)
        args.summary.write_text(render_summary(counts, blocking, args.image, args.image_id, args.scanner))
    except (OSError, ValueError, TypeError, AttributeError) as error:
        args.summary.write_text(f"# Container vulnerability scan\n\n**ERROR: {error}. No clean result can be reported.**\n")
        print(f"Scan report error: {error}", file=sys.stderr)
        return 2
    print(f"Container scan: HIGH={counts['HIGH']}, CRITICAL={counts['CRITICAL']}; {'FAIL' if blocking else 'PASS'}")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
