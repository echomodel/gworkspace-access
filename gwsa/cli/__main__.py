"""gwsa CLI — domain-only Google Workspace operations.

Profile, account, token, and OAuth-client management live exclusively
in ``gwsa-admin`` (see docs/CLOUD-MULTI-USER.md §6.3). This CLI only
talks to Google APIs; credentials are resolved by the SDK from the
mcp-app ``current_user`` ContextVar, which this entry point sets
once at startup from the local user store (see ``_bootstrap_user``).
"""

import asyncio
import json
import logging
import os
import sys

import click
from dotenv import load_dotenv

from gwsa import __version__, app
from gwsa.sdk import mail as sdk_mail

from .chat import chat as chat_module
from .docs_commands import docs as docs_module
from .drive_commands import drive_group as drive_module
from .mail.threads import threads as threads_module
from .sheets_commands import sheets as sheets_module
from .calendar_commands import calendar as calendar_module


if not logging.root.handlers:
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, LOG_LEVEL),
                        format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('googleapiclient.discovery').setLevel(logging.WARNING)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.WARNING)
logging.getLogger('google_auth_oauthlib.flow').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _bootstrap_user(user_email: str | None) -> None:
    """Load a user record from the local store and pin ``current_user``.

    The gwsa CLI is single-user-at-a-time — every command runs in
    exactly one user's identity. mcp-app's HTTP middleware does this
    for hosted requests; for the CLI we do it once here, before any
    Click subcommand runs.

    Args:
        user_email: Explicit ``--user`` selector. If ``None``, the
            store's sole user is used; if the store has multiple
            users with no selector, exit with a clear error.
    """
    from mcp_app.bridge import DataStoreAuthAdapter
    from mcp_app.context import current_user, hydrate_profile

    store = app._build_store()
    adapter = DataStoreAuthAdapter(store)

    if user_email is None:
        users = store.list_users()
        if not users:
            raise click.ClickException(
                "No users in the local store. Register one with: "
                "gwsa-admin accounts add <name> --email <you@example.com> --token=..."
            )
        if len(users) == 1:
            user_email = users[0]
        elif "local" in users:
            user_email = "local"
        else:
            raise click.ClickException(
                f"Multiple users in store ({', '.join(users)}). "
                f"Disambiguate with: gwsa --user <email> ..."
            )

    user_record = asyncio.run(adapter.get_full(user_email))
    if user_record is None:
        raise click.ClickException(
            f"User '{user_email}' not found in local store. "
            f"Register with: gwsa-admin accounts add ..."
        )
    user_record.profile = hydrate_profile(user_record.profile)
    current_user.set(user_record)


@click.group()
@click.version_option(__version__, prog_name="gwsa")
@click.option("--user", "user_email", default=None, metavar="EMAIL",
              help="Operate as this user (required when multiple users exist locally).")
@click.option("--account", "account", default=None, metavar="NAME_OR_EMAIL",
              help="Google account to use for this invocation (account name or "
                   "email). Overrides the user's default account. Omit to use "
                   "the default.")
def gwsa(user_email, account):
    """gwsa CLI — Google Workspace domain operations.

    Profile and credential management lives in ``gwsa-admin`` (e.g.,
    ``gwsa-admin accounts add``, ``gwsa-admin acquire-token``).
    """
    _bootstrap_user(user_email)
    from gwsa.sdk.auth import set_cli_account
    set_cli_account(account)


@gwsa.command("status")
@click.option("--test", "--smoke-test", "run_test", is_flag=True,
              help="Run non-mutating smoke tests across Google Workspace services.")
@click.option("--adc", "--compare-adc", "compare_adc", is_flag=True,
              help="Inspect and compare local Application Default Credentials (ADC).")
@click.option("--gcp", "--check-gcp", "check_gcp", is_flag=True,
              help="Inspect GCP Quota Project configuration and enabled APIs.")
@click.option("--all", "all_flags", is_flag=True,
              help="Run all status diagnostic checks (--test --adc --gcp).")
@click.option("--json", "as_json", is_flag=True, help="Output status as JSON.")
@click.option("--user", "user_email", default=None, metavar="EMAIL",
              help="Operate as this user.")
@click.option("--account", "account", default=None, metavar="NAME_OR_EMAIL",
              help="Google account to inspect.")
def status_cmd(run_test, compare_adc, check_gcp, all_flags, as_json, user_email, account):
    """Display active workstation auth state, profile configuration, and OAuth scopes."""
    if all_flags:
        run_test = True
        compare_adc = True
        check_gcp = True

    if user_email:
        _bootstrap_user(user_email)
    if account:
        from gwsa.sdk.auth import set_cli_account
        set_cli_account(account)

    from gwsa.sdk.auth import get_auth_status, get_all_scopes

    st = get_auth_status(account=account, run_smoke_tests=run_test, compare_adc=compare_adc, check_gcp=check_gcp)

    if as_json:
        click.echo(json.dumps(st, indent=2))
        return

    granted_scopes_set = set(st.get("granted_scopes", []))
    expected_scopes = get_all_scopes(workspace=True)
    expected_scopes_set = set(expected_scopes)

    all_scopes = sorted(list(expected_scopes_set.union(granted_scopes_set)))

    scope_lines = []
    granted_count = 0
    extra_count = 0

    for s in all_scopes:
        if s in granted_scopes_set and s in expected_scopes_set:
            scope_lines.append(f"  ✓  {s}")
            granted_count += 1
        elif s in expected_scopes_set and s not in granted_scopes_set:
            scope_lines.append(f"  ❌ {s} (missing)")
        else:
            scope_lines.append(f"  ➕ {s} (extra)")
            extra_count += 1

    extra_summary = f", {extra_count} extra" if extra_count else ""
    scopes_header = f"OAuth Scopes ({granted_count}/{len(expected_scopes)} granted{extra_summary}):"
    scope_block = "\n".join(scope_lines) if scope_lines else "  (none)"

    users_str = ", ".join(st.get("all_users", [])) or "(none)"
    accounts_str = ", ".join(st.get("all_accounts", [])) or "(none)"

    output_blocks = [
        f"""=== 🔐 GWSA Workstation Auth Status ===

Store Mode: {st['store_mode']}
Active User: {st['active_user']}
Default Account: {st['default_account']}
Quota Project: {st['quota_project']}

Store Profiles: {users_str}
Profile Accounts: {accounts_str}

Live OAuth Token Status: {st['token_status']}
{scopes_header}
{scope_block}"""
    ]

    if compare_adc and "adc" in st:
        adc = st["adc"]
        gwsa_email = st.get("default_account", "").split("(")[-1].rstrip(")") if "(" in st.get("default_account", "") else ""
        gwsa_quota = st.get("quota_project", "")

        email_match = (adc.get("email") == gwsa_email) if gwsa_email and adc.get("email") != "(none)" else False
        quota_match = (adc.get("quota_project") == gwsa_quota) if gwsa_quota and adc.get("quota_project") != "(none)" else False

        if email_match and quota_match:
            match_status = f"✅ MATCH (Account: {adc['email']}, Quota: {adc['quota_project']})"
        elif email_match:
            match_status = f"🔸 MISMATCH QUOTA (GWSA Quota: {gwsa_quota} vs ADC Quota: {adc['quota_project']})"
        else:
            match_status = f"⚠️ DIFFERENT (GWSA Account: {gwsa_email or '(none)'} vs ADC Account: {adc['email']})"

        adc_scopes = adc.get("granted_scopes", [])
        adc_scope_lines = "\n".join(f"    ✓  {s}" for s in adc_scopes) if adc_scopes else "    (none)"

        output_blocks.append(f"""=== 🅰️ Application Default Credentials (ADC) Comparison ===

  ADC Credentials File: {adc['adc_file']}
  ADC Account Email:    {adc['email']}
  ADC Quota Project:    {adc['quota_project']}
  ADC Token Status:     {adc['status']}
  ADC Client ID:        {adc['client_id']}
  GWSA vs ADC Match:    {match_status}

  ADC Granted Scopes ({len(adc_scopes)}):
{adc_scope_lines}""")

    if check_gcp and "gcp" in st:
        gcp = st["gcp"]
        q_proj = gcp.get("quota_project", "(none)")
        q_status = gcp.get("quota_project_status", "(none)")
        api_map = gcp.get("api_statuses", {})
        api_lines = "\n".join(f"    • {name:<17} {status}" for name, status in api_map.items()) if api_map else "    (none)"

        output_blocks.append(f"""=== ☁️ GCP Quota Project & API Status ===

  Quota Project ID:     {q_proj}
  Quota Project Access: {q_status}

  Required Workspace APIs:
{api_lines}""")

    if run_test and "smoke_tests" in st:
        header_row = f"  {'Service':<15} {'Status':<14} {'Latency':<10} {'CLI Command Probe'}"
        divider_row = f"  {'-'*14:<15} {'-'*13:<14} {'-'*9:<10} {'-'*45}"
        
        table_lines = [header_row, divider_row]
        for svc, test_info in st["smoke_tests"].items():
            status_str = test_info["status"]
            lat = test_info.get("latency_ms")
            lat_str = f"{lat}ms" if lat is not None else "-"
            probe_str = test_info["probe"]
            table_lines.append(f"  {svc:<15} {status_str:<14} {lat_str:<10} {probe_str}")

        smoke_table = "\n".join(table_lines)
        output_blocks.append(f"""=== 🧪 Service Smoke Tests ===
{smoke_table}""")

        errors = st.get("smoke_test_errors", [])
        if errors:
            err_lines = "\n\n".join(
                f"  • [{err['service']}] {err['step']} (after {err.get('latency_ms', 0)}ms)\n    Error: {err['error']}"
                for err in errors
            )
            output_blocks.append(f"""=== ⚠️ Smoke Test Error Details ===
{err_lines}""")

    click.echo("\n\n".join(output_blocks))


@click.group()
def mail():
    """Operations related to Gmail."""
    pass


@mail.command("search")
@click.argument('query')
@click.option('--page-token', default=None,
              help='Token for fetching the next page of results.')
@click.option('--max-results', type=int, default=25,
              help='Maximum number of results to return.')
@click.option('--format', type=click.Choice(['full', 'metadata']), default='full',
              help='Format of the response. "full" includes message details, '
                   '"metadata" omits the message body.')
def mail_search(query, page_token, max_results, format):
    """Search emails. QUERY is a Gmail search expression."""
    try:
        result = sdk_mail.search(query, max_results=max_results, page_token=page_token)
        click.echo(json.dumps(result, indent=2, default=str))
    except Exception as e:
        logger.critical(f"Mail search failed: {e}", exc_info=True)
        sys.exit(1)


@mail.command("read")
@click.argument('message_id')
def mail_read(message_id):
    """Read a single Gmail message by ID."""
    try:
        message = sdk_mail.read_message(message_id)
        click.echo(json.dumps(message, indent=2, default=str))
    except Exception as e:
        logger.critical(f"Mail read failed for {message_id}: {e}", exc_info=True)
        sys.exit(1)


@mail.command("label")
@click.argument('message_ids', nargs=-1)
@click.option('--add', 'add_labels', multiple=True,
              help='Label to add (repeatable). Created if missing.')
@click.option('--remove', 'remove_labels', multiple=True,
              help='Label to remove (repeatable). Use "INBOX" to archive.')
def mail_label(message_ids, add_labels, remove_labels):
    """Add and/or remove labels across one or more messages (idempotent).

    MESSAGE_IDS is one or more Gmail message IDs; pass "-" to read
    whitespace-separated IDs from stdin. Applies the same label delta to
    every message in a single batch. Examples:

        gwsa mail label MID1 MID2 --remove INBOX          # archive
        gwsa mail label MID --add ToReview --remove INBOX # relabel
    """
    try:
        ids = list(message_ids)
        if ids == ["-"]:
            ids = sys.stdin.read().split()
        if not ids:
            raise click.UsageError("No message IDs provided.")
        if not add_labels and not remove_labels:
            raise click.UsageError("Provide at least one --add or --remove label.")
        result = sdk_mail.modify_labels(
            ids,
            add_labels=list(add_labels) or None,
            remove_labels=list(remove_labels) or None,
        )
        click.echo(json.dumps(result, indent=2))
    except click.UsageError:
        raise
    except Exception as e:
        logger.critical(f"Mail label failed: {e}", exc_info=True)
        sys.exit(1)


gwsa.add_command(mail)
gwsa.add_command(sheets_module, name='sheets')
gwsa.add_command(docs_module, name='docs')
gwsa.add_command(drive_module, name='drive')
gwsa.add_command(chat_module, name='chat')
gwsa.add_command(calendar_module, name='calendar')

mail.add_command(threads_module, name='threads')


def main():
    """Entry point for the CLI."""
    load_dotenv()
    gwsa()


if __name__ == '__main__':
    main()
