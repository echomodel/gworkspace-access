"""Google Docs SDK module.

Reads (structure, position map, find, Google's text exports), document
creation and listing, and one write path: guarded ``batch_update``.
"""

from .service import get_docs_service
from .create import create_document
from .read import (
    get_document,
    get_document_content,
    get_document_markdown,
    get_document_text,
    get_document_map,
    find_in_document,
    export_document,
)
from .update import batch_update, ExpectationError, DocumentChangedError
from .list import list_documents

__all__ = [
    "get_docs_service",
    "create_document",
    "get_document",
    "get_document_content",
    "get_document_markdown",
    "get_document_text",
    "get_document_map",
    "find_in_document",
    "export_document",
    "batch_update",
    "ExpectationError",
    "DocumentChangedError",
    "list_documents",
]
