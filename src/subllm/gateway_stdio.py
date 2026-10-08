"""Connect a stdio-only MCP client to the central SubLLM HTTP proxy."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse

import anyio
import httpx
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.stdio import stdio_server


class _StdinLines:
    """UTF-8 lines from a cancelable Unix pipe, without a blocking worker."""

    def __init__(self, reader):
        self.reader = reader

    def __aiter__(self):
        return self

    async def __anext__(self):
        line = await self.reader.readline()
        if not line:
            raise StopAsyncIteration
        return line.decode("utf-8", errors="replace")


@contextlib.asynccontextmanager
async def _local_stdio():
    if os.name != "posix":
        async with stdio_server() as streams:
            yield streams
        return

    # MCP messages can exceed StreamReader's default 64 KiB line limit.
    reader = asyncio.StreamReader(limit=2**31)
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)
    try:
        async with stdio_server(stdin=_StdinLines(reader)) as (local_read, local_write):
            try:
                yield local_read, local_write
            finally:
                reader.feed_eof()
                await local_write.aclose()
    finally:
        transport.close()


def _failure_code(error):
    """Classify errors without serializing untrusted exceptions or paths."""
    if isinstance(error, BaseExceptionGroup):
        return _failure_code(error.exceptions[0])
    if isinstance(error, httpx.HTTPStatusError):
        return "upstream_rejected"
    if isinstance(error, httpx.TransportError):
        return "upstream_unavailable"
    return "bridge_failed"


async def bridge(url, token_file, ca_file=None):
    if token_file.is_symlink() or token_file.stat().st_mode & 0o077:
        raise ValueError("Token file must be private and not a symbolic link")
    credential = token_file.read_text().strip()
    if len(credential) < 32:
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
        _local_stdio() as (local_read, local_write),
        streamablehttp_client(url, headers={"Authorization": "Bearer " + credential}, httpx_client_factory=factory) as (
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
    # The SDK may log validation exceptions containing a private response body.
    # This CLI boundary emits only closed categories, including nested failures.
    logging.getLogger("mcp.client.streamable_http").setLevel(logging.CRITICAL)
    with contextlib.suppress(KeyboardInterrupt):
        try:
            asyncio.run(bridge(args.url, args.token_file, args.ca_file))
        except Exception as error:
            print("MCP transport failed: " + _failure_code(error), file=sys.stderr)
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
