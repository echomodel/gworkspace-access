import os
from pathlib import Path
import pytest
import yaml
from unittest.mock import MagicMock
from gwsa.cli.setup_local import _get_status_report

def test_get_status_report_not_configured(tmp_path: Path, monkeypatch):
    """
    Verify that _get_status_report correctly identifies a system with no config file.
    """
    # Arrange
    non_existent_config = tmp_path / "config.yaml"
    monkeypatch.setenv("GWSA_CONFIG_FILE", str(non_existent_config))

    # Action
    report = _get_status_report()

    # Assertion
    assert report == {"status": "NOT_CONFIGURED"}

def test_get_status_report_configured_adc_no_creds(tmp_path: Path, monkeypatch):
    """
    Verify status report for a system configured for ADC profile but missing ADC credentials.
    """
    # Arrange: Config with active_profile = "adc"
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"active_profile": "adc"}, f)
    monkeypatch.setenv("GWSA_CONFIG_FILE", str(config_path))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr("google.auth.default", lambda: (_ for _ in ()).throw(Exception("ADC not found")))

    # Action
    report = _get_status_report()

    # Assertion
    assert report["status"] == "ERROR"
    assert report["mode"] == "adc"
    assert report["profile"] == "adc"
    assert "error_details" in report
    assert "ADC not found" in report["error_details"]

def test_get_status_report_configured_token_no_token_file(tmp_path: Path, monkeypatch):
    """
    Verify status report for a system configured for a token profile but missing the token file.
    """
    # Arrange: Config with active_profile pointing to a non-existent profile
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"active_profile": "myprofile"}, f)
    monkeypatch.setenv("GWSA_CONFIG_FILE", str(config_path))

    # Create profiles directory but no token file
    profiles_dir = tmp_path / "profiles" / "myprofile"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    # Note: No user_token.json file created

    # Action
    report = _get_status_report()

    # Assertion
    assert report["status"] == "ERROR"
    assert report["mode"] == "token"
    assert report["profile"] == "myprofile"
    assert "error_details" in report
    # Profile doesn't exist (no token file)
    assert "not found" in report["error_details"].lower() or "profile" in report["error_details"].lower()

def test_get_status_report_configured_adc_valid_creds(tmp_path: Path, monkeypatch):
    """
    Verify status report for a system configured for ADC profile with valid credentials.
    """
    # Arrange: Config with active_profile = "adc"
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"active_profile": "adc"}, f)
    monkeypatch.setenv("GWSA_CONFIG_FILE", str(config_path))

    # Arrange: Mock Credentials
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds.expired = False
    mock_creds.refresh_token = "fake-refresh-token"
    mock_scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/spreadsheets",
    ]

    # Mock the functions that would make network calls
    monkeypatch.setattr("google.auth.default", lambda: (mock_creds, "mock-project"))
    monkeypatch.setattr("gwsa.cli.setup_local.get_token_info", lambda creds: {
        "scopes": mock_scopes,
        "email": "user@example.com"
    })

    # Action
    report = _get_status_report()

    # Assertion
    assert report["status"] == "CONFIGURED"
    assert report["mode"] == "adc"
    assert report["profile"] == "adc"
    assert report["creds_valid"] is True
    assert report["user_email"] == "user@example.com"
    assert report["feature_status"]["mail"] is False # We only have readonly
    assert report["feature_status"]["sheets"] is True
    assert report["feature_status"]["docs"] is False

def test_get_status_report_configured_token_valid_creds(tmp_path: Path, monkeypatch):
    """
    Verify status report for a system configured for a token profile with a valid token file.
    """
    # Arrange: Config with active_profile = "myprofile"
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"active_profile": "myprofile"}, f)
    monkeypatch.setenv("GWSA_CONFIG_FILE", str(config_path))

    # Arrange: Mock Credentials & Scopes
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds.expired = False
    mock_creds.refresh_token = "fake-refresh-token"
    mock_scopes = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/documents.readonly",
    ]

    # Mock the functions that would make network calls
    monkeypatch.setattr("gwsa.cli.setup_local.get_active_credentials", lambda: (mock_creds, "mock_token_file"))
    monkeypatch.setattr("gwsa.cli.setup_local.get_token_info", lambda creds: {
        "scopes": mock_scopes,
        "email": "test@example.com"
    })

    # Action
    report = _get_status_report()

    # Assertion
    assert report["status"] == "CONFIGURED"
    assert report["mode"] == "token"
    assert report["profile"] == "myprofile"
    assert report["creds_valid"] is True
    assert report["user_email"] == "test@example.com"
    assert "error_details" not in report
    assert report["feature_status"]["mail"] is True
    assert report["feature_status"]["sheets"] is False
    assert report["feature_status"]["docs"] is False # We only have readonly
