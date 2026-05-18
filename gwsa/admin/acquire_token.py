"""``gwsa-admin acquire-token`` — run an OAuth browser flow and emit the token.

Stdout is the token JSON. All progress chatter goes to stderr. Pipe into
``accounts add --token=-`` or redirect to a file.

For ADC-style credentials (gcloud's well-known client) we don't drive the
flow — operators run ``gcloud auth application-default login`` themselves
and pass the resulting file to ``accounts add --token=@...``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from gwsa.sdk.auth import resolve_scopes


@click.command("acquire-token")
@click.option(
    "--client-secrets",
    "client_secrets_path",
    required=True,
    help="Path to your OAuth client_secrets.json (downloaded from GCP Console).",
)
@click.option(
    "--scopes",
    default="mail,drive,docs,sheets",
    show_default=True,
    help=(
        "Comma-separated scope aliases (mail, drive, docs, sheets, chat, tasks) "
        "or full scope URLs. Use 'workspace' to include the chat/people set."
    ),
)
@click.option(
    "--out",
    "out_path",
    default=None,
    help="Write the token JSON to this path instead of stdout.",
)
def acquire_token(client_secrets_path, scopes, out_path):
    """Run an OAuth browser flow with your client_secrets and emit a token.

    Stdout receives the token JSON (or --out writes it to a file).
    Pipe straight into 'accounts add':

      gwsa-admin acquire-token --client-secrets ~/client_secrets.json | \\
        gwsa-admin accounts add personal --email me@example.com --token=-
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    cs_path = Path(client_secrets_path).expanduser()
    if not cs_path.exists():
        raise click.ClickException(f"client_secrets file not found: {cs_path}")

    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    if not scope_list:
        raise click.ClickException("At least one scope is required.")
    resolved = resolve_scopes(scope_list)

    click.echo(f"Requesting scopes: {', '.join(sorted(resolved))}", err=True)
    click.echo("Opening browser for OAuth consent...", err=True)

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(cs_path), resolved)
        creds = flow.run_local_server(port=0)
    except Exception as e:
        raise click.ClickException(f"OAuth flow failed: {e}")

    click.echo("Consent complete; emitting token.", err=True)

    token_json = creds.to_json()
    if out_path:
        Path(out_path).expanduser().write_text(token_json)
        click.echo(f"Wrote token to {out_path}", err=True)
    else:
        sys.stdout.write(token_json)
        sys.stdout.write("\n")
        sys.stdout.flush()
