"""Optional official-SDK contract smoke tests.

These tests are skipped when the official MCP SDK is not installed. They are
separate from `test_mcp_wire.py`, which intentionally exercises the
SDK-independent compatibility harness.
"""
from __future__ import annotations

import importlib.util
import json

import pytest

mcp_available = importlib.util.find_spec("mcp") is not None
pytestmark = pytest.mark.skipif(not mcp_available, reason="official MCP SDK not installed")


def test_official_fastmcp_server_metadata_and_tool_count():
    import shift_relay.mcp_server as server

    assert server.SERVER_VERSION == "0.4.0"
    assert server.mcp._mcp_server.version == "0.4.0"
    tools = server.mcp._tool_manager.list_tools()
    assert len(tools) == 11
    assert "report_exception" in {t.name for t in tools}


def test_official_result_normalizer_accepts_content_text_shape():
    # The official v1 FastMCP server may serialize a dict tool result into
    # content[0].text instead of structuredContent. Our proof client must accept
    # the real envelope rather than requiring the compatibility-harness shape.
    from scripts.official_mcp_e2e import normalize

    class Text:
        text = json.dumps({"status": "verified"})

    class Result:
        structuredContent = None
        isError = False
        content = [Text()]

    out = normalize(Result())
    assert out["structured"] == {"status": "verified"}
    assert out["is_error"] is False
