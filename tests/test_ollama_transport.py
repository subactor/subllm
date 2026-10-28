"""Consumer protocol checks; a synthetic response never qualifies a live model."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from subllm import MODELS, PROVIDERS, resolve


@pytest.mark.parametrize('model', [
    'qwen3-coder:30b', 'qwen2.5:1.5b', 'qwen2.5', 'qwen2.5-coder',
])
def test_ollama_catalog_matches_its_openai_endpoint(model):
    provider = PROVIDERS['ollama']
    binding = MODELS[model].providers['ollama']
    assert provider.transport == 'openai-compatible'
    assert provider.api_base.endswith('/v1')
    assert binding.litellm_model == 'openai/' + binding.wire_model


def test_real_litellm_uses_openai_endpoint_and_preserves_wire_identity(monkeypatch):
    # LiteLLM is an optional consumer, not a dependency of the policy library.
    # The protected OneDev runtime and the local consumer canary provide it.
    monkeypatch.setenv('LITELLM_LOCAL_MODEL_COST_MAP', 'True')
    litellm = pytest.importorskip('litellm')
    litellm.telemetry = False
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append((self.path, request['model']))
            success = self.path == '/v1/chat/completions'
            response = {'error': {'message': 'native Ollama API is not this endpoint'}}
            if success:
                response = {
                    'id': 'fixture', 'object': 'chat.completion', 'created': 1,
                    'model': request['model'],
                    'choices': [{'index': 0, 'finish_reason': 'stop',
                                 'message': {'role': 'assistant', 'content': 'fixture'}}],
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
                }
            payload = json.dumps(response).encode()
            self.send_response(200 if success else 404)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        route = resolve('validator-agent', 'direct-pr-review', provider='ollama',
                        environ={'OLLAMA_API_KEY': 'fixture-key'})
        route = replace(route, api_base=f'http://127.0.0.1:{server.server_port}/v1')
        result = litellm.completion(
            **route.litellm_kwargs(), messages=[{'role': 'user', 'content': 'fixture'}],
            num_retries=0, timeout=5, max_tokens=8,
        )
        assert result.choices[0].message.content == 'fixture'
        assert seen == [('/v1/chat/completions', route.wire_model)]
        assert route.provider == 'ollama'
        assert route.model == 'qwen3-coder:30b'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
