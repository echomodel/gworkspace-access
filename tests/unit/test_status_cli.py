"""Unit tests for `gwsa status` CLI command and get_auth_status SDK helper."""

import json
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner

from mcp_app.context import current_user
from gwsa.cli.__main__ import gwsa
from gwsa.sdk.auth import get_auth_status, get_adc_status, get_gcp_status, run_service_smoke_tests
from gwsa import Profile, GoogleAccount


@pytest.fixture
def mock_user_record():
    user = MagicMock()
    user.email = "local"
    user.profile = Profile(
        accounts=[
            GoogleAccount(
                name="work",
                email="alice@example.com",
                quota_project="my-quota-project",
                token={
                    "access_token": "fake-access-token",
                    "refresh_token": "fake-refresh-token",
                    "client_id": "fake-client-id",
                    "client_secret": "fake-client-secret",
                    "token_uri": "https://oauth2.googleapis.com/token",
                },
            )
        ],
        default_account="work",
    )
    return user


def test_get_auth_status_valid_token(mock_user_record):
    token = current_user.set(mock_user_record)
    mock_creds = MagicMock()
    mock_creds.valid = True
    account = mock_user_record.profile.accounts[0]
    try:
        with patch("gwsa.sdk.auth.get_google_account_creds", return_value=(mock_creds, account)), \
             patch("gwsa.sdk.auth.get_token_info", return_value={
                 "scopes": ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/drive"],
                 "email": "alice@example.com",
             }), \
             patch("gwsa.admin._helpers.is_local_store", return_value=True):
            
            status = get_auth_status()
            assert status["active_user"] == "local"
            assert "work (alice@example.com)" in status["default_account"]
            assert status["quota_project"] == "my-quota-project"
            assert status["token_status"] == "VALID"
            assert len(status["granted_scopes"]) == 3
            assert "openid" in status["granted_scopes"]
    finally:
        current_user.reset(token)


def test_get_auth_status_no_accounts():
    user = MagicMock()
    user.email = "local"
    user.profile = Profile(accounts=[], default_account=None)

    token = current_user.set(user)
    try:
        with patch("gwsa.admin._helpers.is_local_store", return_value=True):
            status = get_auth_status()
            assert status["active_user"] == "local"
            assert status["default_account"] == "(none)"
            assert status["quota_project"] == "(none)"
            assert status["token_status"] == "NO TOKEN"
            assert status["granted_scopes"] == []
    finally:
        current_user.reset(token)


def test_get_auth_status_invalid_token(mock_user_record):
    token = current_user.set(mock_user_record)
    try:
        with patch("gwsa.sdk.auth.get_token_info", side_effect=Exception("Token revoked")), \
             patch("gwsa.admin._helpers.is_local_store", return_value=True):
            
            status = get_auth_status()
            assert status["token_status"].startswith("INVALID") or "revoked" in status["token_status"]
            assert status["granted_scopes"] == []
    finally:
        current_user.reset(token)


def test_gwsa_status_cli_text_output(mock_user_record):
    runner = CliRunner()
    fake_status = {
        "store_mode": "local (~/.local/share/gwsa/users/)",
        "active_user": "local",
        "default_account": "work (alice@example.com)",
        "quota_project": "my-quota-project",
        "token_status": "VALID",
        "granted_scopes": [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/drive",
        ],
    }

    with patch("gwsa.cli.__main__._bootstrap_user"), \
         patch("gwsa.sdk.auth.get_auth_status", return_value=fake_status):
        
        result = runner.invoke(gwsa, ["status"])
        assert result.exit_code == 0
        assert "=== 🔐 GWSA Workstation Auth Status ===" in result.output
        assert "Store Mode: local (~/.local/share/gwsa/users/)" in result.output
        assert "Active User: local" in result.output
        assert "Default Account: work (alice@example.com)" in result.output
        assert "Quota Project: my-quota-project" in result.output
        assert "Live OAuth Token Status: VALID" in result.output
        assert "OAuth Scopes (" in result.output
        assert "  ✓  openid" in result.output
        assert "  ✓  https://www.googleapis.com/auth/drive" in result.output


def test_gwsa_status_cli_json_output(mock_user_record):
    runner = CliRunner()
    fake_status = {
        "store_mode": "local (~/.local/share/gwsa/users/)",
        "active_user": "local",
        "default_account": "work (alice@example.com)",
        "quota_project": "my-quota-project",
        "token_status": "VALID",
        "granted_scopes": ["openid"],
    }

    with patch("gwsa.cli.__main__._bootstrap_user"), \
         patch("gwsa.sdk.auth.get_auth_status", return_value=fake_status):
        
        result = runner.invoke(gwsa, ["status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["active_user"] == "local"
        assert data["token_status"] == "VALID"


def test_run_service_smoke_tests_all_pass():
    scopes = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/chat.spaces.readonly",
    ]
    fake_spaces = MagicMock()
    fake_spaces.list.return_value.execute.return_value = {"spaces": []}
    mock_chat_service = MagicMock()
    mock_chat_service.spaces.return_value = fake_spaces

    with patch("gwsa.sdk.mail.search_messages", return_value=([], None)), \
         patch("gwsa.sdk.drive.search_drive", return_value=([], None)), \
         patch("gwsa.sdk.docs.list_documents", return_value=([])), \
         patch("gwsa.sdk.sheets.list_spreadsheets", return_value=([])), \
         patch("gwsa.sdk.calendar.list_calendars", return_value=([])), \
         patch("gwsa.sdk.chat.get_chat_service", return_value=mock_chat_service):

        results, errors = run_service_smoke_tests(scopes)
        assert results["Gmail"]["status"] == "✅ PASS"
        assert results["Drive"]["status"] == "✅ PASS"
        assert results["Docs"]["status"] == "✅ PASS"
        assert results["Sheets"]["status"] == "✅ PASS"
        assert results["Calendar"]["status"] == "✅ PASS"
        assert results["Chat"]["status"] == "✅ PASS"
        assert errors == []


def test_run_service_smoke_tests_with_failures():
    scopes = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/documents",
    ]
    with patch("gwsa.sdk.mail.search_messages", return_value=([], None)), \
         patch("gwsa.sdk.docs.list_documents", side_effect=Exception("API Error 403: Forbidden")):

        results, errors = run_service_smoke_tests(scopes)
        assert results["Gmail"]["status"] == "✅ PASS"
        assert results["Docs"]["status"] == "❌ FAIL"
        assert results["Drive"]["status"].startswith("⏭️ SKIPPED")
        assert len(errors) == 1
        assert errors[0]["service"] == "Docs"
        assert errors[0]["step"] == "gwsa docs list --limit 1"
        assert "API Error 403" in errors[0]["error"]


def test_run_service_smoke_tests_timeout():
    import time
    scopes = ["https://www.googleapis.com/auth/gmail.modify"]

    def hanging_call(*args, **kwargs):
        time.sleep(6)

    with patch("gwsa.sdk.mail.search_messages", side_effect=hanging_call), \
         patch("gwsa.sdk.auth.PROBE_TIMEOUT_SECONDS", 0.5):
        results, errors = run_service_smoke_tests(scopes)
        assert results["Gmail"]["status"] == "❌ FAIL"
        assert len(errors) == 1
        assert errors[0]["service"] == "Gmail"
        assert "timed out" in errors[0]["error"].lower()


def test_get_adc_status_not_found():
    with patch("pathlib.Path.exists", return_value=False):
        adc = get_adc_status()
        assert adc["status"] == "NOT FOUND"
        assert adc["email"] == "(none)"


def test_get_gcp_status_no_quota_project():
    user = MagicMock()
    user.email = "local"
    user.profile = Profile(
        accounts=[GoogleAccount(
            name="work",
            email="alice@example.com",
            quota_project=None,
            token={
                "access_token": "fake-access-token",
                "refresh_token": "fake-refresh-token",
                "client_id": "fake-client-id",
                "client_secret": "fake-client-secret",
                "token_uri": "https://oauth2.googleapis.com/token",
            },
        )],
        default_account="work",
    )
    token = current_user.set(user)
    mock_creds = MagicMock()
    try:
        with patch("gwsa.sdk.auth.get_google_account_creds", return_value=(mock_creds, user.profile.accounts[0])):
            gcp = get_gcp_status()
            assert gcp["quota_project"] == "(none)"
            assert gcp["quota_project_status"] == "(none)"
    finally:
        current_user.reset(token)


def test_gwsa_status_cli_with_gcp_flag():
    runner = CliRunner()
    fake_status = {
        "store_mode": "local (~/.local/share/gwsa/users/)",
        "active_user": "local",
        "default_account": "work (alice@example.com)",
        "quota_project": "my-quota-project",
        "all_users": ["local [active]"],
        "all_accounts": ["work (alice@example.com) [default]"],
        "token_status": "VALID",
        "granted_scopes": ["openid"],
        "gcp": {
            "quota_project": "my-quota-project",
            "quota_project_status": "✅ AUTHORIZED (serviceusage.services.use granted)",
            "api_statuses": {
                "Gmail API": "✅ ENABLED",
                "Drive API": "✅ ENABLED",
            },
            "errors": [],
        },
    }

    with patch("gwsa.cli.__main__._bootstrap_user"), \
         patch("gwsa.sdk.auth.get_auth_status", return_value=fake_status):

        result = runner.invoke(gwsa, ["status", "--gcp"])
        assert result.exit_code == 0
        assert "=== ☁️ GCP Quota Project & API Status ===" in result.output
        assert "Quota Project Access: ✅ AUTHORIZED" in result.output
        assert "Gmail API         ✅ ENABLED" in result.output


def test_get_adc_status_valid():
    fake_adc = {
        "client_id": "fake-client-id",
        "client_secret": "fake-client-secret",
        "refresh_token": "fake-refresh",
        "type": "authorized_user",
        "quota_project_id": "adc-project",
    }
    mock_creds = MagicMock()
    mock_creds.valid = True

    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=json.dumps(fake_adc)), \
         patch("google.oauth2.credentials.Credentials.from_authorized_user_info", return_value=mock_creds), \
         patch("gwsa.sdk.auth.get_token_info", return_value={"email": "alice@example.com", "scopes": ["openid"]}):

        adc = get_adc_status()
        assert adc["status"] == "VALID"
        assert adc["email"] == "alice@example.com"
        assert adc["quota_project"] == "adc-project"


def test_gwsa_status_cli_with_adc_flag():
    runner = CliRunner()
    fake_status = {
        "store_mode": "local (~/.local/share/gwsa/users/)",
        "active_user": "local",
        "default_account": "work (alice@example.com)",
        "quota_project": "my-quota-project",
        "all_users": ["local [active]"],
        "all_accounts": ["work (alice@example.com) [default]"],
        "token_status": "VALID",
        "granted_scopes": ["openid"],
        "adc": {
            "adc_file": "~/.config/gcloud/application_default_credentials.json",
            "status": "VALID",
            "email": "alice@example.com",
            "quota_project": "my-quota-project",
            "client_id": "764086051850-...",
            "granted_scopes": ["openid"],
        },
    }

    with patch("gwsa.cli.__main__._bootstrap_user"), \
         patch("gwsa.sdk.auth.get_auth_status", return_value=fake_status):

        result = runner.invoke(gwsa, ["status", "--adc"])
        assert result.exit_code == 0
        assert "=== 🅰️ Application Default Credentials (ADC) Comparison ===" in result.output
        assert "ADC Account Email:    alice@example.com" in result.output
        assert "GWSA vs ADC Match:" in result.output


def test_gwsa_status_cli_with_all_flag():
    runner = CliRunner()
    fake_status = {
        "store_mode": "local (~/.local/share/gwsa/users/)",
        "active_user": "local",
        "default_account": "work (alice@example.com)",
        "quota_project": "my-quota-project",
        "all_users": ["local [active]"],
        "all_accounts": ["work (alice@example.com) [default]"],
        "token_status": "VALID",
        "granted_scopes": ["openid"],
        "adc": {
            "adc_file": "~/.config/gcloud/application_default_credentials.json",
            "status": "VALID",
            "email": "alice@example.com",
            "quota_project": "my-quota-project",
            "client_id": "764086051850-...",
            "granted_scopes": ["openid"],
        },
        "gcp": {
            "quota_project": "my-quota-project",
            "quota_project_status": "✅ AUTHORIZED (quota project: my-quota-project)",
            "api_statuses": {
                "Gmail API": "✅ ENABLED",
            },
            "errors": [],
        },
        "smoke_tests": {
            "Gmail": {"status": "✅ PASS", "latency_ms": 120, "probe": "gwsa mail search ..."},
        },
        "smoke_test_errors": [],
    }

    with patch("gwsa.cli.__main__._bootstrap_user"), \
         patch("gwsa.sdk.auth.get_auth_status", return_value=fake_status) as mock_get_status:

        result = runner.invoke(gwsa, ["status", "--all"])
        assert result.exit_code == 0
        assert "=== 🔐 GWSA Workstation Auth Status ===" in result.output
        assert "=== 🅰️ Application Default Credentials (ADC) Comparison ===" in result.output
        assert "=== ☁️ GCP Quota Project & API Status ===" in result.output
        assert "=== 🧪 Service Smoke Tests ===" in result.output
        mock_get_status.assert_called_once_with(account=None, run_smoke_tests=True, compare_adc=True, check_gcp=True)


