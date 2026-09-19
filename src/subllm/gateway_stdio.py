"""Connect a stdio-only MCP client to the central SubLLM HTTP proxy."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ssl
from pathlib import Path
from urllib.parse import urlparse

import anyio
import httpx
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.stdio import stdio_server


async def bridge(url, token_file, ca_file=None):
    if token_file.is_symlink() or token_file.stat().st_mode & 0o077:
        raise ValueError("Token file must be private and not a symbolic link")
    token = token_file.read_text().strip()
    if len(token) < 32:
        raise ValueError("Invalid gateway credential")
    parsed = urlparse(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Credentials and queries are forbidden in the endpoint URL")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
        raise ValueError("Remote gateway requires HTTPS")
    tls = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)

    def factory(**kwargs):
        return httpx.AsyncClient(verify=tls, trust_env=False, **kwargs)

    async def pump(source, destination, group):
        try:
            async for message in source:
                if isinstance(message, Exception):
                    raise RuntimeError("MCP transport failed") from None
                await destination.send(message)
        finally:
            group.cancel_scope.cancel()

    async with (
        stdio_server() as (local_read, local_write),
        streamablehttp_client(url, headers={"Authorization": "Bearer " + token}, httpx_client_factory=factory) as (
            remote_read,
            remote_write,
            _,
        ),
        anyio.create_task_group() as group,
    ):
        group.start_soon(pump, local_read, remote_write, group)
        group.start_soon(pump, remote_read, local_write, group)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--ca-file", type=Path)
    args = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(bridge(args.url, args.token_file, args.ca_file))


if __name__ == "__main__":
    main()
