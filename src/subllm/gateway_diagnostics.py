"""Bounded diagnostic vocabulary aligned with wellmanifest/logs 0.5 fields.

Private provider/tool responses remain in the private archive, not this envelope.
Possible causes are explicitly distinguished from observed facts.
"""

CATALOG = {
    "SUBLLM-ARCHIVE-WRITE": (
        "STORAGE",
        "Private archive write failed",
        False,
        "Check database availability, permissions and free space; do not repeat a completed paid or tool call.",
    ),
    "SUBLLM-ARCHIVE-READ": (
        "STORAGE",
        "Private archive read failed",
        True,
        "Check database availability and permissions. Reading the archive is safe to retry.",
    ),
    "SUBLLM-UPSTREAM-AUTH": (
        "AUTHORITY",
        "Upstream rejected credentials",
        False,
        "Check the configured provider or MCP credential and account access.",
    ),
    "SUBLLM-UPSTREAM-LIMIT": (
        "RESOURCE",
        "Upstream rate or quota limit",
        True,
        "Inspect quota and Retry-After; distinguish exhausted credit from a temporary rate limit.",
    ),
    "SUBLLM-UPSTREAM-TIMEOUT": (
        "TRANSPORT",
        "Upstream did not finish before the deadline",
        True,
        "Inspect server load and timeout. Check side effects before retrying a tool.",
    ),
    "SUBLLM-UPSTREAM-TRANSPORT": (
        "TRANSPORT",
        "Upstream connection failed",
        True,
        "Check endpoint, DNS, TLS and whether the configured server is running.",
    ),
    "SUBLLM-MCP-PROTOCOL": (
        "CONTRACT",
        "MCP server returned a JSON-RPC error",
        False,
        "Inspect the RPC code and validate method, arguments and negotiated capabilities.",
    ),
    "SUBLLM-MCP-TOOL": (
        "RUNTIME",
        "MCP tool returned isError=true",
        False,
        "Read the tool response and its runbook. Transport success does not imply tool success.",
    ),
    "SUBLLM-LLM-EXECUTION": (
        "DEPENDENCY",
        "LLM execution failed",
        False,
        "Inspect the provider attempt code and configured route; the root cause may still be unknown.",
    ),
    "SUBLLM-MCP-INTERRUPTED": (
        "RUNTIME",
        "MCP session ended before the response",
        False,
        "Inspect process exit or client cancellation; verify side effects before retrying.",
    ),
}


def diagnostic(code, *, duration_ms=0, http_status=None, transport_code=None):
    category, meaning, retryable, action = CATALOG[code]
    return {
        "code": code,
        "severity": "ERROR",
        "category": category,
        "meaning": meaning,
        "cause_certainty": "observed_failure_class",
        "root_cause": "See private response; not inferred",
        "remediation": action,
        "phase": "upstream",
        "status": "failed",
        "retryable": retryable,
        "attempt": 1,
        "attempts": 1,
        "durationMs": max(0, int(duration_ms)),
        "endpointRef": None,
        "transportCode": transport_code,
        "httpStatus": http_status,
        "remediationRefs": [f"error://subactor.subllm/{code}/v1"],
        "traceId": None,
        "spanId": None,
    }


def rpc_diagnostic(message):
    if "error" in message:
        return diagnostic("SUBLLM-MCP-PROTOCOL")
    result = message.get("result")
    if isinstance(result, dict) and result.get("isError") is True:
        return diagnostic("SUBLLM-MCP-TOOL")
    return None


def transport_diagnostic(error):
    """Classify typed evidence only; exception messages and URLs may contain secrets."""
    import errno
    import socket
    import ssl

    import httpx

    queue, seen, errors = [error], set(), []
    while queue and len(errors) < 64:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        errors.append(current)
        if isinstance(current, BaseExceptionGroup):
            queue.extend(current.exceptions[:64])
        cause = current.__cause__
        if cause is None:
            # HTTP transports may suppress traceback context while retaining typed errno evidence.
            cause = current.__context__
        if cause is not None:
            queue.append(cause)

    def observed(code, transport, fact, status=None):
        info = diagnostic(code, transport_code=transport, http_status=status)
        info["root_cause"] = fact
        return info

    for current in errors:
        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code
            if 100 <= status <= 599:
                code = (
                    "SUBLLM-UPSTREAM-AUTH" if status in {401, 403}
                    else "SUBLLM-UPSTREAM-LIMIT" if status == 429
                    else "SUBLLM-UPSTREAM-TRANSPORT"
                )
                return observed(code, "HTTP_ERROR", f"Upstream returned HTTP {status}.", status)
        if isinstance(current, ssl.SSLCertVerificationError):
            return observed(
                "SUBLLM-UPSTREAM-TRANSPORT", "TLS_CERT_VERIFY_FAILED", "TLS certificate verification failed."
            )
        if isinstance(current, socket.gaierror):
            return observed("SUBLLM-UPSTREAM-TRANSPORT", "DNS_ERROR", "Address resolution failed.")
        if isinstance(current, OSError) and current.errno == errno.ECONNREFUSED:
            return observed("SUBLLM-UPSTREAM-TRANSPORT", "ECONNREFUSED", "Connection refused by the upstream endpoint.")
        if isinstance(current, (TimeoutError, httpx.TimeoutException)):
            return observed("SUBLLM-UPSTREAM-TIMEOUT", "TIMEOUT", "Upstream transport or session deadline expired.")
    for current in errors:
        if isinstance(current, ssl.SSLError):
            return observed("SUBLLM-UPSTREAM-TRANSPORT", "TLS_ERROR", "TLS negotiation failed.")
        if isinstance(current, httpx.ConnectError):
            return observed(
                "SUBLLM-UPSTREAM-TRANSPORT", "CONNECT_ERROR", "Upstream connection could not be established."
            )
    return diagnostic("SUBLLM-UPSTREAM-TRANSPORT")
