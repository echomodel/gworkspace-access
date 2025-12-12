"""CLI mail read - thin wrapper around SDK."""

from gwsa.sdk.mail import read_message

# Re-export for backwards compatibility with CLI imports
__all__ = ["read_message"]
