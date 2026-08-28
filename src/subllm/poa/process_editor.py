from __future__ import annotations

from copy import deepcopy
from typing import Any

from .canonical import digest_document
from .errors import PoaContractError
from .refs import SHA256, exact, require_pattern

_MAX_EDITS = 16
_PROTECTED_PATHS = {
    "/schema_version",
    "/process_id",
    "/process_ref",
    "/entrypoint",
    "/owner",
    "/required_inputs",
    "/allowed_actions",
    "/required_artifacts",
    "/decision_policy/deterministic_controls",
    "/decision_policy/heuristic/authority",
    "/decision_policy/llm_editor/authority",
    "/decision_policy/llm_editor/editable_paths",
    "/decision_policy/publication",
}


def propose_process_edit(
    source_process: Any,
    base_sha256: Any,
    edits: Any,
) -> dict[str, Any]:
    """Apply a closed, proposal-only edit set to a process DSL document."""
    if not isinstance(source_process, dict):
        raise PoaContractError("POA-EDIT-001", "source_process must be an object")
    expected = require_pattern(base_sha256, "base_sha256", SHA256)
    actual = digest_document(source_process)
    if expected != actual:
        raise PoaContractError("POA-EDIT-002", "process base digest is stale")

    editor = _editor_policy(source_process)
    editable_paths = editor["editable_paths"]
    if (
        not isinstance(editable_paths, list)
        or not editable_paths
        or any(not isinstance(item, str) for item in editable_paths)
    ):
        raise PoaContractError("POA-EDIT-001", "editable_paths is not a closed list")
    allowed = set(editable_paths) - _PROTECTED_PATHS

    if not isinstance(edits, list) or not 1 <= len(edits) <= _MAX_EDITS:
        raise PoaContractError("POA-EDIT-001", "edits must contain between 1 and 16 operations")
    candidate = deepcopy(source_process)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in edits:
        edit = exact(raw, {"op", "path", "value"})
        if edit["op"] != "replace" or not isinstance(edit["path"], str):
            raise PoaContractError("POA-EDIT-001", "only closed replace operations are supported")
        path = edit["path"]
        if path in seen:
            raise PoaContractError("POA-EDIT-001", "an editable path may occur only once")
        seen.add(path)
        if path in _PROTECTED_PATHS or path not in allowed:
            raise PoaContractError("POA-EDIT-003", "edit path is not authorized by the process DSL")
        previous = _replace(candidate, path, edit["value"])
        if type(previous) is not type(edit["value"]):
            raise PoaContractError("POA-EDIT-004", "edit must preserve the field value type")
        normalized.append({"op": "replace", "path": path, "value": deepcopy(edit["value"])})

    _preserve_controls(source_process, candidate)
    candidate_sha256 = digest_document(candidate)
    if candidate_sha256 == actual:
        raise PoaContractError("POA-EDIT-005", "process edit proposal has no material change")
    return {
        "schema": "subllm.process-edit-proposal/v1",
        "authority": "proposal-only",
        "base_sha256": actual,
        "candidate_sha256": candidate_sha256,
        "edits": normalized,
        "candidate_process": candidate,
        "publication_required": True,
    }


def _editor_policy(source: dict[str, Any]) -> dict[str, Any]:
    decision = source.get("decision_policy")
    if not isinstance(decision, dict):
        raise PoaContractError("POA-EDIT-001", "source process has no decision_policy")
    editor = decision.get("llm_editor")
    if not isinstance(editor, dict) or editor.get("authority") != "proposal-only":
        raise PoaContractError("POA-EDIT-001", "source process has no proposal-only LLM editor")
    publication = decision.get("publication")
    required = {"schema_validation", "exact_base_digest", "independent_validation"}
    if not isinstance(publication, dict) or any(publication.get(key) is not True for key in required):
        raise PoaContractError("POA-EDIT-001", "source process publication gates are incomplete")
    return editor


def _replace(document: dict[str, Any], path: str, value: Any) -> Any:
    if not path.startswith("/") or "~" in path:
        raise PoaContractError("POA-EDIT-001", "edit path is not a closed JSON pointer")
    parts = path[1:].split("/")
    target: Any = document
    for part in parts[:-1]:
        if not isinstance(target, dict) or part not in target:
            raise PoaContractError("POA-EDIT-001", "edit path does not exist")
        target = target[part]
    leaf = parts[-1]
    if not isinstance(target, dict) or leaf not in target:
        raise PoaContractError("POA-EDIT-001", "edit path does not exist")
    previous = target[leaf]
    target[leaf] = deepcopy(value)
    return previous


def _preserve_controls(source: dict[str, Any], candidate: dict[str, Any]) -> None:
    identity = ("schema_version", "process_id", "process_ref", "entrypoint", "owner")
    for key in identity:
        if source.get(key) != candidate.get(key):
            raise PoaContractError("POA-EDIT-006", "process identity changed")
    for key in ("required_inputs", "allowed_actions", "required_artifacts"):
        if source.get(key) != candidate.get(key):
            raise PoaContractError("POA-EDIT-006", "process authority surface changed")
    source_policy = source["decision_policy"]
    candidate_policy = candidate["decision_policy"]
    for key in ("deterministic_controls", "heuristic", "publication"):
        if source_policy.get(key) != candidate_policy.get(key):
            raise PoaContractError("POA-EDIT-006", "process control boundary changed")
    if source_policy["llm_editor"].get("editable_paths") != candidate_policy["llm_editor"].get(
        "editable_paths"
    ):
        raise PoaContractError("POA-EDIT-006", "process editor authority changed")
