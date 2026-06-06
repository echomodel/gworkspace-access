"""Inline base64 decoding for byte-consuming tools.

Drive upload/update accept content one of two ways (see
``gwsa/mcp/tools/drive.py``): a **local path** the server can read
directly (stdio), or **inline base64** carried in the tool call. This
module owns the inline path — decode the base64, enforce a size cap
(tool-call arguments have a practical ceiling across MCP clients), and
guess a MIME type. Larger files don't go inline at all: they use a local
path (stdio) or a direct-to-Google resumable upload session URL (HTTP).
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
from typing import Optional

# Inline base64 is ~4/3 the size of the raw bytes it encodes, and the
# whole MCP request must fit through the transport. This cap is on the
# RAW decoded byte count, sized to keep a base64 request body well under
# the ~1MB practical ceiling observed for tool-call arguments across MCP
# clients (a ~900KB file became ~1.2MB base64 and was rejected in live
# testing).
DEFAULT_INLINE_SOURCE_CAP_BYTES = 700_000
"""Default ceiling for inline upload payloads, on **raw** bytes.

Base64 expands raw bytes by 4/3, so 700,000 raw → ~933,000 encoded,
which fits under the ~1MB tool-call argument ceiling seen across MCP
clients with headroom for the surrounding JSON envelope. Override per
call via ``max_size_bytes`` when the client is known to allow larger
request bodies.
"""


class InlineSourceTooLargeError(ValueError):
    """Inline upload payload exceeded the size cap.

    Surfaced to MCP callers as a structured error envelope suggesting a
    local path (stdio) or the resumable upload session URL (HTTP) for
    larger files.
    """

    def __init__(self, size_bytes: int, cap_bytes: int, name: str):
        self.size_bytes = size_bytes
        self.cap_bytes = cap_bytes
        self.name = name
        super().__init__(
            f"Inline upload too large: {name!r} decodes to {size_bytes} "
            f"bytes, cap is {cap_bytes} bytes. Pass local_path instead — on "
            f"a local server it uploads directly, on a remote server you get "
            f"a direct-to-Google upload URL."
        )


class InvalidInlineSourceError(ValueError):
    """The inline base64 payload could not be decoded."""


def decode_inline_upload(
    data_base64: str,
    name: Optional[str] = None,
    mime_type: Optional[str] = None,
    max_size_bytes: Optional[int] = None,
) -> tuple[bytes, Optional[str], str]:
    """Decode an inline base64 upload payload to ``(data, name, mime_type)``.

    The small-payload, any-transport path: the bytes travel in-band in the
    tool call. Subject to the inline size cap; larger files use a local
    path (stdio) or the out-of-band resumable session URL (HTTP).

    Raises:
        InvalidInlineSourceError: ``data_base64`` is not valid base64.
        InlineSourceTooLargeError: the decoded payload exceeds the cap.
    """
    try:
        data = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise InvalidInlineSourceError(f"data_base64 is not valid base64: {e}") from e

    cap = max_size_bytes or DEFAULT_INLINE_SOURCE_CAP_BYTES
    if len(data) > cap:
        raise InlineSourceTooLargeError(
            size_bytes=len(data), cap_bytes=cap, name=name or "inline-upload"
        )
    if not mime_type:
        guessed, _ = mimetypes.guess_type(name) if name else (None, None)
        mime_type = guessed or "application/octet-stream"
    return data, name, mime_type
