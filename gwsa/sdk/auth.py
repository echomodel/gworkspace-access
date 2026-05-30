"""Authentication and credential management for GWSA SDK.

Provides functions to load and validate Google API credentials based on
the active profile configuration.
"""

import os
import logging
from typing import Tuple, Optional, Any

logger = logging.getLogger(__name__)

# Scopes required for full GWSA functionality
REQUIRED_SCOPES = {
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
}

# Scope aliases for convenience
SCOPE_ALIASES = {
    "mail-read": "https://www.googleapis.com/auth/gmail.readonly",
    "mail-modify": "https://www.googleapis.com/auth/gmail.modify",
    "mail-labels": "https://www.googleapis.com/auth/gmail.labels",
    "mail": "https://www.googleapis.com/auth/gmail.modify",
    "sheets-read": "https://www.googleapis.com/auth/spreadsheets.readonly",
    "sheets": "https://www.googleapis.com/auth/spreadsheets",
    "docs-read": "https://www.googleapis.com/auth/documents.readonly",
    "docs": "https://www.googleapis.com/auth/documents",
    "drive-read": "https://www.googleapis.com/auth/drive.readonly",
    "drive": "https://www.googleapis.com/auth/drive",
    "tasks": "https://www.googleapis.com/auth/tasks",
    "tasks-read": "https://www.googleapis.com/auth/tasks.readonly",
    "calendar-read": "https://www.googleapis.com/auth/calendar.readonly",
    "calendar-events": "https://www.googleapis.com/auth/calendar.events",
    "calendar": "https://www.googleapis.com/auth/calendar.events",
}

# Scope implication rules (having X implies having Y)
SCOPE_IMPLICATIONS = {
    "https://www.googleapis.com/auth/gmail.modify": [
        "https://www.googleapis.com/auth/gmail.readonly",
    ],
    "https://www.googleapis.com/auth/spreadsheets": [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    ],
    "https://www.googleapis.com/auth/documents": [
        "https://www.googleapis.com/auth/documents.readonly",
    ],
    "https://www.googleapis.com/auth/drive": [
        "https://www.googleapis.com/auth/drive.readonly",
    ],
    "https://www.googleapis.com/auth/calendar.events": [
        "https://www.googleapis.com/auth/calendar.readonly",
    ],
}


def resolve_scope_alias(alias: str) -> str:
    """Resolve a scope alias to its full URL, or return the input if not an alias."""
    return SCOPE_ALIASES.get(alias, alias)


def resolve_scopes(scopes: list[str]) -> list[str]:
    """Resolve a list of aliases / feature names / full URLs into unique full URLs.

    Accepts:
    - Full scope URLs (passed through)
    - Single-URL aliases from SCOPE_ALIASES (e.g. ``mail-read``)
    - Multi-URL feature names from FEATURE_SCOPES (e.g. ``chat``)
    """
    resolved = set()
    for scope in scopes:
        if scope in FEATURE_SCOPES:
            resolved.update(FEATURE_SCOPES[scope])
        elif scope in SCOPE_ALIASES:
            resolved.add(SCOPE_ALIASES[scope])
        else:
            resolved.add(scope)
    return list(resolved)


def get_effective_scopes(granted_scopes: list) -> set:
    """
    Get effective scopes including implied ones.

    For example, if gmail.modify is granted, gmail.readonly is implied.
    """
    effective = set(granted_scopes)
    for scope in granted_scopes:
        implied = SCOPE_IMPLICATIONS.get(scope, [])
        effective.update(implied)
    return effective


def has_scope(granted_scopes: list, required_scope: str) -> bool:
    """
    Check if a required scope is available (directly or implied).

    Args:
        granted_scopes: List of granted scope URLs
        required_scope: Scope alias or URL to check

    Returns:
        True if the scope is available
    """
    required_url = resolve_scope_alias(required_scope)
    effective = get_effective_scopes(granted_scopes)
    return required_url in effective


def get_credentials(account: Optional[str] = None) -> Tuple[Any, str]:
    """Load credentials for the current mcp-app user's chosen Google account.

    Thin wrapper over :func:`get_google_account_creds` that also formats a
    human-readable source string for logging.

    Args:
        account: Optional selector — either the account ``name`` (e.g.
            ``"work"``) or its Google ``email`` (e.g.
            ``"alice@example.com"``). When omitted, falls back to the
            user's ``default_account``, or the sole account if there's
            only one. See :func:`get_google_account_creds` for the full
            resolution order and error modes.

    Returns:
        Tuple of (credentials object, source description).

    Raises:
        LookupError: No user is set on the ContextVar. Caller is
            invoking the SDK outside any request context — a
            programmer error.
        NoAccountsConfiguredError: User exists but has no Google
            accounts. Direct the operator to ``gwsa-admin accounts add``.
        AmbiguousAccountError: User has multiple accounts and no
            ``default_account``. Direct them to ``gwsa-admin accounts use``.
        AccountNotFoundError: ``account`` selector (or stale
            ``default_account``) doesn't match any account on the profile.
    """
    from mcp_app.context import current_user

    user = current_user.get()
    creds, chosen = get_google_account_creds(account=account)
    return creds, f"mcp-app user {user.email} / account '{chosen.name}'"


class AccountNotFoundError(ValueError):
    """Raised when a named account is not present on the current user's profile."""


class NoAccountsConfiguredError(ValueError):
    """Raised when the current user has no Google accounts in their profile."""


class AmbiguousAccountError(ValueError):
    """Raised when no account selector was given, no default is set, and the
    user has more than one account — so the resolver can't pick one."""


def get_google_account_creds(account: Optional[str] = None):
    """Resolve google-auth Credentials for the active mcp-app user.

    Selects a ``GoogleAccount`` from ``current_user.get().profile.accounts``
    using this order:

    1. If ``account`` is given, find that selector on the profile. The
       selector matches either ``GoogleAccount.name`` (e.g. ``"work"``)
       or ``GoogleAccount.email`` (e.g. ``"alice@example.com"``). Raise
       :class:`AccountNotFoundError` if neither matches.
    2. Otherwise, if ``profile.default_account`` is set, use it. Raise
       :class:`AccountNotFoundError` if the default points to a name
       that's no longer on the profile (stale default).
    3. Otherwise, if the profile has exactly one account, use it
       (single-account auto-inference, per docs/CLOUD-MULTI-USER.md §6).
    4. Otherwise raise :class:`AmbiguousAccountError` — the user must
       set a default or pass an explicit ``account`` argument.

    Builds a ``google.oauth2.credentials.Credentials`` from the chosen
    account's ``token`` (an authorized_user blob — same shape that
    ``Credentials.from_authorized_user_info`` consumes). Applies the
    account's ``quota_project`` if set, which becomes the
    ``x-goog-user-project`` header billed for the API call (mandatory
    for ADC-sourced credentials).

    Returns:
        Tuple of (credentials, account) where ``account`` is the
        ``GoogleAccount`` model that was selected — useful for the
        caller to inspect ``account.email`` or ``account.quota_project``
        without re-reading the profile.

    Raises:
        LookupError: No user is set on the current_user ContextVar.
            Means the caller is invoking the SDK outside any request
            (no HTTP middleware ran, stdio didn't pass --user). This
            is a programmer error, not a user error.
        NoAccountsConfiguredError: User exists but profile is empty —
            an operator registered the user but didn't add any Google
            accounts yet. Direct the user to ``gwsa-admin accounts add``.
        AccountNotFoundError: ``account`` was given (or a stale
            ``default_account`` points) to a name that isn't on the
            profile.
        AmbiguousAccountError: Multiple accounts and no selector / default.
    """
    from google.oauth2.credentials import Credentials
    from mcp_app.context import current_user

    from gwsa import Profile

    user = current_user.get()  # LookupError if not set
    profile = user.profile

    if isinstance(profile, dict):
        profile = Profile(**profile)

    if profile is None or not getattr(profile, "accounts", None):
        raise NoAccountsConfiguredError(
            f"User {user.email} has no Google accounts configured. "
            f"Add one with: gwsa-admin accounts add <name> --user {user.email}"
        )

    accounts = profile.accounts
    chosen = None

    if account is not None:
        for a in accounts:
            if a.name == account or a.email == account:
                chosen = a
                break
        if chosen is None:
            available = ", ".join(
                f"{a.name} ({a.email})" for a in accounts
            ) or "(none)"
            raise AccountNotFoundError(
                f"Account '{account}' not found for {user.email}. "
                f"Tried both name and email; available: {available}"
            )
    elif profile.default_account is not None:
        for a in accounts:
            if a.name == profile.default_account:
                chosen = a
                break
        if chosen is None:
            available = ", ".join(a.name for a in accounts) or "(none)"
            raise AccountNotFoundError(
                f"default_account='{profile.default_account}' for {user.email} "
                f"is stale — that account is no longer on the profile. "
                f"Available: {available}. Set a new default with: "
                f"gwsa-admin accounts use <name> --user {user.email}"
            )
    elif len(accounts) == 1:
        chosen = accounts[0]
    else:
        names = ", ".join(a.name for a in accounts)
        raise AmbiguousAccountError(
            f"{user.email} has multiple accounts ({names}) and no default. "
            f"Pick one with the account argument or set a default with: "
            f"gwsa-admin accounts use <name> --user {user.email}"
        )

    creds = Credentials.from_authorized_user_info(chosen.token)
    if chosen.quota_project:
        creds = creds.with_quota_project(chosen.quota_project)
    return creds, chosen


def refresh_credentials(creds) -> bool:
    """
    Refresh credentials if needed.

    Args:
        creds: Google credentials object

    Returns:
        True if refresh succeeded or not needed

    Raises:
        Exception if refresh fails
    """
    from google.auth.transport.requests import Request

    if not creds.valid:
        if creds.refresh_token:
            creds.refresh(Request())
            return True
        else:
            raise ValueError("Credentials expired and no refresh token available")
    return True


def get_token_info(creds) -> dict:
    """
    Use Google's tokeninfo endpoint to get info about a credential.

    Returns:
        A dict with:
            - scopes: list of scope strings
            - email: user email associated with the token (may be None)

    Raises:
        Exception on network error or if token is invalid.
    """
    import urllib.request
    import json
    from google.auth.transport.requests import Request

    if not creds.valid and hasattr(creds, 'refresh_token') and creds.refresh_token:
        creds.refresh(Request())

    access_token = creds.token
    if not access_token:
        raise ValueError("Credentials object has no access token.")

    url = f"https://www.googleapis.com/oauth2/v3/tokeninfo?access_token={access_token}"

    with urllib.request.urlopen(url) as response:
        if response.status == 200:
            data = json.loads(response.read().decode())
            return {
                "scopes": data.get("scope", "").split(" "),
                "email": data.get("email"),
            }
        else:
            raise ConnectionError(
                f"Tokeninfo endpoint failed with status {response.status}"
            )


# Feature scope definitions
FEATURE_SCOPES = {
    "mail": {"https://www.googleapis.com/auth/gmail.modify"},
    "sheets": {"https://www.googleapis.com/auth/spreadsheets"},
    "docs": {"https://www.googleapis.com/auth/documents"},
    "drive": {"https://www.googleapis.com/auth/drive"},
    "tasks": {"https://www.googleapis.com/auth/tasks"},
    "calendar": {
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
    },
    "chat": {
        "https://www.googleapis.com/auth/chat.spaces.readonly",
        "https://www.googleapis.com/auth/chat.messages.readonly",
        "https://www.googleapis.com/auth/chat.memberships.readonly",
        "https://www.googleapis.com/auth/directory.readonly",
    },
}

IDENTITY_SCOPES = {
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid"
}


def get_feature_status(granted_scopes: set) -> dict:
    """
    Determine if each major GWSA feature is supported by the granted scopes.

    Returns:
        A dictionary where keys are feature names and values are booleans.
    """
    effective = get_effective_scopes(list(granted_scopes))
    status = {}
    for feature, required_scopes in FEATURE_SCOPES.items():
        status[feature] = required_scopes.issubset(effective)
    return status


def get_all_scopes(workspace: bool = False) -> list[str]:
    """
    Get all scopes required for the requested feature set.

    Args:
        workspace: If True, include scopes for Google Workspace-specific features
                   (Chat, People API). If False, only include standard consumer
                   scopes (Gmail, Drive, Docs, Sheets).

    Returns:
        A list of scope URLs.
    """
    scopes = set()
    
    # Standard scopes (available to all users)
    for feature in ["mail", "sheets", "docs", "drive", "calendar"]:
        scopes.update(FEATURE_SCOPES[feature])
    
    # Workspace-specific scopes
    if workspace:
        scopes.update(FEATURE_SCOPES["chat"])
        
    # Always include identity scopes
    scopes.update(IDENTITY_SCOPES)
    
    return sorted(list(scopes))
