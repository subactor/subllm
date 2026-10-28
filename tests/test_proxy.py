from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import subllm.proxy as proxy
from subllm import CompletionResponse, make_proxy_server


@pytest.fixture
def proxy_server(monkeypatch):
    """Start proxy server on ephemeral port."""
    server = make_proxy_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    try:
        yield base_url, server
    finally:
        server.shutdown()
        server.server_close()


def _request(method: str, url: str, payload: dict | None = None, headers: dict | None = None,
             *, timeout_seconds: float = 30) -> tuple[int, dict, dict]:
    """Bound client transport waiting separately from the application's payload timeout."""
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers=req_headers, method=method)
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            body = resp.read().decode()
            resp_headers = dict(resp.headers)
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"raw": body}
            return resp.status, parsed, resp_headers
    except HTTPError as exc:
        body = exc.read().decode()
        resp_headers = dict(exc.headers)
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return exc.code, parsed, resp_headers


def test_proxy_health_and_cors(proxy_server):
    base_url, _ = proxy_server
    status, body, headers = _request("GET", f"{base_url}/health")
    assert status == 200
    assert body["status"] == "ok"
    assert body["service"] == "subllm-proxy"
    assert "access-control-allow-origin" in [k.lower() for k in headers]


@pytest.mark.parametrize("stream", [False, True])
def test_openai_wire_preserves_cached_input_without_counting_it_twice(proxy_server, monkeypatch, stream):
    response = CompletionResponse("review", "codex-cli", "gpt-5.6-sol",
                                  {"input_tokens": 14945, "cached_input_tokens": 11008, "output_tokens": 177})
    monkeypatch.setattr(proxy.SubLLMProxyHandler, "_execute_model_or_route", lambda *a: response)
    status, body, _ = _request("POST", proxy_server[0] + "/v1/chat/completions", {
        "model": "glm-5.3", "messages": [{"role": "user", "content": "review fixture"}],
        "stream": stream, "stream_options": {"include_usage": True},
    })
    assert status == 200
    if stream:
        events = [json.loads(line[6:]) for line in body["raw"].splitlines()
                  if line.startswith("data: ") and line != "data: [DONE]"]
        assert events[-1]["choices"] == []
        body = events[-1]
    assert body["usage"] == {"prompt_tokens": 14945, "completion_tokens": 177, "total_tokens": 15122,
                             "prompt_tokens_details": {"cached_tokens": 11008}}


@pytest.mark.parametrize("cached", [None, 0, -1, True, "11008", 14946])
def test_openai_wire_keeps_unknown_or_invalid_cache_unknown(proxy_server, monkeypatch, cached):
    response = CompletionResponse("ok", "fixture", "fixture",
                                  {"prompt_tokens": 14945, "cached_input_tokens": cached, "completion_tokens": 1})
    monkeypatch.setattr(proxy.SubLLMProxyHandler, "_execute_model_or_route", lambda *a: response)
    status, body, _ = _request("POST", proxy_server[0] + "/v1/chat/completions", {
        "model": "glm-5.3", "messages": [{"role": "user", "content": "fixture"}],
    })
    assert status == 200
    if type(cached) is int and cached == 0:
        assert body["usage"]["prompt_tokens_details"] == {"cached_tokens": 0}
    else:
        assert "prompt_tokens_details" not in body["usage"]


def test_proxy_options_cors(proxy_server):
    base_url, _ = proxy_server
    status, _, headers = _request("OPTIONS", f"{base_url}/v1/chat/completions")
    assert status == 204
    assert any(k.lower() == "access-control-allow-methods" for k in headers)


def test_proxy_models_openai(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("GET", f"{base_url}/v1/models")
    assert status == 200
    assert body["object"] == "list"
    model_ids = {m["id"] for m in body["data"]}
    assert "glm-5.3" in model_ids
    assert "gpt-5.6-sol" in model_ids
    assert "deepseek-v4-pro" in model_ids
    assert "koru-agent/queue-executor" in model_ids


def test_proxy_tags_ollama(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("GET", f"{base_url}/api/tags")
    assert status == 200
    models = body["models"]
    model_names = {m["name"] for m in models}
    assert "glm-5.3:latest" in model_names
    glm_entry = next(m for m in models if m["name"] == "glm-5.3:latest")
    assert glm_entry["details"]["family"] == "glm"


def test_proxy_version_ollama(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("GET", f"{base_url}/api/version")
    assert status == 200
    assert "version" in body


def test_proxy_show_ollama(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("POST", f"{base_url}/api/show", {"name": "glm-5.3"})
    assert status == 200
    assert "modelfile" in body
    assert body["details"]["family"] == "glm"


def test_proxy_openai_chat_completions_non_streaming(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    fake_response = CompletionResponse(
        content="SubLLM proxy generated answer",
        provider="zai",
        model="glm-5.3",
        usage={"input_tokens": 12, "output_tokens": 8},
        finish_reason="stop",
    )
    monkeypatch.setattr(proxy, "_complete_model_direct", lambda *args, **kwargs: fake_response)

    payload = {
        "model": "glm-5.3@ticket-008",
        "messages": [{"role": "user", "content": "How does subllm work?"}],
        "stream": False,
    }
    status, body, headers = _request("POST", f"{base_url}/v1/chat/completions", payload)
    assert status == 200
    assert body["object"] == "chat.completion"
    assert body["model"] == "glm-5.3"
    assert body["choices"][0]["message"]["content"] == "SubLLM proxy generated answer"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["prompt_tokens"] == 12
    assert body["usage"]["completion_tokens"] == 8
    assert headers.get("X-Subactor-Provider") == "zai"
    assert headers.get("X-Subactor-Ticket") == "ticket-008"


def test_proxy_openai_chat_completions_streaming(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    fake_response = CompletionResponse(
        content="Hello world",
        provider="zai",
        model="glm-5.3",
        usage={"input_tokens": 5, "output_tokens": 2},
        finish_reason="stop",
    )
    monkeypatch.setattr(proxy, "_complete_model_direct", lambda *args, **kwargs: fake_response)

    payload = {
        "model": "glm-5.3",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True,
    }
    req = Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        assert "text/event-stream" in resp.headers.get("Content-Type", "")
        raw = resp.read().decode()
        assert "data: " in raw
        assert "[DONE]" in raw


def test_proxy_ollama_chat_non_streaming(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    fake_response = CompletionResponse(
        content="Ollama format reply",
        provider="zai",
        model="glm-5.3",
        usage={"input_tokens": 7, "output_tokens": 4},
        finish_reason="stop",
    )
    monkeypatch.setattr(proxy, "_complete_model_direct", lambda *args, **kwargs: fake_response)

    payload = {
        "model": "glm-5.3",
        "messages": [{"role": "user", "content": "test"}],
        "stream": False,
    }
    headers = {"X-Ticket": "ticket-101"}
    status, body, resp_headers = _request("POST", f"{base_url}/api/chat", payload, headers=headers)
    assert status == 200
    assert body["done"] is True
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "Ollama format reply"
    assert body["prompt_eval_count"] == 7
    assert body["eval_count"] == 4
    assert resp_headers.get("X-Subactor-Ticket") == "ticket-101"


def test_proxy_ollama_generate(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    fake_response = CompletionResponse(
        content="Generated completion",
        provider="zai",
        model="glm-5.3",
        usage={"input_tokens": 10, "output_tokens": 5},
        finish_reason="stop",
    )
    monkeypatch.setattr(proxy, "_complete_model_direct", lambda *args, **kwargs: fake_response)

    payload = {
        "model": "glm-5.3",
        "prompt": "Write a poem",
        "stream": False,
    }
    status, body, _ = _request("POST", f"{base_url}/api/generate", payload)
    assert status == 200
    assert body["done"] is True
    assert body["response"] == "Generated completion"


def test_proxy_route_notation_dispatch(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    fake_response = CompletionResponse(
        content="Koru queue plan ready",
        provider="zai",
        model="glm-5.3",
        usage={"input_tokens": 20, "output_tokens": 10},
        finish_reason="stop",
    )
    called = []
    def fake_complete(app, func, messages, **kwargs):
        called.append((app, func))
        return fake_response

    monkeypatch.setattr(proxy, "complete", fake_complete)

    payload = {
        "model": "koru-agent/queue-executor@ticket-042",
        "messages": [{"role": "user", "content": "Execute queue"}],
        "stream": False,
    }
    status, body, headers = _request("POST", f"{base_url}/v1/chat/completions", payload)
    assert status == 200
    assert called == [("koru-agent", "queue-executor")]
    assert body["choices"][0]["message"]["content"] == "Koru queue plan ready"
    assert headers.get("X-Subactor-Ticket") == "ticket-042"


def test_proxy_rejects_non_local_host(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("GET", f"{base_url}/health", headers={"Host": "evil.external.com"})
    assert status == 421
    assert body["error"]["code"] == "PROXY-001"


@pytest.mark.parametrize("explicit,expected", [(None, 130.0), (8, 8.0)])
def test_openai_timeout_uses_policy_unless_explicit(proxy_server, monkeypatch, explicit, expected):
    monkeypatch.setenv("SUBLLM_ATTEMPT_TIMEOUT_SECONDS", "130")
    seen = []

    def execute(self, clean_model, messages, app, func, timeout, req_id, payload):
        seen.append(timeout)
        return CompletionResponse("ok", "cursor-cli", "auto")

    monkeypatch.setattr(proxy.SubLLMProxyHandler, "_execute_model_or_route", execute)
    monkeypatch.setattr(proxy, "is_upstream_ollama_alive", lambda *_: False)
    payload = {"model": "cursor-auto", "messages": [{"role": "user", "content": "hello"}]}
    if explicit is not None:
        payload["timeout"] = explicit
    status, _, _ = _request("POST", proxy_server[0] + "/v1/chat/completions", payload)
    assert status == 200
    assert seen == [expected]


@pytest.mark.parametrize("timeout", [0, -1, True, "nan", "inf", "invalid", {}])
def test_openai_invalid_timeout_is_rejected_before_dispatch(proxy_server, monkeypatch, timeout):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid request must not invoke provider")

    monkeypatch.setattr(proxy.SubLLMProxyHandler, "_execute_model_or_route", unexpected)
    status, body, _ = _request("POST", proxy_server[0] + "/v1/chat/completions", {
        "model": "cursor-auto", "messages": [{"role": "user", "content": "hello"}], "timeout": timeout,
    })
    assert status == 400
    assert body["error"]["code"] == "INVALID_REQUEST"


def test_adaptive_http_alias_exposes_actual_model_and_preserves_strength(proxy_server, monkeypatch, tmp_path):
    from subllm.types import ResolvedRoute
    config = tmp_path / 'adaptive.json'
    config.write_text(json.dumps({'classes': {'strong': ['gemini-3.1-pro-high'], 'fast': ['gpt-5.6-luna']},
                                 'aliases': {'vendor/unavailable-pro': 'strong'},
                                 'routes': {'subactor-proxy/chat': 'strong'}}))
    monkeypatch.setenv('SUBLLM_ADAPTIVE_POLICY', str(config))
    def build(model, *args, **kwargs):
        return [ResolvedRoute(application='subactor-proxy', application_name='test', application_url='',
            function='chat', provider='agy-cli', model=model, priority=1, api_base='', api_key_env='',
            litellm_model='', wire_model=model, extra_headers={}, transport='agy-cli', api_key='')]
    monkeypatch.setattr(proxy, '_build_model_resolved_routes', build)
    monkeypatch.setattr(proxy, '_complete_route',
                        lambda r, *a, **k: CompletionResponse('{"ok":true}', r.provider, r.model))
    base_url,_=proxy_server
    status,body,headers=_request('POST',base_url+'/v1/chat/completions',{
        'model':'vendor/unavailable-pro','messages':[{'role':'user','content':'hello'}],
        'response_format':{'type':'json_object'}})
    assert status==200
    assert body['model']=='gemini-3.1-pro-high'
    assert headers['X-Subactor-Provider']=='agy-cli'
    status, body, _ = _request('POST', base_url+'/v1/chat/completions', {
        'model': 'gpt-5.6-luna', 'messages': [{'role':'user','content':'hello'}]})
    assert status == 200
    assert body['model'] == 'gemini-3.1-pro-high'
    monkeypatch.setattr(proxy, '_build_model_resolved_routes',
                        lambda model, *a, **k: build(model) if model == 'gpt-5.6-luna' else [])
    monkeypatch.setattr(proxy, 'is_upstream_ollama_alive', lambda *a,**k:True)
    # An unrelated live Ollama upstream must never bypass the required class.
    status,body,_=_request('POST',base_url+'/v1/chat/completions',{
        'model':'vendor/unavailable-pro','messages':[{'role':'user','content':'hello'}]})
    assert status==500
    assert 'requested model class' in body['error']['message']


def test_direct_candidates_respect_enabled_custom_provider_without_key(monkeypatch, tmp_path):
    from pathlib import Path
    policy = tmp_path / 'policy.toml'
    base = (Path(__file__).resolve().parents[1] / 'subllm.toml').read_text()
    custom = '''
[custom_providers.quota-test]
api_base = "http://127.0.0.1:1/v1"
api_key_env = ""
default_model = "quota-test-model"
models = ["quota-test-model"]
priority = 1
enabled = true
routes = ["subactor-proxy"]
'''
    policy.write_text(base + custom)
    monkeypatch.setenv('SUBLLM_POLICY_FILE', str(policy))
    routes = proxy._build_model_resolved_routes('quota-test-model')
    assert len(routes) == 1 and routes[0].api_key == ''
    policy.write_text(base + custom.replace('enabled = true', 'enabled = false'))
    assert proxy._build_model_resolved_routes('quota-test-model') == ()


def test_client_wait_is_independent_of_application_timeout(proxy_server, monkeypatch):
    """A slow local backend exposes socket waiting without any provider or database."""
    started, release = threading.Event(), threading.Event()
    seen, delayed_request = [], []
    json_response = proxy.SubLLMProxyHandler._json

    def respond(self, *args, **kwargs):
        try:
            return json_response(self, *args, **kwargs)
        except (BrokenPipeError, ConnectionResetError):
            # Only the intentionally timed-out first client may disconnect.
            if delayed_request and self is delayed_request[0]:
                return None
            raise

    def delayed(self, model, messages, app, func, timeout, request_id, payload):
        seen.append(timeout)
        if not delayed_request:
            delayed_request.append(self)
        started.set()
        assert release.wait(10), "test must release the delayed backend"
        return CompletionResponse("controlled reply", "agy", "gemini-3.8-flash")

    monkeypatch.setattr(proxy.SubLLMProxyHandler, "_execute_model_or_route", delayed)
    monkeypatch.setattr(proxy.SubLLMProxyHandler, "_json", respond)
    base_url, server = proxy_server
    payload = {"model": "glm-5.3", "messages": [{"role": "user", "content": "fixture"}], "timeout": .5}
    try:
        with pytest.raises(TimeoutError):
            _request("POST", base_url + "/v1/chat/completions", payload, timeout_seconds=.05)
        assert started.wait(5)
    finally:
        release.set()
    status, body, headers = _request("POST", base_url + "/v1/chat/completions", payload, timeout_seconds=5)
    assert status == 200 and body["choices"][0]["message"]["content"] == "controlled reply"
    assert headers["X-Subactor-Model"] == "gemini-3.8-flash"
    assert seen == [.5, .5]


def test_proxy_system_one_decide_uses_local_qwen3_5_ollama_when_available(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    monkeypatch.setattr(proxy, "is_upstream_ollama_alive", lambda url, *_: True)
    monkeypatch.setattr(
        proxy,
        "get_upstream_ollama_models",
        lambda url, *_: [
            {"name": "qwen3.5:0.8b", "model": "qwen3.5:0.8b"},
            {"name": "qwen3.5:4b", "model": "qwen3.5:4b"},
        ],
    )
    seen_ollama = []

    def fake_ollama_system_one(upstream_url, ollama_model, messages, **kwargs):
        seen_ollama.append((ollama_model, kwargs.get("temperature")))
        return CompletionResponse(
            content=json.dumps({
                "answers": {
                    "uri_choice": "heyasa://local/audio/control/set-volume?level=30",
                    "risk_score": "1",
                    "execution_allowed": "true",
                }
            }),
            provider="ollama",
            model=ollama_model,
            usage={"input_tokens": 90, "output_tokens": 28},
            finish_reason="stop",
        )

    monkeypatch.setattr(proxy, "_complete_ollama_system_one", fake_ollama_system_one)

    payload = {
        "schema": "wellmanifest.system-one-request/v1",
        "model": "laya/laya-multilingual-322m@ticket-149",
        "wire_format": "jev-system-one",
        "temperature": 0.35,
        "state": {"query": "ustaw głośność na 30%", "autonomy_mode": "confirm"},
        "questions": [
            {
                "id": "uri_choice",
                "type": "choice",
                "question": "Select the canonical DockURI / Action URI.",
                "options": [
                    "heyasa://local/audio/control/set-volume?level=30",
                    "heyasa://local/system/query/status",
                ],
            },
            {
                "id": "risk_score",
                "type": "score",
                "question": "Score operational risk level from 1 to 3.",
                "options": ["1", "2", "3"],
            },
            {
                "id": "execution_allowed",
                "type": "noul",
                "question": "Is immediate execution safe and free of negation?",
                "options": ["true", "false"],
            },
        ],
    }
    status, body, headers = _request("POST", f"{base_url}/v1/decide", payload)
    assert status == 200
    assert body["schema"] == "wellmanifest.system-one-response/v1"
    assert body["provider"] == "ollama"
    assert body["model"] == "qwen3.5:0.8b"
    assert seen_ollama == [("qwen3.5:0.8b", 0.35)]
    assert headers.get("X-Subactor-Provider") == "ollama"
    assert headers.get("X-Subactor-Model") == "qwen3.5:0.8b"
    assert headers.get("X-Subactor-Ticket") == "ticket-149"

    probs = body["probabilities"]
    assert probs["uri_choice"]["heyasa://local/audio/control/set-volume?level=30"] > probs["uri_choice"]["heyasa://local/system/query/status"]
    assert abs(sum(probs["uri_choice"].values()) - 1.0) < 1e-4
    assert abs(sum(probs["risk_score"].values()) - 1.0) < 1e-4
    assert abs(sum(probs["execution_allowed"].values()) - 1.0) < 1e-4
    assert body["answers"]["uri_choice"] == "heyasa://local/audio/control/set-volume?level=30"
    assert body["answers"]["execution_allowed"] is True


def test_system_one_model_selection_prefers_d1_and_keeps_qwen_fallback(monkeypatch):
    installed = [
        {"name": "qwen3.5:0.8b", "model": "qwen3.5:0.8b"},
        {"name": "d1:3b", "model": "d1:3b"},
    ]
    monkeypatch.setattr(proxy, "get_upstream_ollama_models", lambda *_: installed)

    assert proxy._select_local_system_one_ollama_model("d1") == "d1:3b"
    assert proxy._select_local_system_one_ollama_model("d1:3b") == "d1:3b"
    assert proxy._select_local_system_one_ollama_model("d1:3b", exclude_d1=True) == "qwen3.5:0.8b"

    monkeypatch.setattr(proxy, "get_upstream_ollama_models", lambda *_: installed[:1])
    assert proxy._select_local_system_one_ollama_model("d1:3b") == "qwen3.5:0.8b"

    aliases_only = [
        {"name": "d1:latest", "model": "d1:latest"},
        {"name": "qwen3.5:0.8b", "model": "qwen3.5:0.8b"},
    ]
    monkeypatch.setattr(proxy, "get_upstream_ollama_models", lambda *_: aliases_only)
    assert proxy._select_local_system_one_ollama_model("d1:3b") == "qwen3.5:0.8b"


def test_ollama_d1_uses_native_system_one_contract_and_normalizes_answers(monkeypatch):
    request_payload = {
        "state": {"query": "Zrestartuj worker na staging."},
        "questions": [
            {
                "id": "operation",
                "type": "choice",
                "question": "Which operation?",
                "options": {"op_0": "Restart", "NO_MATCH": "No match"},
            },
            {"id": "safe", "type": "noul", "question": "Is the operation safe?", "options": ["true", "false"]},
            {"id": "risk", "type": "score", "question": "How risky?", "options": ["1", "2", "3"]},
        ],
    }
    upstream_data = {
        "model": "d1:3b",
        "answers": {
            "operation": {"type": "choice", "choice": "op_0", "probabilities": {"op_0": 0.9, "NO_MATCH": 0.1}},
            "safe": {"type": "noul", "noul": 0.8},
            "risk": {"type": "score", "score": 1.7, "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7}},
        },
        "usage": {"input_tokens": 42, "output_tokens": 0},
    }
    seen = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(upstream_data).encode()

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr(proxy, "urlopen", fake_urlopen)
    response = proxy._complete_ollama_system_one(
        "http://127.0.0.1:11434",
        "d1:3b",
        [],
        request_payload=request_payload,
        timeout_seconds=3.0,
    )

    assert seen["url"] == "http://127.0.0.1:11434/v1/systemone"
    assert seen["timeout"] == 3.0
    assert seen["body"] == {
        "model": "d1:3b",
        "state": {"query": "Zrestartuj worker na staging."},
        "questions": {
            "operation": {
                "type": "choice",
                "instructions": "Which operation?",
                "criteria": {"op_0": "Restart", "NO_MATCH": "No match"},
            },
            "safe": {
                "type": "noul",
                "instructions": "Is the operation safe?",
                "criteria": {"true": "The statement is true.", "false": "The statement is false."},
            },
            "risk": {"type": "score", "instructions": "How risky?", "criteria": ["1", "2", "3"]},
        },
    }
    parsed = json.loads(response.content)
    assert response.provider == "ollama"
    assert response.model == "d1:3b"
    assert response.usage == {"input_tokens": 42, "output_tokens": 0}
    assert parsed["answers"]["operation"] == "op_0"
    assert parsed["probabilities"]["operation"] == {"op_0": 0.9, "NO_MATCH": 0.1}
    assert parsed["probabilities"]["safe"] == {"true": 0.8, "false": 0.2}
    assert parsed["probabilities"]["risk"] == {"1": 0.1, "2": 0.2, "3": 0.7}


def test_malformed_d1_response_raises_for_local_fallback():
    payload = {
        "questions": [
            {"id": "operation", "type": "choice", "question": "Which operation?", "options": ["op_0", "NO_MATCH"]},
        ],
    }
    with pytest.raises(ValueError, match="malformed d1 response"):
        proxy._normalize_ollama_d1_response(
            {"answers": {"operation": {"type": "choice", "choice": "missing", "probabilities": {}}}},
            payload,
        )


def test_proxy_system_one_retries_qwen_after_local_d1_failure(proxy_server, monkeypatch):
    base_url, _ = proxy_server
    monkeypatch.setattr(proxy, "is_upstream_ollama_alive", lambda *_: True)
    monkeypatch.setattr(
        proxy,
        "get_upstream_ollama_models",
        lambda *_: [{"name": "d1:3b", "model": "d1:3b"}, {"name": "qwen3.5:0.8b", "model": "qwen3.5:0.8b"}],
    )
    seen = []

    def fail_d1_then_return_qwen(upstream_url, model, messages, **kwargs):
        seen.append(model)
        if model.startswith("d1"):
            raise ValueError("malformed d1 response")
        return CompletionResponse(
            content=json.dumps({"answers": {"operation": "op_0"}}),
            provider="ollama",
            model=model,
            usage={},
            finish_reason="stop",
        )

    monkeypatch.setattr(proxy, "_complete_ollama_system_one", fail_d1_then_return_qwen)
    payload = {
        "schema": "wellmanifest.system-one-request/v1",
        "questions": [
            {
                "id": "operation",
                "type": "choice",
                "question": "Which operation?",
                "options": ["op_0", "NO_MATCH"],
            },
        ],
    }
    status, body, _ = _request("POST", f"{base_url}/v1/decide", payload)

    assert status == 200
    assert seen == ["d1:3b", "qwen3.5:0.8b"]
    assert body["requested_model"] == "d1:3b"
    assert body["model"] == "qwen3.5:0.8b"
    assert body["answers"]["operation"] == "op_0"


def test_proxy_system_one_decide_falls_back_to_subllm_route_when_ollama_unavailable(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    monkeypatch.setattr(proxy, "is_upstream_ollama_alive", lambda *_: False)
    seen_routes = []

    def fake_execute(self, clean_model, messages, app, func, timeout, req_id, payload):
        seen_routes.append((clean_model, app, func, payload.get("response_format")))
        return CompletionResponse(
            content=json.dumps({
                "probabilities": {
                    "selected_operation": {"op_0": 0.9, "NO_MATCH": 0.05, "CLARIFY": 0.03, "PLAN_REQUIRED": 0.02},
                    "read_only_diagnosis": {"true": 0.1, "false": 0.9},
                }
            }),
            provider="zai",
            model="glm-5.3-flash",
            usage={"input_tokens": 64, "output_tokens": 22},
            finish_reason="stop",
        )

    monkeypatch.setattr(proxy.SubLLMProxyHandler, "_execute_model_or_route", fake_execute)

    payload = {
        "schema": "wellmanifest.system-one-request/v1",
        "model": "kev/kev-4b-qwen3.5",
        "wire_format": "jev-system-one",
        "state": {"query": "zrestartuj usługę auth"},
        "questions": [
            {
                "id": "selected_operation",
                "type": "choice",
                "question": "Która operacja najlepiej odpowiada żądaniu użytkownika?",
                "options": {
                    "op_0": "Restart usługi systemowej.",
                    "NO_MATCH": "Żadna dostępna operacja nie odpowiada żądaniu.",
                    "CLARIFY": "Żądanie wymaga doprecyzowania.",
                    "PLAN_REQUIRED": "Zadanie wymaga sekwencji operacji.",
                },
            },
            {
                "id": "read_only_diagnosis",
                "type": "noul",
                "question": "Czy użytkownik oczekuje wyłącznie diagnozy?",
                "options": ["true", "false"],
            },
        ],
    }
    status, body, headers = _request("POST", f"{base_url}/v1/system-one/decide", payload)
    assert status == 200
    assert seen_routes == [("heyasa/command", "heyasa", "command", {"type": "json_object"})]
    assert body["provider"] == "zai"
    assert body["model"] == "glm-5.3-flash"
    assert body["answers"]["selected_operation"] == "op_0"
    assert body["answers"]["read_only_diagnosis"] is False
    assert headers.get("X-Subactor-Provider") == "zai"


def test_proxy_system_one_decide_rejects_missing_questions(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("POST", f"{base_url}/v1/decide", {"schema": "wellmanifest.system-one-request/v1"})
    assert status == 400
    assert body["error"]["code"] == "INVALID_REQUEST"
