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

    Args:
        title: Title for the new document.
        body_text: Optional initial body text to insert.
        folder_id: Optional folder ID (defaults to My Drive root).
        mime_type: Optional MIME type for body_text (e.g. 'text/html' to parse and convert HTML formatting).
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


async def read_doc(
    doc_id: str,
    format: str = "content",
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Read a Google Doc by ID.

    NOTE: Works only with remote Google Docs in the cloud.

    Args:
        doc_id: Google Doc ID.
        format: "content" (metadata + text), "text" (plain text only),
            or "raw" (full API response).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Document content in the requested format. HTTP 403s surface
        as an actionable error envelope pointing at account selection.
    """
    try:
        if format == "text":
            return {"text": docs.get_document_text(doc_id, account=account)}
        if format == "raw":
            return docs.get_document(doc_id, account=account)
        return docs.get_document_content(doc_id, account=account)
    except (LocalPathError, InvalidDocIdError) as e:
        return {"error": str(e)}
    except ValueError as e:
        logger.error(f"ValueError reading doc: {e}")
        return {"error": str(e)}
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error reading doc: {e}")
            return {
                "error": "The caller does not have permission.",
                "details": str(e),
                "hint": (
                    "The chosen gwsa account may not have access to this "
                    "document. Try a different account via the 'account' "
                    "parameter (see 'list_google_accounts'), or re-acquire "
                    "the token if it has expired."
                ),
            }
        raise
    except Exception as e:
        logger.error(f"Error reading doc: {e}")
        return {"error": str(e)}


async def append_to_doc(
    doc_id: str,
    text: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Append text to the end of a Google Doc.

    NOTE: Works only with remote Google Docs in the cloud.

    Args:
        doc_id: Google Doc ID.
        text: Text to append.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``success``, ``document_id``, and ``write_control``.
    """
    try:
        result = docs.append_text(doc_id, text, account=account)
        return {
            "success": True,
            "document_id": doc_id,
            "write_control": result.get("writeControl", {}),
        }
    except (LocalPathError, InvalidDocIdError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error appending to doc: {e}")
        return {"error": str(e)}


async def insert_in_doc(
    doc_id: str,
    text: str,
    index: int = 1,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Insert text at a specific position in a Google Doc.

    NOTE: Works only with remote Google Docs in the cloud.

    Args:
        doc_id: Google Doc ID.
        text: Text to insert.
        index: Position to insert at (1 = beginning of document).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``success``, ``document_id``, ``inserted_at_index``,
        and ``write_control``.
    """
    try:
        result = docs.insert_text(doc_id, text, index=index, account=account)
        return {
            "success": True,
            "document_id": doc_id,
            "inserted_at_index": index,
            "write_control": result.get("writeControl", {}),
        }
    except (LocalPathError, InvalidDocIdError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error inserting in doc: {e}")
        return {"error": str(e)}


async def replace_in_doc(
    doc_id: str,
    find_text: str,
    replace_with: str,
    match_case: bool = True,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Replace all occurrences of text in a Google Doc.

    NOTE: Works only with remote Google Docs in the cloud.

    Args:
        doc_id: Google Doc ID.
        find_text: Text to find.
        replace_with: Text to replace with.
        match_case: Whether to match case (default True).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``success``, ``document_id``, ``occurrences_replaced``,
        ``find_text``, and ``replace_with``.
    """
    try:
        result = docs.replace_text(
            doc_id,
            find_text,
            replace_with,
            match_case=match_case,
            account=account,
        )
        replies = result.get("replies", [])
        occurrences = 0
        if replies:
            occurrences = (
                replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
            )
        return {
            "success": True,
            "document_id": doc_id,
            "occurrences_replaced": occurrences,
            "find_text": find_text,
            "replace_with": replace_with,
        }
    except (LocalPathError, InvalidDocIdError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error replacing in doc: {e}")
        return {"error": str(e)}
