"""Render opt-in local development profiles without changing shared routing.

Usage: python -m subllm.local_runtime --base-url http://127.0.0.1:11435
    --model gemma4:12b --output-dir /path/to/new/profile

For a LAN Ollama host, forward it through SSH to a loopback port. SubLLM's
existing requirement for HTTPS on remote endpoints remains in force. Generated
profiles select a model; ticket ownership, verification and publication still
belong to the execution controller. Use each SubLLM profile in its own process.
OpenCode's context limit does not change Ollama's server-side num_ctx setting.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .policy import APPLICATIONS, ROUTES
from .policy_config import _DEFAULTS

DEFAULT_ROUTES = ("koru-agent/queue-executor", "subactor-proxy/completion")
PROVIDER = "local-development"
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                          ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))


def local_base_url(value: str) -> str:
    """Normalize an explicit loopback/private address; never resolve a hostname."""
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/", "/v1", "/v1/"}):
        raise ValueError("use a local HTTP(S) base URL without credentials, query or extra path")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid endpoint port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("invalid endpoint port")
    hostname = parsed.hostname
    if hostname == "localhost":
        loopback = True
    else:
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise ValueError("use localhost or an explicit private IP address") from exc
        loopback = address.is_loopback
        if not loopback and not any(address in network for network in _PRIVATE_NETWORKS):
            raise ValueError("public and unspecified endpoints are not local development endpoints")
    if parsed.scheme != "https" and hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("LAN HTTP needs an SSH tunnel to loopback; remote SubLLM endpoints require HTTPS")
    return urlunsplit((parsed.scheme, parsed.netloc, "/v1", "", ""))


def _integer(value: int, name: str, lower: int, upper: int) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer from {lower} to {upper}")
    return value


def render_profiles(*, base_url: str, model: str, routes: tuple[str, ...] = DEFAULT_ROUTES,
                    context: int = 16384, output_tokens: int = 2048,
                    timeout_seconds: int = 300, steps: int = 12) -> dict[str, str]:
    """Return deterministic SubLLM TOML and OpenCode JSON with no cloud route."""
    base_url = local_base_url(base_url)
    if not isinstance(model, str) or not _MODEL.fullmatch(model) or model.endswith(("-cloud", ":cloud")):
        raise ValueError("select an explicit local model identifier, without a cloud tag")
    context = _integer(context, "context", 4096, 131072)
    output_tokens = _integer(output_tokens, "output_tokens", 128, context - 1)
    timeout_seconds = _integer(timeout_seconds, "timeout_seconds", 30, 3600)
    steps = _integer(steps, "steps", 1, 32)
    if not routes or len(set(routes)) != len(routes):
        raise ValueError("provide nonempty, unique application/function routes")
    for route in routes:
        if not isinstance(route, str) or tuple(route.split("/")) not in ROUTES:
            raise ValueError(f"unknown application/function route: {route}")
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    lines = ["# Isolated local profile; load in a dedicated process.", "schema_version = 3", "",
             "[execution]", "failover_enabled = true",
             f"attempt_timeout_seconds = {timeout_seconds}.0",
             f"slow_response_seconds = {timeout_seconds}.0", "cooldown_seconds = 60.0",
             "failure_threshold = 1", "max_attempts = 1", ""]
    for name, default in _DEFAULTS.items():
        lines.extend((f"[providers.{quote(name)}]", "enabled = false",
                      f"priority = {default.priority}", f"default_model = {quote(default.default_model)}", ""))
    for name, application in APPLICATIONS.items():
        lines.extend((f"[applications.{quote(name)}]", f"name = {quote(application.title)}",
                      f"url = {quote(application.url)}", ""))
    lines.extend((f"[custom_providers.{PROVIDER}]", f"api_base = {quote(base_url)}", 'api_key_env = ""',
                  f"default_model = {quote(model)}", f"models = [{quote(model)}]", "priority = 0",
                  "enabled = true", "routes = [" + ", ".join(map(quote, routes)) + "]", ""))
    config = {"$schema": "https://opencode.ai/config.json", "enabled_providers": [PROVIDER],
              "model": f"{PROVIDER}/{model}", "small_model": f"{PROVIDER}/{model}",
              "share": "disabled", "autoupdate": False,
              "agent": {"build": {"steps": steps}},
              "provider": {PROVIDER: {"npm": "@ai-sdk/openai-compatible", "name": "Local development",
                  "options": {"baseURL": base_url}, "models": {model: {"name": model, "tool_call": True,
                      "limit": {"context": context, "output": output_tokens}}}}}}
    return {"subllm.toml": "\n".join(lines), "opencode.json": json.dumps(config, indent=2) + "\n"}


def write_profiles(directory: Path, **options) -> dict[str, str]:
    """Create a new opt-in directory; existing profiles are never overwritten."""
    profiles = render_profiles(**options)
    directory = directory.expanduser().absolute()
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(mode=0o700)
    for name, content in profiles.items():
        path = directory / name
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    return {"SUBLLM_POLICY_FILE": str(directory / "subllm.toml"),
            "OPENCODE_CONFIG": str(directory / "opencode.json")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--route", action="append")
    parser.add_argument("--context", type=int, default=16384)
    parser.add_argument("--output-tokens", type=int, default=2048)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--steps", type=int, default=12)
    args = parser.parse_args(argv)
    try:
        environment = write_profiles(args.output_dir, base_url=args.base_url, model=args.model,
            routes=tuple(args.route) if args.route else DEFAULT_ROUTES, context=args.context,
            output_tokens=args.output_tokens, timeout_seconds=args.timeout_seconds, steps=args.steps)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(environment, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
