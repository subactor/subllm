#!/usr/bin/env python3
"""Validate adopted machine runbooks using the pinned Logs checker, not the prose Docs profile."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / ".governance/wellmanifest/logs"
PINS = {'standard/logs_check.py': 'aab380273416b72528079679fb9b5d0659ffe305f4c82bdc95025f41926e162e', 'contracts/logs.contract.v0.5.json': '72e16ac823359879e01722e1e3e7017f50524c8cdf54e8eaec9d8802bc804e36'}

for name, expected in PINS.items():
    path = VENDOR / name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit("Pinned Logs artifact differs: " + name)
for command, flag, path in [
    ("error-adoption", "--catalog", ROOT / ".governance/logs/catalog.json"),
    ("adoption", "--event-schema", ROOT / "policy/adopted/logs/event.schema.json"),
]:
    subprocess.run([sys.executable, str(VENDOR / "standard/logs_check.py"), command, "--root", str(VENDOR),
                    flag, str(path), "--format", "json"], check=True)
