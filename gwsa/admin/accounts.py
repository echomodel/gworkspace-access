"""``gwsa-admin accounts`` subgroup — manage Google accounts on a user profile.

A gwsa user holds a ``Profile`` with a list of ``GoogleAccount`` entries
(see ``gwsa.__init__``). These commands are sugar over mcp-app's
``store.update_profile`` primitive — they read the user's profile,
mutate ``accounts`` or ``default_account``, and write back. No new
storage path, no framework assumptions broken.

See docs/CLOUD-MULTI-USER.md §6 for the architectural model and §6.5
for the command surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import click

from mcp_app.models import UserAuthRecord

from gwsa import GoogleAccount, Profile
from gwsa.admin._helpers import (
    get_store,
    is_gcloud_issued_token,
    load_token_spec,
    resolve_user_for_add,
    resolve_user_for_read,
    run,
)


def _load_profile(user_email: str) -> Profile:
    """Load a user's profile as a typed ``Profile``. Empty profile on a new user."""
    store = get_store()
    user_record = run(store.get_full(user_email))
    if user_record is None:
        return Profile()
    raw = user_record.profile or {}
    return Profile(**raw) if isinstance(raw, dict) else raw


def _save_profile(user_email: str, profile: Profile) -> None:
    """Write the full profile back via mcp-app's update_profile primitive."""
    store = get_store()
    run(store.update_profile(user_email, profile.model_dump(mode="json")))


@click.group("accounts")
def accounts_group():
    """Manage the Google accounts on a user's profile."""


@accounts_group.command("add")
@click.argument("name")
@click.option(
    "--email",
    required=True,
    help="The Google account email (as it appears on tokeninfo).",
)
@click.option(
    "--token",
    "token_spec",
    required=True,
    help="Token blob. - for stdin, @path/to/file.json for a file, or inline JSON.",
)
@click.option(
    "--quota-project",
    default=None,
    help=(
        "GCP project billed for API usage. Overrides the blob's quota_project_id "
        "if present. Required when the token was issued by gcloud's well-known "
        "OAuth client (gcloud's client has no host project of its own)."
    ),
)
@click.option(
    "--user",
    "user_arg",
    default=None,
    help=(
        "Target user email. If omitted and the store is empty, the user record "
        "is auto-created using --email. If omitted and exactly one user exists, "
        "that user is used. Required when multiple users exist."
    ),
)
def accounts_add(name, email, token_spec, quota_project, user_arg):
    """Add a Google account to a user's profile.

    When the store has no users yet, this command auto-creates the user
    record with the account's --email. This keeps the single-user local
    install one step: there is no separate 'create the user first'
    ceremony for the common case.
    """
    token = load_token_spec(token_spec)

    # Resolve quota_project: explicit flag wins; else blob's quota_project_id;
    # else None. Guard: gcloud-issued tokens MUST end up with one.
    effective_quota = quota_project or token.get("quota_project_id")
    if is_gcloud_issued_token(token) and not effective_quota:
        raise click.ClickException(
            "This token was issued by gcloud's well-known OAuth client, which "
            "has no host project of its own. Pass --quota-project <GCP_PROJECT> "
            "(or set it on the blob with `gcloud auth application-default "
            "set-quota-project <id>` before adding)."
        )

    user_email, is_new_user = resolve_user_for_add(user_arg, fallback_email=email)

    store = get_store()
    if is_new_user:
        run(store.save(
            UserAuthRecord(email=user_email, created=datetime.now(timezone.utc)),
            profile=None,
        ))

    profile = _load_profile(user_email)
    if any(a.name == name for a in profile.accounts):
        raise click.ClickException(
            f"Account '{name}' already exists for {user_email}. "
            f"Remove it first with 'gwsa-admin accounts remove {name}' or use a different name."
        )

    profile.accounts.append(GoogleAccount(
        name=name,
        email=email,
        quota_project=effective_quota,
        token=token,
    ))

    if profile.default_account is None:
        profile.default_account = name
        default_changed = True
    else:
        default_changed = False

    _save_profile(user_email, profile)

    click.echo(f"Added account '{name}' ({email}) to user {user_email}")
    if is_new_user:
        click.echo(f"  (auto-created user record for {user_email})")
    if default_changed:
        click.echo(f"  (set as default account)")


@accounts_group.command("list")
@click.option("--user", "user_arg", default=None, help="Target user email.")
def accounts_list(user_arg):
    """List the Google accounts on a user's profile."""
    user_email = resolve_user_for_read(user_arg)
    profile = _load_profile(user_email)

    if not profile.accounts:
        click.echo(f"No accounts on user {user_email}.")
        return

    click.echo(f"Accounts for {user_email}:")
    for a in profile.accounts:
        marker = " (default)" if a.name == profile.default_account else ""
        quota = f" quota={a.quota_project}" if a.quota_project else ""
        client = " [gcloud]" if is_gcloud_issued_token(a.token) else ""
        click.echo(f"  {a.name}{marker} — {a.email}{client}{quota}")


@accounts_group.command("get")
@click.argument("name")
@click.option("--user", "user_arg", default=None, help="Target user email.")
@click.option(
    "--show-token",
    is_flag=True,
    default=False,
    help="Include the raw token blob in output (sensitive — usually omit).",
)
def accounts_get(name, user_arg, show_token):
    """Show details of one account on a user's profile."""
    user_email = resolve_user_for_read(user_arg)
    profile = _load_profile(user_email)
    account = next((a for a in profile.accounts if a.name == name), None)
    if account is None:
        available = ", ".join(a.name for a in profile.accounts) or "(none)"
        raise click.ClickException(
            f"Account '{name}' not found for {user_email}. Available: {available}"
        )

    is_default = (account.name == profile.default_account)
    data = account.model_dump(mode="json")
    if not show_token:
        data["token"] = "<hidden — pass --show-token to display>"

    click.echo(f"User: {user_email}")
    click.echo(f"Default: {'yes' if is_default else 'no'}")
    for key, value in data.items():
        click.echo(f"  {key}: {value}")


@accounts_group.command("remove")
@click.argument("name")
@click.option("--user", "user_arg", default=None, help="Target user email.")
def accounts_remove(name, user_arg):
    """Remove an account from a user's profile.

    If the removed account was the default and exactly one account
    remains, that account becomes the new default. Otherwise the
    default is cleared and must be set explicitly with 'accounts use'.
    """
    user_email = resolve_user_for_read(user_arg)
    profile = _load_profile(user_email)
    if not any(a.name == name for a in profile.accounts):
        available = ", ".join(a.name for a in profile.accounts) or "(none)"
        raise click.ClickException(
            f"Account '{name}' not found for {user_email}. Available: {available}"
        )

    profile.accounts = [a for a in profile.accounts if a.name != name]

    default_note = None
    if profile.default_account == name:
        if len(profile.accounts) == 1:
            profile.default_account = profile.accounts[0].name
            default_note = f"  (new default: {profile.default_account})"
        else:
            profile.default_account = None
            default_note = "  (default cleared — set one with 'accounts use <name>')"

    _save_profile(user_email, profile)
    click.echo(f"Removed account '{name}' from user {user_email}")
    if default_note:
        click.echo(default_note)


@accounts_group.command("use")
@click.argument("name")
@click.option("--user", "user_arg", default=None, help="Target user email.")
def accounts_use(name, user_arg):
    """Set the default account on a user's profile."""
    user_email = resolve_user_for_read(user_arg)
    profile = _load_profile(user_email)
    if not any(a.name == name for a in profile.accounts):
        available = ", ".join(a.name for a in profile.accounts) or "(none)"
        raise click.ClickException(
            f"Account '{name}' not found for {user_email}. Available: {available}"
        )

    profile.default_account = name
    _save_profile(user_email, profile)
    click.echo(f"Default account for {user_email} is now '{name}'")
