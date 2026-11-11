"""Regression tests for release distribution qualification and PyPI OIDC workflow gates."""

from __future__ import annotations

import importlib.util
import io
import tarfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("verify_release_package", ROOT / "scripts/verify-release-package.py")
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def _write_synthetic_dists(
    dist_dir: Path,
    *,
    version: str = "1.14.0",
    requires_dist: tuple[str, ...] = (
        "jsonschema==4.26.0",
        'subactor-procache==0.1.0; extra == "cache"',
    ),
) -> tuple[Path, Path]:
    dist_dir.mkdir(parents=True, exist_ok=True)
    header_lines = [
        "Metadata-Version: 2.1",
        "Name: subactor-subllm",
        f"Version: {version}",
        *[f"Requires-Dist: {req}" for req in requires_dist],
        "",
        "Body",
    ]
    metadata_bytes = "\n".join(header_lines).encode("utf-8")

    wheel_path = dist_dir / f"subactor_subllm-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as whl:
        whl.writestr(f"subactor_subllm-{version}.dist-info/METADATA", metadata_bytes)

    sdist_path = dist_dir / f"subactor_subllm-{version}.tar.gz"
    with tarfile.open(sdist_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"subactor_subllm-{version}/PKG-INFO")
        info.size = len(metadata_bytes)
        tar.addfile(info, io.BytesIO(metadata_bytes))

    return wheel_path, sdist_path


def test_tag_binding_enforces_exact_declared_version() -> None:
    assert VERIFIER.verify_tag_matches_version("v1.14.0", "1.14.0") == "v1.14.0"
    assert VERIFIER.verify_tag_matches_version("refs/tags/v1.14.0", "1.14.0") == "v1.14.0"

    with pytest.raises(VERIFIER.ReleaseVerificationError, match="TAG_INVALID"):
        VERIFIER.verify_tag_matches_version("1.14.0", "1.14.0")

    with pytest.raises(VERIFIER.ReleaseVerificationError, match="TAG_VERSION_MISMATCH"):
        VERIFIER.verify_tag_matches_version("v1.13.0", "1.14.0")


def test_dist_artifacts_reject_direct_url_and_unexpected_files(tmp_path: Path) -> None:
    bad_url_dir = tmp_path / "bad_url"
    _write_synthetic_dists(
        bad_url_dir,
        requires_dist=(
            "jsonschema==4.26.0",
            'subactor-procache @ git+https://github.com/dockuri/procache.git@7fe316c9; extra == "cache"',
        ),
    )
    with pytest.raises(VERIFIER.ReleaseVerificationError, match="DIRECT_URL_DEPENDENCY_FORBIDDEN"):
        VERIFIER.verify_dist_artifacts(bad_url_dir, "subactor-subllm", "1.14.0")

    no_procache_dir = tmp_path / "no_procache"
    _write_synthetic_dists(no_procache_dir, requires_dist=("jsonschema==4.26.0",))
    with pytest.raises(VERIFIER.ReleaseVerificationError, match="PROCACHE_PIN_MISSING"):
        VERIFIER.verify_dist_artifacts(no_procache_dir, "subactor-subllm", "1.14.0")

    extra_file_dir = tmp_path / "extra_file"
    _write_synthetic_dists(extra_file_dir)
    (extra_file_dir / "subactor_subllm-1.13.0.tar.gz").write_bytes(b"stale")
    with pytest.raises(VERIFIER.ReleaseVerificationError, match="DIST_UNEXPECTED_FILES"):
        VERIFIER.verify_dist_artifacts(extra_file_dir, "subactor-subllm", "1.14.0")


def _pack_checkout_distributions(dist_dir: Path) -> tuple[str, str]:
    dist_dir.mkdir(parents=True, exist_ok=True)
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    pkg_name = str(project["name"])
    version = str(project["version"])
    requires_dist: list[str] = list(project.get("dependencies", []))
    for extra, deps in (project.get("optional-dependencies") or {}).items():
        for dep in deps:
            requires_dist.append(f'{dep}; extra == "{extra}"')

    metadata_bytes = "\n".join(
        [
            "Metadata-Version: 2.1",
            f"Name: {pkg_name}",
            f"Version: {version}",
            *[f"Requires-Dist: {req}" for req in requires_dist],
            "",
            "Body",
        ]
    ).encode("utf-8")

    wheel_path = dist_dir / f"subactor_subllm-{version}-py3-none-any.whl"
    src_root = ROOT / "src"
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as whl:
        for file_path in sorted((src_root / "subllm").rglob("*")):
            if file_path.is_file() and "__pycache__" not in file_path.parts and file_path.suffix != ".pyc":
                whl.write(file_path, file_path.relative_to(src_root).as_posix())
        whl.writestr(f"subactor_subllm-{version}.dist-info/METADATA", metadata_bytes)

    sdist_path = dist_dir / f"subactor_subllm-{version}.tar.gz"
    with tarfile.open(sdist_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"subactor_subllm-{version}/PKG-INFO")
        info.size = len(metadata_bytes)
        tar.addfile(info, io.BytesIO(metadata_bytes))

    return pkg_name, version


def test_real_built_distributions_pass_metadata_and_isolated_six_routes(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    pkg_name, version = _pack_checkout_distributions(dist_dir)
    checksums = dist_dir / "sha256sums.txt"
    rc = VERIFIER.main(
        [
            "--pyproject",
            str(ROOT / "pyproject.toml"),
            "--dist-dir",
            str(dist_dir),
            "--tag",
            f"v{version}",
            "--write-checksums",
            str(checksums),
        ]
    )
    assert rc == 0
    assert pkg_name == "subactor-subllm"
    assert checksums.is_file()
    lines = checksums.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_pypi_preconditions_fail_closed_on_missing_procache_and_daily_cap() -> None:
    expected = {"subactor_subllm-1.14.0-py3-none-any.whl": "aaa", "subactor_subllm-1.14.0.tar.gz": "bbb"}

    def missing_procache(url: str) -> tuple[int, dict[str, Any] | None]:
        return 404, None

    with pytest.raises(VERIFIER.ReleaseVerificationError, match="PROCACHE_INDEX_UNAVAILABLE"):
        VERIFIER.verify_pypi_preconditions(
            pypi_base_url="https://pypi.org",
            package_name="subactor-subllm",
            version="1.14.0",
            procache_version="0.1.0",
            expected_digests=expected,
            utc_today="2026-11-11",
            fetch_json=missing_procache,
        )

    procache_ok = {"releases": {"0.1.0": [{"filename": "subactor_procache-0.1.0-py3-none-any.whl", "yanked": False}]}}
    five_today = {
        "releases": {
            f"1.13.{idx}": [{"upload_time_iso_8601": "2026-11-11T01:00:00Z"}]
            for idx in range(5)
        }
    }

    def capped_fetch(url: str) -> tuple[int, dict[str, Any] | None]:
        if "subactor-procache" in url:
            return 200, procache_ok
        return 200, five_today

    with pytest.raises(VERIFIER.ReleaseVerificationError, match="PYPI_DAILY_LIMIT_EXCEEDED"):
        VERIFIER.verify_pypi_preconditions(
            pypi_base_url="https://pypi.org",
            package_name="subactor-subllm",
            version="1.14.0",
            procache_version="0.1.0",
            expected_digests=expected,
            utc_today="2026-11-11",
            fetch_json=capped_fetch,
        )

    four_today = {
        "releases": {
            **{f"1.13.{idx}": [{"upload_time_iso_8601": "2026-11-11T01:00:00Z"}] for idx in range(4)},
            "1.4.2": [{"upload_time_iso_8601": "2026-08-26T10:00:00Z"}],
        }
    }

    def allowed_fetch(url: str) -> tuple[int, dict[str, Any] | None]:
        if "subactor-procache" in url:
            return 200, procache_ok
        return 200, four_today

    result = VERIFIER.verify_pypi_preconditions(
        pypi_base_url="https://pypi.org",
        package_name="subactor-subllm",
        version="1.14.0",
        procache_version="0.1.0",
        expected_digests=expected,
        utc_today="2026-11-11",
        fetch_json=allowed_fetch,
    )
    assert result == {"daily_publications_utc": 4, "utc_date": "2026-11-11", "already_published": False}


def test_pypi_published_hash_readback_verifies_exact_digests() -> None:
    expected = {
        "subactor_subllm-1.14.0-py3-none-any.whl": "deadbeef",
        "subactor_subllm-1.14.0.tar.gz": "cafebabe",
    }

    def matching_fetch(url: str) -> tuple[int, dict[str, Any] | None]:
        return 200, {
            "urls": [
                {"filename": name, "yanked": False, "digests": {"sha256": sha}}
                for name, sha in expected.items()
            ]
        }

    verified = VERIFIER.verify_pypi_published_hashes(
        pypi_base_url="https://pypi.org",
        package_name="subactor-subllm",
        version="1.14.0",
        expected_digests=expected,
        retries=0,
        retry_delay_seconds=0.0,
        fetch_json=matching_fetch,
    )
    assert verified == expected

    def tampered_fetch(url: str) -> tuple[int, dict[str, Any] | None]:
        return 200, {
            "urls": [
                {
                    "filename": "subactor_subllm-1.14.0-py3-none-any.whl",
                    "yanked": False,
                    "digests": {"sha256": "deadbeef"},
                },
                {"filename": "subactor_subllm-1.14.0.tar.gz", "yanked": False, "digests": {"sha256": "wrong"}},
            ]
        }

    with pytest.raises(VERIFIER.ReleaseVerificationError, match="PUBLISHED_DIGEST_MISMATCH"):
        VERIFIER.verify_pypi_published_hashes(
            pypi_base_url="https://pypi.org",
            package_name="subactor-subllm",
            version="1.14.0",
            expected_digests=expected,
            retries=0,
            retry_delay_seconds=0.0,
            fetch_json=tampered_fetch,
        )


def test_publish_workflow_enforces_oidc_and_no_shell_expression_injection() -> None:
    workflow_text = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "pull_request:" not in workflow_text
    assert "id-token: write" in workflow_text
    assert "pypa/gh-action-pypi-publish@release/v1" in workflow_text
    assert "softprops/action-gh-release@v2" in workflow_text
    # Ensure no GitHub expression is interpolated inside shell `run:` blocks
    in_run = False
    run_indent = 0
    for line in workflow_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if in_run:
            if stripped and indent <= run_indent:
                in_run = False
            else:
                assert "${{" not in line, f"Unsafe GitHub expression inside run block: {line}"
        if stripped.startswith("run:"):
            in_run = True
            run_indent = indent
            assert "${{" not in line, f"Unsafe GitHub expression inside run line: {line}"
