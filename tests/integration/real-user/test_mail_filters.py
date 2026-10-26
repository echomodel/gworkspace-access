"""Live Gmail filter lifecycle against the configured local account.

Creates a filter on a throwaway ``example.com`` sender, checks it is
listed and fetchable, checks the duplicate refusal, deletes it, and
checks it is gone. The account is left exactly as found. Skips, with
the error's own words, when the stored token lacks
``gmail.settings.basic``.
"""

import uuid

import pytest

from gwsa.sdk import mail
from gwsa.sdk.mail import DuplicateFilterError, FilterScopeError


@pytest.mark.integration
def test_filter_lifecycle():
    sender = f"gwsa-test-{uuid.uuid4().hex[:8]}@example.com"
    created = None
    try:
        try:
            created = mail.create_filter(from_address=sender, remove_labels=["INBOX"])
        except FilterScopeError as e:
            pytest.skip(str(e))

        assert created["id"]
        assert created["criteria"] == {"from": sender}
        assert created["action"]["remove_labels"] == ["INBOX"]
        assert created["summary"] == f"from:{sender} → archive"

        listed = {f["id"]: f for f in mail.list_filters()}
        assert created["id"] in listed
        assert listed[created["id"]]["summary"] == created["summary"]

        fetched = mail.get_filter(created["id"])
        assert fetched["id"] == created["id"]

        with pytest.raises(DuplicateFilterError) as info:
            mail.create_filter(from_address=sender, add_labels=["STARRED"])
        assert info.value.existing["id"] == created["id"]
    finally:
        if created is not None:
            assert mail.delete_filter(created["id"]) == {
                "id": created["id"], "deleted": True
            }
            created = None

    assert all(f["criteria"] != {"from": sender} for f in mail.list_filters())
