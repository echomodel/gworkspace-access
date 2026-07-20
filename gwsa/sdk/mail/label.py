"""Gmail label operations."""

import logging
from typing import Any, Dict, List, Optional

from .service import get_gmail_service

logger = logging.getLogger(__name__)


def list_labels(account: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all Gmail labels.

    Args:
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        List of label dicts with 'id', 'name', 'type' fields.
    """
    service = get_gmail_service(account=account)
    results = service.users().labels().list(userId='me').execute()
    return results.get('labels', [])


def get_or_create_label(
    label_name: str,
    account: Optional[str] = None,
) -> str:
    """Get the ID of a label by name, creating it if it doesn't exist.

    Args:
        label_name: Name of the label.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Label ID.
    """
    service = get_gmail_service(account=account)
    labels = service.users().labels().list(userId='me').execute().get('labels', [])

    for label in labels:
        if label['name'] == label_name:
            logger.debug(f"Label '{label_name}' exists with ID: {label['id']}")
            return label['id']

    logger.debug(f"Creating label '{label_name}'")
    create_body = {
        'name': label_name,
        'labelListVisibility': 'labelShow',
        'messageListVisibility': 'show'
    }
    created = service.users().labels().create(userId='me', body=create_body).execute()
    logger.debug(f"Created label '{label_name}' with ID: {created['id']}")
    return created['id']


# Gmail's batchModify accepts at most 1000 message ids per call.
_BATCH_MODIFY_LIMIT = 1000


def modify_labels(
    message_ids: List[str] | str,
    add_labels: Optional[List[str]] = None,
    remove_labels: Optional[List[str]] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """Add and/or remove labels across one or more Gmail messages.

    Applies the same label delta to every message via Gmail's
    ``messages.batchModify`` (chunked at 1000 ids per API call). Labels
    named in ``add_labels`` are created if missing; labels named in
    ``remove_labels`` that don't exist are skipped.

    The operation is idempotent: adding a label already present, or
    removing one already absent, is a silent no-op — each message
    converges to the desired state without per-message failures.

    Args:
        message_ids: One Gmail message ID or a list of them. A bare
            string is treated as a single-element list.
        add_labels: Label names to ensure present.
        remove_labels: Label names to ensure absent.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Summary dict: ``message_ids``, ``count``, ``added``, ``removed``.
        (``batchModify`` returns no per-message body, so the confirmed
        delta is reported rather than fetched message resources.)
    """
    if isinstance(message_ids, str):
        message_ids = [message_ids]

    service = get_gmail_service(account=account)

    add_label_ids = []
    remove_label_ids = []

    if add_labels:
        for name in add_labels:
            add_label_ids.append(get_or_create_label(name, account=account))

    if remove_labels:
        label_map = {l['name']: l['id'] for l in list_labels(account=account)}
        for name in remove_labels:
            if name in label_map:
                remove_label_ids.append(label_map[name])

    summary: Dict[str, Any] = {
        'message_ids': message_ids,
        'count': len(message_ids),
        'added': add_labels or [],
        'removed': remove_labels or [],
    }

    if not message_ids or (not add_label_ids and not remove_label_ids):
        return summary

    label_delta = {
        'addLabelIds': add_label_ids,
        'removeLabelIds': remove_label_ids,
    }

    for start in range(0, len(message_ids), _BATCH_MODIFY_LIMIT):
        chunk = message_ids[start:start + _BATCH_MODIFY_LIMIT]
        service.users().messages().batchModify(
            userId='me', body={'ids': chunk, **label_delta}
        ).execute()

    logger.debug(f"Modified labels on {len(message_ids)} message(s)")
    return summary
