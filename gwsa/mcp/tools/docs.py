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
from gwsa.sdk.docs.expect import DocsRequest
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
    For rich-text formatting (headings, bold, lists, links, tables, or code
    blocks), pass an HTML string in ``body_text`` and set
    ``mime_type="text/html"``. ``body_text`` here is plain text or HTML only:
    Markdown passed here shows its literal ``##`` / ``**`` characters.
    **To turn Markdown into a formatted Doc,** use ``drive_create_file`` with
    ``name="<title>.md"``, the Markdown as ``content_base64``, and
    ``mime_type="application/vnd.google-apps.document"`` — Drive converts it.

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
        count characters yourself. The result's ``revision_id`` is the
        revision these positions belong to: pass it as
        ``batch_update_doc``'s ``required_revision_id``.
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
        Dict with ``revision_id`` (the revision these positions belong to —
        pass it as ``batch_update_doc``'s ``required_revision_id``) and
        ``matches``: each ``tab_id``, ``segment`` (body/header/footer/
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
    requests: list[DocsRequest],
    required_revision_id: str,
    dry_run: bool = False,
    account: Optional[str] = None,
) -> dict[str, Any]:
    r"""Edit a Google Doc: the Docs API ``documents.batchUpdate``, with checks.

    This is the only Docs write tool. ``requests`` are Docs API request
    objects passed to Google unchanged, so anything the API can do is
    available: text, headings, bullets and nested lists, indentation,
    fonts, colors, links, tables, images, people/date chips, named ranges,
    tabs. The batch is atomic: all requests apply, or none do.

    PASS THE REVISION ID FROM YOUR READ (required)
      ``required_revision_id`` is the ``revision_id`` returned by the read
      your positions came from (``read_doc`` or ``find_in_doc``), or by your
      previous ``batch_update_doc`` call. If the document changed since, the
      call is refused with the current revision id and nothing is written:
      read again and take positions from the new read.

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

    EXPECT (required on every index-based request)
      Give each request that addresses an index an ``expect`` key beside its
      request type; gwsa checks it and removes it before sending:
      ``{"deleteContentRange": {...}, "expect": {"text": "Q3 Plan"}}``.
      Requests that address no index (``replaceAllText``,
      ``replaceNamedRangeContent``, ``endOfSegmentLocation`` inserts, tab
      and named-range management) have no ``expect``. State what is at the
      position at the moment the request runs (after earlier requests in
      the call), using the same units as the map (markers like
      ``⟦person⟧``; a paragraph break is ``"\n"`` — the map's ``⏎`` is
      also accepted and means the same):
        - a range (``deleteContentRange``, ``updateTextStyle``,
          ``updateParagraphStyle``, ``createParagraphBullets``, ...):
          ``{"text": "<exact content of startIndex..endIndex>"}``
        - a range that is exactly ONE WHOLE paragraph (including its
          ``"\n"``) or ONE WHOLE table (from its ``⟦table⟧`` through its
          ``⟦table-end⟧``): ``{"element": "paragraph"}`` or
          ``{"element": "table"}`` — use this instead of repeating a whole
          paragraph's or table's text. Both ends
          must sit on that element's boundaries (take them from the map
          line), so a shifted range is refused. Part of a paragraph always
          needs ``{"text": ...}``.
        - a point (``insertText``/``insertTable``/``insertPerson``/... at
          ``location.index``, or table ops via ``tableStartLocation``):
          ``{"before": "<text just before>", "after": "<text just after>"}``
          (either or both; a table start is ``{"after": "⟦table⟧"}``)
      Every index-based request needs its own ``expect`` — including an
      insert at the position a delete just emptied: its ``after`` is the
      text that followed the deleted range (see "Replace a phrase").
      gwsa replays the call's text inserts/deletes, chip/image inserts, and
      ``createParagraphBullets`` (which removes each covered paragraph's
      leading tabs) exactly, checks every expectation, and only then sends
      the batch. If
      any expectation does not match, NOTHING is written and the response
      states what was expected and what is actually there. Unexpected text
      there means the position is wrong: take it again from the map or
      ``find_in_doc`` — do not copy the reported text into ``expect``.
      ``{"unchecked": true}`` skips the check for one request explicitly.
      Requests whose effect on positions gwsa does not replay —
      ``insertTable``, table row/column changes, page/section breaks,
      footnotes — end checking at their position: later requests at or
      after it go in a separate call (put such requests last).
      No index-based request may follow ``replaceAllText`` /
      ``replaceNamedRangeContent`` in the same call (put them last).

    LOOK BEFORE YOU WRITE: ``dry_run=true``
      Runs every check and returns the predicted ``changes`` (each changed
      paragraph before and after, with ranges) without writing. Text
      inserts and deletes are drawn exactly; ``not_shown`` lists requests
      whose result is not drawn (styles, bullets, tables,
      ``replaceAllText``) — they are still checked.

    AFTER EVERY WRITE
      Read ``changes``: each changed paragraph before and after, with its
      ranges. Confirm it shows exactly the edit you intended, and use the new
      ranges (not old ones) for any follow-up edit — with the ``revision_id``
      this call returned as the next call's ``required_revision_id``.

    BUILDING NEW CONTENT (new doc, new section, new list)
      Insert all the text in one request — paragraphs separated by
      ``"\n"``, nested list items prefixed with ``"\t"`` per level —
      e.g. at the end of a tab with ``endOfSegmentLocation`` (no
      ``expect``). Then style it in a second call, using the ranges shown in
      the first call's ``changes`` (no counting). Note that
      ``createParagraphBullets`` removes the leading ``"\t"`` characters,
      so text after it moves back by the number of tabs removed.

      Append a styled paragraph (e.g. a heading) — two calls:
        1. ``{"insertText": {"endOfSegmentLocation": {"tabId": "t.0"},
           "text": "\nNew heading"}}`` (no ``expect``). Start the text with
           ``"\n"``: the insert lands before the body's final paragraph
           break, so without it the new text joins the last paragraph.
        2. From call 1's ``changes``, take the new paragraph's range (e.g.
           ``"137-149 New heading⏎"``) and call again with
           ``required_revision_id`` = call 1's returned ``revision_id``:
           ``{"updateParagraphStyle": {"range": {"startIndex": 137,
           "endIndex": 149}, "paragraphStyle": {"namedStyleType":
           "HEADING_2"}, "fields": "namedStyleType"},
           "expect": {"element": "paragraph"}}``.

    RECIPES (each is one entry in ``requests``)
      - Append to the end of a tab's body (no index, no ``expect``):
        ``{"insertText": {"endOfSegmentLocation": {"tabId": "t.0"},
        "text": "\nNew paragraph"}}``
      - Insert at a point:
        ``{"insertText": {"location": {"index": 64}, "text": "New line\n"},
        "expect": {"before": "Q3 Plan\n"}}``
      - Replace a phrase inside a paragraph, keeping the paragraph's style:
        delete the range, then insert at the same start. The insert runs
        after the delete, so its ``after`` is whatever followed the deleted
        text (here the paragraph break):
        ``{"deleteContentRange": {"range": {"startIndex": 54, "endIndex": 61}},
        "expect": {"text": "Q3 Plan"}}``, then
        ``{"insertText": {"location": {"index": 54}, "text": "Q4 Plan"},
        "expect": {"after": "\n"}}``.
      - Delete a whole table (map lines ``98-99 [table 2x2] ⟦table⟧`` …
        ``124-125 [table end] ⟦table-end⟧``):
        ``{"deleteContentRange": {"range": {"startIndex": 98,
        "endIndex": 125}}, "expect": {"element": "table"}}``
      - Delete a whole paragraph (map line ``84-97 Before table⏎``):
        ``{"deleteContentRange": {"range": {"startIndex": 84,
        "endIndex": 97}}, "expect": {"element": "paragraph"}}``
      - Replace every occurrence (no index):
        ``{"replaceAllText": {"containsText": {"text": "{{DATE}}",
        "matchCase": true}, "replaceText": "Oct 1",
        "tabsCriteria": {"tabIds": ["t.0"]}}}`` (no ``expect``); check
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
        ``replaceNamedRangeContent`` by name (no index, no ``expect``).

    Args:
        doc_id: Google Doc ID.
        requests: Docs API request objects, each with an ``expect`` when it
            addresses an index (see EXPECT).
        required_revision_id: The ``revision_id`` from the read your
            positions came from (or from your previous write). Required.
        dry_run: Check and return the predicted ``changes`` without writing.
        account: Optional account selector (name or email).

    Returns:
        On success: ``success``, ``document_id``, ``previous_revision_id``,
        ``revision_id`` (after this write — pass it to your next call),
        ``replies`` (Google's, one per request — e.g.
        ``replaceAllText.occurrencesChanged``), ``changes`` (``segment``,
        ``before`` lines, ``after`` lines), ``truncated``.
        With ``dry_run``: ``success``, ``dry_run: true``, ``revision_id``
        (unchanged), predicted ``changes``, ``not_shown``. Nothing written.
        On a failed check or a stale revision: ``success: false``,
        ``error``, ``failures`` (one statement per problem, for checks),
        ``revision_id`` (current). Nothing written.
        On a Google error: ``success: false``, ``error``, ``details``.
        Nothing written (the batch is atomic).
    """
    try:
        result = docs.batch_update(
            doc_id, [dict(r) for r in requests], required_revision_id,
            account=account, dry_run=dry_run,
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
