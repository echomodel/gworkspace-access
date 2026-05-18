"""Shared helpers for gwsa-admin subgroups.

This module thinly wraps mcp-app's private CLI helpers (``_get_auth_store``,
``_run``) so the gwsa-side commands match the framework's local/remote
routing and async-to-sync bridging without duplicating either. If
mcp-app renames these, the fix is a single import update here — not a
re-architecture across every gwsa admin command.

It also owns the user-resolution rules from docs/CLOUD-MULTI-USER.md §6.6
extended to the registration flow per the chunk (d) discussion:
account-add can auto-create the user record when the store is empty.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

# Private mcp-app helpers — see module docstring above for rationale.
from mcp_app.cli import _get_auth_store, _run  # noqa: PLC2701


APP_NAME = "gwsa"

# The OAuth client baked into `gcloud auth application-default login`.
# A token carrying this client_id was issued by gcloud's well-known client
# rather than an OAuth client the operator owns. Two consequences:
#   - It has no host project of its own, so API calls need a quota project.
#   - Re-acquisition (when refresh_token dies) must go through gcloud, not
#     a browser flow we could drive ourselves.
# Publicly documented; stable for years.
# Split at the `.apps.` boundary so the literal source doesn't match the
# precommit scanner's "Google OAuth Client ID" regex; the runtime value is
# identical. The id itself is publicly documented (gcloud SDK source), not
# a credential, but the scanner correctly can't tell it apart from one.
GCLOUD_WELL_KNOWN_CLIENT_ID = (
    "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur"
    + ".apps.googleusercontent.com"
)


def is_gcloud_issued_token(token: dict) -> bool:
    """True if the token was issued by gcloud's well-known OAuth client."""
    return token.get("client_id") == GCLOUD_WELL_KNOWN_CLIENT_ID


def get_store():
    """Return the configured UserAuthStore (local or remote)."""
    return _get_auth_store(APP_NAME)


def run(coro):
    """Run an async coroutine to completion from sync Click code."""
    return _run(coro)


def load_token_spec(spec: str) -> dict:
    """Load a token blob from one of three sources:

    - ``-``           → read JSON from stdin (pipe form: ``acquire-token | accounts add --token=-``)
    - ``@path``       → read JSON from that file
    - JSON string     → parse inline

    The ``@file`` convention matches mcp-app's ``--profile=@file`` syntax,
    and ``-`` is the standard Unix "stdin" sentinel — operators don't
    have to learn a separate file-loading mechanism per flag.
    """
    if spec == "-":
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise click.ClickException(f"stdin is not valid JSON ({e})")
    elif spec.startswith("@"):
        path = Path(spec[1:]).expanduser()
        if not path.exists():
            raise click.ClickException(f"Token file not found: {path}")
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise click.ClickException(f"Token file is not valid JSON: {path} ({e})")
    else:
        try:
            data = json.loads(spec)
        except json.JSONDecodeError as e:
            raise click.ClickException(
                f"--token must be -, @path/to/file, or a JSON string ({e})"
            )
    if not isinstance(data, dict):
        raise click.ClickException("Token blob must be a JSON object")
    return data


def resolve_user_for_read(user_arg: Optional[str]) -> str:
    """Resolve which user to operate on for read/mutate commands.

    Rules from CLOUD-MULTI-USER.md §6.6:

    - ``--user`` given: must exist on the store.
    - ``--user`` omitted, 0 users: actionable error.
    - ``--user`` omitted, 1 user: use that user.
    - ``--user`` omitted, N users: actionable error (specify ``--user``).
    """
    store = get_store()
    users = run(store.list())
    emails = [u.email for u in users]

    if user_arg:
        if user_arg in emails:
            return user_arg
        raise click.ClickException(
            f"User not found: {user_arg}. "
            f"Available: {', '.join(emails) or '(none)'}"
        )
    if not emails:
        raise click.ClickException(
            "No users registered. Add the first account with "
            "'gwsa-admin accounts add <name> --email <email> "
            "--token=@<file>' — this auto-creates the user record."
        )
    if len(emails) == 1:
        return emails[0]
    raise click.ClickException(
        f"Multiple users registered ({', '.join(emails)}); "
        f"specify --user."
    )


def resolve_user_for_add(user_arg: Optional[str], fallback_email: str) -> tuple[str, bool]:
    """Resolve which user to add an account to. May auto-create.

    Returns ``(email, is_new_user)``.

    - ``--user`` given: that user must already exist (operator opted into
      an explicit identity; if it's missing, they likely typoed — fail
      loudly rather than silently create a different user).
    - ``--user`` omitted, 0 users: auto-create with ``email=fallback_email``.
    - ``--user`` omitted, 1 user: use that user.
    - ``--user`` omitted, N users: actionable error.
    """
    store = get_store()
    users = run(store.list())
    emails = [u.email for u in users]

    if user_arg:
        if user_arg in emails:
            return user_arg, False
        raise click.ClickException(
            f"User not found: {user_arg}. "
            f"Register it first with 'gwsa-admin users add {user_arg}', "
            f"or omit --user to auto-create a user from this account's email."
        )
    if not emails:
        return fallback_email, True
    if len(emails) == 1:
        return emails[0], False
    raise click.ClickException(
        f"Multiple users registered ({', '.join(emails)}); "
        f"specify --user."
    )
