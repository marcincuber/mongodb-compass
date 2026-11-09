#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Trivy 0.76.2, pinned to the official multi-platform image digest.
scanner='ghcr.io/aquasecurity/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb'
image="${IMAGE_NAME:-mongodb-compass}:${IMAGE_TAG:-local}"
mkdir -p "${REPORT_DIR:-$project_dir/reports/security}" "$project_dir/.cache/trivy"
report_dir="$(cd -- "${REPORT_DIR:-$project_dir/reports/security}" && pwd)"
scan_tmp="$(mktemp -d)"
rm -f "$report_dir/trivy.json" "$report_dir/trivy.txt" "$report_dir/trivy.sarif" "$report_dir/summary.md"
finish() {
  scan_exit=$?
  if [[ ! -s "$report_dir/summary.md" ]]; then
    printf '%s\n' '# Container vulnerability scan' '' '**ERROR: scanning did not complete. No clean result can be reported.**' > "$report_dir/summary.md"
  fi
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then cat "$report_dir/summary.md" >> "$GITHUB_STEP_SUMMARY"; fi
  rm -rf "$scan_tmp"
  return "$scan_exit"
}
trap finish EXIT
docker image inspect "$image" > /dev/null
# Scan an archive of this exact image; the scanner never receives the Docker socket.
docker save --output "$scan_tmp/image.tar" "$image"
image_id="$(python3 - "$project_dir/scripts" "$scan_tmp/image.tar" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from scan_report import archive_image_id
print(archive_image_id(sys.argv[2]))
PY
)"
scanner_args=(run --rm --platform linux/amd64
  --mount "type=bind,src=$scan_tmp,dst=/scan,readonly"
  --mount "type=bind,src=$report_dir,dst=/reports"
  --mount "type=bind,src=$project_dir/.cache/trivy,dst=/root/.cache/trivy"
  "$scanner")
docker "${scanner_args[@]}" image --input /scan/image.tar --scanners vuln \
  --pkg-types os,library --list-all-pkgs --ignore-unfixed=false --ignorefile /dev/null \
  --format json --output /reports/trivy.json --exit-code 0 --timeout 15m
docker "${scanner_args[@]}" convert --scanners vuln --ignorefile /dev/null --format table --severity HIGH,CRITICAL \
  --output /reports/trivy.txt /reports/trivy.json
docker "${scanner_args[@]}" convert --scanners vuln --ignorefile /dev/null --format sarif --output /reports/trivy.sarif /reports/trivy.json
python3 "$project_dir/scripts/scan_report.py" --input "$report_dir/trivy.json" \
  --image "$image" --image-id "$image_id" --scanner "$scanner" --summary "$report_dir/summary.md"
