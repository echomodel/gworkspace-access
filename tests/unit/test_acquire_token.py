"""Tests for ``gwsa-admin acquire-token``.

The OAuth browser flow is the only mocked boundary; the rest of the
command runs against real code — Click parsing,
``InstalledAppFlow.from_client_secrets_file`` (which parses real test
fixtures), ``Credentials.to_json`` serialization, scope resolution
via the SDK, and stdout-vs-file output dispatch.

Mocking only ``run_local_server`` is the same philosophy main's
deleted ``test_token_setup.py`` used: exercise the maximum surface
that has no external dependency.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from gwsa import app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def client_secrets(tmp_path):
    """Write a real-shape client_secrets.json. from_client_secrets_file
    parses this locally without any network call."""
    path = tmp_path / "client_secrets.json"
    path.write_text(json.dumps({
        "installed": {
            "client_id": "test-id.apps.googleusercontent.com",
            "project_id": "test-project",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": "test-secret",
            "redirect_uris": ["http://localhost"],
        }
    }))
    return path


def _fake_credentials(refresh_token: str = "from-fake-flow"):
    """A MagicMock that serializes like a real Credentials object."""
    creds = MagicMock()
    creds.to_json.return_value = json.dumps({
        "client_id": "test-id.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
    })
    return creds


def test_writes_token_to_stdout_when_no_out_flag(runner, client_secrets):
    fake = _fake_credentials()
    with patch(
        "google_auth_oauthlib.flow.InstalledAppFlow.run_local_server",
        return_value=fake,
    ):
        result = runner.invoke(app.admin_cli, [
            "acquire-token",
            "--client-secrets", str(client_secrets),
        ])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["refresh_token"] == "from-fake-flow"


def test_progress_chatter_goes_to_stderr(runner, client_secrets):
    """stdout must be parseable JSON; chatter must not leak into it."""
    with patch(
        "google_auth_oauthlib.flow.InstalledAppFlow.run_local_server",
        return_value=_fake_credentials(),
    ):
        result = runner.invoke(app.admin_cli, [
            "acquire-token",
            "--client-secrets", str(client_secrets),
        ])

    json.loads(result.stdout)  # would raise on chatter contamination
    assert "Opening browser" in result.stderr
    assert "Requesting scopes" in result.stderr


def test_out_flag_writes_file_not_stdout(runner, client_secrets, tmp_path):
    out_path = tmp_path / "token.json"
    with patch(
        "google_auth_oauthlib.flow.InstalledAppFlow.run_local_server",
        return_value=_fake_credentials(refresh_token="from-file"),
    ):
        result = runner.invoke(app.admin_cli, [
            "acquire-token",
            "--client-secrets", str(client_secrets),
            "--out", str(out_path),
        ])

    assert result.exit_code == 0, result.stderr
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["refresh_token"] == "from-file"
    # stdout stays clean when --out is used
    assert result.stdout == ""


def test_scope_aliases_are_resolved(runner, client_secrets):
    """The SDK's resolve_scopes turns aliases into full URLs before
    passing them to InstalledAppFlow.from_client_secrets_file."""
    captured = {}

    def _capture(_path, scopes):
        captured["scopes"] = sorted(scopes)
        return MagicMock(run_local_server=MagicMock(
            return_value=_fake_credentials()
        ))

    with patch(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
        side_effect=_capture,
    ):
        result = runner.invoke(app.admin_cli, [
            "acquire-token",
            "--client-secrets", str(client_secrets),
            "--scopes", "mail,docs-read",
        ])

    assert result.exit_code == 0, result.stderr
    assert "https://www.googleapis.com/auth/gmail.modify" in captured["scopes"]
    assert "https://www.googleapis.com/auth/documents.readonly" in captured["scopes"]


def test_missing_client_secrets_file_errors_cleanly(runner, tmp_path):
    result = runner.invoke(app.admin_cli, [
        "acquire-token",
        "--client-secrets", str(tmp_path / "does-not-exist.json"),
    ])
    assert result.exit_code != 0
    assert "client_secrets file not found" in result.stderr


def test_oauth_flow_failure_surfaces_as_click_error(runner, client_secrets):
    with patch(
        "google_auth_oauthlib.flow.InstalledAppFlow.run_local_server",
        side_effect=RuntimeError("user closed the browser"),
    ):
        result = runner.invoke(app.admin_cli, [
            "acquire-token",
            "--client-secrets", str(client_secrets),
        ])

    assert result.exit_code != 0
    assert "OAuth flow failed" in result.stderr
    assert "user closed the browser" in result.stderr


def test_empty_scopes_arg_rejected(runner, client_secrets):
    result = runner.invoke(app.admin_cli, [
        "acquire-token",
        "--client-secrets", str(client_secrets),
        "--scopes", "",
    ])
    assert result.exit_code != 0
    assert "At least one scope" in result.stderr
