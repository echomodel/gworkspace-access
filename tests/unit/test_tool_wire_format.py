"""What MCP clients actually receive from tools that return content blocks.

A tool whose return annotation includes ``ContentBlock`` makes the MCP
library generate an output schema and a ``structuredContent`` copy of the
result, serialized without dropping ``None`` fields. Strict clients (e.g.
claude.ai connectors) reject the whole result over the resulting
``"_meta": null``. These tests pin the wire format through the same HTTP
stack mcp-app builds (stateless, JSON responses).
"""

from __future__ import annotations

import json
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP
from mcp_app.app import _discover_tools
from mcp_app.context import current_user
from mcp_app.models import UserRecord
from starlette.testclient import TestClient

from gwsa import GoogleAccount, Profile, app
from gwsa.mcp.tools.drive import drive_download


def _contains_null_meta(obj) -> bool:
    if isinstance(obj, dict):
        if "_meta" in obj and obj["_meta"] is None:
            return True
        return any(_contains_null_meta(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_null_meta(v) for v in obj)
    return False


def test_no_tool_declares_content_blocks_as_structured_output():
    """Every tool, both transports: no output schema built from content blocks."""
    for transport in ("http", "stdio"):
        mcp = FastMCP("probe")
        for func in _discover_tools(app._discovered_modules, transport):
            mcp.tool()(func)
        for tool in mcp._tool_manager.list_tools():
            schema = json.dumps(tool.output_schema or {})
            for block in ("EmbeddedResource", "TextContent", "ImageContent",
                          "ResourceLink", "BlobResourceContents"):
                assert block not in schema, (transport, tool.name, block)


def test_drive_download_over_http_has_no_null_fields_or_structured_copy():
    profile = Profile(accounts=[GoogleAccount(
        name="p", email="a@example.com",
        token={"client_id": "c", "client_secret": "s", "refresh_token": "r",
               "token_uri": "https://oauth2.googleapis.com/token"})])
    tok = current_user.set(UserRecord(email="a@example.com",
                                      profile=profile.model_dump(mode="json")))
    try:
        mcp = FastMCP("t", stateless_http=True, json_response=True,
                      streamable_http_path="/")
        mcp.settings.transport_security.enable_dns_rebinding_protection = False
        mcp.tool()(drive_download)
        meta = {"name": "settings.yaml", "mime_type": "application/octet-stream", "size": "9"}
        fetched = {"data": b"retries: 3", "name": "settings.yaml",
                   "mime_type": "application/octet-stream", "size_bytes": 9}
        with patch("gwsa.sdk.drive.get_download_metadata", return_value=meta), \
                patch("gwsa.sdk.drive.download_bytes", return_value=fetched), \
                TestClient(mcp.streamable_http_app()) as client:
            resp = client.post(
                "/", headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "drive_download",
                                 "arguments": {"file_id": "f1"}}})
        result = resp.json()["result"]
        assert "structuredContent" not in result
        assert not _contains_null_meta(result)
        assert result["content"][1]["resource"]["text"] == "retries: 3"
    finally:
        current_user.reset(tok)
