"""Reusable source parameter for tools that consume binary input.

Background: tools that accept bytes (Drive upload, Drive update) cannot
use a ``local_path: str`` parameter and remain correct under HTTP
transport. The agent and the MCP server may not share a filesystem, so
a path the agent names is unreachable from the server's side — the
server's ``open(path)`` fails with ``FileNotFoundError`` even though the
file exists on the agent's machine.

This is the exact mirror of the problem ``destinations.py`` solves for
byte-*producing* tools. Design principle is the same: **the data plane
must travel in-band when the filesystem isn't shared.** A source is
either a server-local path (fine for stdio, where agent and server are
the same machine) or inline base64 bytes (works under any transport).

This module defines the shared ``Source`` parameter shape and the
``resolve_source()`` helper that any byte-consuming SDK function can call
to obtain ``(data, name, mime_type)`` regardless of which kind it was
given.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import os
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

# Inline base64 is ~4/3 the size of the raw bytes it encodes, and the
# whole MCP request must fit through the transport. This cap is on the
# RAW decoded byte count, sized to keep a base64 request body well under
# the ~1MB practical ceiling observed for tool-call arguments across MCP
# clients (a ~900KB file became ~1.2MB base64 and was rejected in live
# testing). Larger files should be uploaded by a path the server can
# read (stdio), or staged to Drive by other means first.
DEFAULT_INLINE_SOURCE_CAP_BYTES = 700_000
"""Default ceiling for inline upload payloads, on **raw** bytes.

Base64 expands raw bytes by 4/3, so 700,000 raw → ~933,000 encoded,
which fits under the ~1MB tool-call argument ceiling seen across MCP
clients with headroom for the surrounding JSON envelope. Override per
call via ``InlineSource.max_size_bytes`` when the client is known to
allow larger request bodies.
"""


class LocalPathSource(BaseModel):
    """Read the bytes from a path on the server's filesystem.

    Correct ONLY when the MCP server and the agent share a filesystem —
    i.e. stdio transport, where the server process runs on the same
    machine as the agent. Under HTTP transport the server cannot see the
    agent's files; use :class:`InlineSource` instead.
    """

    kind: Literal["path"] = "path"
    path: str = Field(
        description=(
            "Absolute path to the file on the server's filesystem. Only "
            "usable under stdio transport (server and agent share a "
            "filesystem). For HTTP transport use an inline source."
        )
    )


class InlineSource(BaseModel):
    """Carry the bytes inline as base64 in the tool call.

    Works under any transport because the bytes travel in the request
    body rather than being read from a filesystem the server may not
    share. Subject to a size cap because tool-call arguments have a
    practical ceiling across MCP clients.
    """

    kind: Literal["inline"] = "inline"
    data_base64: str = Field(
        description="The file content, base64-encoded."
    )
    name: Optional[str] = Field(
        default=None,
        description=(
            "File name to use in Drive. Strongly recommended for inline "
            "sources — there is no path to derive a name from."
        ),
    )
    mime_type: Optional[str] = Field(
        default=None,
        description=(
            "MIME type of the content. Defaults to a guess from ``name`` "
            "(or application/octet-stream if neither is available)."
        ),
    )
    max_size_bytes: Optional[int] = Field(
        default=None,
        description=(
            f"Override the raw-byte cap (default "
            f"{DEFAULT_INLINE_SOURCE_CAP_BYTES}). Payloads above the cap "
            f"raise InlineSourceTooLargeError — upload via a server-"
            f"readable path under stdio for larger files."
        ),
    )


Source = Annotated[
    Union[LocalPathSource, InlineSource],
    Field(discriminator="kind"),
]


class InlineSourceTooLargeError(ValueError):
    """Inline source payload exceeded the size cap.

    Surfaced to MCP callers as a structured error envelope suggesting a
    server-readable path (stdio) for larger files.
    """

    def __init__(self, size_bytes: int, cap_bytes: int, name: str):
        self.size_bytes = size_bytes
        self.cap_bytes = cap_bytes
        self.name = name
        super().__init__(
            f"Inline source too large: {name!r} decodes to {size_bytes} "
            f"bytes, cap is {cap_bytes} bytes. Upload via a server-"
            f"readable path (stdio transport), or raise max_size_bytes "
            f"if the client allows larger request bodies."
        )


class InvalidInlineSourceError(ValueError):
    """The inline source's base64 payload could not be decoded."""


def resolve_source(source: Source) -> tuple[bytes, Optional[str], str]:
    """Resolve any :data:`Source` to ``(data, name, mime_type)``.

    Args:
        source: A :class:`LocalPathSource` or :class:`InlineSource`.

    Returns:
        ``(data, name, mime_type)``. ``name`` may be ``None`` for a path
        source (the caller can fall back to the path basename); it is the
        provided name for an inline source. ``mime_type`` is always a
        non-empty string (guessed when not supplied).

    Raises:
        FileNotFoundError: A path source points at a missing file.
        InlineSourceTooLargeError: An inline payload exceeds the cap.
        InvalidInlineSourceError: An inline payload is not valid base64.
    """
    if source.kind == "path":
        path = source.path
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"No file at {path!r}. Under HTTP transport the server "
                f"cannot read the agent's filesystem — use an inline "
                f"source instead."
            )
        with open(path, "rb") as fh:
            data = fh.read()
        name = os.path.basename(path)
        mime_type, _ = mimetypes.guess_type(path)
        return data, name, mime_type or "application/octet-stream"

    # inline
    try:
        data = base64.b64decode(source.data_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise InvalidInlineSourceError(
            f"data_base64 is not valid base64: {e}"
        ) from e

    cap = source.max_size_bytes or DEFAULT_INLINE_SOURCE_CAP_BYTES
    if len(data) > cap:
        raise InlineSourceTooLargeError(
            size_bytes=len(data),
            cap_bytes=cap,
            name=source.name or "inline-upload",
        )

    name = source.name
    mime_type = source.mime_type
    if not mime_type:
        guessed, _ = mimetypes.guess_type(name) if name else (None, None)
        mime_type = guessed or "application/octet-stream"
    return data, name, mime_type
