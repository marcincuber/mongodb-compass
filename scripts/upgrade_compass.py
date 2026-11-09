"""Resolve an official stable Compass release and update its version/checksum pins."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SHA256 = re.compile(r"[a-f0-9]{64}")


def pinned_release(root):
    dockerfile = (root / "Dockerfile").read_text()
    versions = re.findall(r"^ARG COMPASS_VERSION=([0-9.]+)$", dockerfile, re.M)
    checksums = re.findall(r"^ARG COMPASS_SHA256=([a-f0-9]{64})$", dockerfile, re.M)
    if len(versions) != 1 or len(checksums) != 1 or not VERSION.fullmatch(versions[0]):
        raise ValueError("Dockerfile must contain exactly one stable Compass version and SHA-256 pin")
    return versions[0], checksums[0]


def fetch_release(requested):
    requested = requested.removeprefix("v")
    if requested != "latest" and not VERSION.fullmatch(requested):
        raise ValueError("Use latest or a stable version such as 1.53.2")
    endpoint = "latest" if requested == "latest" else "tags/v" + requested
    request = urllib.request.Request(
        "https://api.github.com/repos/mongodb-js/compass/releases/" + endpoint,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "mongodb-compass-upgrade"},
    )
    if os.environ.get("GH_TOKEN"):
        request.add_header("Authorization", "Bearer " + os.environ["GH_TOKEN"])
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def release_pin(release):
    tag = release.get("tag_name", "")
    version = tag.removeprefix("v")
    if not VERSION.fullmatch(version) or tag != "v" + version or release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("Only official stable, non-draft Compass releases are supported")
    name = f"mongodb-compass_{version}_amd64.deb"
    assets = [asset for asset in release.get("assets", []) if asset.get("name") == name]
    if len(assets) != 1:
        raise ValueError("Release must contain exactly one Linux amd64 installer")
    expected_url = f"https://github.com/mongodb-js/compass/releases/download/{tag}/{name}"
    digest = assets[0].get("digest") or ""
    if assets[0].get("browser_download_url") != expected_url or not digest.startswith("sha256:") or not SHA256.fullmatch(digest[7:]):
        raise ValueError("Official installer must have a published SHA-256 digest and matching release URL")
    return version, digest[7:]


def resolve(root, release, expected_sha256=None):
    current, current_sha = pinned_release(root)
    version, checksum = release_pin(release)
    if tuple(map(int, version.split("."))) < tuple(map(int, current.split("."))):
        raise ValueError("Refusing to downgrade Compass")
    if expected_sha256 and checksum != expected_sha256:
        raise ValueError("Release checksum changed after candidate validation")
    if version == current and checksum != current_sha:
        raise ValueError("Published checksum differs from the existing pin for the same version")
    return {"current_version": current, "version": version, "sha256": checksum, "changed": version != current}


def update_files(root, pin):
    if not pin["changed"]:
        return
    dockerfile = root / "Dockerfile"
    content = dockerfile.read_text()
    content = re.sub(r"^ARG COMPASS_VERSION=.*$", "ARG COMPASS_VERSION=" + pin["version"], content, flags=re.M)
    content = re.sub(r"^ARG COMPASS_SHA256=.*$", "ARG COMPASS_SHA256=" + pin["sha256"], content, flags=re.M)
    dockerfile.write_text(content)
    old, new = pin["current_version"], pin["version"]
    for filename in [root / "README.md", root / "docs/publishing.md", *sorted((root / "k8s/examples").glob("*.yaml"))]:
        content = filename.read_text()
        content = content.replace("Compass " + old, "Compass " + new)
        content = content.replace("/releases/tag/v" + old, "/releases/tag/v" + new)
        content = re.sub(re.escape(old) + r"-\d+\b", new + "-1", content)
        filename.write_text(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="latest")
    parser.add_argument("--check", action="store_true", help="Resolve the release without editing files")
    parser.add_argument("--expected-sha256", help="Require the exact checksum previously tested by CI")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        if args.expected_sha256 and not SHA256.fullmatch(args.expected_sha256):
            raise ValueError("Expected checksum must be 64 lowercase hexadecimal characters")
        release = fetch_release(args.version)
        if args.version != "latest" and release.get("tag_name") != "v" + args.version.removeprefix("v"):
            raise ValueError("Release metadata does not match the requested version")
        pin = resolve(ROOT, release, args.expected_sha256)
        if not args.check:
            update_files(ROOT, pin)
        if args.github_output:
            with args.github_output.open("a") as output:
                for key in ("version", "sha256", "changed"):
                    value = str(pin[key]).lower() if isinstance(pin[key], bool) else pin[key]
                    output.write(f"{key}={value}\n")
        print(json.dumps(pin))
    except (ValueError, OSError, urllib.error.URLError) as error:
        print(f"Compass upgrade error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
