"""Reusable destination parameter for tools that produce binary output.

Background: tools that return bytes (email attachments, Drive downloads)
cannot use a ``save_path: str`` parameter and remain correct under HTTP
transport. The agent and the MCP server may not share a filesystem, so
the file the server saves is unreachable from the agent's side.

Design principle: **control plane carries references; data plane is
out-of-band.** The tool response either inlines the bytes (small, agent
consumes immediately) or names a user-owned destination the agent can
reach by other means (Drive file id + URL).

This module defines the shared ``Destination`` parameter shape and the
``materialize()`` helper that any byte-producing SDK function can call
to honor the caller's choice.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

DEFAULT_INLINE_SIZE_CAP_BYTES = 100_000
"""Default ceiling for inline payloads.

Chosen well below Claude Code's ~25K-token tool-response limit (hit
around 80–100KB of base64 EmbeddedResource content). Override per-call
via ``InlineDestination.max_size_bytes`` when the caller knows the
client can handle more.
"""


class InlineDestination(BaseModel):
    """Return the bytes inline in the tool response.

    The MCP layer renders this as an ``EmbeddedResource`` content block
    paired with a ``TextContent`` summary so clients that don't render
    embedded resources still get usable metadata.

    Suitable for small payloads the agent consumes immediately. Larger
    payloads should use :class:`DriveDestination` instead.
    """

    kind: Literal["inline"] = "inline"
    max_size_bytes: Optional[int] = Field(
        default=None,
        description=(
            f"Maximum payload size in bytes. Default "
            f"{DEFAULT_INLINE_SIZE_CAP_BYTES}. Payloads above the cap "
            f"raise InlineTooLargeError — use destination kind 'drive' "
            f"instead for larger files."
        ),
    )


class DriveDestination(BaseModel):
    """Upload the bytes to the caller's Google Drive.

    Uses the same OAuth credentials the rest of gwsa uses for the
    target account. The agent receives a Drive file id and webViewLink
    in the tool response — the bytes themselves stay in Drive, where
    the user already has tools to retrieve, share, or organize them.

    Default folder is My Drive root, so the simplest caller pattern is
    ``DriveDestination()`` with no folder_id. Use :func:`drive_move`
    afterwards to organize the file into a project folder.
    """

    kind: Literal["drive"] = "drive"
    folder_id: Optional[str] = Field(
        default=None,
        description=(
            "Destination Drive folder ID. Omit (or pass None / 'root') "
            "for My Drive root."
        ),
    )
    name: Optional[str] = Field(
        default=None,
        description=(
            "File name to use in Drive. Defaults to the source name "
            "(e.g., the attachment filename)."
        ),
    )


Destination = Annotated[
    Union[InlineDestination, DriveDestination],
    Field(discriminator="kind"),
]


class InlinePayload(BaseModel):
    """Result returned by :func:`materialize` for inline destinations.

    The MCP layer translates this into a ``[TextContent,
    EmbeddedResource]`` pair. SDK callers receive it as a typed object
    so the SDK remains transport-agnostic.
    """

    name: str
    mime_type: str
    size_bytes: int
    data: bytes


class DriveUpload(BaseModel):
    """Result returned by :func:`materialize` for Drive destinations."""

    drive_file_id: str
    drive_url: str
    name: str
    mime_type: str
    size_bytes: int
    folder_id: Optional[str] = None


class InlineTooLargeError(ValueError):
    """Inline destination payload exceeded the size cap.

    Surfaced to MCP callers as a structured error envelope with the
    suggestion to retry with ``destination={"kind": "drive"}``.
    """

    def __init__(self, size_bytes: int, cap_bytes: int, name: str):
        self.size_bytes = size_bytes
        self.cap_bytes = cap_bytes
        self.name = name
        super().__init__(
            f"Inline payload too large: {name!r} is {size_bytes} bytes, "
            f"cap is {cap_bytes} bytes. Retry with destination "
            f'{{"kind": "drive"}} to upload to the user\'s Drive instead, '
            f"or pass a larger max_size_bytes on the inline destination."
        )


def materialize(
    data: bytes,
    *,
    name: str,
    mime_type: str,
    destination: Destination,
    account: Optional[str] = None,
) -> Union[InlinePayload, DriveUpload]:
    """Honor the caller's destination choice for a bytes payload.

    Args:
        data: The raw bytes to deliver.
        name: Source name (used as the inline ``name`` and the default
            Drive filename).
        mime_type: MIME type of the bytes.
        destination: Where the caller wants the bytes to land.
        account: Account selector for the Drive case. Ignored for
            inline.

    Returns:
        :class:`InlinePayload` for the inline kind or :class:`DriveUpload`
        for the drive kind.

    Raises:
        InlineTooLargeError: ``data`` exceeds the inline size cap.
    """
    # Late import: only the drive kind needs the Drive SDK, and the
    # SDK has its own service dependencies we'd rather not pull in
    # for inline-only callers.
    if destination.kind == "inline":
        cap = destination.max_size_bytes or DEFAULT_INLINE_SIZE_CAP_BYTES
        if len(data) > cap:
            raise InlineTooLargeError(
                size_bytes=len(data), cap_bytes=cap, name=name
            )
        return InlinePayload(
            name=name,
            mime_type=mime_type,
            size_bytes=len(data),
            data=data,
        )

    if destination.kind == "drive":
        from gwsa.sdk.drive import upload_bytes

        drive_name = destination.name or name
        result = upload_bytes(
            data=data,
            name=drive_name,
            mime_type=mime_type,
            folder_id=destination.folder_id,
            account=account,
        )
        return DriveUpload(
            drive_file_id=result["id"],
            drive_url=result["url"],
            name=result["name"],
            mime_type=mime_type,
            size_bytes=len(data),
            folder_id=destination.folder_id,
        )

    raise ValueError(f"Unknown destination kind: {destination.kind!r}")
