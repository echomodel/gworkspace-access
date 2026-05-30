"""``gwsa-admin migrate`` — one-shot upgrade for pre-mcp-app installs.

Before the mcp-app migration, gwsa stored credentials in a per-profile
vault under ``~/.config/gworkspace-access/profiles/<name>/``. That layout
is being replaced by mcp-app's user store, which groups everything
under one user record per human.

This command reads the legacy vault, builds one mcp-app user record
with each legacy profile becoming a ``GoogleAccount`` on the user's
profile, and writes the result via the standard store API. The legacy
vault on disk is left untouched — operators can confirm the migration
worked, then delete the old directory themselves.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click

from mcp_app.models import UserAuthRecord

from gwsa import GoogleAccount, Profile
from gwsa.admin._helpers import get_store, run


def _build_account(legacy_profile: dict) -> GoogleAccount:
    """Convert one legacy profile entry into a typed ``GoogleAccount``.

    ``legacy_profile`` is the dict shape returned by
    ``gwsa.sdk.profiles.list_profiles()`` — name, email, plus type/is_adc.
    (Legacy scope/validation metadata is intentionally not carried over —
    the token blob already holds its own scopes, and the authoritative
    check is a live tokeninfo call, not stored metadata.)
    """
    from gwsa.sdk import profiles as legacy

    name = legacy_profile["name"]
    token_path = legacy.get_profile_token_path(name)
    if not token_path.exists():
        raise click.ClickException(
            f"Legacy profile '{name}' has no token file at {token_path}. "
            f"Skip-able with --skip-broken or delete the profile dir manually."
        )
    token = json.loads(token_path.read_text())

    email = legacy_profile.get("email")
    if not email:
        raise click.ClickException(
            f"Legacy profile '{name}' has no cached email. "
            f"Run 'gwsa profiles validate' on the OLD code first, "
            f"or skip with --skip-broken."
        )

    return GoogleAccount(
        name=name,
        email=email,
        token=token,
        quota_project=token.get("quota_project_id"),
    )


@click.command("migrate")
@click.option(
    "--user-key",
    default="local",
    show_default=True,
    metavar="KEY",
    help=(
        "Identifier for the new mcp-app user record. Defaults to "
        "'local' — an opaque local-store handle for single-human "
        "installs. Pass any string; the Google account emails live "
        "inside the user's profile and never need to surface here."
    ),
)
@click.option(
    "--skip-broken",
    is_flag=True,
    default=False,
    help="Skip legacy profiles missing a token or cached email instead of erroring.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be created without writing anything.",
)
def migrate(user_key: str, skip_broken: bool, dry_run: bool):
    """Migrate the legacy ~/.config/gworkspace-access/profiles vault.

    Each legacy profile becomes one GoogleAccount on a single user
    record (one human = one user). The active legacy profile becomes
    default_account. The legacy directory is left in place — delete
    it yourself once you've verified 'gwsa-admin accounts list'.

    The new user record is keyed by ``--user-key`` (default
    ``local``). The Google account emails live on each GoogleAccount
    inside the user's profile; they never need to be the user key
    itself, and putting them there would force MCP client
    registrations to embed PII (``gwsa-mcp stdio --user EMAIL``).
    """
    from gwsa.sdk import profiles as legacy

    legacy_list = legacy.list_profiles()
    if not legacy_list:
        click.echo(
            "No legacy profiles found in ~/.config/gworkspace-access/profiles/. "
            "Nothing to migrate."
        )
        return

    active_name = legacy.get_active_profile_name()

    accounts: list[GoogleAccount] = []
    for p in legacy_list:
        try:
            accounts.append(_build_account(p))
        except click.ClickException:
            if skip_broken:
                click.echo(f"  skipped: {p['name']} (missing token or email)", err=True)
                continue
            raise

    if not accounts:
        raise click.ClickException("No legacy profiles were migrate-able.")

    profile = Profile(
        accounts=accounts,
        default_account=active_name if active_name and any(
            a.name == active_name for a in accounts
        ) else None,
    )

    if dry_run:
        click.echo(f"Would create user: {user_key}")
        click.echo(f"With {len(accounts)} account(s):")
        for a in accounts:
            marker = " (default)" if a.name == profile.default_account else ""
            click.echo(f"  - {a.name}{marker} — {a.email}")
        return

    store = get_store()
    existing = run(store.get(user_key))
    if existing:
        raise click.ClickException(
            f"User '{user_key}' already exists on the mcp-app store. "
            f"Either remove it first ('gwsa-admin users revoke {user_key}') "
            f"or pass a different --user-key."
        )

    run(store.save(
        UserAuthRecord(email=user_key, created=datetime.now(timezone.utc)),
        profile=profile.model_dump(mode="json"),
    ))

    click.echo(f"Migrated {len(accounts)} legacy profile(s) into user '{user_key}'.")
    click.echo(
        "Legacy vault at ~/.config/gworkspace-access/profiles/ is untouched. "
        "Verify with 'gwsa-admin accounts list', then delete the legacy dir "
        "when you're satisfied."
    )


