"""Google Docs reading operations."""

from typing import List, Dict, Any

from .service import get_docs_service


def get_document(doc_id: str) -> dict:
    """
    Get a document's full structure.

    Args:
        doc_id: The Google Doc ID

    Returns:
        The full document object from the API including:
            - documentId
            - title
            - body (with content array)
            - revisionId
    """
    service = get_docs_service()
    return service.documents().get(documentId=doc_id).execute()


def get_document_text(doc_id: str) -> str:
    """
    Get the plain text content of a document.

    Args:
        doc_id: The Google Doc ID

    Returns:
        Plain text content of the document
    """
    doc = get_document(doc_id)
    return extract_text_from_document(doc)


def get_document_content(doc_id: str) -> dict:
    """
    Get document metadata and content.

    Args:
        doc_id: The Google Doc ID

    Returns:
        Dict with:
            - id: Document ID
            - title: Document title
            - url: URL to the document
            - text: Plain text content
            - revision_id: Current revision ID
    """
    doc = get_document(doc_id)

    return {
        "id": doc.get("documentId"),
        "title": doc.get("title"),
        "url": f"https://docs.google.com/document/d/{doc.get('documentId')}/edit",
        "text": extract_text_from_document(doc),
        "revision_id": doc.get("revisionId"),
    }


def extract_text_from_document(doc: dict) -> str:
    """
    Extract plain text from a document structure.

    Args:
        doc: The document object from the API

    Returns:
        Plain text content
    """
    content = doc.get("body", {}).get("content", [])
    text_parts = []

    for element in content:
        if "paragraph" in element:
            paragraph = element["paragraph"]
            para_text = extract_paragraph_text(paragraph)
            text_parts.append(para_text)
        elif "table" in element:
            # Extract text from table cells
            table = element["table"]
            for row in table.get("tableRows", []):
                for cell in row.get("tableCells", []):
                    for cell_content in cell.get("content", []):
                        if "paragraph" in cell_content:
                            para_text = extract_paragraph_text(cell_content["paragraph"])
                            text_parts.append(para_text)

    return "".join(text_parts)


def extract_paragraph_text(paragraph: dict) -> str:
    """
    Extract text from a paragraph element.

    Args:
        paragraph: A paragraph element from the document

    Returns:
        Plain text content of the paragraph
    """
    text = ""
    for element in paragraph.get("elements", []):
        text_run = element.get("textRun")
        if text_run:
            text += text_run.get("content", "")
    return text
