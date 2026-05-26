"""Tests for the shared destination model in ``gwsa.sdk.destinations``.

The destination layer is the home of the "control plane carries
references, data plane is out-of-band" rule. These tests cover the
discriminated-union plumbing, the inline size cap, and the Drive
upload delegation — everything downstream tools (mail attachments,
Drive download) inherit from it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from gwsa.sdk.destinations import (
    DEFAULT_INLINE_SIZE_CAP_BYTES,
    Destination,
    DriveDestination,
    DriveUpload,
    InlineDestination,
    InlinePayload,
    InlineTooLargeError,
    materialize,
)


def test_inline_default_returns_payload_under_cap():
    payload = materialize(
        b"hello world",
        name="hello.txt",
        mime_type="text/plain",
        destination=InlineDestination(),
    )
    assert isinstance(payload, InlinePayload)
    assert payload.name == "hello.txt"
    assert payload.mime_type == "text/plain"
    assert payload.size_bytes == len(b"hello world")
    assert payload.data == b"hello world"


def test_inline_uses_default_cap_when_unspecified():
    """The default cap is 100KB; right at the boundary should pass."""
    data = b"x" * DEFAULT_INLINE_SIZE_CAP_BYTES
    payload = materialize(
        data,
        name="big.bin",
        mime_type="application/octet-stream",
        destination=InlineDestination(),
    )
    assert payload.size_bytes == DEFAULT_INLINE_SIZE_CAP_BYTES


def test_inline_exceeds_default_cap_raises():
    data = b"x" * (DEFAULT_INLINE_SIZE_CAP_BYTES + 1)
    with pytest.raises(InlineTooLargeError) as exc_info:
        materialize(
            data,
            name="huge.bin",
            mime_type="application/octet-stream",
            destination=InlineDestination(),
        )
    assert exc_info.value.size_bytes == DEFAULT_INLINE_SIZE_CAP_BYTES + 1
    assert exc_info.value.cap_bytes == DEFAULT_INLINE_SIZE_CAP_BYTES
    assert "huge.bin" in str(exc_info.value)


def test_inline_respects_caller_override_cap():
    """Lower the cap below the data size to force a rejection even on
    small payloads."""
    with pytest.raises(InlineTooLargeError) as exc_info:
        materialize(
            b"hello",
            name="x.txt",
            mime_type="text/plain",
            destination=InlineDestination(max_size_bytes=2),
        )
    assert exc_info.value.cap_bytes == 2


def test_drive_destination_delegates_to_upload_bytes():
    """The drive kind calls ``gwsa.sdk.drive.upload_bytes`` with the
    right arguments and wraps the result in a typed DriveUpload."""
    fake_upload = {
        "id": "drive-file-id-abc",
        "name": "report.pdf",
        "url": "https://drive.google.com/file/d/drive-file-id-abc/view",
    }
    with patch(
        "gwsa.sdk.drive.upload_bytes", return_value=fake_upload
    ) as upload_patch:
        result = materialize(
            b"PDF-CONTENT",
            name="report.pdf",
            mime_type="application/pdf",
            destination=DriveDestination(folder_id="folder-xyz"),
            account="work",
        )

    upload_patch.assert_called_once_with(
        data=b"PDF-CONTENT",
        name="report.pdf",
        mime_type="application/pdf",
        folder_id="folder-xyz",
        account="work",
    )
    assert isinstance(result, DriveUpload)
    assert result.drive_file_id == "drive-file-id-abc"
    assert result.drive_url == fake_upload["url"]
    assert result.name == "report.pdf"
    assert result.folder_id == "folder-xyz"
    assert result.size_bytes == len(b"PDF-CONTENT")


def test_drive_destination_default_folder_is_root():
    """No folder_id means My Drive root; passed through as None."""
    fake_upload = {
        "id": "f1",
        "name": "x.bin",
        "url": "https://drive.google.com/file/d/f1/view",
    }
    with patch(
        "gwsa.sdk.drive.upload_bytes", return_value=fake_upload
    ) as upload_patch:
        result = materialize(
            b"data",
            name="x.bin",
            mime_type="application/octet-stream",
            destination=DriveDestination(),
        )
    upload_patch.assert_called_once()
    assert upload_patch.call_args.kwargs["folder_id"] is None
    assert result.folder_id is None


def test_drive_destination_name_override():
    """A custom ``name`` on the destination overrides the source name."""
    fake_upload = {
        "id": "f1",
        "name": "renamed.pdf",
        "url": "https://drive.google.com/file/d/f1/view",
    }
    with patch(
        "gwsa.sdk.drive.upload_bytes", return_value=fake_upload
    ) as upload_patch:
        materialize(
            b"content",
            name="original.pdf",
            mime_type="application/pdf",
            destination=DriveDestination(name="renamed.pdf"),
        )
    upload_patch.assert_called_once()
    assert upload_patch.call_args.kwargs["name"] == "renamed.pdf"


def test_destination_union_parses_inline_from_dict():
    """A dict ``{"kind": "inline"}`` round-trips through the
    discriminated union — this is how MCP clients pass it."""
    from pydantic import TypeAdapter

    adapter = TypeAdapter(Destination)
    parsed = adapter.validate_python({"kind": "inline", "max_size_bytes": 50})
    assert isinstance(parsed, InlineDestination)
    assert parsed.max_size_bytes == 50


def test_destination_union_parses_drive_from_dict():
    from pydantic import TypeAdapter

    adapter = TypeAdapter(Destination)
    parsed = adapter.validate_python(
        {"kind": "drive", "folder_id": "folder-abc"}
    )
    assert isinstance(parsed, DriveDestination)
    assert parsed.folder_id == "folder-abc"


def test_encoded_response_at_cap_fits_inside_claude_code_budget():
    """A payload at exactly the inline cap, once rendered as
    ``[TextContent, EmbeddedResource]`` and JSON-serialized, must fit
    comfortably inside Claude Code's empirical ~100KB tool-response
    truncation ceiling.

    The v0.12.0 default (100,000 raw bytes) produced ~105KB responses
    that the client truncated and fell back to file-on-disk delivery.
    v0.12.1 lowered the default to 60,000 raw bytes specifically to
    keep encoded responses well under the ceiling. This test pins the
    math so a future bump to the cap can't silently re-introduce the
    bug.

    Empirical truncation threshold observed in live testing: 105,246
    characters. Headroom target: 15KB. Therefore: encoded response at
    the cap must be < 90,000 characters.
    """
    import json

    from mcp.types import EmbeddedResource, TextContent

    from gwsa.mcp.content import inline_payload_to_blocks

    # Worst-case mime: long string adds to envelope. application/pdf
    # is realistic and lands in the middle.
    payload = InlinePayload(
        name="cap-boundary-test.bin",
        mime_type="application/octet-stream",
        size_bytes=DEFAULT_INLINE_SIZE_CAP_BYTES,
        data=b"x" * DEFAULT_INLINE_SIZE_CAP_BYTES,
    )
    blocks = inline_payload_to_blocks(payload)
    assert len(blocks) == 2
    summary, embedded = blocks
    assert isinstance(summary, TextContent)
    assert isinstance(embedded, EmbeddedResource)

    # MCP serializes the result as a JSON array of content blocks.
    # Pydantic's model_dump_json is what the transport eventually uses.
    serialized = json.dumps(
        [summary.model_dump(mode="json"), embedded.model_dump(mode="json")]
    )
    EMPIRICAL_TRUNCATION_THRESHOLD = 105_246
    HEADROOM = 15_000
    safe_ceiling = EMPIRICAL_TRUNCATION_THRESHOLD - HEADROOM
    assert len(serialized) < safe_ceiling, (
        f"Encoded inline response at the cap ({len(serialized)} chars) "
        f"is within {EMPIRICAL_TRUNCATION_THRESHOLD - len(serialized)} "
        f"chars of Claude Code's truncation ceiling. The cap default "
        f"({DEFAULT_INLINE_SIZE_CAP_BYTES} bytes) must be lowered so "
        f"the encoded response stays below {safe_ceiling} chars."
    )
