"""Export formats for native Google files — the one mapping in the SDK.

A *native* Google file (Docs, Sheets, Slides, Drawings, Apps Script; any
``mimeType`` under ``application/vnd.google-apps.``) has no stored bytes.
Drive refuses ``files.get?alt=media`` on it with HTTP 403
``fileNotDownloadable``; its content is reachable only by **exporting** it
to a concrete format (``files.export``, or an authorized GET of one of the
file's or revision's ``exportLinks``). Uploaded (non-native) files are the
reverse: they are downloaded as stored and cannot be exported.

This module maps a short format name (``xlsx``, ``docx``, ``md``, …) to the
export MIME type Drive accepts, per native file type. Everything that
exports — :mod:`gwsa.sdk.drive.export`, the Docs Markdown/text reads in
:mod:`gwsa.sdk.docs.read`, and revision export through ``exportLinks`` —
resolves formats here, so the names an agent or a CLI user types mean the
same thing everywhere.

The format names double as the file extension of the export.

Content caveats by type (the full notes are on :func:`gwsa.sdk.drive.export.export_file`):

- **Sheets**: only ``xlsx`` and ``ods`` carry every tab. ``csv`` and
  ``tsv`` export the **first tab only** and drop cell hyperlinks.
- **Slides**: ``txt`` is the slides' text only.
- **Drawings**: image formats render the whole drawing.
"""

from __future__ import annotations

from typing import Mapping, Optional

NATIVE_MIME_PREFIX = "application/vnd.google-apps."

DOCUMENT = "application/vnd.google-apps.document"
SPREADSHEET = "application/vnd.google-apps.spreadsheet"
PRESENTATION = "application/vnd.google-apps.presentation"
DRAWING = "application/vnd.google-apps.drawing"
SCRIPT = "application/vnd.google-apps.script"

#: Format name → export MIME type, per native file type. Mirrors the
#: ``exportFormats`` Drive's ``about.get`` reports, under the extension-like
#: names users type. Order is the order formats are listed in errors.
EXPORT_FORMATS: dict[str, dict[str, str]] = {
    DOCUMENT: {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "odt": "application/vnd.oasis.opendocument.text",
        "pdf": "application/pdf",
        "md": "text/markdown",
        "txt": "text/plain",
        "html": "text/html",
        "rtf": "application/rtf",
        "epub": "application/epub+zip",
        "zip": "application/zip",  # HTML plus images, zipped
    },
    SPREADSHEET: {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "ods": "application/vnd.oasis.opendocument.spreadsheet",
        "csv": "text/csv",  # first tab only
        "tsv": "text/tab-separated-values",  # first tab only
        "pdf": "application/pdf",
        "zip": "application/zip",  # one HTML page per tab, zipped
    },
    PRESENTATION: {
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "odp": "application/vnd.oasis.opendocument.presentation",
        "pdf": "application/pdf",
        "txt": "text/plain",
    },
    DRAWING: {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "svg": "image/svg+xml",
    },
    SCRIPT: {
        "json": "application/vnd.google-apps.script+json",
    },
}

#: Other names accepted for a format. Resolved before lookup.
FORMAT_ALIASES: dict[str, str] = {
    "markdown": "md",
    "text": "txt",
    "jpeg": "jpg",
}

_TYPE_LABELS = {
    DOCUMENT: "Google Doc",
    SPREADSHEET: "Google Sheet",
    PRESENTATION: "Google Slides file",
    DRAWING: "Google Drawing",
    SCRIPT: "Apps Script project",
    "application/vnd.google-apps.folder": "Drive folder",
    "application/vnd.google-apps.shortcut": "Drive shortcut",
    "application/vnd.google-apps.form": "Google Form",
    "application/vnd.google-apps.site": "Google Site",
}


_SHORT_LABELS = {
    SPREADSHEET: "Sheets",
    DOCUMENT: "Docs",
    PRESENTATION: "Slides",
    DRAWING: "Drawings",
    SCRIPT: "Apps Script",
}


def formats_summary() -> str:
    """Every format, by file type, on one line — for help texts."""
    return "; ".join(
        f"{label}: {', '.join(EXPORT_FORMATS[mime])}"
        for mime, label in _SHORT_LABELS.items()
    ) + "."


def is_native(mime_type: Optional[str]) -> bool:
    """True for a native Google file (``application/vnd.google-apps.*``).

    Native files are exported, never downloaded; every other file is
    downloaded, never exported. Folders and shortcuts are native too, but
    have no export formats (:func:`export_formats` returns ``{}``).
    """
    return bool(mime_type) and mime_type.startswith(NATIVE_MIME_PREFIX)


def type_label(mime_type: Optional[str]) -> str:
    """A readable name for a Drive file type, for messages."""
    if mime_type in _TYPE_LABELS:
        return _TYPE_LABELS[mime_type]
    if is_native(mime_type):
        return f"native Google file ({mime_type})"
    return f"file of type {mime_type or 'unknown'}"


def export_formats(mime_type: Optional[str]) -> dict[str, str]:
    """Format name → export MIME type for a native file type.

    Returns ``{}`` for non-native files and for native types that have no
    content to export (folders, shortcuts, Forms, Sites).
    """
    return dict(EXPORT_FORMATS.get(mime_type or "", {}))


def normalize_format(fmt: str) -> str:
    """Lower-case a format name, strip a leading dot, and resolve aliases."""
    name = (fmt or "").strip().lower().lstrip(".")
    return FORMAT_ALIASES.get(name, name)


class NotNativeFileError(ValueError):
    """Export was asked of an uploaded (non-native) file.

    Uploaded files have stored bytes; Drive exports only native Google
    files. The message points to download.
    """

    def __init__(self, file_id: str, mime_type: Optional[str], name: Optional[str] = None):
        self.file_id = file_id
        self.mime_type = mime_type
        self.name = name
        super().__init__(
            f"{_describe(file_id, name)} is not a native Google file "
            f"(mimeType {mime_type or 'unknown'}), so it has no export "
            f"formats. Download it "
            f"as stored instead (CLI: gwsa drive download {file_id} PATH; "
            f"MCP: drive_download)."
        )


class NoExportFormatsError(ValueError):
    """The native file type has no exportable content (folder, shortcut, Form, Site)."""

    def __init__(self, file_id: str, mime_type: Optional[str], name: Optional[str] = None):
        self.file_id = file_id
        self.mime_type = mime_type
        self.name = name
        super().__init__(
            f"{_describe(file_id, name)} is a {type_label(mime_type)}; Drive "
            f"has no file content to download or export for it."
        )


class UnsupportedExportFormatError(ValueError):
    """The format is not one Drive exports this native file type to."""

    def __init__(self, fmt: str, mime_type: Optional[str], available: list[str]):
        self.format = fmt
        self.mime_type = mime_type
        self.available = available
        super().__init__(
            f"A {type_label(mime_type)} cannot be exported as {fmt!r}. "
            f"Formats for this file: {', '.join(available)}."
        )


class NativeFileDownloadError(ValueError):
    """Download was asked of a native Google file, which has no stored bytes.

    Drive answers ``files.get?alt=media`` on a native file with HTTP 403
    ``fileNotDownloadable``. This error is raised before that call, and its
    message names the export command and the formats available.
    """

    def __init__(self, file_id: str, mime_type: Optional[str], name: Optional[str] = None):
        self.file_id = file_id
        self.mime_type = mime_type
        self.name = name
        self.available = list(export_formats(mime_type))
        if not self.available:
            message = (
                f"{_describe(file_id, name)} is a {type_label(mime_type)}; "
                f"Drive has no file content to download or export for it."
            )
        else:
            example = self.available[0]
            message = (
                f"{_describe(file_id, name)} is a {type_label(mime_type)}, which "
                f"has no stored bytes to download. Export it instead (CLI: "
                f"gwsa drive export {file_id} PATH --format {example}; MCP: "
                f"drive_export). Formats for this file: "
                f"{', '.join(self.available)}."
            )
        super().__init__(message)


def _describe(file_id: str, name: Optional[str]) -> str:
    return f"File {name!r} ({file_id})" if name else f"File {file_id}"


def resolve_export_mime(
    mime_type: Optional[str],
    fmt: str,
    file_id: str = "",
    name: Optional[str] = None,
) -> tuple[str, str]:
    """Validate ``fmt`` for a file of ``mime_type``; return ``(format, export_mime)``.

    Args:
        mime_type: The Drive file's ``mimeType``.
        fmt: Format name or alias (``"xlsx"``, ``"markdown"``, ``".pdf"``).
        file_id: Used only in error messages.
        name: The file's name, used only in error messages.

    Returns:
        The canonical format name and the export MIME type to request.

    Raises:
        NotNativeFileError: The file is not a native Google file.
        NoExportFormatsError: A native type with nothing to export.
        UnsupportedExportFormatError: ``fmt`` is not available for this type;
            ``available`` lists the formats that are.
    """
    if not is_native(mime_type):
        raise NotNativeFileError(file_id, mime_type, name)
    formats = export_formats(mime_type)
    if not formats:
        raise NoExportFormatsError(file_id, mime_type, name)
    canonical = normalize_format(fmt)
    if canonical not in formats:
        raise UnsupportedExportFormatError(fmt, mime_type, list(formats))
    return canonical, formats[canonical]


def format_for_export_mime(mime_type: Optional[str], export_mime: str) -> Optional[str]:
    """The format name for an export MIME type of a native file type, if any."""
    for name, mime in export_formats(mime_type).items():
        if mime == export_mime:
            return name
    return None


def formats_in_export_links(
    mime_type: Optional[str], export_links: Optional[Mapping[str, str]]
) -> dict[str, str]:
    """Format name → URL, for the entries of an ``exportLinks`` map gwsa names.

    ``exportLinks`` (on a file or on a native file's revision) is keyed by
    export MIME type. This turns it into the format names used everywhere
    else, keeping only MIME types this module maps, in this module's order.
    """
    links = export_links or {}
    return {
        name: links[mime]
        for name, mime in export_formats(mime_type).items()
        if mime in links
    }


def export_file_name(name: Optional[str], fmt: str, fallback: str = "export") -> str:
    """The file name for an export: the Drive name plus ``.<fmt>``.

    The extension is not doubled when the Drive name already ends with it.
    """
    base = (name or fallback).strip() or fallback
    suffix = f".{fmt}"
    return base if base.lower().endswith(suffix) else base + suffix
