import errno
import json
import socket
import ssl

import httpx
import pytest

from subllm.gateway_diagnostics import transport_diagnostic


@pytest.mark.parametrize(
    "error,code,transport",
    [
        (
            ConnectionRefusedError(errno.ECONNREFUSED, "private endpoint credential"),
            "SUBLLM-UPSTREAM-TRANSPORT",
            "ECONNREFUSED",
        ),
        (TimeoutError("private timeout context"), "SUBLLM-UPSTREAM-TIMEOUT", "TIMEOUT"),
        (httpx.ReadTimeout("private request URL"), "SUBLLM-UPSTREAM-TIMEOUT", "TIMEOUT"),
        (socket.gaierror(socket.EAI_NONAME, "private hostname"), "SUBLLM-UPSTREAM-TRANSPORT", "DNS_ERROR"),
        (ssl.SSLCertVerificationError("private certificate"), "SUBLLM-UPSTREAM-TRANSPORT", "TLS_CERT_VERIFY_FAILED"),
        (ssl.SSLError("private TLS context"), "SUBLLM-UPSTREAM-TRANSPORT", "TLS_ERROR"),
        (httpx.ConnectError("private connection string"), "SUBLLM-UPSTREAM-TRANSPORT", "CONNECT_ERROR"),
    ],
)
def test_typed_causes_never_copy_exception_messages(error, code, transport):
    result = transport_diagnostic(ExceptionGroup("private group", [error]))
    assert result["code"] == code
    assert result["transportCode"] == transport
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "SUBLLM-UPSTREAM-AUTH"),
        (403, "SUBLLM-UPSTREAM-AUTH"),
        (429, "SUBLLM-UPSTREAM-LIMIT"),
        (503, "SUBLLM-UPSTREAM-TRANSPORT"),
    ],
)
def test_http_status_keeps_only_numeric_evidence(status, code):
    response = httpx.Response(status, request=httpx.Request("GET", "https://private.invalid/secret"))
    result = transport_diagnostic(httpx.HTTPStatusError("private body", request=response.request, response=response))
    assert result["code"] == code and result["httpStatus"] == status
    assert result["root_cause"] == f"Upstream returned HTTP {status}."
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(result)


def test_wrapped_connection_prefers_specific_nested_cause_and_bounds_cycles():
    wrapped = httpx.ConnectError("private URL")
    cause = ConnectionRefusedError(errno.ECONNREFUSED, "private endpoint")
    wrapped.__cause__ = ExceptionGroup("private group", [cause])
    cause.__context__ = wrapped
    result = transport_diagnostic(wrapped)
    assert result["transportCode"] == "ECONNREFUSED"
    unknown = RuntimeError("private credential")
    unknown.__cause__ = unknown
    result = transport_diagnostic(unknown)
    assert result["transportCode"] is None
    assert result["root_cause"] == "See private response; not inferred"
    assert "credential" not in json.dumps(result)


def test_suppressed_transport_context_retains_typed_errno_without_text():
    wrapper = httpx.ConnectError("private outer endpoint")
    wrapper.__context__ = ConnectionRefusedError(errno.ECONNREFUSED, "private inner endpoint")
    wrapper.__suppress_context__ = True
    result = transport_diagnostic(wrapper)
    assert result["transportCode"] == "ECONNREFUSED"
    assert "private" not in json.dumps(result)
