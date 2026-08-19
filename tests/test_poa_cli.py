from __future__ import annotations

import json

from subllm.cli import main
from subllm.poa.registry import LIST_ROUTES_REF


def test_poa_inspect_and_catalog(capsys) -> None:
    assert main(["poa", "catalog"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert catalog["single_exporter"] == "subactor/subllm"
    assert LIST_ROUTES_REF in catalog["uris"]

    assert main(["poa", "inspect", LIST_ROUTES_REF]) == 0
    inspect = json.loads(capsys.readouterr().out)
    assert inspect["ready"] is True
    assert inspect["process"]["steps"][0]["kind"] == "query"


def test_existing_cli_still_uses_public_check(capsys) -> None:
    assert main(["check"]) == 0
    assert capsys.readouterr().out == "SubLLM policy: OK\n"
