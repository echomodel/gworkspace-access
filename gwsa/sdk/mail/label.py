"""Gmail label operations."""

import logging
from typing import Dict, Any, List

from .service import get_gmail_service

logger = logging.getLogger(__name__)


def list_labels() -> List[Dict[str, Any]]:
    """List all Gmail labels.

    Returns:
        List of label dicts with 'id', 'name', 'type' fields.
    """
    service = get_gmail_service()
    results = service.users().labels().list(userId='me').execute()
    return results.get('labels', [])


def get_or_create_label(label_name: str) -> str:
    """Get the ID of a label by name, creating it if it doesn't exist.

    Args:
        label_name: Name of the label.

    Returns:
        Label ID.
    """
    service = get_gmail_service()
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


def modify_labels(
    message_id: str,
    add_labels: List[str] = None,
    remove_labels: List[str] = None,
) -> Dict[str, Any]:
    """Modify labels on a Gmail message.

    Args:
        message_id: The Gmail message ID.
        add_labels: List of label names to add.
        remove_labels: List of label names to remove.

    Returns:
        Updated message resource dict.
    """
    service = get_gmail_service()

    add_label_ids = []
    remove_label_ids = []

    if add_labels:
        for name in add_labels:
            add_label_ids.append(get_or_create_label(name))

    if remove_labels:
        label_map = {l['name']: l['id'] for l in list_labels()}
        for name in remove_labels:
            if name in label_map:
                remove_label_ids.append(label_map[name])

    if not add_label_ids and not remove_label_ids:
        return service.users().messages().get(
            userId='me', id=message_id, format='minimal'
        ).execute()

    body = {
        'addLabelIds': add_label_ids,
        'removeLabelIds': remove_label_ids,
    }

    updated = service.users().messages().modify(
        userId='me', id=message_id, body=body
    ).execute()

    logger.debug(f"Modified labels for message {message_id}")
    return updated


def add_label(message_id: str, label_name: str) -> Dict[str, Any]:
    """Add a label to a Gmail message."""
    return modify_labels(message_id, add_labels=[label_name])


def remove_label(message_id: str, label_name: str) -> Dict[str, Any]:
    """Remove a label from a Gmail message."""
    return modify_labels(message_id, remove_labels=[label_name])
