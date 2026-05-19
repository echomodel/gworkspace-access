"""Google account discovery MCP tools.

Lightweight tools that expose the current user's profile shape — the
``name`` and ``email`` of each Google account, plus the
``default_account`` pointer. AI clients and MCP-aware UIs use this to
populate dropdowns and to know which selector to pass in the
``account`` parameter of every other gwsa tool.

These tools never touch Google's APIs; they read only from the
mcp-app user record bound to the current request context.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def list_google_accounts() -> dict[str, Any]:
    """List the Google accounts configured on the current user's profile.

    Returns the name and email of every account this user has registered
    with gwsa, plus a pointer to which one is the default. Use the
    ``name`` or ``email`` of any entry as the ``account`` argument on
    any other gwsa tool to operate as that specific account; omit the
    ``account`` argument to fall back to ``default_account`` (or the
    sole account when only one is configured).

    Returns:
        Dict with:
        - ``accounts``: list of ``{name, email}`` dicts (never includes
          tokens or any secret material).
        - ``default_account``: the ``name`` of the default account, or
          ``None`` if no default is set.
        - ``user_email``: the mcp-app user the listing is for (the
          human, not any specific Google account).

        On error returns ``{"error": str}``.
    """
    try:
        from mcp_app.context import current_user

        from gwsa import Profile

        user = current_user.get()
        profile = user.profile

        if isinstance(profile, dict):
            profile = Profile(**profile)

        accounts = []
        default_account = None
        if profile is not None:
            for a in getattr(profile, "accounts", []) or []:
                accounts.append({"name": a.name, "email": a.email})
            default_account = getattr(profile, "default_account", None)

        return {
            "accounts": accounts,
            "default_account": default_account,
            "user_email": user.email,
        }
    except Exception as e:
        logger.error(f"Error listing google accounts: {e}")
        return {"error": str(e)}
