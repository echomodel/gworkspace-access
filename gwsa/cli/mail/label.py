"""CLI mail label - thin wrapper around SDK."""

from gwsa.sdk.mail import modify_labels, add_label, remove_label, list_labels


def modify_message_labels(message_id: str, label_name: str, add: bool = True):
    """Add or remove a label from a message (legacy API for CLI backwards compat)."""
    if add:
        return add_label(message_id, label_name)
    else:
        return remove_label(message_id, label_name)


__all__ = ["modify_labels", "add_label", "remove_label", "list_labels", "modify_message_labels"]
