"""Safe recipient management and validation for unattended email delivery."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from gwsa.sdk.exceptions import GWSAError
from .send import send_message, _get_active_account_email

logger = logging.getLogger(__name__)


class UnapprovedRecipientError(GWSAError):
    """Raised when an email recipient does not match any approved safe alias."""
    pass


def _parse_env_recipients(raw_val: str) -> dict[str, str]:
    """Parse safe recipients string from environment variable.

    Supports JSON objects or comma/semicolon-separated ``alias=email`` pairs.
    """
    raw_val = raw_val.strip()
    if not raw_val:
        return {}

    # Attempt JSON parse first
    if raw_val.startswith("{") and raw_val.endswith("}"):
        try:
            parsed = json.loads(raw_val)
            if isinstance(parsed, dict):
                return {str(k).strip().lower(): str(v).strip() for k, v in parsed.items()}
        except Exception as e:
            logger.warning(f"Failed to parse safe recipients as JSON: {e}")

    # Fallback to delimiter-separated key=value pairs
    result: dict[str, str] = {}
    delimiters = [",", ";", "\n"]
    # Replace secondary delimiters with comma
    normalized = raw_val
    for d in delimiters[1:]:
        normalized = normalized.replace(d, ",")

    for item in normalized.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            alias, email = item.split("=", 1)
            alias = alias.strip().lower()
            email = email.strip()
            if alias and email:
                result[alias] = email
        elif ":" in item:
            alias, email = item.split(":", 1)
            alias = alias.strip().lower()
            email = email.strip()
            if alias and email:
                result[alias] = email

    return result


def get_safe_recipients(account: Optional[str] = None) -> dict[str, str]:
    """Resolve the active dictionary of approved safe recipient aliases.

    Resolution order:
    1. Built-in defaults: ``me`` and ``self`` strictly mapped to the active
       account's own email address. Other accounts on the profile are NOT
       included unless explicitly configured.
    2. Local configuration file: ``safe_recipients`` mapping in config.yaml.
    3. Environment variables: ``SAFE_RECIPIENTS`` and ``GWSA_SAFE_RECIPIENTS``
       (take highest precedence).

    Args:
        account: Optional account selector (name or email).

    Returns:
        Dict mapping lowercase alias names to target email addresses.
    """
    recipients: dict[str, str] = {}

    # 1. Built-in: active account email for 'me' and 'self'
    active_email = _get_active_account_email(account=account)
    if active_email:
        recipients["me"] = active_email.strip()
        recipients["self"] = active_email.strip()

    # 2. Local config file if present
    try:
        from ..config import get_config_value
        cfg_recipients = get_config_value("safe_recipients")
        if isinstance(cfg_recipients, dict):
            for k, v in cfg_recipients.items():
                recipients[str(k).strip().lower()] = str(v).strip()
    except Exception:
        pass

    # 3. Environment variables (SAFE_RECIPIENTS, then GWSA_SAFE_RECIPIENTS)
    env_fallback = os.getenv("SAFE_RECIPIENTS")
    if env_fallback:
        recipients.update(_parse_env_recipients(env_fallback))

    env_primary = os.getenv("GWSA_SAFE_RECIPIENTS")
    if env_primary:
        recipients.update(_parse_env_recipients(env_primary))

    return recipients


def resolve_safe_recipient(recipient: str, account: Optional[str] = None) -> str:
    """Validate and resolve a recipient string to an approved safe email address.

    Args:
        recipient: An approved alias (e.g. 'me', 'work', 'phone') or an exact
            email address already present in the approved safe list.
        account: Optional account selector.

    Returns:
        The target email address.

    Raises:
        UnapprovedRecipientError: If the recipient does not match any approved alias or email.
    """
    safe_map = get_safe_recipients(account=account)
    target = recipient.strip()
    target_lower = target.lower()

    # Match by alias key
    if target_lower in safe_map:
        return safe_map[target_lower]

    # Match by exact approved email address
    for approved_email in safe_map.values():
        if target_lower == approved_email.strip().lower():
            return approved_email

    allowed = sorted(list(safe_map.keys()))
    raise UnapprovedRecipientError(
        f"Recipient '{recipient}' is not an approved safe recipient. "
        f"Approved aliases: {allowed}"
    )


def send_safe_message(
    recipient: str,
    subject: str,
    body: Optional[str] = None,
    html_body: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Send an email strictly to an approved safe recipient or alias.

    Args:
        recipient: Safe alias or approved email address.
        subject: Email subject line.
        body: Optional plain-text body.
        html_body: Optional HTML body.
        account: Optional account to send from.

    Returns:
        Dict returned by send_message, augmented with ``resolved_to``.
    """
    to_email = resolve_safe_recipient(recipient, account=account)
    result = send_message(
        to=to_email,
        subject=subject,
        body=body,
        html_body=html_body,
        account=account,
    )
    result["resolved_to"] = to_email
    return result
