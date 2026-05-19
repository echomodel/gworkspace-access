"""Google Docs update operations."""

from typing import Optional

from .service import get_docs_service
from .validators import validate_doc_id


def insert_text(
    doc_id: str,
    text: str,
    index: int = 1,
    account: Optional[str] = None,
) -> dict:
    """Insert text at a specific index in a document.

    Args:
        doc_id: The Google Doc ID
        text: Text to insert
        index: Position to insert at (1 = beginning of document)
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        The batchUpdate response.
    """
    validate_doc_id(doc_id)
    service = get_docs_service(account=account)
    requests = [{"insertText": {"location": {"index": index}, "text": text}}]
    return service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()


def append_text(
    doc_id: str,
    text: str,
    account: Optional[str] = None,
) -> dict:
    """Append text to the end of a document.

    Args:
        doc_id: The Google Doc ID
        text: Text to append
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        The batchUpdate response.
    """
    validate_doc_id(doc_id)
    service = get_docs_service(account=account)

    doc = service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])

    end_index = 1
    if content:
        last_element = content[-1]
        end_index = last_element.get("endIndex", 1) - 1

    if not text.startswith("\n"):
        text = "\n" + text

    requests = [{"insertText": {"location": {"index": end_index}, "text": text}}]
    return service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()


def replace_text(
    doc_id: str,
    find_text: str,
    replace_with: str,
    match_case: bool = True,
    account: Optional[str] = None,
) -> dict:
    """Replace all occurrences of text in a document.

    Args:
        doc_id: The Google Doc ID
        find_text: Text to find
        replace_with: Text to replace with
        match_case: Whether to match case (default True)
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        The batchUpdate response with occurrencesChanged count.
    """
    validate_doc_id(doc_id)
    service = get_docs_service(account=account)
    requests = [{
        "replaceAllText": {
            "containsText": {"text": find_text, "matchCase": match_case},
            "replaceText": replace_with,
        }
    }]
    return service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()


def batch_update(
    doc_id: str,
    requests: list,
    account: Optional[str] = None,
) -> dict:
    """Execute a batch of update requests on a document.

    Args:
        doc_id: The Google Doc ID
        requests: List of update request objects
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        The batchUpdate response.
    """
    validate_doc_id(doc_id)
    service = get_docs_service(account=account)
    return service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()
