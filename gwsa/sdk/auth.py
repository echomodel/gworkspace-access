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
}


def resolve_scope_alias(alias: str) -> str:
    """Resolve a scope alias to its full URL, or return the input if not an alias."""
    return SCOPE_ALIASES.get(alias, alias)


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


def get_credentials(
    profile: str = None,
    use_adc: bool = False,
) -> Tuple[Any, str]:
    """
    Load credentials based on profile or explicit flags.

    Args:
        profile: Explicit profile name to use (overrides active profile)
        use_adc: Force use of Application Default Credentials

    Returns:
        Tuple of (credentials object, source description)

    Raises:
        ValueError: If no profile is configured or profile not found
        FileNotFoundError: If token file not found
    """
    import google.auth
    from google.oauth2.credentials import Credentials
    from .profiles import (
        ADC_PROFILE_NAME, get_active_profile_name, profile_exists,
        get_profile_token_path
    )

    # Explicit ADC flag
    if use_adc:
        creds, project = google.auth.default()
        source = "Application Default Credentials (from flag)"
        if project:
            source += f" (project: {project})"
        return creds, source

    # Explicit profile override
    if profile:
        if profile == ADC_PROFILE_NAME:
            creds, project = google.auth.default()
            source = f"Application Default Credentials (profile: {profile})"
            if project:
                source += f" (project: {project})"
            return creds, source
        elif profile_exists(profile):
            token_path = get_profile_token_path(profile)
            creds = Credentials.from_authorized_user_file(str(token_path))
            return creds, f"Profile '{profile}': {token_path}"
        else:
            raise ValueError(f"Profile not found: {profile}")

    # Use active profile
    active_profile = get_active_profile_name()
    if active_profile:
        if active_profile == ADC_PROFILE_NAME:
            creds, project = google.auth.default()
            source = f"Application Default Credentials (profile: {active_profile})"
            if project:
                source += f" (project: {project})"
            return creds, source
        elif profile_exists(active_profile):
            token_path = get_profile_token_path(active_profile)
            creds = Credentials.from_authorized_user_file(str(token_path))
            return creds, f"Profile '{active_profile}': {token_path}"
        else:
            raise ValueError(f"Active profile not found: {active_profile}")

    raise ValueError("No active profile configured. Run 'gwsa setup' or 'gwsa profiles create' first.")


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
    for feature in ["mail", "sheets", "docs", "drive"]:
        scopes.update(FEATURE_SCOPES[feature])
    
    # Workspace-specific scopes
    if workspace:
        scopes.update(FEATURE_SCOPES["chat"])
        
    # Always include identity scopes
    scopes.update(IDENTITY_SCOPES)
    
    return sorted(list(scopes))
