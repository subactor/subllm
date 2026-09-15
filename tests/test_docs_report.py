"""Negative canaries for independently pinned Docs/Report integration."""

import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("docs_report_adapter", ROOT / "standards/docs_report.py")
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class DocumentationPins(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ("docs", "report"):
            directory = ".governance/wellmanifest/docs" if name == "docs" else "standards/report"
            shutil.copytree(ROOT / directory, self.root / directory)
        self.entries = {
            e["id"]: e for e in json.loads((ROOT / "standards/standards-lock.json").read_text())["standards"]
        }

    def test_published_runtime_copies_match(self):
        adapter.verify(self.root, self.entries)

    def test_unknown_pin_rejected(self):
        for field, value in [
            ("sourceRevision", "main"),
            ("status", "draft"),
            ("sourceRepository", "https://example.invalid"),
        ]:
            entries = copy.deepcopy(self.entries)
            entries["wellmanifest/docs"][field] = value
            with self.assertRaises(RuntimeError):
                adapter.verify(self.root, entries)

    def test_incomplete_inventory_rejected(self):
        self.entries["wellmanifest/report"]["artifacts"].pop()
        with self.assertRaises(RuntimeError):
            adapter.verify(self.root, self.entries)

    def test_tampered_executable_rejected(self):
        (self.root / ".governance/wellmanifest/docs/docs/standard/check.py").write_text(
            'raise Exception("must not run")'
        )
        with self.assertRaises(RuntimeError):
            adapter.verify(self.root, self.entries)

    def test_artifact_target_cannot_escape(self):
        self.entries["wellmanifest/docs"]["artifacts"][0]["targetPath"] = "../outside"
        with self.assertRaises(RuntimeError):
            adapter.verify(self.root, self.entries)

    def test_symlinked_parent_rejected(self):
        target = self.root / "standards/report/models"
        target.rename(self.root / "models")
        target.symlink_to(self.root / "models", target_is_directory=True)
        with self.assertRaises(RuntimeError):
            adapter.verify(self.root, self.entries)


class DocumentationCompletion(unittest.TestCase):
    def setUp(self):
        import os
        from unittest.mock import patch

        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("ONEDEV_PR_REPOSITORY", None)
        os.environ.pop("ONEDEV_PR_MAIN_SHA", None)
        DocumentationPins.setUp(self)
        import subprocess

        self.git = lambda *args: subprocess.check_output(["git", *args], cwd=self.root, text=True).strip()
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("remote", "add", "origin", "https://github.com/subactor/subllm.git")
        (self.root / ".governance").mkdir(exist_ok=True)
        (self.root / ".governance/docs.json").write_bytes((ROOT / ".governance/docs.json").read_bytes())
        policy = json.loads((self.root / ".governance/wellmanifest/docs/docs/standard/policy.json").read_text())
        metadata = dict(
            schema="wellmanifest.docs/document/v1",
            id="adoption",
            kind="information",
            version=1,
            title="Test adoption",
            status="implemented",
            owner="subactor/subllm",
            created="2026-09-15",
            updated="2026-09-15",
            review_after="2026-10-15",
            source_revision="a" * 40,
            affected_repositories=["subactor/subllm"],
            evidence=["receipt:test-fixture"],
            scope="repository",
        )
        self.document = "docs/information/adoption.md"
        path = self.root / self.document
        path.parent.mkdir(parents=True)
        body = "".join(
            "\n<!-- docs:section " + section + " -->\n## " + section + "\nBounded fixture evidence.\n"
            for section in policy["kinds"]["information"]["sections"]
        )
        path.write_text("---\n" + json.dumps(metadata) + "\n---\n# Test adoption\n" + body)
        (self.root / "docs/README.md").write_text("[Adoption](information/adoption.md)\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        prepared = adapter.run_json(
            self.root,
            ".governance/wellmanifest/docs/docs/standard/check.py",
            "--root",
            str(self.root),
            "--standard-revision",
            adapter.DOCS_REVISION,
            "--prepare",
            "--scope",
            "repository",
            "--kind",
            "information",
            "--id",
            "adoption",
            "--deliverable",
            self.document,
        )
        self.receipt = self.root / "prepared.json"
        self.receipt.write_text(json.dumps(prepared))

    def test_authenticated_mirror_identity_is_read_only(self):
        import os

        mirror = str(self.root / "local-mirror.git")
        self.git("remote", "set-url", "origin", mirror)
        os.environ.update(ONEDEV_PR_REPOSITORY="subactor/subllm", ONEDEV_PR_MAIN_SHA=self.base)
        result = adapter.check(self.root, self.entries, self.base)
        self.assertTrue(result["docs"]["ok"])
        self.assertEqual(self.git("remote", "get-url", "origin"), mirror)

    def test_wrong_job_identity_is_rejected(self):
        import os

        os.environ.update(ONEDEV_PR_REPOSITORY="other/repo", ONEDEV_PR_MAIN_SHA=self.base)
        with self.assertRaises(RuntimeError):
            adapter.check(self.root, self.entries, self.base)

    def test_completion_checks_actual_files(self):
        result = adapter.check(self.root, self.entries, self.base, self.document, self.receipt)
        self.assertTrue(result["docs"]["completion"]["ready"])
        self.assertFalse(result["publication_verified"])

    def test_completion_rejects_changed_plan(self):
        prepared = json.loads(self.receipt.read_text())
        prepared["plan"]["id"] = "other"
        self.receipt.write_text(json.dumps(prepared))
        with self.assertRaises(RuntimeError):
            adapter.check(self.root, self.entries, self.base, self.document, self.receipt)

    def test_completion_rejects_missing_index(self):
        (self.root / "docs/README.md").write_text("# No link\n")
        with self.assertRaises(RuntimeError):
            adapter.check(self.root, self.entries, self.base, self.document, self.receipt)

    def test_new_analysis_requires_sidecar(self):
        path = self.root / "docs/analysis/new.md"
        path.parent.mkdir()
        path.write_text("# Report\n")
        self.git("add", "docs")
        with self.assertRaisesRegex(RuntimeError, "tracked Report sidecar"):
            adapter.check(self.root, self.entries, self.base)


if __name__ == "__main__":
    unittest.main()
