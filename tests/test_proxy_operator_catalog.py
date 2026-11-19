"""HTTP discovery loads the current operator TOML in each request's context."""
import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from subllm import proxy


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    policy = tmp_path / "operator.toml"
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy))
    monkeypatch.setattr(proxy, "get_upstream_ollama_models", lambda *args, **kwargs: [])
    server = proxy.make_proxy_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield policy, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize(("endpoint", "key", "field", "suffix"), [
    ("/v1/models", "data", "id", ""),
    ("/api/tags", "models", "name", ":latest"),
])
def test_catalog_loads_custom_models_on_first_request_and_after_update(catalog, endpoint, key, field, suffix):
    policy, base = catalog
    defaults = (Path(__file__).resolve().parents[1] / "subllm.toml").read_text()
    for model, missing in (("private-a", "private-b"), ("private-b", "private-a")):
        policy.write_text(defaults + f'\n[custom_providers.fixture]\napi_base = "http://127.0.0.1:12345/v1"\n'
                          f'default_model = "{model}"\nroutes = ["onedev-agent/code-edit"]\n')
        with urlopen(base + endpoint, timeout=5) as response:
            names = {row[field] for row in json.load(response)[key]}
        assert model + suffix in names
        assert missing + suffix not in names


def test_catalog_reports_invalid_operator_policy(catalog):
    policy, base = catalog
    policy.write_text("invalid TOML")
    with pytest.raises(HTTPError) as error:
        urlopen(base + "/v1/models", timeout=5)
    with error.value as response:
        assert response.code == 503
        assert json.load(response)["error"]["code"] == "INVALID_POLICY"
