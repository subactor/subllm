"""Exercise upstream Streamable HTTP and server-to-client RPC, not only tools/list."""

import json
import socket
import sys
import time
from contextlib import contextmanager

import anyio
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client

from subllm.interaction_store import InteractionStore, utc_now


@contextmanager
def running(config, store):
    # Separate processes match deployment and avoid SSE library globals crossing event loops.
    import os
    import subprocess
    from pathlib import Path

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config["allowed_hosts"] = [f"127.0.0.1:{port}"]
    bootstrap = """import json,sys,pathlib,uvicorn
from subllm.gateway import create_app
from subllm.interaction_store import InteractionStore
source=json.loads(sys.stdin.readline())
app=create_app(source['config'],InteractionStore(pathlib.Path(source['archive'])))
uvicorn.run(app,host='127.0.0.1',port=source['port'],log_level='critical')
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    process = subprocess.Popen(
        [sys.executable, "-c", bootstrap],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    process.stdin.write((json.dumps({"config": config, "archive": str(store.directory), "port": port}) + "\n").encode())
    process.stdin.close()
    try:
        ready = False
        for _ in range(300):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    ready = True
                break
            except OSError:
                assert process.poll() is None
                time.sleep(0.02)
        assert ready
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_http_upstream_preserves_server_request_and_caller_response(tmp_path, monkeypatch):
    token = "transport-test-" + "x" * 32
    monkeypatch.setenv("GATEWAY_TEST_TOKEN", token)
    monkeypatch.setenv("GATEWAY_TEST_HEADER", "Bearer " + token)
    fixture = tmp_path / "roots_server.py"
    fixture.write_text("""import sys,json
pending=None
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 if m.get('method')=='initialize':
  result={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'roots-test','version':'1'}}
 elif m.get('method')=='tools/list':
  result={'tools':[{'name':'inspect_roots','inputSchema':{'type':'object'}}]}
 elif m.get('method')=='tools/call':
  pending=m['id']
  print(json.dumps({'jsonrpc':'2.0','id':'server-roots','method':'roots/list'}),flush=True)
  continue
 elif m['id']=='server-roots':
  m['id']=pending
  result={'content':[{'type':'text','text':json.dumps(m['result'])}],'isError':False}
 else: result={}
 print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':result}),flush=True)
""")
    upstream_store = InteractionStore(tmp_path / "upstream")
    upstream_config = {
        "clients": {"test": {"token_env": "GATEWAY_TEST_TOKEN", "mcp": ["roots"]}},
        "mcp": {"roots": {"command": sys.executable, "args": [str(fixture)]}},
    }
    outer_store = InteractionStore(tmp_path / "outer")
    with running(upstream_config, upstream_store) as upstream:
        outer_config = {
            "clients": {"test": {"token_env": "GATEWAY_TEST_TOKEN", "mcp": ["remote"]}},
            "mcp": {
                "remote": {"url": upstream + "/mcp/roots", "headers_from": {"Authorization": "GATEWAY_TEST_HEADER"}}
            },
        }
        with running(outer_config, outer_store) as outer:

            async def exercise():
                async def roots(context):
                    return types.ListRootsResult(roots=[types.Root(uri="file:///workspace", name="Test root")])

                with anyio.fail_after(15):
                    async with (
                        streamablehttp_client(outer + "/mcp/remote", headers={"Authorization": "Bearer " + token}) as (
                            read,
                            write,
                            _,
                        ),
                        ClientSession(read, write, list_roots_callback=roots) as session,
                    ):
                        await session.initialize()
                        response = await session.call_tool("inspect_roots", {})
                        assert not response.isError
                        assert json.loads(response.content[0].text)["roots"][0]["name"] == "Test root"

            anyio.run(exercise)
    rows = outer_store.query(utc_now()[:10])
    callbacks = [row for row in rows if row["direction"] == "server_to_client"]
    assert len(callbacks) == 1 and callbacks[0]["status"] == "success"
    detail = outer_store.query(callbacks[0]["day"], callbacks[0]["id"])
    assert detail["request"]["method"] == "roots/list"
    assert detail["response"]["id"] == "server-roots"


def test_pinned_logs_adoption_and_runtime_catalog():
    import subprocess
    from pathlib import Path

    from subllm.gateway_diagnostics import CATALOG

    root = Path(__file__).parents[1]
    catalog = json.loads((root / ".governance/logs/catalog.json").read_text())
    assert catalog["diagnosticCodes"] == sorted(CATALOG)
    subprocess.run([sys.executable, str(root / "scripts/check-logs.py")], check=True, capture_output=True)


def test_failed_upstream_returns_rpc_error_before_http_session_closes(tmp_path, monkeypatch):
    import httpx

    credential = "refused-test-" + "x" * 32
    monkeypatch.setenv("REFUSED_GATEWAY_CREDENTIAL", credential)
    store = InteractionStore(tmp_path / "refused")
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        config = {
            "clients": {"test": {"token_env": "REFUSED_GATEWAY_CREDENTIAL", "mcp": ["offline"]}},
            "mcp": {"offline": {"url": f"http://127.0.0.1:{unavailable.getsockname()[1]}/mcp"}},
        }
        with running(config, store) as gateway, httpx.Client(timeout=5, trust_env=False) as client:
            headers = {"Authorization": "Bearer " + credential, "Accept": "application/json, text/event-stream"}
            response = client.post(gateway + "/mcp/offline", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"}}})
            assert response.status_code == 200
            assert '"message":"SUBLLM-UPSTREAM-TRANSPORT"' in response.text
            headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
            headers["Mcp-Protocol-Version"] = "2025-06-18"
            response = client.post(gateway + "/mcp/offline", headers=headers,
                                   json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert '"message":"SUBLLM-UPSTREAM-TRANSPORT"' in response.text
            assert client.delete(gateway + "/mcp/offline", headers=headers).status_code == 200
    rows = store.query(utc_now()[:10])
    assert len(rows) == 2
    assert all(row["diagnostic"]["transportCode"] == "ECONNREFUSED" for row in rows)
    for row in rows:
        detail = store.query(row["day"], row["id"])
        assert detail["response"]["error"]["message"] == "SUBLLM-UPSTREAM-TRANSPORT"
        assert detail["metadata"]["response_origin"] == "gateway"
        assert detail["duration_ms"] == detail["diagnostic"]["durationMs"]
