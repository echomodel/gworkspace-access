"""Google Docs write operation: guarded ``documents.batchUpdate``.

``batchUpdate`` is the Docs API's only content-write method, and this is
gwsa's only Docs write path. Requests are passed to Google unchanged; gwsa
adds three checks around them:

1. **Revision guard** — the batch is checked and written against one
   snapshot, and sent with ``writeControl.requiredRevisionId`` so Google
   rejects it if the document changed in between.
2. **Expectations** — every request that addresses an index must state
   what is at that index (``{"text": ...}`` for a range, ``{"before": ...}``
   / ``{"after": ...}`` for a point). If any expectation does not match the
   snapshot, nothing is written. See :mod:`gwsa.sdk.docs.positions`.
3. **Change report** — after writing, the document is read back and every
   changed line is returned with its before/after ranges.
"""

from typing import Optional

from .service import get_docs_service
from .validators import validate_doc_id
from .read import get_document
from . import positions


class ExpectationError(ValueError):
    """One or more expectations did not match; nothing was written."""

    def __init__(self, failures: list[str], revision_id: Optional[str]):
        self.failures = failures
        self.revision_id = revision_id
        super().__init__("; ".join(failures))


class DocumentChangedError(ValueError):
    """The document's revision differs from the caller's required revision."""

    def __init__(self, required: str, current: Optional[str]):
        self.required = required
        self.current = current
        super().__init__(
            f"Document is at revision {current}, not the required revision "
            f"{required}. Nothing was written."
        )


def batch_update(
    doc_id: str,
    requests: list,
    expectations: Optional[list] = None,
    required_revision_id: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """Apply a Docs API ``batchUpdate`` with expectation and revision checks.

    Args:
        doc_id: The Google Doc ID.
        requests: Docs API request objects, sent to Google unchanged.
        expectations: One entry per request (``None`` for requests that
            address no index). See module docstring.
        required_revision_id: Optional — refuse unless the document is
            still at this revision (the one the caller read positions from).
        account: Optional account selector — name or email.

    Returns:
        Dict with ``document_id``, ``previous_revision_id``, ``revision_id``
        (after the write), ``replies`` (Google's, one per request), and
        ``changes`` (line-level before/after report; ``truncated`` if long).

    Raises:
        ValueError: ``requests`` is not a non-empty list of objects.
        DocumentChangedError: ``required_revision_id`` is stale.
        ExpectationError: An expectation failed or is missing.
    """
    validate_doc_id(doc_id)
    if not isinstance(requests, list) or not requests:
        raise ValueError("requests must be a non-empty list of request objects.")
    if not all(isinstance(r, dict) and len(r) == 1 for r in requests):
        raise ValueError("Each request must be an object with exactly one request type.")

    before = get_document(doc_id, account=account)
    current = before.get("revisionId")
    if required_revision_id and required_revision_id != current:
        raise DocumentChangedError(required_revision_id, current)

    failures = positions.check_expectations(before, requests, expectations)
    if failures:
        raise ExpectationError(failures, current)

    service = get_docs_service(account=account)
    result = service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests, "writeControl": {"requiredRevisionId": current}},
    ).execute()

    after = get_document(doc_id, account=account)
    report = positions.diff_documents(before, after)
    return {
        "document_id": doc_id,
        "previous_revision_id": current,
        "revision_id": after.get("revisionId"),
        "replies": result.get("replies", []),
        "changes": report["changes"],
        "truncated": report["truncated"],
    }
