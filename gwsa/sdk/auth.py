"""Authentication and credential management for GWSA SDK.

Provides functions to load and validate Google API credentials based on
the active profile configuration.
"""

import os
import time
import logging
from contextvars import ContextVar
from typing import Tuple, Optional, Any

logger = logging.getLogger(__name__)

# CLI-set account selection. The gwsa domain CLI runs one account per
# process invocation; ``gwsa --account NAME`` records the choice here so
# the credential resolver picks it exactly as an explicit per-call
# ``account=`` would — overriding the profile's ``default_account`` but
# yielding to an explicit per-call argument. This mirrors how the CLI
# already sets ``current_user`` for the SDK. It stays None in HTTP/MCP
# mode, where each tool call passes its own ``account`` argument instead.
_cli_account_override: ContextVar[Optional[str]] = ContextVar(
    "gwsa_cli_account_override", default=None
)


def set_cli_account(account: Optional[str]) -> None:
    """Record the CLI's ``--account`` selection for the credential resolver.

    Called once by the gwsa domain CLI's top-level group callback. A
    ``None`` selection is a no-op (resolver falls back to
    ``default_account``).
    """
    _cli_account_override.set(account)

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

    user = current_user.get()  # LookupError if not set or None
    if user is None:
        raise LookupError("No active mcp-app user in request context.")
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

    # A CLI ``--account`` selection behaves exactly like an explicit
    # per-call ``account=`` argument: it wins over ``default_account``,
    # but an explicit per-call argument (account is not None) wins over it.
    if account is None:
        account = _cli_account_override.get()

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
            raw_scope = data.get("scope", "")
            scopes = [s for s in raw_scope.split(" ") if s]
            return {
                "scopes": scopes,
                "email": data.get("email"),
            }
        else:
            raise ConnectionError(
                f"Tokeninfo endpoint failed with status {response.status}"
            )


def get_auth_status(
    account: Optional[str] = None,
    run_smoke_tests: bool = False,
    compare_adc: bool = False,
    check_gcp: bool = False,
) -> dict:
    """Collect workstation authentication state, profile configuration, and OAuth token status.

    Args:
        account: Optional account handle or email selector.
        run_smoke_tests: If True, execute non-mutating read-only smoke tests across services.
        compare_adc: If True, inspect local Application Default Credentials (ADC).
        check_gcp: If True, inspect GCP quota project and Service Usage API status.

    Returns:
        Dict containing auth status metadata, all profiles/accounts, and optionally
        smoke_tests, adc, & gcp info.
    """
    from mcp_app.context import current_user
    from gwsa.admin._helpers import is_local_store, store_call

    user = current_user.get()
    if user is None:
        res = {
            "store_mode": "local (~/.local/share/gwsa/users/)" if is_local_store() else "remote",
            "active_user": "(none)",
            "default_account": "(none)",
            "quota_project": "(none)",
            "all_users": [],
            "all_accounts": [],
            "token_status": "NO USER",
            "granted_scopes": [],
        }
        if run_smoke_tests:
            res["smoke_tests"] = {}
            res["smoke_test_errors"] = []
        if compare_adc:
            res["adc"] = get_adc_status()
        if check_gcp:
            res["gcp"] = get_gcp_status(account=account)
        return res

    store_mode = "local (~/.local/share/gwsa/users/)" if is_local_store() else "remote"
    active_user = user.email

    try:
        users = store_call(lambda s: s.list())
        all_users = [
            f"{u.email}{' [active]' if u.email == active_user else ''}"
            for u in users
            if not getattr(u, "revoke_after", None)
        ]
    except Exception:
        all_users = [f"{active_user} [active]"] if active_user != "(none)" else []

    all_accounts = []
    if user and getattr(user, "profile", None) and getattr(user.profile, "accounts", None):
        for a in user.profile.accounts:
            is_def = (a.name == user.profile.default_account)
            all_accounts.append(f"{a.name} ({a.email}){' [default]' if is_def else ''}")

    try:
        creds, chosen_account = get_google_account_creds(account=account)
        account_name = chosen_account.name
        account_email = chosen_account.email
        quota_project = chosen_account.quota_project or "(none)"
        default_account_str = f"{account_name} ({account_email})"

        try:
            if not creds.valid and hasattr(creds, 'refresh_token') and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())

            token_info = get_token_info(creds)
            token_status = "VALID"
            granted_scopes = token_info.get("scopes", [])
        except Exception as exc:
            token_status = f"INVALID ({exc})"
            granted_scopes = []
    except NoAccountsConfiguredError:
        default_account_str = "(none)"
        quota_project = "(none)"
        token_status = "NO TOKEN"
        granted_scopes = []
    except Exception as exc:
        default_account_str = "(none)"
        quota_project = "(none)"
        token_status = f"INVALID ({exc})"
        granted_scopes = []

    res = {
        "store_mode": store_mode,
        "active_user": active_user,
        "default_account": default_account_str,
        "quota_project": quota_project,
        "all_users": all_users,
        "all_accounts": all_accounts,
        "token_status": token_status,
        "granted_scopes": granted_scopes,
    }

    if run_smoke_tests:
        smoke_tests, smoke_test_errors = run_service_smoke_tests(granted_scopes)
        res["smoke_tests"] = smoke_tests
        res["smoke_test_errors"] = smoke_test_errors

    if compare_adc:
        res["adc"] = get_adc_status()

    if check_gcp:
        res["gcp"] = get_gcp_status(account=account)

    return res


def get_gcp_status(account: Optional[str] = None) -> dict:
    """Inspect GCP Quota Project configuration and optional Service Usage enablement.

    Returns:
        Dict containing quota_project, quota_project_status, api_statuses, errors.
    """
    from gwsa.admin._helpers import is_gcloud_issued_token

    try:
        creds, chosen = get_google_account_creds(account=account)
        quota_project = chosen.quota_project or "(none)"
        is_gcloud = is_gcloud_issued_token(chosen.token or {})
    except Exception as exc:
        return {
            "quota_project": "(none)",
            "quota_project_status": f"NO CREDENTIALS ({exc})",
            "api_statuses": {},
            "errors": [],
        }

    if quota_project == "(none)":
        status_msg = "⚠️ MISSING (Quota project required for gcloud billing)" if is_gcloud else "(none)"
        return {
            "quota_project": "(none)",
            "quota_project_status": status_msg,
            "api_statuses": {},
            "errors": [],
        }

    required_apis = {
        "Gmail API": "gmail.googleapis.com",
        "Drive API": "drive.googleapis.com",
        "Docs API": "docs.googleapis.com",
        "Sheets API": "sheets.googleapis.com",
        "Calendar API": "calendar-json.googleapis.com",
        "Chat API": "chat.googleapis.com",
    }

    api_statuses = {}
    errors = []

    def _probe_serviceusage():
        from googleapiclient.discovery import build
        service = build("serviceusage", "v1", credentials=creds)
        resp = service.services().list(
            parent=f"projects/{quota_project}",
            filter="state:ENABLED",
            pageSize=200,
        ).execute()

        enabled_services = {
            item.get("config", {}).get("name"): item.get("state")
            for item in resp.get("services", [])
        }

        for api_name, api_id in required_apis.items():
            if enabled_services.get(api_id) == "ENABLED":
                api_statuses[api_name] = "✅ ENABLED"
            else:
                api_statuses[api_name] = f"❌ DISABLED ({api_id})"

        return f"✅ AUTHORIZED (quota project: {quota_project})"

    try:
        quota_status = _run_with_timeout(_probe_serviceusage, timeout_seconds=PROBE_TIMEOUT_SECONDS)
    except Exception as exc:
        quota_status = f"⏭️ SKIPPED ({exc})"
        for api_name in required_apis:
            api_statuses[api_name] = "⏭️ UNKNOWN (serviceusage API unavailable)"

    return {
        "quota_project": quota_project,
        "quota_project_status": quota_status,
        "api_statuses": api_statuses,
        "errors": errors,
    }


def get_adc_status() -> dict:
    """Inspect local Application Default Credentials (ADC) state and live tokeninfo.

    Returns:
        Dict containing:
            - adc_file: str
            - status: str
            - email: str
            - quota_project: str
            - client_id: str
            - granted_scopes: list[str]
    """
    import json
    from pathlib import Path

    adc_path_str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.path.expanduser(
        "~/.config/gcloud/application_default_credentials.json"
    )
    adc_path = Path(adc_path_str)

    if not adc_path.exists():
        return {
            "adc_file": adc_path_str,
            "status": "NOT FOUND",
            "email": "(none)",
            "quota_project": "(none)",
            "client_id": "(none)",
            "granted_scopes": [],
        }

    try:
        data = json.loads(adc_path.read_text())
        client_id = data.get("client_id", "(none)")
        quota_project = data.get("quota_project_id", "(none)")

        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_info(data)

        if not creds.valid and hasattr(creds, 'refresh_token') and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())

        token_info = get_token_info(creds)
        email = token_info.get("email") or "(unknown)"
        granted_scopes = token_info.get("scopes", [])
        status = "VALID"
    except Exception as exc:
        email = "(unknown)"
        granted_scopes = []
        status = f"INVALID ({exc})"

    return {
        "adc_file": adc_path_str,
        "status": status,
        "email": email,
        "quota_project": quota_project,
        "client_id": client_id,
        "granted_scopes": granted_scopes,
    }


PROBE_TIMEOUT_SECONDS = 5.0


def _run_with_timeout(fn, timeout_seconds: float = PROBE_TIMEOUT_SECONDS):
    """Execute a function inside a worker thread with a hard timeout and ContextVar inheritance."""
    import contextvars
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

    ctx = contextvars.copy_context()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(ctx.run, fn)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            raise TimeoutError(f"Probe timed out after {timeout_seconds} seconds")


def run_service_smoke_tests(granted_scopes: list) -> Tuple[dict, list]:
    """Run safe, non-mutating read-only smoke tests across Google Workspace services.

    Args:
        granted_scopes: List of scope URLs granted to the current token.

    Returns:
        Tuple of (service_results_dict, error_details_list) where:
            - service_results_dict maps service names (Gmail, Drive, Docs, Sheets, Calendar, Chat)
              to dicts with keys "status" and "probe".
            - error_details_list contains dicts with keys: service, step, error.
    """
    from gwsa.sdk import mail as sdk_mail
    from gwsa.sdk import drive as sdk_drive
    from gwsa.sdk import docs as sdk_docs
    from gwsa.sdk import sheets as sdk_sheets
    from gwsa.sdk import calendar as sdk_calendar
    from gwsa.sdk import chat as sdk_chat

    feature_status = get_feature_status(set(granted_scopes))

    results = {}
    errors = []

    tests = [
        (
            "Gmail",
            "mail",
            'gwsa mail search "label:INBOX" --max-results 1',
            lambda: sdk_mail.search_messages("label:INBOX", max_results=1),
        ),
        (
            "Drive",
            "drive",
            'gwsa drive search "trashed = false" --max-results 1',
            lambda: sdk_drive.search_drive("trashed = false", max_results=1),
        ),
        (
            "Docs",
            "docs",
            "gwsa docs list --limit 1",
            lambda: sdk_docs.list_documents(max_results=1),
        ),
        (
            "Sheets",
            "sheets",
            "gwsa sheets list --limit 1",
            lambda: sdk_sheets.list_spreadsheets(max_results=1),
        ),
        (
            "Calendar",
            "calendar",
            "gwsa calendar list --limit 1",
            lambda: sdk_calendar.list_calendars(),
        ),
        (
            "Chat",
            "chat_spaces",
            "gwsa chat spaces list --limit 1",
            lambda: sdk_chat.get_chat_service().spaces().list(pageSize=1).execute(),
        ),
    ]

    for name, feature_key, step_desc, test_fn in tests:
        if not feature_status.get(feature_key, False):
            results[name] = {
                "status": "⏭️ SKIPPED (missing scope)",
                "latency_ms": None,
                "probe": step_desc,
            }
            continue

        start_time = time.perf_counter()
        try:
            _run_with_timeout(test_fn, timeout_seconds=PROBE_TIMEOUT_SECONDS)
            duration_ms = round((time.perf_counter() - start_time) * 1000)
            results[name] = {
                "status": "✅ PASS",
                "latency_ms": duration_ms,
                "probe": step_desc,
            }
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000)
            results[name] = {
                "status": "❌ FAIL",
                "latency_ms": duration_ms,
                "probe": step_desc,
            }
            errors.append({
                "service": name,
                "step": step_desc,
                "latency_ms": duration_ms,
                "error": str(exc),
            })

    return results, errors


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
    "chat_spaces": {"https://www.googleapis.com/auth/chat.spaces.readonly"},
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
    "openid",
    "email",
    "profile",
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
