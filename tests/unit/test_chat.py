"""Unit tests for Google Chat tools (SDK + MCP wrappers)."""

from __future__ import annotations

import pytest
from typing import Any, Optional
from gwsa.sdk import chat as chat_sdk
from gwsa.mcp.tools import chat as chat_tools
from gwsa.sdk.destinations import InlineDestination, DriveDestination

class FakeExecute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeMedia:
    def __init__(self, store):
        self._store = store

    def download_media(self, resourceName):
        self._store["download_media_resource"] = resourceName
        return FakeExecute({"resourceName": resourceName})


class FakeMessages:
    def __init__(self, store):
        self._store = store

    def list(self, **kwargs):
        self._store["list_kwargs"] = kwargs
        messages = [
            {
                "name": "spaces/space-id/messages/msg-id",
                "text": "Hello world with attachment",
                "createTime": "2026-06-17T10:00:00Z",
                "sender": {"name": "users/user-id", "displayName": "Alice"},
                "attachment": [
                    {
                        "name": "spaces/space-id/messages/msg-id/attachments/att-id",
                        "contentName": "test.pdf",
                        "contentType": "application/pdf",
                        "attachmentDataRef": {"resourceName": "base64-ref"},
                        "downloadUri": "https://chat.google.com/download/test.pdf",
                    }
                ],
            }
        ]
        return FakeExecute({"messages": messages, "nextPageToken": None})


class FakeSpaces:
    def __init__(self, store):
        self._store = store

    def messages(self):
        return FakeMessages(self._store)


class FakeChatService:
    def __init__(self, store):
        self._store = store

    def spaces(self):
        return FakeSpaces(self._store)

    def media(self):
        return FakeMedia(self._store)


@pytest.fixture
def patch_chat_service(monkeypatch):
    store: dict = {}

    def fake_factory(account=None):
        return FakeChatService(store)

    monkeypatch.setattr("gwsa.sdk.chat.service.get_chat_service", fake_factory)
    monkeypatch.setattr("gwsa.mcp.tools.chat.chat.get_chat_service", fake_factory)
    
    # Mock MediaIoBaseDownload
    class MockMediaIoBaseDownload:
        def __init__(self, fd, request):
            self.fd = fd
            self.request = request

        def next_chunk(self):
            self.fd.write(b"%PDF-1.4 dummy pdf content")
            return None, True

    monkeypatch.setattr(
        "googleapiclient.http.MediaIoBaseDownload", MockMediaIoBaseDownload
    )
    
    # Mock get_person_name in all modules to avoid caching/import issues
    mock_get_name = lambda uid, account=None: f"Resolved {uid}"
    
    # original definition
    monkeypatch.setattr("gwsa.sdk.people.service.get_person_name", mock_get_name)
    # package exports
    monkeypatch.setattr("gwsa.sdk.people.get_person_name", mock_get_name)
    # module imports
    monkeypatch.setattr("gwsa.mcp.tools.chat.get_person_name", mock_get_name)
    
    return store


# -----------------------------------------------------------------------------
# SDK Unit Tests (SDK-First testing)
# -----------------------------------------------------------------------------

def test_search_messages_sdk_includes_attachments(patch_chat_service):
    res = chat_sdk.search_messages(space_id="spaces/space-id", query="attachment")
    # search_messages returns a dict with "messages" list
    messages = res.get("messages", [])
    assert len(messages) == 1
    msg = messages[0]
    assert msg["name"] == "spaces/space-id/messages/msg-id"
    assert msg["attachment"] is not None
    assert msg["attachment"][0]["contentName"] == "test.pdf"


def test_download_attachment_sdk_downloads_bytes(patch_chat_service):
    content = chat_sdk.download_attachment(resource_name="base64-ref")
    assert content == b"%PDF-1.4 dummy pdf content"
    assert patch_chat_service["download_media_resource"] == "base64-ref"


# -----------------------------------------------------------------------------
# MCP Wrapper Unit Tests (Thin Wrapper Integration checks)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_chat_messages_includes_attachments(patch_chat_service):
    res = await chat_tools.list_chat_messages(space_id="spaces/space-id")
    messages = res.get("messages", [])
    assert len(messages) == 1
    msg = messages[0]
    assert msg["name"] == "spaces/space-id/messages/msg-id"
    assert msg["author"] == "Resolved users/user-id"
    assert msg["attachment"] is not None
    assert msg["attachment"][0]["contentName"] == "test.pdf"


@pytest.mark.asyncio
async def test_download_chat_attachment_inline(patch_chat_service):
    res = await chat_tools.download_chat_attachment(
        resource_name="base64-ref",
        filename="test.pdf",
        mime_type="application/pdf",
        destination=InlineDestination(max_size_bytes=1000),
    )
    
    # Should return a list of ContentBlocks
    assert isinstance(res, list)
    assert len(res) == 2
    # First is summary
    assert res[0].type == "text"
    # Second is embedded resource blob
    assert res[1].type == "resource"
    assert res[1].resource.mimeType == "application/pdf"
