"""Google Docs MCP tools.

Plain async functions delegating to ``gwsa.sdk.docs``. The wrapper
catches ``LocalPathError`` / ``InvalidDocIdError`` cleanly and
maps Google API HTTP 403s to an actionable error envelope.

Every tool accepts an optional ``account`` parameter: pass either
the account ``name`` (e.g. ``"work"``) or its Google ``email`` (e.g.
``"alice@example.com"``) to operate as a specific account on the
current user's profile. Omit to use the user's ``default_account``
(or the sole account if only one is configured). Use the
``list_google_accounts`` tool to discover available account names
and emails.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from googleapiclient.errors import HttpError

from gwsa.sdk import docs
from gwsa.sdk.exceptions import InvalidDocIdError, LocalPathError

logger = logging.getLogger(__name__)


async def list_docs(
    max_results: int = 25,
    query: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """List Google Docs the chosen account can access.

    NOTE: Works only with remote Google Docs in the cloud.

    Args:
        max_results: Maximum number of documents to return (default 25).
        query: Optional search query to filter documents by title or
            content.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with a list of documents (id, title, url, timestamps).
    """
    try:
        return docs.list_documents(
            max_results=max_results, query=query, account=account
        )
    except Exception as e:
        logger.error(f"Error listing docs: {e}")
        return {"error": str(e)}


async def create_doc(
    title: str,
    body_text: Optional[str] = None,
    folder_id: Optional[str] = None,
    mime_type: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new Google Doc.

    NOTE: Works only with remote Google Docs in the cloud.
    IMPORTANT: For rich-text formatting (headings, bold, lists, links, tables,
    or code blocks), pass an HTML string in ``body_text`` and set
    ``mime_type="text/html"``. Do NOT pass raw Markdown syntax (e.g. ``##`` or
    ``**``) in ``body_text``, as Google Docs does not parse Markdown on import
    and will display the literal syntax characters.

    Args:
        title: Title for the new document.
        body_text: Optional initial body text (plain text by default, or HTML
            when ``mime_type="text/html"``).
        folder_id: Optional folder ID (defaults to My Drive root).
        mime_type: Optional MIME type for ``body_text`` — pass ``"text/html"``
            to convert HTML tags into native Google Docs formatting.
        account: Optional account selector (name or email). Omit to
            create in the user's default account.

    Returns:
        Dict with document ``id``, ``title``, and ``url``.
    """
    try:
        return docs.create_document(
            title=title,
            body_text=body_text,
            folder_id=folder_id,
            mime_type=mime_type,
            account=account,
        )
    except Exception as e:
        logger.error(f"Error creating doc: {e}")
        return {"error": str(e)}


def _http_error(e: HttpError, action: str) -> dict[str, Any]:
    status = getattr(getattr(e, "resp", None), "status", None)
    if status == 403:
        return {
            "error": "The caller does not have permission.",
            "details": str(e),
            "hint": (
                "The chosen gwsa account may not have access to this "
                "document. Try a different account via the 'account' "
                "parameter (see 'list_google_accounts')."
            ),
        }
    logger.error(f"HTTP error {action}: {e}")
    return {"error": str(e)}


_READ_FORMATS = ("content", "markdown", "text", "raw", "map")


async def read_doc(
    doc_id: str,
    format: str = "content",
    tab_id: Optional[str] = None,
    fields: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Read a Google Doc.

    Two kinds of read — use the right one for the job:

    **Reading to understand the document** (no positions):
      - ``"content"`` (default): ``id``, ``title``, ``url``, ``revision_id``,
        ``tabs`` (``tab_id``, ``title``, ``parent_tab_id``, ``depth``), and
        ``text`` — Google's own Markdown export of ALL tabs (headings, lists,
        tables, people/date chips rendered).
      - ``"markdown"`` / ``"text"``: Google's Markdown or plain-text export
        only, as ``{"text": ...}``.
      Exported text has NO document positions. Never compute an index from
      it: its character offsets do not match document indices (paragraph
      breaks, chips, tables, and tabs are laid out differently).

    **Reading to edit** (positions for ``batch_update_doc``):
      - ``"map"``: the position map. For each tab and segment (body,
        headers, footers, footnotes), one line per paragraph:
        ``"<start>-<end> [tags] text"`` — e.g. ``"54-63 [HEADING_2] Q3 Plan⏎"``.
        ``⏎`` is the paragraph's newline (one index). Non-text items occupy
        exactly one index each and show as markers: ``⟦person⟧``,
        ``⟦date⟧``, ``⟦link-chip⟧``, ``⟦image⟧``, ``⟦footnote-ref⟧``,
        ``⟦page-break⟧``, ``⟦section⟧``, ``⟦table⟧``, ``⟦row⟧``, ``⟦cell⟧``.
        Characters outside the Basic Multilingual Plane (most emoji) occupy
        two indices. Copy ranges from here (or from ``find_in_doc``); do not
        count characters yourself.
      - ``"raw"``: the Docs API document verbatim (``documents.get`` with all
        tabs' content): every element's ``startIndex``/``endIndex``, styles,
        named ranges, list definitions, ``revisionId``.

    Args:
        doc_id: Google Doc ID.
        format: ``"content"``, ``"markdown"``, ``"text"``, ``"map"``, or
            ``"raw"``.
        tab_id: Optional — only this tab. Applies to ``"map"`` and ``"raw"``
            (exports always include every tab).
        fields: Optional Docs API partial-response mask for ``"raw"`` (e.g.
            ``"revisionId,namedRanges"``), passed through verbatim.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        The document in the requested format, or an ``error`` envelope.
    """
    try:
        if format not in _READ_FORMATS:
            return {"error": f"format must be one of {list(_READ_FORMATS)}; got {format!r}."}
        if tab_id and format not in ("map", "raw"):
            return {"error": "tab_id applies to format 'map' or 'raw'; exports include every tab."}
        if fields and format != "raw":
            return {"error": "fields applies to format 'raw' only."}
        if format == "content":
            return docs.get_document_content(doc_id, account=account)
        if format == "markdown":
            return {"text": docs.get_document_markdown(doc_id, account=account)}
        if format == "text":
            return {"text": docs.get_document_text(doc_id, account=account)}
        if format == "map":
            return docs.get_document_map(doc_id, tab_id=tab_id, account=account)
        return docs.get_document(doc_id, account=account, tab_id=tab_id, fields=fields)
    except (LocalPathError, InvalidDocIdError, ValueError) as e:
        return {"error": str(e)}
    except HttpError as e:
        return _http_error(e, "reading doc")
    except Exception as e:
        logger.error(f"Error reading doc: {e}")
        return {"error": str(e)}


async def find_in_doc(
    doc_id: str,
    text: str,
    tab_id: Optional[str] = None,
    match_case: bool = True,
    account: Optional[str] = None,
) -> dict[str, Any]:
    r"""Find text in a Google Doc and return each occurrence's exact index range.

    Read-only. Use it to get positions for ``batch_update_doc`` instead of
    counting characters. Searches every tab and segment (body, headers,
    footers, footnotes) unless ``tab_id`` is given. Matching is on the same
    units as ``read_doc(format="map")``: ``text`` may include markers such
    as ``⟦person⟧``, and ``"\n"`` to match across a paragraph break.

    Args:
        doc_id: Google Doc ID.
        text: Text to find (exact; may span paragraph breaks with ``\n``).
        tab_id: Optional — search only this tab.
        match_case: Case-sensitive match (default True).
        account: Optional account selector (name or email).

    Returns:
        Dict with ``revision_id`` (the revision these positions belong to)
        and ``matches``: each ``tab_id``, ``segment`` (body/header/footer/
        footnote), ``segment_id``, ``start``, ``end`` (end-exclusive).
        Zero matches is ``[]``; more than one means the text is not unique.
    """
    try:
        return docs.find_in_document(
            doc_id, text, tab_id=tab_id, match_case=match_case, account=account
        )
    except (LocalPathError, InvalidDocIdError, ValueError) as e:
        return {"error": str(e)}
    except HttpError as e:
        return _http_error(e, "finding in doc")
    except Exception as e:
        logger.error(f"Error finding in doc: {e}")
        return {"error": str(e)}


async def batch_update_doc(
    doc_id: str,
    requests: list[dict[str, Any]],
    expectations: Optional[list[Optional[dict[str, Any]]]] = None,
    required_revision_id: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    r"""Edit a Google Doc: the Docs API ``documents.batchUpdate``, with checks.

    This is the only Docs write tool. ``requests`` are Docs API request
    objects passed to Google unchanged, so anything the API can do is
    available: text, headings, bullets and nested lists, indentation,
    fonts, colors, links, tables, images, people/date chips, named ranges,
    tabs. The batch is atomic: all requests apply, or none do.

    HOW POSITIONS WORK
      Index-based requests address a position in one segment (a tab's body,
      or a header/footer/footnote via ``segmentId``; a tab via ``tabId`` —
      default is the first tab). Take every index from
      ``read_doc(format="map")``, ``read_doc(format="raw")``, or
      ``find_in_doc`` — from the current revision. Never from exported text
      (``content``/``markdown``/``text``) and never by counting characters.

    REQUESTS RUN IN ORDER (as in the Docs API)
      Each request's indices refer to the document as it is after the
      requests before it in the same call. Positions from your read are
      valid for the first request; after an insert or delete, positions
      after that point have moved by the inserted/deleted length. Simplest
      way to avoid arithmetic: order content changes from the END of the
      document backwards — then positions from your read stay valid.

    EXPECTATIONS (required for every index-based request)
      ``expectations`` aligns one-to-one with ``requests``; use ``null`` for
      requests that address no index (``replaceAllText``,
      ``replaceNamedRangeContent``, ``endOfSegmentLocation`` inserts, tab
      and named-range management). For an index-based request, state what
      is at its position at the moment it runs (after earlier requests in
      the call), using the same units as the map (markers like
      ``⟦person⟧``; ``"\n"`` for a paragraph break):
        - a range (``deleteContentRange``, ``updateTextStyle``,
          ``updateParagraphStyle``, ``createParagraphBullets``, ...):
          ``{"text": "<exact content of startIndex..endIndex>"}``
        - a point (``insertText``/``insertTable``/``insertPerson``/... at
          ``location.index``, or table ops via ``tableStartLocation``):
          ``{"before": "<text just before>", "after": "<text just after>"}``
          (either or both; a table start is ``{"after": "⟦table⟧"}``)
      gwsa replays the call's text inserts/deletes, chip/image inserts, and
      ``createParagraphBullets`` (which removes each covered paragraph's
      leading tabs) exactly, checks every expectation, and only then sends
      the batch. If
      any expectation does not match, NOTHING is written and the response
      states what was expected and what is actually there.
      ``{"unchecked": true}`` skips the check for one request explicitly.
      Requests whose effect on positions gwsa does not replay —
      ``insertTable``, table row/column changes, page/section breaks,
      footnotes — end checking at their position: later requests at or
      after it go in a separate call (put such requests last).
      No index-based request may follow ``replaceAllText`` /
      ``replaceNamedRangeContent`` in the same call (put them last).

    AFTER EVERY WRITE
      Read ``changes``: each changed paragraph before and after, with its
      ranges. Confirm it shows exactly the edit you intended, and use the new
      ranges (not old ones) for any follow-up edit.

    BUILDING NEW CONTENT (new doc, new section, new list)
      Insert all the text in one request — paragraphs separated by
      ``"\n"``, nested list items prefixed with ``"\t"`` per level —
      e.g. at the end of a tab with ``endOfSegmentLocation`` (expectation
      ``null``). Then style it, either later in the same call (ranges
      computed from where you inserted; each with ``{"text": ...}`` of the
      new text, which gwsa checks) or — avoiding any counting — in a second
      call using the ranges shown in the first call's ``changes``. Note that
      ``createParagraphBullets`` removes the leading ``"\t"`` characters,
      so text after it moves back by the number of tabs removed.

    RECIPES (one entry in ``requests`` -> its expectation)
      - Append to the end of a tab's body (no index):
        ``{"insertText": {"endOfSegmentLocation": {"tabId": "t.0"},
        "text": "\nNew paragraph"}}`` -> ``null``
      - Insert at a point:
        ``{"insertText": {"location": {"index": 64}, "text": "New line\n"}}``
        -> ``{"before": "Q3 Plan\n"}``
      - Replace a phrase inside a paragraph, keeping the paragraph's style:
        delete the range, then insert at the same start. The insert runs
        after the delete, so its ``after`` is whatever followed the deleted
        text (here the paragraph break):
        ``{"deleteContentRange": {"range": {"startIndex": 54, "endIndex": 61}}}``
        -> ``{"text": "Q3 Plan"}``, then
        ``{"insertText": {"location": {"index": 54}, "text": "Q4 Plan"}}``
        -> ``{"after": "\n"}``.
      - Replace every occurrence (no index):
        ``{"replaceAllText": {"containsText": {"text": "{{DATE}}",
        "matchCase": true}, "replaceText": "Oct 1",
        "tabsCriteria": {"tabIds": ["t.0"]}}}`` -> ``null``; check
        ``occurrencesChanged`` in its reply.
      - Heading: ``{"updateParagraphStyle": {"range": {...}, "paragraphStyle":
        {"namedStyleType": "HEADING_2"}, "fields": "namedStyleType"}}``
      - Font/color/size: ``{"updateTextStyle": {"range": {...},
        "textStyle": {"weightedFontFamily": {"fontFamily": "Lora"},
        "foregroundColor": {"color": {"rgbColor": {"blue": 0.8}}},
        "fontSize": {"magnitude": 12, "unit": "PT"}},
        "fields": "weightedFontFamily,foregroundColor,fontSize"}}``
      - Bullets / nested outline: insert the lines with leading tab
        characters for deeper levels, then ``createParagraphBullets`` over
        their range; Google converts leading tabs to nesting levels and
        removes them (later positions move back accordingly).
      - Indentation: ``updateParagraphStyle`` with ``indentStart`` /
        ``indentFirstLine`` (``{"magnitude": 36, "unit": "PT"}``).
      - Newly inserted text takes the style of the text before it; follow
        an insert with ``updateTextStyle``/``updateParagraphStyle`` on the
        new range to set its style explicitly.
      - Stable anchor for repeated edits: ``createNamedRange`` once, then
        ``replaceNamedRangeContent`` by name (no index; ``null``).

    Args:
        doc_id: Google Doc ID.
        requests: Docs API request objects.
        expectations: One per request; see above.
        required_revision_id: Optional — refuse unless the document is still
            at this revision (the ``revision_id`` your positions came from).
            The batch is always checked and written against one snapshot and
            Google rejects it if the document changed in between.
        account: Optional account selector (name or email).

    Returns:
        On success: ``success``, ``document_id``, ``previous_revision_id``,
        ``revision_id`` (after this write), ``replies`` (Google's, one per
        request — e.g. ``replaceAllText.occurrencesChanged``), ``changes``
        (``segment``, ``before`` lines, ``after`` lines), ``truncated``.
        On a failed check: ``success: false``, ``error``, ``failures`` (one
        statement per problem), ``revision_id`` (current). Nothing written.
        On a Google error: ``success: false``, ``error``, ``details``.
        Nothing written (the batch is atomic).
    """
    try:
        # Positional: (doc_id, requests, expectations, required revision, account).
        result = docs.batch_update(
            doc_id, requests, expectations, required_revision_id, account
        )
        return {"success": True, **result}
    except docs.ExpectationError as e:
        return {
            "success": False,
            "error": "Expectation check failed. Nothing was written.",
            "failures": e.failures,
            "revision_id": e.revision_id,
        }
    except docs.DocumentChangedError as e:
        return {"success": False, "error": str(e), "revision_id": e.current}
    except (LocalPathError, InvalidDocIdError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        status = getattr(getattr(e, "resp", None), "status", None)
        if status == 403:
            return {"success": False, **_http_error(e, "in batch_update_doc")}
        return {
            "success": False,
            "error": "Google rejected the batch. Nothing was written.",
            "details": str(e),
        }
    except Exception as e:
        logger.error(f"Error in batch_update_doc: {e}")
        return {"success": False, "error": str(e)}
