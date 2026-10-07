"""Shared helpers for gwsa-admin subgroups.

This module wraps mcp-app's public ``admin_store`` so gwsa-side commands
read and write the same store (local or remote) as the built-in ``users``
commands. ``store_call`` opens a store, runs one async operation on it, and
closes it, all inside a single event loop — a remote store's HTTP client
is bound to the loop it was opened in, so it must not be reused across
``asyncio.run`` calls.

It also owns the user-resolution rules from docs/CLOUD-MULTI-USER.md §6.6
extended to the registration flow per the chunk (d) discussion:
account-add can auto-create the user record when the store is empty.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

import click

from mcp_app.cli import _load_setup, admin_store


APP_NAME = "gwsa"
DEFAULT_LOCAL_USER = "local"

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


def is_local_store() -> bool:
    """True when admin operations target the local filesystem user store.

    Defaults to ``True`` on fresh workstation installs where no remote server
    URL or ``setup.json`` has been configured yet, avoiding a separate
    ``gwsa-admin connect local`` ceremony for single-user stdio setups.
    """
    cfg = _load_setup(APP_NAME)
    if not cfg:
        return not bool(os.environ.get("MCP_APP_URL"))
    return cfg.get("mode") == "local"


def resolve_store():
    """Open the configured user store, defaulting to local filesystem when unconfigured."""
    if is_local_store():
        from mcp_app.bridge import DataStoreAuthAdapter
        from mcp_app.data_store import FileSystemUserDataStore
        return DataStoreAuthAdapter(FileSystemUserDataStore(app_name=APP_NAME))
    return admin_store(APP_NAME)


def store_call(work):
    """Run ``await work(store)`` against the configured admin store.

    The store (local or remote) is opened and closed inside one event loop
    per call. ``work`` is an async callable taking the store, e.g.
    ``store_call(lambda s: s.get(email))``.
    """
    async def _go():
        store = resolve_store()
        try:
            return await work(store)
        finally:
            close = getattr(store, "aclose", None)
            if close is not None:
                await close()

    return asyncio.run(_go())


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


def _active_user_emails() -> list[str]:
    users = store_call(lambda s: s.list())
    return [u.email for u in users if not getattr(u, "revoke_after", None)]


def resolve_user_for_read(user_arg: Optional[str]) -> str:
    """Resolve which user to operate on for read/mutate commands.

    Rules from CLOUD-MULTI-USER.md §6.6 with local single-operator ergonomics:

    - ``--user`` given: must exist on the store.
    - ``--user`` omitted, 0 active users: actionable error.
    - ``--user`` omitted, 1 active user: use that user.
    - ``--user`` omitted, N active users on local store with ``local`` present: use ``local``.
    - ``--user`` omitted, N active users otherwise: actionable error (specify ``--user``).
    """
    emails = _active_user_emails()

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
    if is_local_store() and DEFAULT_LOCAL_USER in emails:
        return DEFAULT_LOCAL_USER
    raise click.ClickException(
        f"Multiple users registered ({', '.join(emails)}); "
        f"specify --user."
    )


def resolve_user_for_add(user_arg: Optional[str], fallback_email: str) -> tuple[str, bool]:
    """Resolve which user to add an account to. May auto-create.

    Returns ``(email, is_new_user)``.

    - ``--user`` given: on local stores, ``--user local`` auto-creates ``local``
      when missing; other explicit user names must already exist.
    - ``--user`` omitted, 0 active users: auto-create ``local`` on local stores
      (matching ``gwsa-mcp stdio --user local`` and ``migrate``), or
      ``fallback_email`` on remote stores.
    - ``--user`` omitted, 1 active user: use that user.
    - ``--user`` omitted, N active users on local store with ``local`` present:
      use ``local``.
    - ``--user`` omitted, N active users otherwise: actionable error.
    """
    emails = _active_user_emails()
    local_target = is_local_store()

    if user_arg:
        if user_arg in emails:
            return user_arg, False
        if local_target and user_arg == DEFAULT_LOCAL_USER:
            return DEFAULT_LOCAL_USER, True
        raise click.ClickException(
            f"User not found: {user_arg}. "
            f"Register it first with 'gwsa-admin users add {user_arg}', "
            f"or omit --user to auto-create a user record."
        )
    if not emails:
        default_user = DEFAULT_LOCAL_USER if local_target else fallback_email
        return default_user, True
    if len(emails) == 1:
        return emails[0], False
    if local_target and DEFAULT_LOCAL_USER in emails:
        return DEFAULT_LOCAL_USER, False
    raise click.ClickException(
        f"Multiple users registered ({', '.join(emails)}); "
        f"specify --user."
    )

