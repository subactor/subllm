"""Managed Docs exemptions require the complete reviewed byte inventory."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("docs_check", ROOT / "scripts/check-docs-report.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


@pytest.fixture
def adopted(tmp_path):
    lock = ROOT / ".governance/manifest.lock.json"
    files = json.loads(lock.read_text())["managedFiles"]
    for relative in [".governance/manifest.lock.json", *files]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    return tmp_path


def test_exact_adoption_provides_document_digests(adopted):
    copies = CHECK.managed_document_copies(adopted)
    assert ".governance/docs/SNAPSHOT_MIGRATION.md" in copies
    assert all(path.startswith(".governance/docs/") for path in copies)


@pytest.mark.parametrize("path", [".governance/docs/SNAPSHOT_MIGRATION.md", ".governance/governance_check.py"])
def test_modified_managed_file_rejected(adopted, path):
    with (adopted / path).open("ab") as stream:
        stream.write(b"\nchanged\n")
    with pytest.raises(RuntimeError, match="Modified managed artifact"):
        CHECK.managed_document_copies(adopted)


def test_forged_lock_rejected(adopted):
    path = adopted / ".governance/manifest.lock.json"
    value = json.loads(path.read_text())
    value["managedFiles"] = {}
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="Unreviewed"):
        CHECK.managed_document_copies(adopted)


def test_identical_symlink_rejected(adopted):
    path = adopted / ".governance/docs/SNAPSHOT_MIGRATION.md"
    path.unlink()
    path.symlink_to(ROOT / ".governance/docs/SNAPSHOT_MIGRATION.md")
    with pytest.raises(RuntimeError, match="Symlinked"):
        CHECK.managed_document_copies(adopted)
