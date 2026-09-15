#!/usr/bin/env python3
"""Read-only structural and semantic conformance, never an authority verifier."""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import subprocess
import re

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 2 * 1024 * 1024


class ContractError(ValueError):
    """Malformed input or an unavailable immutable dependency."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON member")
        result[key] = value
    return result


def reject_constant(_value):
    raise ContractError("non-finite JSON number")


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise ContractError("input exceeds the declared byte budget")
    return json.loads(raw, object_pairs_hook=unique_object,
                      parse_constant=reject_constant)


def load(path):
    with Path(path).open("rb") as stream:
        return decode(stream.read(MAX_BYTES + 1))


def dependencies():
    schema = load(ROOT / "models/report-manifest.schema.json")
    policy = schema["x-report-policy"]
    binding = policy["dependencies"]["docs"]
    raw = binding["policy_json"].encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != binding["policy_sha256"]:
        raise ContractError("Docs policy digest mismatch")
    docs = decode(raw)
    if docs.get("schema") != "wellmanifest.docs/policy/v1":
        raise ContractError("unsupported Docs policy")
    Draft202012Validator.check_schema(schema)
    return docs, Draft202012Validator(schema, format_checker=FormatChecker())


def safe_path(value):
    parts = value.split("/")
    return (bool(value) and not value.startswith("/") and "\\" not in value
            and ":" not in value and not any(p in {"", ".", ".."} for p in parts))


def validate_acceptance(manifest, *, today=None):
    """Check scoped acceptance claims, not external evidence or authority."""
    from datetime import datetime

    schema = load(ROOT / "models/acceptance.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    if next(validator.iter_errors(manifest), None) is not None:
        return [{"code": "RPT-ACCEPTANCE-SCHEMA-001", "message": "Invalid acceptance payload."}]
    today = today or date.today()
    errors = []

    def reject(code, message):
        errors.append({"code": "RPT-ACCEPTANCE-" + code, "message": message})

    def indexed(items, key):
        result = {}
        for item in items:
            if item[key] in result:
                reject("REFERENCE-001", "Duplicate acceptance identifier.")
            result[item[key]] = item
        return result

    subjects = indexed(manifest["subjects"], "id")
    evidence = indexed(manifest["evidence"], "id")
    answers = indexed(manifest["answers"], "questionId")
    stages = indexed(manifest["stages"], "id")
    created, updated, review = (date.fromisoformat(manifest[key])
                                for key in ("created", "updated", "review_after"))
    if not created <= updated <= review or updated > today:
        reject("DATE-001", "Invalid date ordering or future update.")
    subject_hashes = {
        key: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True).encode("utf-8")).hexdigest()
        for key, value in subjects.items()
    }
    for item in evidence.values():
        target = subjects.get(item["subject_id"])
        if target is None or item["subject_sha256"] != subject_hashes.get(item["subject_id"]):
            reject("SUBJECT-001", "Evidence does not bind the exact subject and scope.")
        reference = item["reference"]
        if reference.startswith(("artifact:sha256:", "receipt:sha256:")):
            if reference.rsplit(":", 1)[-1] != item["sha256"]:
                reject("EVIDENCE-001", "Content-addressed evidence digest mismatch.")
        elif target is not None:
            prefix = ("repo://" + target["scope"]["repository"] + "@"
                      + str(target["source_revision"]) + "/")
            if not reference.startswith(prefix) or not safe_path(reference[len(prefix):]):
                reject("EVIDENCE-001", "Source evidence requires the exact revision and safe path.")
    acceptable = {}
    for key, item in answers.items():
        target = subjects.get(item["subject_id"])
        if target is None:
            reject("REFERENCE-001", "Answer has an unknown subject.")
        links = [evidence.get(value) for value in item["evidence_ids"]]
        if any(value is None or value["subject_id"] != item["subject_id"] for value in links):
            reject("REFERENCE-001", "Answer evidence is missing or belongs to another subject.")
        observed = datetime.fromisoformat(item["observation"]["at"].replace("Z", "+00:00")).date()
        valid = date.fromisoformat(item["limits"]["valid_through"])
        if observed > updated or valid < observed or valid > review:
            reject("DATE-001", "Observation or validity lies outside the declared interval.")
        status = item["status"]
        applicability = item["applicability"]
        if status == "N/A":
            if applicability["state"] != "NOT_APPLICABLE" or not applicability["activation_condition"]:
                reject("APPLICABILITY-001", "N/A requires a reason and activation condition.")
        elif applicability["state"] != "APPLICABLE":
            reject("APPLICABILITY-001", "An applicable answer cannot declare N/A scope.")
        if status in {"PASS", "FAIL"}:
            if item["observation"]["execution"] != "PERFORMED" or not links:
                reject("EVIDENCE-001", "PASS/FAIL require a performed observation and evidence.")
            if any(value is not None and value["verification"]["result"] != "MATCH" for value in links):
                reject("EVIDENCE-001", "PASS/FAIL require declared matching evidence verification.")
            if target is not None and target["source_revision"] is None and target["artifact_sha256"] is None:
                reject("SUBJECT-001", "PASS/FAIL require an identified source or artifact.")
        if status == "UNKNOWN" and not item["limits"]["missing_data"]:
            reject("UNKNOWN-001", "UNKNOWN must identify the missing knowledge.")
        if status in {"FAIL", "UNKNOWN"} and not (item["nextAction"]["ticket_ref"] or item["nextAction"]["proposal"]):
            reject("ACTION-001", "FAIL/UNKNOWN require an owned ticket or bounded proposal.")
        acceptable[key] = status in {"PASS", "N/A"} and valid >= today and review >= today

    visiting, resolved = set(), {}

    def eligible(key):
        if key in resolved:
            return resolved[key]
        if key not in stages:
            reject("REFERENCE-001", "Unknown stage dependency.")
            return False
        if key in visiting:
            reject("DAG-001", "Acceptance dependencies contain a cycle.")
            return False
        visiting.add(key)
        stage = stages[key]
        own = []
        for question in stage["requires"]:
            if question not in answers:
                reject("REFERENCE-001", "Required acceptance answer is missing.")
            own.append(acceptable.get(question, False))
        dependencies = [eligible(other) for other in stage["depends_on"]]
        result = all(own) and all(dependencies)
        visiting.remove(key)
        resolved[key] = result
        return result

    for key, stage in stages.items():
        expected = "ELIGIBLE" if eligible(key) else "BLOCKED"
        if stage["eligibility"] != expected:
            reject("STAGE-001", "Declared eligibility differs from scoped assessment.")
    return errors


def validate(manifest, *, today=None):
    if isinstance(manifest, dict) and manifest.get("schema") == "wellmanifest.report/acceptance/v1":
        return validate_acceptance(manifest, today=today)
    docs, validator = dependencies()
    if next(validator.iter_errors(manifest), None) is not None:
        return [{"code": "RPT-SCHEMA-001", "message": "Invalid closed manifest shape or unsupported version."}]
    errors = []

    def reject(code, message):
        errors.append({"code": code, "message": message})

    owner = manifest["owner"]
    repositories = manifest["scope"]["repositories"]
    profile = docs["profile"]
    central = profile["cross_repository_home"]
    if (len(repositories) > 1 and owner != central
            or len(repositories) == 1 and owner not in {repositories[0], central}):
        reject("RPT-PLACEMENT-001", "Report owner does not match the local or cross-repository scope.")
    layout = {**profile, **profile.get("repository_overrides", {}).get(owner, {})}
    directory = docs["kinds"][manifest["kind"]]["directory"]
    expected = str(PurePosixPath(layout["docs_root"]) / layout.get("prefix", "")
                   / directory / (manifest["id"] + ".md"))
    document = manifest["document"]
    if (not safe_path(document["path"]) or document["path"] != expected
            or document["index_path"] != layout["index"]):
        reject("RPT-PLACEMENT-001", "Use the canonical document and index paths from the pinned Docs policy.")
    if any(document["path"].startswith(prefix) for prefix in docs["forbidden_delivery_roots"]):
        reject("RPT-PLACEMENT-001", "Operational storage is not a report delivery location.")

    created, updated, review = (date.fromisoformat(manifest[k])
                                for k in ("created", "updated", "review_after"))
    if created > updated or updated > review or updated > (today or date.today()):
        reject("RPT-DATE-001", "Report dates are inconsistent or future-dated.")

    def indexed(items, label):
        result = {item["id"]: item for item in items}
        if len(result) != len(items):
            reject("RPT-REFERENCE-001", label + " identifiers must be unique.")
        return result

    subjects = indexed(manifest["scope"]["subjects"], "Subject")
    evidence = indexed(manifest["evidence"], "Evidence")
    indexed(manifest["findings"], "Finding")
    for subject in subjects.values():
        if subject["repository"] not in {*repositories, owner}:
            reject("RPT-REFERENCE-001", "Subject is outside the declared repositories.")
    analyzed = {s["repository"] for s in subjects.values()}
    if set(repositories) - analyzed:
        reject("RPT-REFERENCE-001", "Every scoped repository requires an exact-revision subject.")

    def references(ids, *, kind=None, subject=None):
        selected = []
        for identifier in ids:
            item = evidence.get(identifier)
            if item is None or (kind and item["kind"] != kind) or (subject and item["subject_id"] != subject):
                reject("RPT-REFERENCE-001", "Evidence reference is missing or has an incompatible binding.")
            else:
                selected.append(item)
        return selected

    for item in evidence.values():
        subject = subjects.get(item["subject_id"])
        if subject is None:
            reject("RPT-REFERENCE-001", "Evidence requires a declared exact-revision subject.")
            continue
        reference = item["reference"]
        if reference.startswith("repo://"):
            prefix = f"repo://{subject['repository']}@{subject['revision']}/"
            if not reference.startswith(prefix) or not safe_path(reference[len(prefix):]):
                reject("RPT-REFERENCE-001", "Source reference must bind the subject repository and immutable revision.")
        elif reference.rsplit(":", 1)[-1] != item["sha256"]:
            reject("RPT-REFERENCE-001", "Content-addressed reference and evidence digest differ.")
    for finding in manifest["findings"]:
        references(finding["evidence_ids"])
        if finding["kind"] == "fact" and not finding["evidence_ids"]:
            reject("RPT-EVIDENCE-001", "Facts require evidence; unsupported statements remain hypotheses.")

    coverage = manifest["coverage"]
    if coverage["expected"] is not None and coverage["observed"] > coverage["expected"]:
        reject("RPT-COVERAGE-001", "Observed coverage exceeds the declared scope.")
    if coverage["state"] == "complete" and (coverage["expected"] is None or coverage["observed"] != coverage["expected"]):
        reject("RPT-COVERAGE-001", "Complete coverage requires a known and fully observed scope.")
    if coverage["state"] != "complete" and not manifest["limitations"]:
        reject("RPT-COVERAGE-001", "Partial or unknown coverage requires explicit limitations.")

    results = []
    for check in manifest["checks"]:
        results.append(check["result"])
        if check["subject_id"] not in subjects:
            reject("RPT-REFERENCE-001", "Check has no declared subject.")
        references(check["evidence_ids"], kind="test", subject=check["subject_id"])
        if check["result"] in {"PASS", "FAIL"} and not check["evidence_ids"]:
            reject("RPT-EVIDENCE-001", "Executed check results require test evidence.")
    assessment = ("failed" if "FAIL" in results else "not_assessed" if not results
                  else "passed" if set(results) == {"PASS"} and coverage["state"] == "complete"
                  else "incomplete")
    if manifest["assessment"] != assessment:
        reject("RPT-ASSESSMENT-001", "Assessment disagrees with checks and scope coverage.")

    redaction = manifest["redaction"]
    references(redaction["evidence_ids"], kind="redaction")
    if redaction["state"] == "checked" and not redaction["evidence_ids"]:
        reject("RPT-EVIDENCE-001", "A redaction claim requires a scanner evidence reference.")
    if manifest["status"] == "final" and redaction["state"] != "checked":
        reject("RPT-EVIDENCE-001", "Final reports require a documented redaction check.")

    publication = manifest["publication"]
    proof = references(publication["evidence_ids"], kind="publication")
    if publication["state"] == "local":
        if publication["revision"] is not None or publication["pull_request"] is not None or proof:
            reject("RPT-PUBLICATION-001", "A local report cannot declare remote publication bindings.")
    elif publication["revision"] is None or not proof:
        reject("RPT-PUBLICATION-001", "Publication claims require a revision and publication evidence.")
    if ((publication["state"] in {"in-pr", "merged"}) != (publication["pull_request"] is not None)):
        reject("RPT-PUBLICATION-001", "PR publication states require a PR number, and other states must omit it.")
    for item in proof:
        subject = subjects.get(item["subject_id"], {})
        if (subject.get("repository") != owner or subject.get("revision") != publication["revision"]
                or item["sha256"] != document["sha256"]):
            reject("RPT-PUBLICATION-001", "Publication evidence must bind the report owner, revision and document digest.")
    return errors


def validate_local(manifest, root, manifest_path):
    """Read back canonical local Git artifacts; never attest remote publication."""
    root = Path(root).resolve()
    errors = []
    def reject(message):
        errors.append({'code': 'RPT-LOCAL-001', 'message': message})
    if manifest.get('schema') != 'wellmanifest.report/manifest/v1':
        return [{'code': 'RPT-LOCAL-001', 'message': 'Local report checks require a report manifest, not acceptance alone.'}]
    try:
        top = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
        remote = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
        match = re.fullmatch(r'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?', remote)
        if Path(top).resolve() != root or not match or match.group(1) != manifest['owner']:
            reject('Root must be the owning Git repository, not a nested directory or another origin.')
        files = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0'))
        document = manifest['document']
        expected_sidecar = str(PurePosixPath(document['path']).with_suffix('.report.json'))
        supplied = Path(manifest_path).absolute()
        if supplied != root / expected_sidecar:
            reject('Manifest must be the canonical sidecar beside the document.')
        contents = {}
        for name in (document['path'], document['index_path'], expected_sidecar):
            if not safe_path(name):
                reject('Unsafe local artifact path.'); continue
            path = root / name
            current = root
            for part in PurePosixPath(name).parts:
                current /= part
                if current.is_symlink():
                    reject('Local artifacts must not use symlinks.'); break
            else:
                if name not in files or not path.is_file():
                    reject('Document, sidecar and index must exist and be tracked in Git.'); continue
                contents[name] = path.read_bytes()
        sidecar_bytes = contents.get(expected_sidecar)
        if sidecar_bytes is not None and decode(sidecar_bytes) != manifest:
            reject('Actual sidecar changed since manifest validation.')
        raw = contents.get(document['path'])
        if raw is not None and hashlib.sha256(raw).hexdigest() != document['sha256']:
            reject('Actual document digest differs from the manifest.')
        index = contents.get(document['index_path'])
        if index is not None:
            link = PurePosixPath(document['path']).relative_to(PurePosixPath(document['index_path']).parent).as_posix()
            if not re.search(r'\]\(' + re.escape(link) + r'(?:#[^)]*)?\)', index.decode('utf-8')):
                reject('Canonical document is missing from the tracked index.')
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, UnicodeError):
        reject('Unable to read owning Git repository and canonical report artifacts.')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?")
    parser.add_argument("--example", action="store_true",
                        help="Validate the inert example embedded in the schema")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--root", type=Path, help="Verify actual document, sidecar, Git tracking, digest and index in the owning repository")
    args = parser.parse_args()
    if args.root and args.example:
        parser.error("--root requires an actual manifest, not --example")
    if args.example == (args.manifest is not None):
        parser.error("Choose a manifest path or --example, but not both")
    try:
        manifest = (load(ROOT / "models/report-manifest.schema.json")["examples"][0]
                    if args.example else load(args.manifest))
        findings = validate(manifest, today=args.as_of)
        if args.root and not findings:
            findings.extend(validate_local(manifest, args.root, args.manifest))
        freshness = ("unknown" if findings else "stale" if
                     date.fromisoformat(manifest["review_after"]) < args.as_of else "current")
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        findings = [{"code": "RPT-INPUT-001", "message": "Input or pinned policy could not be safely decoded."}]
        freshness = "unknown"
    print(json.dumps({"conformance": "FAIL" if findings else "PASS",
                      "authority": "none", "publication_verified": False,
                      "local_artifacts_verified": bool(args.root) and not findings,
                      "evidence_verified": False, "freshness": freshness,
                      "findings": findings}, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
