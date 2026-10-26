"""Gmail filter operations (``users.settings.filters``).

A Gmail filter is a saved rule: ``criteria`` (sender, recipient, subject,
a search query, …) plus an ``action`` (labels to add or remove, an
address to forward to). Gmail applies it to **mail that arrives after
the filter exists**; nothing already in the mailbox changes. The API has
``list``, ``get``, ``create`` and ``delete`` — there is no update, so a
change is "create the replacement, then delete the old one by id".

Scopes: ``list`` and ``get`` work with ``gmail.modify``; ``create`` and
``delete`` need ``gmail.settings.basic`` (see
:class:`FilterScopeError`).

Behavior the CLI/MCP layers rely on:

- **Label names in, label names out.** Actions are given as label
  names and resolved to ids the same way :func:`gwsa.sdk.mail.modify_labels`
  does: a label to add is created if missing; a label to remove must
  exist (:class:`UnknownLabelError` otherwise — a filter that removes a
  label nobody has would be a silent no-op). Returned filters carry
  names, with the ids kept alongside.
- **No duplicate criteria.** ``create_filter`` lists the account's
  filters first and refuses (:class:`DuplicateFilterError`, carrying the
  existing filter) when one already has exactly the same criteria.
- **Forwarding errors are passed through.** Gmail only forwards to an
  address already verified in the account's settings; its rejection is
  surfaced with the API's own message.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from googleapiclient.errors import HttpError

from .label import get_or_create_label, list_labels
from .service import get_gmail_service

logger = logging.getLogger(__name__)

FILTERS_SCOPE = "https://www.googleapis.com/auth/gmail.settings.basic"

SIZE_COMPARISONS = ("smaller", "larger")

# System labels whose presence in an action reads as a verb.
_ADD_VERBS = {
    "STARRED": "star",
    "TRASH": "trash",
    "SPAM": "mark spam",
    "IMPORTANT": "mark important",
}
_REMOVE_VERBS = {
    "INBOX": "archive",
    "UNREAD": "mark read",
}


class FilterScopeError(Exception):
    """The account's token lacks ``gmail.settings.basic``.

    Creating or deleting a filter needs that scope; listing does not. A
    token acquired before gwsa requested it must be re-acquired (the
    message carries the commands).
    """

    def __init__(self):
        super().__init__(
            "This account's stored token lacks the "
            f"{FILTERS_SCOPE} scope, which creating or deleting a Gmail "
            "filter requires (listing works without it). Re-acquire the "
            "token with the current scope set and store it on the same "
            "account: gwsa-admin acquire-token --client-secrets "
            "/path/to/client_secrets.json | gwsa-admin accounts add <name> "
            "--email <email> --token=- . For a gcloud-issued token, re-run "
            "gcloud auth application-default login with that scope added "
            "to --scopes. 'gwsa status' shows the scopes a token carries."
        )


class DuplicateFilterError(Exception):
    """A filter with exactly the same criteria already exists."""

    def __init__(self, existing: dict):
        self.existing = existing
        super().__init__(
            f"A filter with the same criteria already exists (id "
            f"{existing['id']}: {existing['summary']}). Nothing was created. "
            "To change what it does, create the replacement with different "
            "criteria or delete this one by id first, then create."
        )


class UnknownLabelError(ValueError):
    """A label named in ``remove_labels`` does not exist on the account."""

    def __init__(self, name: str, available: List[str]):
        self.name = name
        super().__init__(
            f"Label '{name}' does not exist on this account, so a filter "
            "removing it would do nothing. Nothing was created. Labels "
            f"available: {', '.join(sorted(available))}"
        )


# --- Criteria ---------------------------------------------------------------

def build_criteria(
    from_address: Optional[str] = None,
    to_address: Optional[str] = None,
    subject: Optional[str] = None,
    query: Optional[str] = None,
    negated_query: Optional[str] = None,
    has_attachment: Optional[bool] = None,
    size: Optional[int] = None,
    size_comparison: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Gmail ``FilterCriteria`` body from gwsa's parameters.

    Only set fields are sent. At least one criterion is required; ``size``
    and ``size_comparison`` must be given together.
    """
    criteria: Dict[str, Any] = {}
    if from_address:
        criteria["from"] = from_address
    if to_address:
        criteria["to"] = to_address
    if subject:
        criteria["subject"] = subject
    if query:
        criteria["query"] = query
    if negated_query:
        criteria["negatedQuery"] = negated_query
    if has_attachment:
        criteria["hasAttachment"] = True
    if (size is None) != (size_comparison is None):
        raise ValueError(
            "size and size_comparison must be given together "
            "(size in bytes; size_comparison 'smaller' or 'larger')."
        )
    if size is not None:
        if size_comparison not in SIZE_COMPARISONS:
            raise ValueError(
                f"size_comparison must be one of {SIZE_COMPARISONS}, "
                f"got {size_comparison!r}."
            )
        if size <= 0:
            raise ValueError("size must be a positive number of bytes.")
        criteria["size"] = int(size)
        criteria["sizeComparison"] = size_comparison
    if not criteria:
        raise ValueError(
            "A filter needs at least one criterion: from_address, "
            "to_address, subject, query, negated_query, has_attachment, "
            "or size with size_comparison."
        )
    return criteria


def _criteria_key(criteria: Optional[dict]) -> Dict[str, Any]:
    """Criteria reduced to what Gmail will match on, for equality checks.

    The API omits unset fields and sometimes echoes defaults
    (``sizeComparison: "unspecified"``, ``hasAttachment: false``), so two
    equal filters can serialize differently. Drop every falsy field and
    the unspecified comparison before comparing.
    """
    key: Dict[str, Any] = {}
    for field, value in (criteria or {}).items():
        if value in (None, False, "", 0):
            continue
        if field == "sizeComparison" and value == "unspecified":
            continue
        key[field] = value
    return key


# --- Action -----------------------------------------------------------------

def _match_label_id(name: str, label_map: Dict[str, str]) -> Optional[str]:
    """Label id for ``name``: exact match first, then case-insensitive.

    System labels are canonically upper-case (``INBOX``, ``STARRED``);
    the fallback lets ``inbox`` resolve to the same label.
    """
    if name in label_map:
        return label_map[name]
    lowered = name.lower()
    for candidate, label_id in label_map.items():
        if candidate.lower() == lowered:
            return label_id
    return None


def build_action(
    add_labels: Optional[List[str]] = None,
    remove_labels: Optional[List[str]] = None,
    forward: Optional[str] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Gmail ``FilterAction`` body, resolving label names to ids.

    Labels to add are created if missing (as ``modify_labels`` does).
    Labels to remove must exist. At least one of ``add_labels``,
    ``remove_labels``, ``forward`` is required.
    """
    add_labels = [n for n in (add_labels or []) if n]
    remove_labels = [n for n in (remove_labels or []) if n]
    if not add_labels and not remove_labels and not forward:
        raise ValueError(
            "A filter needs at least one action: add_labels, "
            "remove_labels, or forward."
        )

    action: Dict[str, Any] = {}
    label_map: Optional[Dict[str, str]] = None
    if add_labels or remove_labels:
        label_map = {l["name"]: l["id"] for l in list_labels(account=account)}

    if add_labels:
        ids = []
        for name in add_labels:
            label_id = _match_label_id(name, label_map)
            if label_id is None:
                label_id = get_or_create_label(name, account=account)
                label_map[name] = label_id
            ids.append(label_id)
        action["addLabelIds"] = ids

    if remove_labels:
        ids = []
        for name in remove_labels:
            label_id = _match_label_id(name, label_map)
            if label_id is None:
                raise UnknownLabelError(name, list(label_map))
            ids.append(label_id)
        action["removeLabelIds"] = ids

    if forward:
        action["forward"] = forward
    return action


# --- Normalized shape --------------------------------------------------------

def _summarize(criteria: dict, action: dict) -> str:
    """One line a person can read: ``from:x subject:y → archive, label Z``."""
    parts = []
    if criteria.get("from"):
        parts.append(f"from:{criteria['from']}")
    if criteria.get("to"):
        parts.append(f"to:{criteria['to']}")
    if criteria.get("subject"):
        parts.append(f"subject:{criteria['subject']}")
    if criteria.get("query"):
        parts.append(criteria["query"])
    if criteria.get("negatedQuery"):
        parts.append(f"-({criteria['negatedQuery']})")
    if criteria.get("hasAttachment"):
        parts.append("has:attachment")
    if criteria.get("size"):
        op = "<" if criteria.get("sizeComparison") == "smaller" else ">"
        parts.append(f"size{op}{criteria['size']}")

    verbs = []
    for name in action.get("remove_labels", []):
        verbs.append(_REMOVE_VERBS.get(name, f"remove label {name}"))
    for name in action.get("add_labels", []):
        verbs.append(_ADD_VERBS.get(name, f"label {name}"))
    if action.get("forward"):
        verbs.append(f"forward to {action['forward']}")
    return f"{' '.join(parts)} → {', '.join(verbs)}"


def _normalize(raw: dict, id_to_name: Dict[str, str]) -> Dict[str, Any]:
    """Reshape a raw API filter: names beside ids, plus a summary line."""
    criteria = _criteria_key(raw.get("criteria"))
    raw_action = raw.get("action") or {}
    add_ids = list(raw_action.get("addLabelIds") or [])
    remove_ids = list(raw_action.get("removeLabelIds") or [])
    action = {
        "add_labels": [id_to_name.get(i, i) for i in add_ids],
        "remove_labels": [id_to_name.get(i, i) for i in remove_ids],
        "forward": raw_action.get("forward"),
        "add_label_ids": add_ids,
        "remove_label_ids": remove_ids,
    }
    return {
        "id": raw.get("id"),
        "criteria": criteria,
        "action": action,
        "summary": _summarize(criteria, action),
    }


def _label_names(account: Optional[str]) -> Dict[str, str]:
    return {l["id"]: l["name"] for l in list_labels(account=account)}


def _translate(e: HttpError, forward: Optional[str] = None) -> Exception:
    """Map an API rejection to a typed error where one applies."""
    status = getattr(e, "status_code", None) or getattr(e.resp, "status", None)
    text = str(e)
    if status == 403 and (
        "insufficient" in text.lower() or "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in text
    ):
        return FilterScopeError()
    if forward and status == 400:
        reason = getattr(e, "reason", None) or text
        return ValueError(
            f"Gmail rejected the filter's forward action: {reason}. Gmail "
            f"only forwards to an address already added and verified under "
            f"Settings → Forwarding and POP/IMAP in that account; verify "
            f"{forward} there first. Nothing was created."
        )
    return e


# --- Operations -------------------------------------------------------------

def list_filters(account: Optional[str] = None) -> List[Dict[str, Any]]:
    """List every filter on the account (``settings.filters.list``).

    Returns normalized filters: ``id``, ``criteria`` (API fields that are
    set), ``action`` (label names, ids, forward) and a ``summary`` line.
    """
    service = get_gmail_service(account=account)
    try:
        raw = service.users().settings().filters().list(userId="me").execute()
    except HttpError as e:
        raise _translate(e) from e
    id_to_name = _label_names(account)
    return [_normalize(f, id_to_name) for f in raw.get("filter", [])]


def get_filter(filter_id: str, account: Optional[str] = None) -> Dict[str, Any]:
    """Fetch one filter by id (``settings.filters.get``)."""
    if not filter_id:
        raise ValueError("filter_id is required.")
    service = get_gmail_service(account=account)
    try:
        raw = service.users().settings().filters().get(
            userId="me", id=filter_id
        ).execute()
    except HttpError as e:
        raise _translate(e) from e
    return _normalize(raw, _label_names(account))


def create_filter(
    from_address: Optional[str] = None,
    to_address: Optional[str] = None,
    subject: Optional[str] = None,
    query: Optional[str] = None,
    negated_query: Optional[str] = None,
    has_attachment: Optional[bool] = None,
    size: Optional[int] = None,
    size_comparison: Optional[str] = None,
    add_labels: Optional[List[str]] = None,
    remove_labels: Optional[List[str]] = None,
    forward: Optional[str] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a filter (``settings.filters.create``).

    Builds the criteria and action, refuses a duplicate of an existing
    filter's criteria, and returns the created filter normalized. The
    filter applies to mail arriving from now on only.

    Raises:
        ValueError: no criterion, no action, or inconsistent size fields.
        UnknownLabelError: a label in ``remove_labels`` does not exist.
        DuplicateFilterError: a filter with the same criteria exists.
        FilterScopeError: the token lacks ``gmail.settings.basic``.
    """
    criteria = build_criteria(
        from_address=from_address,
        to_address=to_address,
        subject=subject,
        query=query,
        negated_query=negated_query,
        has_attachment=has_attachment,
        size=size,
        size_comparison=size_comparison,
    )
    # Duplicate check before the action is built, so a refused create
    # never leaves behind a label it would have created.
    wanted = _criteria_key(criteria)
    for existing in list_filters(account=account):
        if existing["criteria"] == wanted:
            raise DuplicateFilterError(existing)

    action = build_action(
        add_labels=add_labels,
        remove_labels=remove_labels,
        forward=forward,
        account=account,
    )

    service = get_gmail_service(account=account)
    try:
        created = service.users().settings().filters().create(
            userId="me", body={"criteria": criteria, "action": action}
        ).execute()
    except HttpError as e:
        raise _translate(e, forward=forward) from e
    logger.debug(f"Created filter {created.get('id')}")
    return _normalize(created, _label_names(account))


def delete_filter(filter_id: str, account: Optional[str] = None) -> Dict[str, Any]:
    """Delete one filter by id (``settings.filters.delete``).

    Only the filter named by ``filter_id`` is touched; there is no
    bulk or criteria-based delete.
    """
    if not filter_id or not str(filter_id).strip():
        raise ValueError("filter_id is required; pass the id from list_filters.")
    service = get_gmail_service(account=account)
    try:
        service.users().settings().filters().delete(
            userId="me", id=filter_id
        ).execute()
    except HttpError as e:
        raise _translate(e) from e
    logger.debug(f"Deleted filter {filter_id}")
    return {"id": filter_id, "deleted": True}
