"""Subllm adapter: verify published copies before invoking upstream validators."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

DOCS_REVISION = "19efafbeb18923cfd51cc69bd519330488500137"
REPORT_REVISION = "3eafc9c212bbfd4060fe15b63eb97e4614725234"
ARTIFACTS = {
    "docs": {
        "docs/standard/" + name
        for name in (
            "check.py",
            "policy.json",
            "POLICY.md",
            "change_contract.py",
            "policy-dsl.lock.json",
        )
    },
    "report": {
        "operations/conformance.py",
        "models/report-manifest.schema.json",
        "models/acceptance.schema.json",
    },
}


def verify(root, entries):
    import hashlib

    for name, revision in [("docs", DOCS_REVISION), ("report", REPORT_REVISION)]:
        entry = entries["wellmanifest/" + name]
        if (
            entry.get("sourceRevision") != revision
            or entry.get("status") != "published"
            or entry.get("sourceRepository") != "https://github.com/wellmanifest/" + name
        ):
            raise RuntimeError("Untrusted published pin: " + name)
        artifacts = entry.get("artifacts", [])
        if len(artifacts) != len(ARTIFACTS[name]) or {a.get("sourcePath") for a in artifacts} != ARTIFACTS[name]:
            raise RuntimeError("Incomplete artifact inventory: " + name)
        for item in artifacts:
            relative = (".governance/wellmanifest/docs/" if name == "docs" else "standards/report/") + item[
                "sourcePath"
            ]
            if item.get("targetPath") != relative:
                raise RuntimeError("Unexpected artifact target")
            current = root
            for part in Path(relative).parts:
                current /= part
                if current.is_symlink():
                    raise RuntimeError("Symlinked standard artifact")
            if hashlib.sha256(current.read_bytes()).hexdigest() != item.get("sha256"):
                raise RuntimeError("Standard artifact digest mismatch")


def checker_environment(root):
    environment = os.environ.copy()
    identity = environment.get("ONEDEV_PR_REPOSITORY")
    if identity is None:
        return environment
    base = environment.get("ONEDEV_PR_MAIN_SHA", "")
    if identity != "subactor/subllm" or not re.fullmatch("[0-9a-f]{40}", base):
        raise RuntimeError("Docs requires the exact authenticated OneDev job identity and base")
    subprocess.run(["git", "cat-file", "-e", base + "^{commit}"], cwd=root, check=True)
    mirror = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=root, text=True).strip()
    if not mirror:
        raise RuntimeError("OneDev mirror origin is missing")
    count = int(environment.get("GIT_CONFIG_COUNT", "0"))
    if not 0 <= count <= 256:
        raise RuntimeError("Invalid inherited Git configuration")
    # Same read-only URL mapping as OneDev's protected documentation adapter.
    # The authenticated job supplies identity; do not rewrite the candidate Git config.
    environment["GIT_CONFIG_COUNT"] = str(count + 1)
    environment[f"GIT_CONFIG_KEY_{count}"] = "url.https://github.com/" + identity + ".git.insteadOf"
    environment[f"GIT_CONFIG_VALUE_{count}"] = mirror
    return environment


def run_json(root, script, *args):
    result = subprocess.run(
        [sys.executable, str(root / script), *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=checker_environment(root),
    )
    if result.returncode:
        raise RuntimeError(result.stdout or "Upstream validator failed: " + script)
    return json.loads(result.stdout)


def check(root, entries, base, deliverable=None, prepared_plan=None, managed_copies=None):
    verify(root, entries)
    if not re.fullmatch("[0-9a-f]{40}", base):
        raise RuntimeError("Trusted base must be a full commit SHA")

    def git_paths(*args):
        return set(subprocess.check_output(["git", *args, "-z"], cwd=root).decode().split("\0")) - {""}

    tracked = git_paths("ls-files")
    changed = git_paths("diff", "--name-only", "--diff-filter=ACMR", base)
    reports = {p for p in tracked if p.endswith(".report.json")}
    for path in changed | ({deliverable} if deliverable else set()):
        if path.startswith("docs/analysis/") and path.endswith(".md"):
            if str(Path(path).with_suffix(".report.json")) not in reports:
                raise RuntimeError("Analysis requires a tracked Report sidecar: " + path)
    report_results = [
        run_json(
            root,
            "standards/report/operations/conformance.py",
            str(root / p),
            "--root",
            str(root),
        )
        for p in sorted(reports)
    ]
    args = ["--root", str(root), "--standard-revision", DOCS_REVISION, "--base", base]
    if deliverable:
        args += [
            "--complete",
            "--deliverable",
            deliverable,
            "--prepared-plan",
            str(prepared_plan.resolve()),
        ]
    import tempfile

    # The caller verifies the whole new-project adoption before supplying this map.
    # Keep the exact upstream inventory input in private local storage, not docs.
    receipts = root / ".subactor/receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docs-check-", dir=receipts) as temporary:
        inventory = Path(temporary) / "managed-copies.json"
        inventory.write_text(json.dumps(managed_copies or {}))
        args += ["--managed-copies", str(inventory)]
        docs = run_json(root, ".governance/wellmanifest/docs/docs/standard/check.py", *args)
    return {
        "docs": docs,
        "reports": report_results,
        "publication_verified": False,
        "authority": "none",
    }
