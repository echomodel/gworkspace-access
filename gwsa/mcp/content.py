"""MCP content-block helpers for byte-producing tools.

The SDK is transport-agnostic: byte-producing helpers in
:mod:`gwsa.sdk.destinations` return either :class:`InlinePayload`
(bytes still in hand) or :class:`DriveUpload` (bytes already in
Drive). The MCP layer is responsible for translating the inline case
into MCP content blocks — that translation lives here so every
byte-producing MCP tool uses the same shape.

Reference: MCP spec content blocks
(https://modelcontextprotocol.io/specification/2025-06-18/server/resources).
"""

from __future__ import annotations

import base64
import json
from typing import Sequence
from uuid import uuid4

from mcp.types import (
    BlobResourceContents,
    ContentBlock,
    EmbeddedResource,
    TextContent,
    TextResourceContents,
)

from gwsa.sdk.destinations import DriveUpload, InlinePayload


def inline_payload_to_blocks(payload: InlinePayload) -> list[ContentBlock]:
    """Render an :class:`InlinePayload` as MCP content blocks.

    Returns ``[TextContent, EmbeddedResource]``:

    - ``TextContent`` carries a JSON summary so clients that don't
      render ``EmbeddedResource`` (notably Claude Desktop's text-only
      surfaces) still receive usable metadata.
    - ``EmbeddedResource`` carries the content: as **text**
      (``TextResourceContents``) when it is a text-like type that decodes
      as UTF-8 (YAML, Markdown, CSV, JSON, …), so any client can read it
      directly; otherwise as **base64** (``BlobResourceContents``).

    The synthetic URI uses a randomly-generated suffix so the resource
    is unique per tool call — clients that key off URI for caching
    won't conflate two different attachments with the same name.
    """
    text = payload.as_text()
    summary = TextContent(
        type="text",
        text=json.dumps(
            {
                "destination": "inline",
                "name": payload.name,
                "mime_type": text[1] if text else payload.mime_type,
                "size_bytes": payload.size_bytes,
                "encoding": "text" if text else "base64",
            },
            indent=2,
        ),
    )

    uri = f"gwsa-inline://{uuid4()}/{payload.name}"
    if text:
        contents = TextResourceContents(uri=uri, mimeType=text[1], text=text[0])
    else:
        contents = BlobResourceContents(
            uri=uri,
            mimeType=payload.mime_type,
            blob=base64.b64encode(payload.data).decode("ascii"),
        )
    embedded = EmbeddedResource(type="resource", resource=contents)

    return [summary, embedded]


def drive_upload_to_dict(result: DriveUpload) -> dict:
    """Render a :class:`DriveUpload` as a tool-response dict.

    Plain JSON: the agent should be able to introspect Drive file id
    and URL without parsing content blocks. FastMCP will serialize the
    dict into a single ``TextContent`` block.
    """
    return {
        "destination": "drive",
        "drive_file_id": result.drive_file_id,
        "drive_url": result.drive_url,
        "name": result.name,
        "mime_type": result.mime_type,
        "size_bytes": result.size_bytes,
        "folder_id": result.folder_id,
    }


__all__ = [
    "inline_payload_to_blocks",
    "drive_upload_to_dict",
    "ContentBlock",
    "Sequence",
]
