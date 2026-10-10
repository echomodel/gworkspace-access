"""Google Docs write operation: guarded ``documents.batchUpdate``.

``batchUpdate`` is the Docs API's only content-write method, and this is
gwsa's only Docs write path. Each request's Docs API fields are passed to
Google unchanged; gwsa adds checks around them:

1. **Revision lock** — the caller passes the revision id of the read its
   positions came from. If the document has changed since, nothing is
   written. The batch is then checked and written against one snapshot,
   sent with ``writeControl.requiredRevisionId`` so Google rejects it if the
   document changed in between.
2. **Expectations** — every request that addresses an index carries an
   ``expect`` key (checked, then removed before sending) stating what is
   there: ``{"text": ...}`` for a range, or ``{"element": "paragraph" |
   "table"}`` when the range is exactly one whole element; ``{"before":
   ...}`` / ``{"after": ...}`` for a point. If any expectation does not
   match, nothing is written. See :mod:`gwsa.sdk.docs.positions`.
3. **Change report** — after writing, the document is read back and every
   changed line is returned with its before/after ranges. ``dry_run``
   returns the same report, predicted, without writing.
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
            f"{required}: it changed after your read. Nothing was written. "
            f"Read it again and take positions from the new read."
        )


REVISION_REQUIRED = (
    "required_revision_id is required: pass the revision_id returned by the "
    "read your positions came from (read_doc or find_in_doc), or by your "
    "previous batch_update_doc call."
)


def split_expectations(items: list) -> tuple[list, list]:
    """Separate each item's ``expect`` from its Docs API request.

    Returns ``(requests, expectations)``: the requests exactly as Google
    receives them (``expect`` removed, nothing else touched) and one
    expectation per request (``None`` where the item has none).

    Raises:
        ValueError: ``items`` is not a non-empty list of objects, or an item
            does not hold exactly one request type besides ``expect``.
    """
    if not isinstance(items, list) or not items:
        raise ValueError("requests must be a non-empty list of request objects.")
    requests, expectations = [], []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each request must be an object with exactly one request type.")
        request = {k: v for k, v in item.items() if k != "expect"}
        if len(request) != 1:
            raise ValueError(
                "Each request must be an object with exactly one request type "
                "(plus an optional 'expect')."
            )
        requests.append(request)
        expectations.append(item.get("expect"))
    return requests, expectations


def batch_update(
    doc_id: str,
    requests: list,
    required_revision_id: Optional[str] = None,
    account: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Apply a Docs API ``batchUpdate`` with expectation and revision checks.

    Args:
        doc_id: The Google Doc ID.
        requests: Docs API request objects, each optionally carrying an
            ``expect`` key (see :mod:`gwsa.sdk.docs.expect`). ``expect`` is
            checked and removed; every other key is sent to Google unchanged.
        required_revision_id: Required — the revision the caller's
            positions came from. Refused if the document has changed since.
        account: Optional account selector — name or email.
        dry_run: Check everything and return the predicted change report
            without writing.

    Returns:
        Dict with ``document_id``, ``previous_revision_id``, ``revision_id``
        (after the write), ``replies`` (Google's, one per request), and
        ``changes`` (line-level before/after report; ``truncated`` if long).
        With ``dry_run``: ``dry_run: True``, ``revision_id`` (unchanged),
        predicted ``changes``, and ``not_shown`` (requests whose effect the
        prediction does not render).

    Raises:
        ValueError: ``requests`` is not a non-empty list of objects, or
            ``required_revision_id`` is missing.
        DocumentChangedError: ``required_revision_id`` is stale.
        ExpectationError: An expectation failed or is missing.
    """
    validate_doc_id(doc_id)
    requests, expectations = split_expectations(requests)
    if not required_revision_id:
        raise ValueError(REVISION_REQUIRED)

    before = get_document(doc_id, account=account)
    current = before.get("revisionId")
    if required_revision_id != current:
        raise DocumentChangedError(required_revision_id, current)

    if dry_run:
        pv = positions.preview(before, requests, expectations)
        if pv["failures"]:
            raise ExpectationError(pv["failures"], current)
        return {
            "document_id": doc_id,
            "dry_run": True,
            "revision_id": current,
            "changes": pv["changes"],
            "truncated": pv["truncated"],
            "not_shown": pv["not_shown"],
        }

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
