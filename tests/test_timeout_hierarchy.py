from pathlib import Path

import pytest

from subllm import CompletionResponse, client_routes, complete, import_credentials, load_env_file, proxy
from subllm.errors import InvalidPolicyError
from subllm.policy_config import resolve_attempt_timeout


@pytest.mark.parametrize('value', ['0', 'nan', 'inf', 'bad', '3601'])
def test_invalid_specific_timeout_does_not_fall_back(value):
    with pytest.raises(InvalidPolicyError):
        resolve_attempt_timeout('zai', 'glm-5.3', environ={
            'SUBLLM_TIMEOUT_ZAI_GLM_5_3': value,
            'SUBLLM_TIMEOUT_DEFAULT': '60',
        })


def test_long_prompt_does_not_raise_an_explicit_model_limit():
    assert resolve_attempt_timeout('zai', 'glm-5.3', environ={
        'SUBLLM_TIMEOUT_ZAI_GLM_5_3': '5',
    }, input_chars=2000) == 5


@pytest.mark.parametrize('model', ['glm-5.3', 'koru-agent/queue-executor'])
def test_proxy_dispatch_preserves_the_callers_total_deadline(monkeypatch, model):
    monkeypatch.setenv('SUBLLM_TIMEOUT_DEFAULT', '100')
    observed = []

    def invoke(*args, **kwargs):
        observed.append(kwargs['timeout_seconds'])
        return CompletionResponse('ok', 'zai', 'glm-5.3', {}, 'stop')

    monkeypatch.setattr(proxy, 'complete', invoke)
    monkeypatch.setattr(proxy, '_complete_model_direct', invoke)
    proxy.SubLLMProxyHandler._execute_model_or_route(
        None, model, [{'role': 'user', 'content': 'x' * 2000}], None, None, 5, None, {},
    )
    assert observed == [5]


@pytest.mark.parametrize('engine', ['client', 'proxy'])
def test_failover_uses_one_total_deadline(monkeypatch, engine):
    clock = [0.0]
    budgets = []
    monkeypatch.setattr(client_routes.time, 'monotonic', lambda: clock[0])

    def invoke(route, *args, **kwargs):
        budgets.append(kwargs['timeout_seconds'])
        if len(budgets) == 1:
            clock[0] = 2.0
            raise client_routes._RetryableAttemptError(
                'timeout', outcome='timeout', provider_level=True,
            )
        return CompletionResponse('ok', route.provider, route.wire_model, {}, 'stop')

    monkeypatch.setattr(client_routes, '_invoke_route', invoke)
    env = {'ZAI_API_KEY': 'id.secret', 'OPENROUTER_API_KEY': 'or-value',
           'SUBLLM_TIMEOUT_DEFAULT': '100'}
    messages = [{'role': 'user', 'content': 'x' * 2000}]
    if engine == 'client':
        complete('repair-agent', 'repair-plan', messages, timeout_seconds=5, environ=env)
    else:
        proxy._complete_model_direct('glm-5.3', messages, timeout_seconds=5, environ=env)
    assert budgets == [5, 3]


def test_import_preserves_hierarchical_timeout_values(tmp_path: Path):
    source = tmp_path / 'source.env'
    source.write_text('ZAI_API_KEY=id.secret\nSUBLLM_TIMEOUT_ZAI_GLM_5_3=7\n')
    source.chmod(0o600)
    target = tmp_path / 'target.env'
    import_credentials([source], target)
    assert load_env_file(target)['SUBLLM_TIMEOUT_ZAI_GLM_5_3'] == '7'


def test_archive_keeps_the_exact_remaining_attempt_budget():
    from types import SimpleNamespace

    from subllm.interaction_context import ACTIVE_ARCHIVE, begin_attempt

    captured = {}

    class Store:
        def begin(self, **kwargs):
            captured.update(kwargs)
            return kwargs

    route = SimpleNamespace(wire_model='glm-5.3', model_parameters={})
    archive_context = ACTIVE_ARCHIVE.set((Store(), {'caller': 'koru-agent', 'id': 'parent'}))
    try:
        begin_attempt(route, [{'role': 'user', 'content': 'prompt'}], None, timeout_seconds=0.04)
    finally:
        ACTIVE_ARCHIVE.reset(archive_context)
    assert captured['request']['timeout_seconds'] == 0.04


@pytest.mark.parametrize('engine', ['client', 'proxy'])
@pytest.mark.parametrize('timeout', [float('nan'), float('inf'), -1])
def test_invalid_caller_budget_never_reaches_a_provider(monkeypatch, engine, timeout):
    from subllm import CompletionError

    def invoke(*args, **kwargs):
        raise AssertionError('invalid timeout reached transport')

    monkeypatch.setattr(client_routes, '_invoke_route', invoke)
    env = {'ZAI_API_KEY': 'id.secret'}
    messages = [{'role': 'user', 'content': 'prompt'}]
    with pytest.raises(CompletionError):
        if engine == 'client':
            complete('repair-agent', 'repair-plan', messages, timeout_seconds=timeout, environ=env)
        else:
            proxy._complete_model_direct('glm-5.3', messages, timeout_seconds=timeout, environ=env)
