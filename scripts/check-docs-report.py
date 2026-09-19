#!/usr/bin/env python3
"""Run the pinned documentation validators; local results grant no authority."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("documentation_adapter", ROOT / "standards/docs_report.py")
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)



# Reviewed adoption 0.20.35 at cfaa0bf0ea6b0e7349fed0bb62b5ce15792d687d.
# An upgrade must explicitly review this pin; candidate metadata cannot exempt files.
ADOPTION_LOCK_SHA256 = "763f1dc2f7b31e9001c4c899388e82e9344932fd304463f950302dc0c09acdd5"


def managed_document_copies(root):
    def verified_path(relative):
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError("Invalid managed path")
        current = root
        for part in path.parts:
            current /= part
            if current.is_symlink():
                raise RuntimeError("Symlinked managed artifact")
        return current

    lock_bytes = verified_path(".governance/manifest.lock.json").read_bytes()
    if hashlib.sha256(lock_bytes).hexdigest() != ADOPTION_LOCK_SHA256:
        raise RuntimeError("Unreviewed new-project adoption lock")
    managed = json.loads(lock_bytes)["managedFiles"]
    for relative, expected in managed.items():
        if hashlib.sha256(verified_path(relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError("Modified managed artifact: " + relative)
    return {path: digest for path, digest in managed.items()
            if path.startswith(".governance/docs/") and path.endswith(".md")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--deliverable")
    parser.add_argument("--prepared-plan", type=Path)
    args = parser.parse_args()
    if (
        args.complete != bool(args.deliverable and args.prepared_plan)
        or (not args.complete and (args.deliverable or args.prepared_plan))
        or (args.complete and not args.base)
    ):
        parser.error("--complete requires --base, --deliverable and --prepared-plan")
    try:
        lock = json.loads((ROOT / "standards/standards-lock.json").read_text())
        entries = {entry["id"]: entry for entry in lock["standards"]}
        if (
            lock.get("schema") != "subllm.documentation-pins/v1"
            or len(lock["standards"]) != 2
            or set(entries) != {"wellmanifest/docs", "wellmanifest/report"}
        ):
            raise RuntimeError("Unexpected documentation pin inventory")
        base = (
            args.base
            or subprocess.check_output(
                ["git", "merge-base", "HEAD", "refs/remotes/origin/main"], cwd=ROOT, text=True
            ).strip()
        )
        result = adapter.check(ROOT, entries, base, args.deliverable, args.prepared_plan, managed_document_copies(ROOT))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
