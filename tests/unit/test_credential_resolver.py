"""Tests for gwsa.sdk.auth.resolve_credentials_for_current_user.

The resolver bridges mcp-app's current_user ContextVar to a
google-auth Credentials. These tests stub the ContextVar with
hand-built UserRecord + Profile fixtures, so no real auth or
network is needed.
"""

import pytest
from mcp_app.context import current_user
from mcp_app.models import UserRecord

from gwsa import GoogleAccount, Profile
from gwsa.sdk.auth import (
    AccountNotFoundError,
    AmbiguousAccountError,
    NoAccountsConfiguredError,
    resolve_credentials_for_current_user,
)


def _token_blob(client_id="test-client", refresh_token="test-refresh"):
    """Minimal authorized_user blob accepted by Credentials.from_authorized_user_info."""
    return {
        "client_id": client_id,
        "client_secret": "test-secret",
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def _set_user(profile: Profile, email: str = "human@example.com"):
    """Push a UserRecord onto the current_user ContextVar and return the reset token.

    UserRecord.profile is typed as ``dict | None`` (mcp-app's middleware
    hydrates with the registered profile model at request boundary). We
    serialize back to a dict here; the resolver re-hydrates as needed.
    """
    user = UserRecord(email=email, profile=profile.model_dump(mode="json"))
    return current_user.set(user)


def test_resolves_single_account_without_selector():
    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token=_token_blob(),
            ),
        ],
    )
    tok = _set_user(profile)
    try:
        creds, account = resolve_credentials_for_current_user()
        assert account.name == "personal"
        assert account.email == "alice@example.com"
        assert creds.refresh_token == "test-refresh"
    finally:
        current_user.reset(tok)


def test_picks_named_account_when_selector_given():
    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token=_token_blob(refresh_token="personal-refresh"),
            ),
            GoogleAccount(
                name="work",
                email="alice-work@example.org",
                quota_project="example-project",
                token=_token_blob(refresh_token="work-refresh"),
            ),
        ],
        default_account="personal",
    )
    tok = _set_user(profile)
    try:
        creds, account = resolve_credentials_for_current_user(account="work")
        assert account.name == "work"
        assert creds.refresh_token == "work-refresh"
        assert creds.quota_project_id == "example-project"
    finally:
        current_user.reset(tok)


def test_falls_back_to_default_account():
    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token=_token_blob(refresh_token="personal-refresh"),
            ),
            GoogleAccount(
                name="work",
                email="alice-work@example.org",
                token=_token_blob(refresh_token="work-refresh"),
            ),
        ],
        default_account="work",
    )
    tok = _set_user(profile)
    try:
        creds, account = resolve_credentials_for_current_user()
        assert account.name == "work"
        assert creds.refresh_token == "work-refresh"
    finally:
        current_user.reset(tok)


def test_ambiguous_raises_when_no_default_and_multiple_accounts():
    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token=_token_blob(),
            ),
            GoogleAccount(
                name="work",
                email="alice-work@example.org",
                token=_token_blob(),
            ),
        ],
    )
    tok = _set_user(profile)
    try:
        with pytest.raises(AmbiguousAccountError, match="multiple accounts"):
            resolve_credentials_for_current_user()
    finally:
        current_user.reset(tok)


def test_account_not_found_when_selector_unknown():
    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token=_token_blob(),
            ),
        ],
    )
    tok = _set_user(profile)
    try:
        with pytest.raises(AccountNotFoundError, match="not found"):
            resolve_credentials_for_current_user(account="ghost")
    finally:
        current_user.reset(tok)


def test_stale_default_account_raises():
    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token=_token_blob(),
            ),
        ],
        default_account="work",
    )
    tok = _set_user(profile)
    try:
        with pytest.raises(AccountNotFoundError, match="stale"):
            resolve_credentials_for_current_user()
    finally:
        current_user.reset(tok)


def test_no_accounts_raises():
    profile = Profile(accounts=[])
    tok = _set_user(profile)
    try:
        with pytest.raises(NoAccountsConfiguredError, match="no Google accounts"):
            resolve_credentials_for_current_user()
    finally:
        current_user.reset(tok)


def test_lookup_error_when_no_user_set():
    with pytest.raises(LookupError):
        resolve_credentials_for_current_user()


def test_get_credentials_lookup_error_when_no_user_set():
    """get_credentials() has no legacy-vault fallback; outside any
    request context it raises LookupError straight through."""
    from gwsa.sdk.auth import get_credentials

    with pytest.raises(LookupError):
        get_credentials()


def test_get_credentials_delegates_to_mcp_resolver_in_request_context():
    """get_credentials() reads current_user and returns a credentials
    object plus a human-readable source string."""
    from gwsa.sdk.auth import get_credentials

    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token=_token_blob(refresh_token="from-mcp-resolver"),
            ),
        ],
    )
    tok = _set_user(profile, email="bridge-test@example.com")
    try:
        creds, source = get_credentials()
        assert creds.refresh_token == "from-mcp-resolver"
        assert "mcp-app user bridge-test@example.com" in source
        assert "'personal'" in source
    finally:
        current_user.reset(tok)


def test_quota_project_not_applied_when_unset():
    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token=_token_blob(),
            ),
        ],
    )
    tok = _set_user(profile)
    try:
        creds, _ = resolve_credentials_for_current_user()
        assert creds.quota_project_id is None
    finally:
        current_user.reset(tok)
