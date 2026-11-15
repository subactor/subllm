"""Exercise the public import boundary in fresh interpreters, without providers."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _fresh(source: str) -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        env=environment, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("entry", [
    "subllm", "subllm.cursor_worker", "subllm.openai_worker",
])
def test_worker_import_does_not_load_unrelated_public_api(entry):
    _fresh(f"""
        import importlib
        import sys

        blocked = {{'subllm.client', 'subllm.proxy', 'subllm.decisions', 'subllm.kpi_ledger'}}

        class RejectUnrelatedImports:
            def find_spec(self, fullname, path=None, target=None):
                assert fullname not in blocked, fullname

        sys.meta_path.insert(0, RejectUnrelatedImports())
        importlib.import_module({entry!r})
        assert not blocked.intersection(sys.modules)
        assert 'cursor_sdk' not in sys.modules
    """)


def test_public_exports_resolve_to_canonical_objects_and_cache():
    _fresh("""
        import importlib
        import subllm

        owners = {
            'client': ('complete', 'stream_complete', 'CompletionResponse'),
            'credential_env': ('load_shared_environment', 'credential_value'),
            'decisions': ('decide', 'DecisionError', 'DEFAULT_DECISION_MODEL'),
            'errors': ('CompletionError', 'UnknownRouteError'),
            'health': ('provider_health',),
            'kpi_ledger': ('KpiCostLedger', 'IncompleteCostMeasurementError'),
            'policy': ('PROVIDERS', 'MODELS', 'APPLICATIONS'),
            'policy_config': ('load_policy_config',),
            'provider_order': ('provider_order', 'parse_provider_order'),
            'proxy': ('make_proxy_server',),
            'resolver': ('resolve', 'validate_policy'),
            'request_scope': ('request_scope', 'RequestAuditContext'),
            'types': ('RoutePolicy', 'ModelSpec'),
        }
        for module_name, names in owners.items():
            module = importlib.import_module('subllm.' + module_name)
            for name in names:
                value = getattr(subllm, name)
                assert value is getattr(module, name), name
                assert vars(subllm)[name] is value, name
    """)


@pytest.mark.parametrize("entry", ["subllm.client", "subllm.openai_worker"])
def test_callable_exports_survive_submodule_import_order(entry):
    _fresh(f"""
        import importlib
        import subllm

        importlib.import_module({entry!r})
        from subllm import provider_order, request_scope
        assert callable(provider_order)
        assert callable(request_scope)
        assert provider_order is importlib.import_module('subllm.provider_order').provider_order
        assert request_scope is importlib.import_module('subllm.request_scope').request_scope
    """)


def test_star_import_discovery_and_unknown_attribute():
    _fresh("""
        import subllm

        assert set(subllm.__all__) <= set(dir(subllm))
        namespace = {}
        exec('from subllm import *', namespace)
        assert set(namespace) - {'__builtins__'} == set(subllm.__all__)
        for name in subllm.__all__:
            assert namespace[name] is getattr(subllm, name), name
        try:
            subllm.this_export_does_not_exist
        except AttributeError as error:
            assert 'this_export_does_not_exist' in str(error)
        else:
            raise AssertionError('Unknown public name must raise AttributeError')
    """)
