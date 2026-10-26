"""Sociable unit tests for Gmail filters (SDK + MCP wrappers).

Exercises the real SDK ``gwsa.sdk.mail.filters`` end-to-end, faking only
the Google API boundary (the discovery ``service`` object). Covers list,
create (criteria/action building, label-name resolution, the duplicate
check, scope and forwarding rejections) and delete.
"""

import asyncio
import json
from unittest.mock import patch

import httplib2
import pytest
from click.testing import CliRunner
from googleapiclient.errors import HttpError

from gwsa.sdk.mail import (
    DuplicateFilterError,
    FilterScopeError,
    UnknownLabelError,
    create_filter,
    delete_filter,
    get_filter,
    list_filters,
)
from gwsa.cli.__main__ import mail as mail_cli
from gwsa.cli.mail.filters import filters as filters_cli
from gwsa.mcp.tools.mail import (
    create_email_filter,
    delete_email_filter,
    list_email_filters,
)


# --- Fake Gmail discovery service (labels + settings.filters) ---------------

class _Exec:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _Labels:
    def __init__(self, service):
        self._s = service

    def list(self, userId):  # noqa: A002 - mirror API kwarg
        self._s.label_lists += 1
        return _Exec({"labels": self._s.labels})

    def create(self, userId, body):  # noqa: A002
        new = {"id": f"Label_{len(self._s.labels) + 1}", "name": body["name"], "type": "user"}
        self._s.labels.append(new)
        self._s.created_labels.append(body["name"])
        return _Exec(new)


class _Filters:
    def __init__(self, service):
        self._s = service

    def list(self, userId):  # noqa: A002
        if self._s.list_error:
            return _Exec(error=self._s.list_error)
        return _Exec({"filter": list(self._s.filters)})

    def get(self, userId, id):  # noqa: A002
        for f in self._s.filters:
            if f["id"] == id:
                return _Exec(f)
        return _Exec(error=_http_error(404, "Not Found"))

    def create(self, userId, body):  # noqa: A002
        self._s.create_calls.append(body)
        if self._s.create_error:
            return _Exec(error=self._s.create_error)
        # Mirror the API: echo the body, assign an id, and echo an
        # "unspecified" sizeComparison when no size was given.
        new = json.loads(json.dumps(body))
        new["id"] = f"ANe1Bmi{len(self._s.filters) + 1}"
        new["criteria"].setdefault("sizeComparison", "unspecified")
        self._s.filters.append(new)
        return _Exec(new)

    def delete(self, userId, id):  # noqa: A002
        self._s.delete_calls.append(id)
        if self._s.delete_error:
            return _Exec(error=self._s.delete_error)
        self._s.filters = [f for f in self._s.filters if f["id"] != id]
        return _Exec("")


class _Settings:
    def __init__(self, service):
        self._s = service

    def filters(self):
        return _Filters(self._s)


class _Users:
    def __init__(self, service):
        self._s = service

    def labels(self):
        return _Labels(self._s)

    def settings(self):
        return _Settings(self._s)


class FakeGmailService:
    def __init__(self, labels, filters=()):
        self.labels = list(labels)
        self.filters = list(filters)
        self.created_labels = []
        self.create_calls = []
        self.delete_calls = []
        self.label_lists = 0
        self.list_error = None
        self.create_error = None
        self.delete_error = None

    def users(self):
        return _Users(self)


def _http_error(status, message):
    """An ``HttpError`` shaped like Google's: JSON body with ``error.message``."""
    resp = httplib2.Response({"status": status})
    body = json.dumps({"error": {"code": status, "message": message}}).encode()
    return HttpError(resp, body, uri="https://gmail.googleapis.com/x")


def _service(filters=()):
    return FakeGmailService(
        labels=[
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "UNREAD", "name": "UNREAD", "type": "system"},
            {"id": "STARRED", "name": "STARRED", "type": "system"},
            {"id": "Label_9", "name": "Receipts", "type": "user"},
        ],
        filters=filters,
    )


_JIRA = {
    "id": "ANe1Bmi_existing",
    "criteria": {"from": "jira@example.com", "sizeComparison": "unspecified"},
    "action": {"removeLabelIds": ["INBOX"]},
}


class _patch:
    """Patch the service factory everywhere the filters path reaches it."""

    def __init__(self, service):
        self._patches = [
            patch("gwsa.sdk.mail.filters.get_gmail_service", return_value=service),
            patch("gwsa.sdk.mail.label.get_gmail_service", return_value=service),
        ]

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


# --- list -----------------------------------------------------------------

def test_list_resolves_label_names_and_summarizes():
    service = _service(filters=[
        _JIRA,
        {
            "id": "f2",
            "criteria": {"query": "list:deals", "hasAttachment": False},
            "action": {"addLabelIds": ["Label_9", "STARRED"],
                       "removeLabelIds": ["INBOX", "UNREAD"],
                       "forward": "other@example.com"},
        },
    ])
    with _patch(service):
        result = list_filters()

    assert [f["id"] for f in result] == ["ANe1Bmi_existing", "f2"]
    first = result[0]
    # API defaults ("unspecified", false) are dropped from criteria.
    assert first["criteria"] == {"from": "jira@example.com"}
    assert first["action"] == {
        "add_labels": [], "remove_labels": ["INBOX"], "forward": None,
        "add_label_ids": [], "remove_label_ids": ["INBOX"],
    }
    assert first["summary"] == "from:jira@example.com → archive"

    second = result[1]
    assert second["criteria"] == {"query": "list:deals"}
    assert second["action"]["add_labels"] == ["Receipts", "STARRED"]
    assert second["action"]["remove_labels"] == ["INBOX", "UNREAD"]
    assert second["summary"] == (
        "list:deals → archive, mark read, label Receipts, star, "
        "forward to other@example.com"
    )


def test_list_keeps_unknown_label_ids_verbatim():
    service = _service(filters=[{
        "id": "f1", "criteria": {"to": "me@example.com"},
        "action": {"addLabelIds": ["Label_gone"]},
    }])
    with _patch(service):
        [only] = list_filters()
    assert only["action"]["add_labels"] == ["Label_gone"]
    assert only["summary"] == "to:me@example.com → label Label_gone"


def test_get_returns_one_filter():
    service = _service(filters=[_JIRA])
    with _patch(service):
        found = get_filter("ANe1Bmi_existing")
    assert found["id"] == "ANe1Bmi_existing"
    assert found["summary"] == "from:jira@example.com → archive"


# --- create: criteria and action building ---------------------------------

def test_create_archive_filter_sends_only_set_fields():
    service = _service()
    with _patch(service):
        created = create_filter(from_address="jira@example.com", remove_labels=["INBOX"])

    assert service.create_calls == [{
        "criteria": {"from": "jira@example.com"},
        "action": {"removeLabelIds": ["INBOX"]},
    }]
    assert created["id"] == "ANe1Bmi1"
    assert created["criteria"] == {"from": "jira@example.com"}
    assert created["action"]["remove_labels"] == ["INBOX"]
    assert created["summary"] == "from:jira@example.com → archive"


def test_create_resolves_names_creates_missing_add_label():
    service = _service()
    with _patch(service):
        created = create_filter(
            query="list:deals",
            add_labels=["Receipts", "Deals"],
            remove_labels=["inbox", "UNREAD"],  # case-insensitive system label
            forward="other@example.com",
        )

    assert service.created_labels == ["Deals"]
    body = service.create_calls[0]
    assert body["action"] == {
        "addLabelIds": ["Label_9", "Label_5"],
        "removeLabelIds": ["INBOX", "UNREAD"],
        "forward": "other@example.com",
    }
    assert created["action"]["add_labels"] == ["Receipts", "Deals"]
    assert created["action"]["remove_labels"] == ["INBOX", "UNREAD"]


def test_create_refuses_unknown_remove_label_without_writing():
    service = _service()
    with _patch(service), pytest.raises(UnknownLabelError) as info:
        create_filter(from_address="x@example.com", remove_labels=["Nope"])
    assert "Nope" in str(info.value)
    assert "Receipts" in str(info.value)
    assert service.create_calls == []
    assert service.created_labels == []


def test_create_with_size_and_all_criteria():
    service = _service()
    with _patch(service):
        created = create_filter(
            from_address="a@example.com", to_address="b@example.com",
            subject="invoice", query="has:attachment", negated_query="label:keep",
            has_attachment=True, size=1000000, size_comparison="larger",
            add_labels=["STARRED"],
        )
    assert service.create_calls[0]["criteria"] == {
        "from": "a@example.com", "to": "b@example.com", "subject": "invoice",
        "query": "has:attachment", "negatedQuery": "label:keep",
        "hasAttachment": True, "size": 1000000, "sizeComparison": "larger",
    }
    assert created["summary"] == (
        "from:a@example.com to:b@example.com subject:invoice has:attachment "
        "-(label:keep) has:attachment size>1000000 → star"
    )


@pytest.mark.parametrize("kwargs, fragment", [
    ({}, "at least one criterion"),
    ({"size": 10}, "together"),
    ({"size_comparison": "larger"}, "together"),
    ({"size": 10, "size_comparison": "bigger"}, "size_comparison must be one of"),
    ({"size": 0, "size_comparison": "larger"}, "positive"),
])
def test_create_refuses_bad_criteria_without_writing(kwargs, fragment):
    service = _service()
    with _patch(service), pytest.raises(ValueError) as info:
        create_filter(remove_labels=["INBOX"], **kwargs)
    assert fragment in str(info.value)
    assert service.create_calls == []


def test_create_requires_an_action_and_makes_no_call():
    service = _service()
    with _patch(service), pytest.raises(ValueError) as info:
        create_filter(from_address="x@example.com")
    assert "at least one action" in str(info.value)
    assert service.create_calls == []


# --- create: duplicate check ----------------------------------------------

def test_create_refuses_duplicate_criteria_even_with_different_action():
    service = _service(filters=[_JIRA])
    with _patch(service), pytest.raises(DuplicateFilterError) as info:
        create_filter(from_address="jira@example.com", add_labels=["NewLabel"])
    assert info.value.existing["id"] == "ANe1Bmi_existing"
    assert "ANe1Bmi_existing" in str(info.value)
    assert "Nothing was created" in str(info.value)
    assert service.create_calls == []
    assert service.created_labels == []  # refused before any label was made


def test_create_allows_same_action_with_different_criteria():
    service = _service(filters=[_JIRA])
    with _patch(service):
        created = create_filter(from_address="@newsletters.example.com", remove_labels=["INBOX"])
    assert created["id"] == "ANe1Bmi2"
    assert len(service.create_calls) == 1


# --- create / delete: API rejections ---------------------------------------

def test_create_translates_missing_scope():
    service = _service()
    service.create_error = _http_error(
        403, "Request had insufficient authentication scopes."
    )
    with _patch(service), pytest.raises(FilterScopeError) as info:
        create_filter(from_address="x@example.com", remove_labels=["INBOX"])
    msg = str(info.value)
    assert "gmail.settings.basic" in msg
    assert "acquire-token" in msg
    assert "accounts add" in msg


def test_create_reports_unverified_forwarding_address():
    service = _service()
    service.create_error = _http_error(
        400, "Invalid forwarding address: other@example.com"
    )
    with _patch(service), pytest.raises(ValueError) as info:
        create_filter(from_address="x@example.com", forward="other@example.com")
    msg = str(info.value)
    assert "Invalid forwarding address" in msg  # the API's own words
    assert "verified" in msg
    assert "Nothing was created" in msg


def test_create_other_http_errors_propagate_unchanged():
    service = _service()
    service.create_error = _http_error(500, "Backend Error")
    with _patch(service), pytest.raises(HttpError):
        create_filter(from_address="x@example.com", remove_labels=["INBOX"])


def test_delete_by_id_only():
    service = _service(filters=[_JIRA])
    with _patch(service):
        result = delete_filter("ANe1Bmi_existing")
    assert result == {"id": "ANe1Bmi_existing", "deleted": True}
    assert service.delete_calls == ["ANe1Bmi_existing"]
    assert service.filters == []


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_delete_requires_an_id(bad):
    service = _service(filters=[_JIRA])
    with _patch(service), pytest.raises(ValueError):
        delete_filter(bad)
    assert service.delete_calls == []


def test_delete_translates_missing_scope():
    service = _service(filters=[_JIRA])
    service.delete_error = _http_error(403, "ACCESS_TOKEN_SCOPE_INSUFFICIENT")
    with _patch(service), pytest.raises(FilterScopeError):
        delete_filter("ANe1Bmi_existing")


# --- MCP wrappers ---------------------------------------------------------

def test_mcp_list_returns_filters_and_count():
    service = _service(filters=[_JIRA])
    with _patch(service):
        result = asyncio.run(list_email_filters())
    assert result["count"] == 1
    assert result["filters"][0]["summary"] == "from:jira@example.com → archive"


def test_mcp_list_reports_failure_as_error():
    with patch("gwsa.sdk.mail.filters.get_gmail_service", side_effect=RuntimeError("boom")):
        result = asyncio.run(list_email_filters())
    assert result == {"error": "boom"}


def test_mcp_create_envelope_says_new_mail_only():
    service = _service()
    with _patch(service):
        result = asyncio.run(
            create_email_filter(from_address="jira@example.com", remove_labels=["INBOX"])
        )
    assert result["success"] is True
    assert result["filter"]["id"] == "ANe1Bmi1"
    assert "from now on" in result["message"]
    assert "unchanged" in result["message"]


def test_mcp_create_duplicate_returns_existing_filter():
    service = _service(filters=[_JIRA])
    with _patch(service):
        result = asyncio.run(
            create_email_filter(from_address="jira@example.com", remove_labels=["INBOX"])
        )
    assert result["success"] is False
    assert result["existing_filter"]["id"] == "ANe1Bmi_existing"
    assert "already exists" in result["error"]
    assert service.create_calls == []


def test_mcp_create_missing_scope_error_is_actionable():
    service = _service()
    service.create_error = _http_error(403, "Request had insufficient authentication scopes.")
    with _patch(service):
        result = asyncio.run(
            create_email_filter(from_address="x@example.com", remove_labels=["INBOX"])
        )
    assert result["success"] is False
    assert "gmail.settings.basic" in result["error"]
    assert "acquire-token" in result["error"]


def test_mcp_delete_succeeds_by_id_and_refuses_blank_id():
    service = _service(filters=[_JIRA])
    with _patch(service):
        ok = asyncio.run(delete_email_filter("ANe1Bmi_existing"))
        missing = asyncio.run(delete_email_filter(""))
    assert ok == {"success": True, "id": "ANe1Bmi_existing"}
    assert missing["success"] is False
    assert "filter_id is required" in missing["error"]


# --- CLI ------------------------------------------------------------------

def _cli(*args):
    return CliRunner().invoke(filters_cli, list(args))


def test_cli_list_prints_filters_as_json():
    service = _service(filters=[_JIRA])
    with _patch(service):
        r = _cli("list")
    assert r.exit_code == 0, r.output
    [only] = json.loads(r.output)
    assert only["id"] == "ANe1Bmi_existing"
    assert only["summary"] == "from:jira@example.com → archive"


def test_cli_get_prints_one_filter():
    service = _service(filters=[_JIRA])
    with _patch(service):
        r = _cli("get", "ANe1Bmi_existing")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["action"]["remove_labels"] == ["INBOX"]


def test_cli_create_archive_filter():
    service = _service()
    with _patch(service):
        r = _cli("create", "--from", "jira@example.com", "--remove", "INBOX")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["summary"] == "from:jira@example.com → archive"
    assert service.create_calls == [{
        "criteria": {"from": "jira@example.com"},
        "action": {"removeLabelIds": ["INBOX"]},
    }]


def test_cli_create_passes_every_option_through():
    service = _service()
    with _patch(service):
        r = _cli("create", "--to", "me@example.com", "--subject", "invoice",
                 "--query", "has:attachment", "--negated-query", "label:keep",
                 "--has-attachment", "--size", "5000", "--size-comparison", "larger",
                 "--add", "Receipts", "--add", "STARRED", "--remove", "UNREAD",
                 "--forward", "other@example.com")
    assert r.exit_code == 0, r.output
    assert service.create_calls[0] == {
        "criteria": {"to": "me@example.com", "subject": "invoice",
                     "query": "has:attachment", "negatedQuery": "label:keep",
                     "hasAttachment": True, "size": 5000, "sizeComparison": "larger"},
        "action": {"addLabelIds": ["Label_9", "STARRED"],
                   "removeLabelIds": ["UNREAD"], "forward": "other@example.com"},
    }


def test_cli_create_errors_are_clean_and_nonzero():
    service = _service(filters=[_JIRA])
    with _patch(service):
        dup = _cli("create", "--from", "jira@example.com", "--remove", "INBOX")
        no_action = _cli("create", "--from", "x@example.com")
        bad_label = _cli("create", "--from", "x@example.com", "--remove", "Nope")
        bad_choice = _cli("create", "--from", "x@example.com", "--remove", "INBOX",
                          "--size", "5", "--size-comparison", "bigger")
    assert dup.exit_code == 1 and "already exists" in dup.output
    assert no_action.exit_code == 1 and "at least one action" in no_action.output
    assert bad_label.exit_code == 1 and "Nope" in bad_label.output
    assert bad_choice.exit_code == 2 and "size-comparison" in bad_choice.output
    assert service.create_calls == []


def test_cli_create_missing_scope_names_the_fix():
    service = _service()
    service.create_error = _http_error(403, "Request had insufficient authentication scopes.")
    with _patch(service):
        r = _cli("create", "--from", "x@example.com", "--remove", "INBOX")
    assert r.exit_code == 1
    assert "gmail.settings.basic" in r.output and "acquire-token" in r.output


def test_cli_delete_by_id():
    service = _service(filters=[_JIRA])
    with _patch(service):
        r = _cli("delete", "ANe1Bmi_existing")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output) == {"id": "ANe1Bmi_existing", "deleted": True}
    assert service.delete_calls == ["ANe1Bmi_existing"]


def test_cli_filters_registered_under_mail():
    assert mail_cli.commands["filters"] is filters_cli
    assert set(filters_cli.commands) == {"list", "get", "create", "delete"}
    for cmd in ("search", "read", "label", "threads"):
        assert cmd in mail_cli.commands, cmd
