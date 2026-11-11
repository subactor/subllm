#!/usr/bin/env python3
"""Fail-closed release package verifier for subactor-subllm distributions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from email.parser import Parser
from pathlib import Path
from typing import Any

REPRESENTATIVE_ROUTES: tuple[tuple[str, str], ...] = (
    ("semcod-pfix", "repair"),
    ("semcod-code2logic", "analyze"),
    ("semcod-planfile", "plan"),
    ("autogrammar-nlp2dsl", "generate"),
    ("autogrammar-doql", "translate"),
    ("autogrammar-testql", "generate"),
)
EXPECTED_ROUTE_PROVIDER = "zai"
EXPECTED_ROUTE_MODEL = "glm-5.3"
DEFAULT_MAX_DAILY_PUBLICATIONS = 5
PROCACHE_PACKAGE = "subactor-procache"


class ReleaseVerificationError(RuntimeError):
    """Raised when any release package or registry gate fails."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_dist_prefix(package_name: str) -> str:
    return re.sub(r"[-_.]+", "_", package_name).lower()


def load_project_identity(pyproject_path: Path) -> tuple[str, str]:
    if pyproject_path.is_symlink() or not pyproject_path.is_file():
        raise ReleaseVerificationError(f"PYPROJECT_MISSING: {pyproject_path} must be a regular file")
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        raise ReleaseVerificationError("PYPROJECT_INVALID: missing [project] table")
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name.strip():
        raise ReleaseVerificationError("PYPROJECT_INVALID: missing [project].name")
    if not isinstance(version, str) or not version.strip():
        raise ReleaseVerificationError("PYPROJECT_INVALID: missing [project].version")
    return name.strip(), version.strip()


def verify_tag_matches_version(tag: str, declared_version: str) -> str:
    normalized = tag.strip()
    if normalized.startswith("refs/tags/"):
        normalized = normalized[len("refs/tags/") :]
    if not normalized.startswith("v") or len(normalized) == 1:
        raise ReleaseVerificationError(f"TAG_INVALID: expected v<version> tag, got {tag!r}")
    tag_version = normalized[1:]
    if tag_version != declared_version:
        raise ReleaseVerificationError(
            f"TAG_VERSION_MISMATCH: tag {normalized!r} != pyproject.toml version {declared_version!r}"
        )
    return normalized


def _parse_metadata_headers(
    raw_metadata: str, source_label: str, expected_name: str, expected_version: str
) -> list[str]:
    msg = Parser().parsestr(raw_metadata)
    meta_name = (msg.get("Name") or "").strip()
    meta_version = (msg.get("Version") or "").strip()
    if _normalize_dist_prefix(meta_name) != _normalize_dist_prefix(expected_name):
        raise ReleaseVerificationError(
            f"METADATA_NAME_MISMATCH: {source_label} declares Name={meta_name!r}, expected {expected_name!r}"
        )
    if meta_version != expected_version:
        raise ReleaseVerificationError(
            f"METADATA_VERSION_MISMATCH: {source_label} Version={meta_version!r}, expected {expected_version!r}"
        )
    requires_dist = [entry.strip() for entry in msg.get_all("Requires-Dist", []) if entry.strip()]
    for req in requires_dist:
        spec_part = req.split(";", 1)[0].strip()
        if "@" in spec_part or "git+" in spec_part or "http://" in spec_part or "https://" in spec_part:
            raise ReleaseVerificationError(
                f"DIRECT_URL_DEPENDENCY_FORBIDDEN: {source_label} contains non-index requirement {req!r}"
            )
    return requires_dist


def _extract_procache_version(requires_dist: list[str], source_label: str) -> str:
    versions: set[str] = set()
    pattern = re.compile(r"(?i)^subactor[-_.]procache\s*==\s*([^\s;]+)")
    for req in requires_dist:
        match = pattern.match(req)
        if match:
            versions.add(match.group(1))
    if not versions:
        raise ReleaseVerificationError(
            f"PROCACHE_PIN_MISSING: {source_label} must declare exact {PROCACHE_PACKAGE}==<version> in extras"
        )
    if len(versions) > 1:
        raise ReleaseVerificationError(
            f"PROCACHE_PIN_AMBIGUOUS: {source_label} declares conflicting procache versions {sorted(versions)}"
        )
    return next(iter(versions))


def _read_wheel_metadata(wheel_path: Path, dist_prefix: str, version: str) -> str:
    expected_member = f"{dist_prefix}-{version}.dist-info/METADATA"
    with zipfile.ZipFile(wheel_path, "r") as archive:
        if expected_member not in archive.namelist():
            raise ReleaseVerificationError(
                f"WHEEL_METADATA_MISSING: {wheel_path.name} missing {expected_member}"
            )
        return archive.read(expected_member).decode("utf-8")


def _read_sdist_metadata(sdist_path: Path, dist_prefix: str, version: str) -> str:
    expected_suffix = f"{dist_prefix}-{version}/PKG-INFO"
    with tarfile.open(sdist_path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.isfile() and (member.name == expected_suffix or member.name.endswith("/PKG-INFO")):
                extracted = archive.extractfile(member)
                if extracted is not None:
                    return extracted.read().decode("utf-8")
    raise ReleaseVerificationError(f"SDIST_METADATA_MISSING: {sdist_path.name} missing PKG-INFO")


def verify_dist_artifacts(dist_dir: Path, package_name: str, version: str) -> dict[str, Any]:
    if dist_dir.is_symlink() or not dist_dir.is_dir():
        raise ReleaseVerificationError(f"DIST_DIR_INVALID: {dist_dir} must be a regular directory")
    dist_prefix = _normalize_dist_prefix(package_name)
    wheel_name = f"{dist_prefix}-{version}-py3-none-any.whl"
    sdist_name = f"{dist_prefix}-{version}.tar.gz"
    wheel_path = dist_dir / wheel_name
    sdist_path = dist_dir / sdist_name

    for artifact_path in (wheel_path, sdist_path):
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ReleaseVerificationError(f"ARTIFACT_MISSING: required distribution {artifact_path.name} not found")

    unexpected = sorted(
        entry.name
        for entry in dist_dir.iterdir()
        if entry.name not in {wheel_name, sdist_name, "sha256sums.txt"}
    )
    if unexpected:
        raise ReleaseVerificationError(f"DIST_UNEXPECTED_FILES: unexpected files in {dist_dir}: {unexpected}")

    wheel_meta = _read_wheel_metadata(wheel_path, dist_prefix, version)
    sdist_meta = _read_sdist_metadata(sdist_path, dist_prefix, version)
    wheel_reqs = _parse_metadata_headers(wheel_meta, wheel_name, package_name, version)
    sdist_reqs = _parse_metadata_headers(sdist_meta, sdist_name, package_name, version)
    procache_wheel = _extract_procache_version(wheel_reqs, wheel_name)
    procache_sdist = _extract_procache_version(sdist_reqs, sdist_name)
    if procache_wheel != procache_sdist:
        raise ReleaseVerificationError(
            f"PROCACHE_PIN_MISMATCH: wheel ({procache_wheel}) != sdist ({procache_sdist})"
        )

    return {
        "wheel": {"name": wheel_name, "path": wheel_path, "sha256": _sha256_file(wheel_path)},
        "sdist": {"name": sdist_name, "path": sdist_path, "sha256": _sha256_file(sdist_path)},
        "procache_version": procache_wheel,
        "requires_dist": wheel_reqs,
    }


def verify_isolated_wheel_routes(wheel_path: Path) -> list[dict[str, str]]:
    resolved_wheel = wheel_path.resolve()
    probe = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "wheel = Path(sys.argv[1]).resolve()\n"
        "routes = json.loads(sys.argv[2])\n"
        "sys.path = [str(wheel)] + [p for p in sys.path if p and 'site-packages' in p or 'lib/python' in p]\n"
        "import subllm\n"
        "origin = str(Path(subllm.__file__).resolve())\n"
        "if not origin.startswith(str(wheel) + '/'):\n"
        "    raise SystemExit(f'WHEEL_IMPORT_MISMATCH: imported from {origin}')\n"
        "results = []\n"
        "for app, fn in routes:\n"
        "    cfg = subllm.configured_route(app, fn)\n"
        "    results.append({'application': app, 'function': fn, 'provider': cfg.provider, "
        "'model': cfg.model, 'priority': cfg.priority})\n"
        "print(json.dumps(results))\n"
    )
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.run(
        [sys.executable, "-I", "-B", "-c", probe, str(resolved_wheel), json.dumps(REPRESENTATIVE_ROUTES)],
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise ReleaseVerificationError(f"WHEEL_ROUTE_CHECK_FAILED: {detail}")
    observed = json.loads(proc.stdout)
    for row in observed:
        if (
            row["provider"] != EXPECTED_ROUTE_PROVIDER
            or row["model"] != EXPECTED_ROUTE_MODEL
            or row["priority"] != 0
        ):
            raise ReleaseVerificationError(
                f"ROUTE_CONTRACT_DRIFT: {row['application']}/{row['function']} resolved {row}, "
                f"expected provider={EXPECTED_ROUTE_PROVIDER!r} model={EXPECTED_ROUTE_MODEL!r} priority=0"
            )
    return [
        {
            "application": str(row["application"]),
            "function": str(row["function"]),
            "provider": str(row["provider"]),
            "model": str(row["model"]),
        }
        for row in observed
    ]


def _default_fetch_json(url: str) -> tuple[int, dict[str, Any] | None]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ReleaseVerificationError(f"INSECURE_INDEX_URL: only https:// URLs are permitted, got {url!r}")
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "subllm-release-gate/1"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return int(response.status), payload
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 404, None
        raise ReleaseVerificationError(f"INDEX_HTTP_ERROR: GET {url} returned HTTP {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise ReleaseVerificationError(f"INDEX_FETCH_FAILED: GET {url} failed: {exc}") from exc


def verify_pypi_preconditions(
    *,
    pypi_base_url: str,
    package_name: str,
    version: str,
    procache_version: str,
    expected_digests: dict[str, str],
    max_daily_publications: int = DEFAULT_MAX_DAILY_PUBLICATIONS,
    utc_today: str | None = None,
    fetch_json: Callable[[str], tuple[int, dict[str, Any] | None]] = _default_fetch_json,
) -> dict[str, Any]:
    base = pypi_base_url.rstrip("/")
    today = utc_today or datetime.now(UTC).strftime("%Y-%m-%d")

    procache_url = f"{base}/pypi/{PROCACHE_PACKAGE}/json"
    status_code, procache_data = fetch_json(procache_url)
    if status_code == 404 or not isinstance(procache_data, dict):
        raise ReleaseVerificationError(
            f"PROCACHE_INDEX_UNAVAILABLE: {PROCACHE_PACKAGE}=={procache_version} absent on {base} (HTTP {status_code})"
        )
    procache_files = (procache_data.get("releases") or {}).get(procache_version) or []
    active_procache_files = [item for item in procache_files if isinstance(item, dict) and not item.get("yanked")]
    if not active_procache_files:
        raise ReleaseVerificationError(
            f"PROCACHE_VERSION_UNAVAILABLE: {PROCACHE_PACKAGE}=={procache_version} has no active files on {base}"
        )

    pkg_url = f"{base}/pypi/{package_name}/json"
    pkg_status, pkg_data = fetch_json(pkg_url)
    if pkg_status == 404 or pkg_data is None:
        return {"daily_publications_utc": 0, "utc_date": today, "already_published": False}

    releases = pkg_data.get("releases") or {}
    published_today_versions: set[str] = set()
    for rel_version, files in releases.items():
        if rel_version == version or not isinstance(files, list):
            continue
        for file_entry in files:
            if not isinstance(file_entry, dict):
                continue
            ts = str(file_entry.get("upload_time_iso_8601") or file_entry.get("upload_time") or "")
            if ts.startswith(today):
                published_today_versions.add(rel_version)
                break

    if len(published_today_versions) >= max_daily_publications:
        raise ReleaseVerificationError(
            f"PYPI_DAILY_LIMIT_EXCEEDED: {len(published_today_versions)} releases already uploaded on {today} UTC "
            f"(limit={max_daily_publications}): {sorted(published_today_versions)}"
        )

    existing_target_files = releases.get(version) or []
    if existing_target_files:
        observed_hashes = {
            str(entry.get("filename")): str((entry.get("digests") or {}).get("sha256") or "")
            for entry in existing_target_files
            if isinstance(entry, dict)
        }
        for filename, expected_sha in expected_digests.items():
            actual_sha = observed_hashes.get(filename)
            if actual_sha is not None and actual_sha != expected_sha:
                raise ReleaseVerificationError(
                    f"EXISTING_RELEASE_DIGEST_MISMATCH: {filename} on {base} has sha256={actual_sha}, "
                    f"expected {expected_sha}"
                )

    return {
        "daily_publications_utc": len(published_today_versions),
        "utc_date": today,
        "already_published": bool(existing_target_files),
    }


def verify_pypi_published_hashes(
    *,
    pypi_base_url: str,
    package_name: str,
    version: str,
    expected_digests: dict[str, str],
    retries: int = 6,
    retry_delay_seconds: float = 5.0,
    fetch_json: Callable[[str], tuple[int, dict[str, Any] | None]] = _default_fetch_json,
) -> dict[str, str]:
    base = pypi_base_url.rstrip("/")
    version_url = f"{base}/pypi/{package_name}/{version}/json"
    attempts = max(1, retries + 1)
    last_error = "no attempts executed"

    for attempt in range(attempts):
        status_code, payload = fetch_json(version_url)
        if status_code == 200 and isinstance(payload, dict):
            urls = payload.get("urls") or []
            observed: dict[str, str] = {}
            for entry in urls:
                if isinstance(entry, dict) and not entry.get("yanked"):
                    fname = str(entry.get("filename") or "")
                    sha = str((entry.get("digests") or {}).get("sha256") or "")
                    if fname and sha:
                        observed[fname] = sha
            missing = [fname for fname in expected_digests if fname not in observed]
            if not missing:
                for fname, expected_sha in expected_digests.items():
                    if observed[fname] != expected_sha:
                        raise ReleaseVerificationError(
                            f"PUBLISHED_DIGEST_MISMATCH: {fname} on {base} has sha256={observed[fname]}, "
                            f"expected {expected_sha}"
                        )
                return {fname: observed[fname] for fname in sorted(expected_digests)}
            last_error = f"missing files on index: {missing}"
        else:
            last_error = f"HTTP {status_code} from {version_url}"

        if attempt + 1 < attempts and retry_delay_seconds > 0:
            time.sleep(retry_delay_seconds)

    raise ReleaseVerificationError(f"PUBLISHED_READBACK_FAILED: {last_error}")


def write_checksums_file(checksums_path: Path, artifacts_info: dict[str, Any]) -> None:
    lines = [
        f"{artifacts_info['wheel']['sha256']}  {artifacts_info['wheel']['name']}",
        f"{artifacts_info['sdist']['sha256']}  {artifacts_info['sdist']['name']}",
    ]
    checksums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--tag", type=str, default=None, help="Optional v<version> tag ref to bind against pyproject")
    parser.add_argument("--write-checksums", type=Path, default=None)
    parser.add_argument("--check-pypi-index", action="store_true")
    parser.add_argument("--verify-pypi-published", action="store_true")
    parser.add_argument("--pypi-base-url", type=str, default="https://pypi.org")
    parser.add_argument("--max-daily-publications", type=int, default=DEFAULT_MAX_DAILY_PUBLICATIONS)
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--retry-delay", type=float, default=5.0)
    args = parser.parse_args(argv)

    try:
        package_name, version = load_project_identity(args.pyproject)
        verified_tag = verify_tag_matches_version(args.tag, version) if args.tag else None
        artifacts_info = verify_dist_artifacts(args.dist_dir, package_name, version)
        routes = verify_isolated_wheel_routes(artifacts_info["wheel"]["path"])

        if args.write_checksums is not None:
            write_checksums_file(args.write_checksums, artifacts_info)

        expected_digests = {
            artifacts_info["wheel"]["name"]: artifacts_info["wheel"]["sha256"],
            artifacts_info["sdist"]["name"]: artifacts_info["sdist"]["sha256"],
        }

        report: dict[str, Any] = {
            "status": "ok",
            "package": package_name,
            "version": version,
            "tag": verified_tag,
            "artifacts": [
                {"name": artifacts_info["wheel"]["name"], "sha256": artifacts_info["wheel"]["sha256"]},
                {"name": artifacts_info["sdist"]["name"], "sha256": artifacts_info["sdist"]["sha256"]},
            ],
            "procache_version": artifacts_info["procache_version"],
            "routes": routes,
        }

        if args.check_pypi_index:
            report["pypi_precheck"] = verify_pypi_preconditions(
                pypi_base_url=args.pypi_base_url,
                package_name=package_name,
                version=version,
                procache_version=artifacts_info["procache_version"],
                expected_digests=expected_digests,
                max_daily_publications=args.max_daily_publications,
            )

        if args.verify_pypi_published:
            report["pypi_published_sha256"] = verify_pypi_published_hashes(
                pypi_base_url=args.pypi_base_url,
                package_name=package_name,
                version=version,
                expected_digests=expected_digests,
                retries=args.retries,
                retry_delay_seconds=args.retry_delay,
            )
    except ReleaseVerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
