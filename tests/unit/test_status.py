import os
import json
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
    Verify status report for an ADC profile with missing credentials.
    """
    # Arrange: Config dir with active_profile = "corp-adc"
    config_dir = tmp_path / "gwsa-config"
    config_dir.mkdir()
    config_path = config_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"active_profile": "corp-adc"}, f)
    monkeypatch.setenv("GWSA_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("GWSA_CONFIG_FILE", str(config_path))

    # Create profile directory with ADC type metadata
    profile_dir = config_dir / "profiles" / "corp-adc"
    profile_dir.mkdir(parents=True)
    with open(profile_dir / "profile.yaml", "w") as f:
        yaml.dump({"type": "adc", "email": "user@example.com"}, f)
    # Create the token file
    with open(profile_dir / "user_token.json", "w") as f:
        json.dump({"type": "authorized_user", "client_id": "test", "refresh_token": "test"}, f)

    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    # Mock get_active_credentials to raise (simulating broken credentials)
    monkeypatch.setattr("gwsa.cli.setup_local.get_active_credentials",
                        lambda: (_ for _ in ()).throw(Exception("ADC not found")))

    # Action
    report = _get_status_report()

    # Assertion
    assert report["status"] == "ERROR"
    assert report["mode"] == "adc"
    assert report["profile"] == "corp-adc"
    assert "error_details" in report
    assert "ADC not found" in report["error_details"]

def test_get_status_report_configured_oauth_no_token_file(tmp_path: Path, monkeypatch):
    """
    Verify status report for an OAuth profile missing its token file.
    """
    # Arrange: Config with active_profile pointing to a profile without token file
    config_dir = tmp_path / "gwsa-config"
    config_dir.mkdir()
    config_path = config_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"active_profile": "myprofile"}, f)
    monkeypatch.setenv("GWSA_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("GWSA_CONFIG_FILE", str(config_path))

    # Create profiles directory with metadata but no token file
    profile_dir = config_dir / "profiles" / "myprofile"
    profile_dir.mkdir(parents=True)
    with open(profile_dir / "profile.yaml", "w") as f:
        yaml.dump({"type": "oauth", "email": "test@example.com"}, f)
    # No user_token.json created

    # Action
    report = _get_status_report()

    # Assertion
    assert report["status"] == "ERROR"
    assert report["mode"] == "oauth"
    assert report["profile"] == "myprofile"
    assert "error_details" in report
    assert "not found" in report["error_details"].lower() or "profile" in report["error_details"].lower()

def test_get_status_report_configured_adc_valid_creds(tmp_path: Path, monkeypatch):
    """
    Verify status report for an ADC profile with valid credentials.
    """
    # Arrange: Config with active_profile = "corp-adc"
    config_dir = tmp_path / "gwsa-config"
    config_dir.mkdir()
    config_path = config_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"active_profile": "corp-adc"}, f)
    monkeypatch.setenv("GWSA_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("GWSA_CONFIG_FILE", str(config_path))

    # Create profile directory with ADC type metadata + token
    profile_dir = config_dir / "profiles" / "corp-adc"
    profile_dir.mkdir(parents=True)
    with open(profile_dir / "profile.yaml", "w") as f:
        yaml.dump({"type": "adc", "email": "user@example.com"}, f)
    with open(profile_dir / "user_token.json", "w") as f:
        json.dump({"type": "authorized_user", "client_id": "test", "refresh_token": "test"}, f)

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
    monkeypatch.setattr("gwsa.cli.setup_local.get_active_credentials", lambda: (mock_creds, "mock-source"))
    monkeypatch.setattr("gwsa.cli.setup_local.get_token_info", lambda creds: {
        "scopes": mock_scopes,
        "email": "user@example.com"
    })

    # Action
    report = _get_status_report()

    # Assertion
    assert report["status"] == "CONFIGURED"
    assert report["mode"] == "adc"
    assert report["profile"] == "corp-adc"
    assert report["creds_valid"] is True
    assert report["user_email"] == "user@example.com"
    assert report["feature_status"]["mail"] is False  # We only have readonly
    assert report["feature_status"]["sheets"] is True
    assert report["feature_status"]["docs"] is False

def test_get_status_report_configured_oauth_valid_creds(tmp_path: Path, monkeypatch):
    """
    Verify status report for an OAuth profile with a valid token file.
    """
    # Arrange: Config with active_profile = "myprofile"
    config_dir = tmp_path / "gwsa-config"
    config_dir.mkdir()
    config_path = config_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"active_profile": "myprofile"}, f)
    monkeypatch.setenv("GWSA_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("GWSA_CONFIG_FILE", str(config_path))

    # Create profile directory with OAuth type metadata + token
    profile_dir = config_dir / "profiles" / "myprofile"
    profile_dir.mkdir(parents=True)
    with open(profile_dir / "profile.yaml", "w") as f:
        yaml.dump({"type": "oauth", "email": "test@example.com"}, f)
    with open(profile_dir / "user_token.json", "w") as f:
        json.dump({"token": "test", "refresh_token": "test"}, f)

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
    assert report["mode"] == "oauth"
    assert report["profile"] == "myprofile"
    assert report["creds_valid"] is True
    assert report["user_email"] == "test@example.com"
    assert "error_details" not in report
    assert report["feature_status"]["mail"] is True
    assert report["feature_status"]["sheets"] is False
    assert report["feature_status"]["docs"] is False  # We only have readonly
