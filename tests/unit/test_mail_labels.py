"""Sociable unit tests for batch label modification.

Exercises the real SDK ``modify_labels`` end-to-end, faking only the
Google API HTTP boundary (the discovery ``service`` object). Asserts
that the batch primitive resolves label names to IDs, applies one
delta to every message via ``messages.batchModify`` (chunked at 1000),
and behaves idempotently.
"""

import asyncio
from unittest.mock import patch

import pytest

from gwsa.sdk.mail import modify_labels
from gwsa.mcp.tools.mail import modify_email_labels


# --- Fake Gmail discovery service (labels + messages resources) -----------

class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _Labels:
    def __init__(self, service):
        self._s = service

    def list(self, userId):  # noqa: A002 - mirror API kwarg
        return _Exec({"labels": self._s.labels})

    def create(self, userId, body):  # noqa: A002
        new = {"id": f"Label_{len(self._s.labels) + 1}", "name": body["name"], "type": "user"}
        self._s.labels.append(new)
        self._s.created.append(body["name"])
        return _Exec(new)


class _Messages:
    def __init__(self, service):
        self._s = service

    def batchModify(self, userId, body):  # noqa: A002
        self._s.batch_calls.append(body)
        return _Exec("")


class _Users:
    def __init__(self, service):
        self._s = service

    def labels(self):
        return _Labels(self._s)

    def messages(self):
        return _Messages(self._s)


class FakeGmailService:
    """Records batchModify calls and label creations."""

    def __init__(self, labels):
        self.labels = list(labels)
        self.created = []
        self.batch_calls = []

    def users(self):
        return _Users(self)


def _service():
    return FakeGmailService([
        {"id": "INBOX", "name": "INBOX", "type": "system"},
        {"id": "UNREAD", "name": "UNREAD", "type": "system"},
        {"id": "Label_9", "name": "Existing", "type": "user"},
    ])


def _patch(service):
    return patch("gwsa.sdk.mail.label.get_gmail_service", return_value=service)


# --- Tests ----------------------------------------------------------------

def test_archive_many_is_one_batch_call():
    service = _service()
    ids = ["m1", "m2", "m3"]
    with _patch(service):
        result = modify_labels(ids, remove_labels=["INBOX"])

    assert result == {"message_ids": ids, "count": 3, "added": [], "removed": ["INBOX"]}
    assert len(service.batch_calls) == 1
    call = service.batch_calls[0]
    assert call["ids"] == ids
    assert call["removeLabelIds"] == ["INBOX"]
    assert call["addLabelIds"] == []


def test_add_and_remove_in_one_delta_creates_missing_label():
    service = _service()
    with _patch(service):
        result = modify_labels(["m1"], add_labels=["ToReview"], remove_labels=["INBOX"])

    assert service.created == ["ToReview"]  # auto-created
    assert len(service.batch_calls) == 1
    call = service.batch_calls[0]
    assert call["addLabelIds"] == ["Label_4"]  # the newly created id
    assert call["removeLabelIds"] == ["INBOX"]
    assert result["added"] == ["ToReview"]
    assert result["removed"] == ["INBOX"]


def test_removing_unknown_label_is_a_clean_noop():
    service = _service()
    with _patch(service):
        result = modify_labels(["m1"], remove_labels=["DoesNotExist"])

    # Unknown label resolves to nothing → no API call, no failure.
    assert service.batch_calls == []
    assert result["count"] == 1
    assert result["removed"] == ["DoesNotExist"]


def test_empty_delta_makes_no_api_call():
    service = _service()
    with _patch(service):
        result = modify_labels(["m1", "m2"])
    assert service.batch_calls == []
    assert result["count"] == 2


def test_no_ids_makes_no_api_call():
    service = _service()
    with _patch(service):
        result = modify_labels([], remove_labels=["INBOX"])
    assert service.batch_calls == []
    assert result["count"] == 0


def test_bare_string_id_is_normalized_to_a_list():
    service = _service()
    with _patch(service):
        result = modify_labels("m1", remove_labels=["INBOX"])
    assert result["message_ids"] == ["m1"]
    assert service.batch_calls[0]["ids"] == ["m1"]


def test_ids_are_chunked_at_1000():
    service = _service()
    ids = [f"m{i}" for i in range(1500)]
    with _patch(service):
        modify_labels(ids, remove_labels=["INBOX"])

    assert len(service.batch_calls) == 2
    assert len(service.batch_calls[0]["ids"]) == 1000
    assert len(service.batch_calls[1]["ids"]) == 500
    # Every id lands exactly once across the chunks.
    seen = service.batch_calls[0]["ids"] + service.batch_calls[1]["ids"]
    assert seen == ids


def test_mcp_tool_wraps_sdk_and_returns_envelope():
    service = _service()
    with _patch(service):
        result = asyncio.run(
            modify_email_labels(["m1", "m2"], remove=["INBOX"])
        )
    assert result == {
        "success": True,
        "count": 2,
        "message_ids": ["m1", "m2"],
        "added": [],
        "removed": ["INBOX"],
    }
    assert service.batch_calls[0]["ids"] == ["m1", "m2"]


def test_mcp_tool_returns_error_envelope_on_failure():
    with patch("gwsa.sdk.mail.label.get_gmail_service", side_effect=RuntimeError("boom")):
        result = asyncio.run(modify_email_labels(["m1"], remove=["INBOX"]))
    assert "error" in result
    assert "boom" in result["error"]
