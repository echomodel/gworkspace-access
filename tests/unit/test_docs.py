"""Tests for Google Docs SDK and MCP tools."""

from unittest.mock import MagicMock, patch
import pytest
from mcp_app.context import current_user
from mcp_app.models import UserRecord

from gwsa import GoogleAccount, Profile
from gwsa.sdk.docs.create import create_document


def _set_user_with_account():
    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token={
                    "client_id": "user-owned-client",
                    "client_secret": "test-secret",
                    "refresh_token": "test-refresh",
                    "token_uri": "https://oauth2.googleapis.com/token",
                },
            ),
        ],
    )
    user = UserRecord(
        email="alice@example.com",
        profile=profile.model_dump(mode="json"),
    )
    return current_user.set(user)


class TestCreateDocument:
    """Test suite for create_document SDK function."""

    @patch("gwsa.sdk.docs.create.get_docs_service")
    def test_create_document_plain_text(self, mock_get_docs_service):
        """Should create a document and insert plain text using Docs API."""
        tok = _set_user_with_account()
        try:
            mock_docs_service = MagicMock()
            mock_get_docs_service.return_value = mock_docs_service

            # Mock docs_service.documents().create(body=...).execute()
            mock_create = mock_docs_service.documents().create
            mock_create.return_value.execute.return_value = {
                "documentId": "test-doc-id-123"
            }

            # Mock docs_service.documents().batchUpdate(body=...).execute()
            mock_batch_update = mock_docs_service.documents().batchUpdate
            mock_batch_update.return_value.execute.return_value = {}

            result = create_document(
                title="Test Plain Doc",
                body_text="Hello World",
            )

            assert result["id"] == "test-doc-id-123"
            assert result["title"] == "Test Plain Doc"

            # Verify Docs API was called
            mock_create.assert_called_once_with(
                body={"title": "Test Plain Doc"}
            )
            mock_batch_update.assert_called_once()
        finally:
            current_user.reset(tok)

    @patch("gwsa.sdk.docs.create.get_drive_service")
    def test_create_document_html(self, mock_get_drive_service):
        """Should upload HTML and convert it using Drive API when mime_type='text/html'."""
        tok = _set_user_with_account()
        try:
            mock_drive_service = MagicMock()
            mock_get_drive_service.return_value = mock_drive_service

            # Mock drive_service.files().create(body=...).execute()
            mock_id = "test-html-doc-id-456"
            mock_create = mock_drive_service.files().create
            mock_create.return_value.execute.return_value = {
                "id": mock_id,
                "name": "Test HTML Doc",
                "webViewLink": f"https://docs.google.com/document/d/{mock_id}/edit",
            }

            result = create_document(
                title="Test HTML Doc",
                body_text="<h1>Hello HTML</h1>",
                mime_type="text/html",
            )

            assert result["id"] == "test-html-doc-id-456"
            assert result["title"] == "Test HTML Doc"
            assert "test-html-doc-id-456" in result["url"]

            # Verify Drive API was called instead of Docs API
            mock_drive_service.files().create.assert_called_once()
            call_args = mock_drive_service.files().create.call_args[1]
            assert call_args["body"]["name"] == "Test HTML Doc"
            assert call_args["body"]["mimeType"] == "application/vnd.google-apps.document"
        finally:
            current_user.reset(tok)
