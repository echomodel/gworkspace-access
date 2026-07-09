"""Tests for Google Docs SDK and MCP tools."""

from unittest.mock import MagicMock, patch
import pytest
from mcp_app.context import current_user
from mcp_app.models import UserRecord

from gwsa import GoogleAccount, Profile
from gwsa.sdk.docs.create import create_document
from gwsa.sdk.docs import get_document, get_document_text, get_document_content


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


class TestReadDocument:
    """Test suite for reading documents, including tabbed document support."""

    @patch("gwsa.sdk.docs.read.get_docs_service")
    @patch("gwsa.sdk.docs.read.get_drive_service")
    def test_get_document_passes_include_tabs_content(self, mock_get_drive_service, mock_get_docs_service):
        """Should pass includeTabsContent=True to the Google Docs API get request."""
        tok = _set_user_with_account()
        try:
            mock_drive = MagicMock()
            mock_get_drive_service.return_value = mock_drive
            mock_drive.files().get().execute.return_value = {"mimeType": "application/vnd.google-apps.document"}

            mock_docs = MagicMock()
            mock_get_docs_service.return_value = mock_docs
            mock_get = mock_docs.documents().get
            mock_get.return_value.execute.return_value = {
                "documentId": "test-doc-id",
                "title": "Test Doc",
                "body": {"content": []}
            }

            get_document("test-doc-id")

            # Verify that includeTabsContent=True was passed to documents().get()
            mock_get.assert_called_once_with(documentId="test-doc-id", includeTabsContent=True)
        finally:
            current_user.reset(tok)

    @patch("gwsa.sdk.docs.read.get_docs_service")
    @patch("gwsa.sdk.docs.read.get_drive_service")
    def test_get_document_content_extracts_text_from_nested_tabs(self, mock_get_drive_service, mock_get_docs_service):
        """Should recursively extract text from all tabs and child tabs in a tabbed document."""
        tok = _set_user_with_account()
        try:
            mock_drive = MagicMock()
            mock_get_drive_service.return_value = mock_drive
            mock_drive.files().get().execute.return_value = {"mimeType": "application/vnd.google-apps.document"}

            mock_docs = MagicMock()
            mock_get_docs_service.return_value = mock_docs
            mock_docs.documents().get().execute.return_value = {
                "documentId": "test-tabbed-doc",
                "title": "Tabbed SOW",
                "revisionId": "rev-123",
                "tabs": [
                    {
                        "tabProperties": {"title": "Tab 1", "tabId": "tab.1"},
                        "documentTab": {
                            "body": {
                                "content": [
                                    {
                                        "paragraph": {
                                            "elements": [{"textRun": {"content": "Content of Tab 1\n"}}]
                                        }
                                    }
                                ]
                            }
                        }
                    },
                    {
                        "tabProperties": {"title": "Tab 2", "tabId": "tab.2"},
                        "childTabs": [
                            {
                                "tabProperties": {"title": "Subtab 2a", "tabId": "tab.2a"},
                                "documentTab": {
                                    "body": {
                                        "content": [
                                            {
                                                "paragraph": {
                                                    "elements": [{"textRun": {"content": "Content of Subtab 2a\n"}}]
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        ]
                    }
                ]
            }

            result = get_document_content("test-tabbed-doc")

            assert result["id"] == "test-tabbed-doc"
            assert result["title"] == "Tabbed SOW"
            assert result["text"] == "Content of Tab 1\nContent of Subtab 2a\n"
            assert result["revision_id"] == "rev-123"
        finally:
            current_user.reset(tok)

