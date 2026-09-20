from __future__ import annotations

import argparse
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="subllm", description="Inspect the central Subactor LLM policy.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="validate the effective policy")
    subparsers.add_parser("list", help="list application/function routes")
    contract = subparsers.add_parser("contract", help="export a versioned exact routing profile")
    contract.add_argument("application")
    contract.add_argument("function")
    subparsers.add_parser("providers", help="show enabled state, priority and default model")
    subparsers.add_parser("applications", help="show application IDs, names and attribution URLs")
    env_parser = subparsers.add_parser("env", help="inspect or initialize the shared local credential file")
    env_subparsers = env_parser.add_subparsers(dest="env_command", required=True)
    env_subparsers.add_parser("path", help="print the detected credential file path")
    env_subparsers.add_parser("check", help="validate the file and print configured variable names")
    import_parser = env_subparsers.add_parser("import", help="import credentials from existing .env files")
    import_parser.add_argument("sources", nargs="+", type=Path)
    import_parser.add_argument("--target", type=Path, default=Path(".env"))
    for name, text in (
        ("list", "show every credential variable: set, empty, invalid or absent (never a value)"),
        ("set", "store or replace one key, checked with the provider first"),
        ("unset", "clear one key (the line stays, the value is emptied)"),
        ("verify", "ask each provider whether its stored key is accepted"),
        ("order", "show or change the provider queue (SUBLLM_PROVIDER_ORDER)"),
    ):
        sub = env_subparsers.add_parser(name, help=text)
        sub.add_argument("--file", type=Path, default=None, help="credential file (default: detected)")
        if name in {"set", "unset"}:
            sub.add_argument("name", help="provider id (agy) or variable (GEMINI_API_KEY)")
        if name == "verify":
            sub.add_argument("names", nargs="*", help="providers or variables; default: every stored key")
        if name == "set":
            source = sub.add_mutually_exclusive_group()
            source.add_argument("--from-file", type=Path, help="read the key from this file (first token)")
            source.add_argument("--stdin", action="store_true", help="read the key from standard input")
            sub.add_argument("--no-verify", action="store_true", help="store without asking the provider")
        if name == "order":
            choice = sub.add_mutually_exclusive_group()
            choice.add_argument("--set", dest="order", help="comma-separated provider ids, or empty to clear")
            choice.add_argument("--preset", help="balanced, high-performance, api-only, cheap or free")
    env_subparsers.add_parser("template", help="print an annotated .env with every provider and queue presets")
    resolve_parser = subparsers.add_parser("resolve", help="resolve one application/function route")
    resolve_parser.add_argument("application")
    resolve_parser.add_argument("function")
    resolve_parser.add_argument("--provider")
    resolve_parser.add_argument(
        "--configured",
        action="store_true",
        help="inspect policy without requiring a credential",
    )
    resolve_parser.add_argument(
        "--field",
        choices=(
            "application-name",
            "application-url",
            "provider",
            "model",
            "priority",
            "api-base",
            "api-key-env",
            "litellm-model",
            "wire-model",
        ),
    )
    poa = subparsers.add_parser("poa", help="POA inspect, plan, query and command surface")
    poa_sub = poa.add_subparsers(dest="poa_command", required=True)
    inspect = poa_sub.add_parser("inspect", help="inspect a declared process")
    inspect.add_argument("process_ref")
    plan = poa_sub.add_parser("plan", help="create a secret-free dry plan")
    plan.add_argument("process_ref")
    plan.add_argument("--application")
    plan.add_argument("--function")
    plan.add_argument("--provider")
    plan.add_argument("--subject", default="service:subllm-cli")
    plan.add_argument("--idempotency-key")
    query = poa_sub.add_parser("query", help="run a registered query URI")
    query.add_argument("process_uri")
    query.add_argument("--application")
    query.add_argument("--function")
    query.add_argument("--provider")
    query.add_argument("--run-id")
    command = poa_sub.add_parser("command", help="run a registered command URI")
    command.add_argument("process_uri")
    command.add_argument("--process-ref")
    command.add_argument("--application")
    command.add_argument("--function")
    command.add_argument("--provider")
    command.add_argument("--subject", default="service:subllm-cli")
    command.add_argument("--idempotency-key")
    command.add_argument("--source", action="append", dest="sources")
    command.add_argument("--target")
    poa_sub.add_parser("catalog", help="print the adopted process catalog")
    serve_parser = subparsers.add_parser("serve", help="serve the local POA CQRS HTTP API")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8788)
    subparsers.add_parser("mcp", help="read-only usage MCP over stdio")
    for name in ("ask", "dsl"):
        usage_parser = subparsers.add_parser(name, help="query API usage through the shared DSL")
        usage_parser.add_argument("text")
    proxy_parser = subparsers.add_parser("proxy", help="serve the Ollama and OpenAI-compatible proxy server")
    proxy_parser.add_argument("--host", default="127.0.0.1")
    proxy_parser.add_argument("--port", type=int, default=11435)
    proxy_parser.add_argument("--ollama-upstream", default="http://127.0.0.1:11434")
    return parser
