"""CLI mail search - thin wrapper around SDK."""

from gwsa.sdk.mail import search_messages

# Re-export for backwards compatibility with CLI imports
__all__ = ["search_messages"]
