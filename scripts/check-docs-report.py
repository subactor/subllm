#!/usr/bin/env python3
"""Run the pinned documentation validators; local results grant no authority."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("documentation_adapter", ROOT / "standards/docs_report.py")
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


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
        result = adapter.check(ROOT, entries, base, args.deliverable, args.prepared_plan)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
