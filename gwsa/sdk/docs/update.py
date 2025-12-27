"""Google Docs update operations."""

from typing import Optional

from .service import get_docs_service
from .validators import validate_doc_id


def insert_text(doc_id: str, text: str, index: int = 1) -> dict:
    """
    Insert text at a specific index in a document.

    Args:
        doc_id: The Google Doc ID
        text: Text to insert
        index: Position to insert at (1 = beginning of document)

    Returns:
        The batchUpdate response
    """
    validate_doc_id(doc_id)
    service = get_docs_service()
    requests = [
        {
            "insertText": {
                "location": {"index": index},
                "text": text
            }
        }
    ]
    return service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()


def append_text(doc_id: str, text: str) -> dict:
    """
    Append text to the end of a document.

    Args:
        doc_id: The Google Doc ID
        text: Text to append

    Returns:
        The batchUpdate response
    """
    validate_doc_id(doc_id)
    service = get_docs_service()

    # Get the document to find the end index
    doc = service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])

    # Find the end index (last element's endIndex - 1 to stay before final newline)
    end_index = 1
    if content:
        last_element = content[-1]
        end_index = last_element.get("endIndex", 1) - 1

    # Ensure we have a newline before appending
    if not text.startswith("\n"):
        text = "\n" + text

    requests = [
        {
            "insertText": {
                "location": {"index": end_index},
                "text": text
            }
        }
    ]
    return service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()


def replace_text(doc_id: str, find_text: str, replace_with: str, match_case: bool = True) -> dict:
    """
    Replace all occurrences of text in a document.

    Args:
        doc_id: The Google Doc ID
        find_text: Text to find
        replace_with: Text to replace with
        match_case: Whether to match case (default True)

    Returns:
        The batchUpdate response with occurrencesChanged count
    """
    validate_doc_id(doc_id)
    service = get_docs_service()
    requests = [
        {
            "replaceAllText": {
                "containsText": {
                    "text": find_text,
                    "matchCase": match_case
                },
                "replaceText": replace_with
            }
        }
    ]
    return service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()


def batch_update(doc_id: str, requests: list) -> dict:
    """
    Execute a batch of update requests on a document.

    Args:
        doc_id: The Google Doc ID
        requests: List of update request objects

    Returns:
        The batchUpdate response
    """
    validate_doc_id(doc_id)
    service = get_docs_service()
    return service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()
