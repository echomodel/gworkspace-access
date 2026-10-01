"""Google Docs reading operations.

Two families of reads, deliberately kept apart:

- **Structure** (``get_document``, ``get_document_map``, ``find_in_document``)
  comes from ``documents.get``. It carries Google's own indices — the only
  valid source of positions for ``batch_update``.
- **Text** (``get_document_markdown``, ``get_document_text``) comes from
  Google's own export (Drive ``files.export``): what *File → Download*
  produces. It includes every tab and renders chips, lists, headings, and
  tables, but its character offsets do NOT correspond to document indices —
  never compute positions from exported text.
"""

from typing import Optional

from googleapiclient.errors import HttpError

from .service import get_docs_service
from .validators import validate_doc_id
from ..drive.service import get_drive_service
from . import positions

_DOC_MIME = "application/vnd.google-apps.document"
_EXPORT_MIME = {"markdown": "text/markdown", "text": "text/plain"}


def _assert_google_doc(doc_id: str, account: Optional[str]) -> None:
    drive_service = get_drive_service(account=account)
    try:
        meta = drive_service.files().get(
            fileId=doc_id, fields="mimeType", supportsAllDrives=True
        ).execute()
    except HttpError:
        return
    mime_type = meta.get("mimeType")
    if mime_type != _DOC_MIME:
        raise ValueError(
            f"File with ID '{doc_id}' is not a Google Doc (MIME type: {mime_type}). "
            f"Use the 'drive_download' tool for non-native formats like PDFs or images."
        )


def _filter_tab(doc: dict, tab_id: str) -> dict:
    for tab, _parent, _depth in positions.iter_tabs(doc):
        if tab.get("tabProperties", {}).get("tabId") == tab_id:
            out = {k: v for k, v in doc.items() if k != "tabs"}
            out["tabs"] = [tab]
            return out
    raise ValueError(f"Document has no tab with id '{tab_id}'.")


def get_document(
    doc_id: str,
    account: Optional[str] = None,
    tab_id: Optional[str] = None,
    fields: Optional[str] = None,
) -> dict:
    """The document as returned by ``documents.get`` (all tabs' content).

    Args:
        doc_id: The Google Doc ID.
        account: Optional account selector — name or email.
        tab_id: Optional — return only this tab (with its child tabs).
        fields: Optional Docs API partial-response mask (e.g.
            ``"revisionId,tabs(tabProperties)"``), passed through verbatim.

    Raises:
        ValueError: The file is not a Google Doc, or ``tab_id`` is unknown.
        LocalPathError / InvalidDocIdError: The ID is malformed.
    """
    validate_doc_id(doc_id)
    _assert_google_doc(doc_id, account)
    service = get_docs_service(account=account)
    kwargs = {"documentId": doc_id, "includeTabsContent": True}
    if fields:
        kwargs["fields"] = fields
    doc = service.documents().get(**kwargs).execute()
    return _filter_tab(doc, tab_id) if tab_id else doc


def export_document(doc_id: str, fmt: str, account: Optional[str] = None) -> str:
    """Google's own export of the document: ``"markdown"`` or ``"text"``."""
    if fmt not in _EXPORT_MIME:
        raise ValueError(f"fmt must be one of {sorted(_EXPORT_MIME)}, got {fmt!r}")
    validate_doc_id(doc_id)
    _assert_google_doc(doc_id, account)
    data = get_drive_service(account=account).files().export(
        fileId=doc_id, mimeType=_EXPORT_MIME[fmt]
    ).execute()
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    return text.lstrip("﻿")


def get_document_markdown(doc_id: str, account: Optional[str] = None) -> str:
    """Google's Markdown export (all tabs; headings, lists, tables, chips)."""
    return export_document(doc_id, "markdown", account=account)


def get_document_text(doc_id: str, account: Optional[str] = None) -> str:
    """Google's plain-text export (all tabs)."""
    return export_document(doc_id, "text", account=account)


def get_document_content(doc_id: str, account: Optional[str] = None) -> dict:
    """Summary read: metadata, tab inventory, and the Markdown export.

    Returns:
        Dict with ``id``, ``title``, ``url``, ``revision_id``, ``tabs``
        (``tab_id``, ``title``, ``parent_tab_id``, ``depth``), and ``text``
        (Google's Markdown export of all tabs).
    """
    doc = get_document(
        doc_id, account=account,
        fields=(
            "documentId,title,revisionId,"
            "tabs(tabProperties,childTabs(tabProperties,"
            "childTabs(tabProperties,childTabs(tabProperties))))"
        ),
    )
    return {
        "id": doc.get("documentId"),
        "title": doc.get("title"),
        "url": f"https://docs.google.com/document/d/{doc.get('documentId')}/edit",
        "revision_id": doc.get("revisionId"),
        "tabs": positions.list_tabs(doc),
        "text": get_document_markdown(doc_id, account=account),
    }


def get_document_map(
    doc_id: str, tab_id: Optional[str] = None, account: Optional[str] = None
) -> dict:
    """Position map: each paragraph's exact index range, per tab and segment.

    See :mod:`gwsa.sdk.docs.positions`. The returned ``revision_id`` is the
    revision the positions belong to.
    """
    doc = get_document(doc_id, account=account)
    if tab_id and not any(t["tab_id"] == tab_id for t in positions.list_tabs(doc)):
        raise ValueError(f"Document has no tab with id '{tab_id}'.")
    return positions.render_map(doc, tab_id=tab_id)


def find_in_document(
    doc_id: str,
    text: str,
    tab_id: Optional[str] = None,
    match_case: bool = True,
    account: Optional[str] = None,
) -> dict:
    """Every occurrence of ``text`` with its exact index range.

    ``text`` may include markers such as ``⟦person⟧`` to match non-text
    elements. Returns ``revision_id`` and ``matches`` (``tab_id``,
    ``segment``, ``segment_id``, ``start``, ``end``).
    """
    doc = get_document(doc_id, account=account)
    return positions.find_text(doc, text, tab_id=tab_id, match_case=match_case)
