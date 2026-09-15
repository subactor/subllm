"""Inert FEATURE/BUGFIX profile over the canonical, hash-pinned Policy IR."""
import hashlib
import json
import re
import sys
import types
from pathlib import Path

PACK = Path(__file__).resolve().parent


class ContractError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def reject(message, code="DOCS_DSL_CONTRACT"):
    raise ContractError(code, message)


def blocks(body):
    """Select complete top-level DSL fences; examples in other fences are inert."""
    selected, lines, fence, info = [], [], None, ""
    for line in body.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is None:
            if not match:
                continue
            fence, info = match[1], match[2].strip()
            if info.lower().split()[:1] == ["dsl"] and info != "dsl":
                reject("Use the exact fence label dsl", "DOCS_DSL_FENCE")
            lines = []
        elif match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
            if info == "dsl":
                selected.append("\n".join(lines) + "\n")
            fence = None
        else:
            lines.append(line)
    if fence is not None and info == "dsl":
        reject("Unclosed DSL fence", "DOCS_DSL_FENCE")
    return selected


def load_parser(runtime_root):
    if runtime_root is None:
        reject("Supply the trusted --policy-dsl-root; no automatic download", "DOCS_DSL_RUNTIME")
    lock = json.loads((PACK / "policy-dsl.lock.json").read_text())
    root = Path(runtime_root).absolute()
    if root.resolve() != root:
        reject("Runtime root must not use symlinks", "DOCS_DSL_RUNTIME")
    payloads = {}
    try:
        for name, digest in lock["files"].items():
            path = root / name
            if path.resolve() != path:
                reject("Runtime artifacts must not use symlinks", "DOCS_DSL_RUNTIME")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                reject("Pinned Policy DSL artifact differs: " + name, "DOCS_DSL_RUNTIME")
            payloads[name] = data
    except OSError as error:
        reject("Pinned Policy DSL runtime unavailable: " + type(error).__name__, "DOCS_DSL_RUNTIME")
    # Execute only verified parser implementation bytes, never document text.
    # Avoid unverified .pyc files and a second filesystem read after hashing.
    name = "_wellmanifest_docs_pinned_policy"
    module = types.ModuleType(name)
    module.__file__ = str(root / lock["parser"])
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(compile(payloads[lock["parser"]], module.__file__, "exec"), module.__dict__)
    finally:
        if previous is None:
            del sys.modules[name]
        else:
            sys.modules[name] = previous
    return module


def literal(node):
    if not isinstance(node, dict) or node.get("node") != "literal":
        reject("Profile bindings and test references must be literals")
    return node["value"]


def text_literal(node):
    value = literal(node)
    if not isinstance(value, str) or not value.strip() or len(value) > 400:
        reject("Expected a nonempty bounded string")
    return value


def symbols(node, inputs):
    kind = node["node"]
    if kind == "symbol":
        if node["name"] not in inputs:
            reject("Undeclared observation symbol: " + node["name"])
        return {node["name"]}
    if kind == "literal":
        return set()
    if kind == "binary":
        return symbols(node["left"], inputs) | symbols(node["right"], inputs)
    if kind == "unary":
        return symbols(node["operand"], inputs)
    if kind == "list":
        result = set()
        for item in node["items"]:
            result |= symbols(item, inputs)
        return result
    reject("Only scalar expressions and lists are supported, not sequences or placeholders")


def validate_ir(ir, meta, root, files, safe_path):
    expected = {"feature": "DOCS_FEATURE", "bugfix": "DOCS_BUGFIX"}
    if (meta.get("schema") != "wellmanifest.docs/document/v2"
            or not isinstance(meta.get("kind"), str) or meta["kind"] not in expected):
        reject("Contracts are supported only in compact FEATURE/BUGFIX documents")
    header = ir["document"]
    if (header["name"] != expected[meta["kind"]] or header["mode"] != "STRICT"
            or header["version"] != meta["version"]
            or header["policy"] != "wellmanifest.docs/change/v1"):
        reject("Contract name, version, mode or profile differs from document metadata")
    if any(ir[key] for key in ("environment", "states", "transitions", "assertions")):
        reject("No environment, secrets, lifecycle transitions or top-level assertions")
    bindings = {b["name"]: b for b in ir["bindings"]}
    required = {"SUBJECT", "COMPATIBILITY", "INPUTS"}
    if meta["kind"] == "bugfix":
        required |= {"REPRODUCTION", "BEFORE", "AFTER"}
    if set(bindings) != required or len(bindings) != len(ir["bindings"]):
        reject("Unexpected, duplicated or missing profile bindings")
    for name, binding in bindings.items():
        if name == "INPUTS":
            continue
        if binding["operator"] != "=":
            reject("Text bindings require =")
        text_literal(binding["value"])
    if literal(bindings["SUBJECT"]["value"]) != meta["id"]:
        reject("SUBJECT must equal the stable document id")
    declaration = bindings["INPUTS"]
    if declaration["operator"] != "IN" or declaration["value"]["node"] != "list":
        reject("INPUTS must be a list of explicit observation names")
    inputs = [text_literal(n) for n in declaration["value"]["items"]]
    if (not 1 <= len(inputs) <= 16 or len(set(inputs)) != len(inputs)
            or any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", n) for n in inputs)):
        reject("INPUTS requires 1–16 unique uppercase observation names")
    if not 1 <= len(ir["rules"]) <= 12:
        reject("Declare 1–12 acceptance criteria")
    seen = set()
    for rule in ir["rules"]:
        if (not re.fullmatch(r"AC-[0-9]{2,}", rule["id"]) or rule["id"] in seen
                or rule["type"] != "REQUIRED" or rule["forbidden"] or rule["next"]
                or not rule["assertions"] or not rule["actions"]):
            reject("Each unique AC rule needs assertions and test references, without effects")
        seen.add(rule["id"])
        symbols(rule["condition"], inputs)
        for assertion in rule["assertions"]:
            if not symbols(assertion, inputs):
                reject("Each assertion must refer to declared observations, not just constants")
        for action in rule["actions"]:
            if action["opcode"] != "VALIDATE" or action["guard"] is not None:
                reject("Only unguarded DO VALIDATE test-file references are supported")
            test = text_literal(action["payload"])
            relative = safe_path(root, test)
            if (Path(test).is_absolute() or relative is None or test != relative.as_posix()
                    or test not in files or not (root / relative).is_file()
                    or not ({"tests", "test"} & set(relative.parts[:-1]))):
                reject("Expected a tracked repository-local test file: " + test, "DOCS_DSL_TEST")
    return {"profile": header["policy"], "criteria": sorted(seen), "authority": "none",
            "assertions_evaluated": False, "tests_executed": False}


def check(body, meta, root, files, safe_path, runtime_root=None):
    selected = blocks(body)
    if not selected:
        return None
    if len(selected) != 1:
        reject("Exactly one DSL contract per document; use text fences for illustrations")
    if len(selected[0].encode()) > 8192:
        reject("DSL block exceeds 8 KiB")
    parser = load_parser(runtime_root)
    try:
        ir = parser.parse(selected[0])
        return validate_ir(ir, meta, root, files, safe_path)
    except parser.PolicyError as error:
        reject(str(error), "DOCS_DSL_SYNTAX")
    except (RecursionError, OverflowError):
        reject("Expression nesting or numeric complexity exceeds parser bounds", "DOCS_DSL_SYNTAX")
