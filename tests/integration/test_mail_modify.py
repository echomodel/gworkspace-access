"""
Integration tests for 'gwsa mail label' command and message modifications.

Tests label application and removal using profile-based configuration
from tests/test-config.yaml.
"""

import pytest


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_labels(cli_runner, search_query, today_minus_n_days, test_label):
    """
    Setup: Remove test label from all matching emails before tests run.
    Teardown: Remove test label from all matching emails after tests complete.

    This ensures a clean test environment and leaves the mailbox in a clean state.
    """
    # Pre-test cleanup: Remove test label from target emails
    full_query = f'{search_query} after:{today_minus_n_days} label:{test_label}'
    search_result = cli_runner(["mail", "search", full_query])

    if search_result["returncode"] == 0 and search_result["json"]:
        for msg in search_result["json"]:
            cli_runner(["mail", "label", msg["id"], test_label, "--remove"])

    # Yield control to tests
    yield

    # Post-test cleanup: Remove test label from all target emails
    search_result = cli_runner(["mail", "search", full_query])

    if search_result["returncode"] == 0 and search_result["json"]:
        for msg in search_result["json"]:
            cli_runner(["mail", "label", msg["id"], test_label, "--remove"])


@pytest.mark.integration
def test_mail_label_apply(cli_runner, search_query, today_minus_n_days, test_email_id, test_label):
    """
    Test applying a label to an email message.

    This test validates:
    1. Label can be applied to a message
    2. Message is readable before and after labeling
    3. Label presence is confirmed in the message details
    4. No other message properties are changed

    Workflow:
    1. Search for target email without the test label
    2. Read email details to verify label is NOT present
    3. Apply test label to the email
    4. Read email details again to verify label IS present
    """
    message_id = test_email_id

    # Step 1: Search for the email without the test label
    full_query = f'{search_query} after:{today_minus_n_days} -label:{test_label}'
    search_result = cli_runner(["mail", "search", full_query])

    assert search_result["returncode"] == 0, f"Search failed: {search_result['stderr']}"
    assert search_result["json"] is not None, "Invalid JSON response"
    assert len(search_result["json"]) > 0, (
        "No unlabeled emails found. Test label may already exist on target email."
    )

    # Step 2: Read email details BEFORE applying label
    read_before = cli_runner(["mail", "read", message_id])

    assert read_before["returncode"] == 0, f"Read command failed: {read_before['stderr']}"
    assert read_before["json"] is not None, "Invalid JSON response"

    message_before = read_before["json"]
    label_ids_before = message_before.get("labelIds", [])

    # Verify test label is NOT present before
    assert not any(test_label in str(label_id) for label_id in label_ids_before), (
        f"{test_label} label already present on message"
    )

    # Step 3: Apply the test label
    label_result = cli_runner(["mail", "label", message_id, test_label])

    assert label_result["returncode"] == 0, f"Label command failed: {label_result['stderr']}"
    assert label_result["json"] is not None, "Invalid JSON response from label command"

    # Step 4: Read email details AFTER applying label
    read_after = cli_runner(["mail", "read", message_id])

    assert read_after["returncode"] == 0, f"Read command failed: {read_after['stderr']}"
    assert read_after["json"] is not None, "Invalid JSON response"

    message_after = read_after["json"]
    label_ids_after = message_after.get("labelIds", [])

    # Verify test label IS present after
    assert len(label_ids_after) > len(label_ids_before), (
        "No new label added to message"
    )

    # Verify other fields unchanged
    assert message_before["id"] == message_after["id"], "Message ID changed"
    assert message_before["subject"] == message_after["subject"], "Subject changed"
    assert message_before["from"] == message_after["from"], "From changed"
    assert message_before["date"] == message_after["date"], "Date changed"


@pytest.mark.integration
def test_mail_label_remove(cli_runner, search_query, today_minus_n_days, test_email_id, test_label):
    """
    Test removing a label from an email message.

    This test validates:
    1. Label can be removed from a message
    2. Message is readable before and after removal
    3. Label absence is confirmed in the message details
    4. No other message properties are changed

    Dependencies:
        Must run AFTER test_mail_label_apply so the label exists

    Workflow:
    1. Search for the email WITH the test label
    2. Read email details to verify label IS present
    3. Remove test label from the email
    4. Read email details again to verify label is NOT present
    """
    message_id = test_email_id

    # Step 1: Search for the email WITH the test label
    full_query = f'{search_query} after:{today_minus_n_days} label:{test_label}'
    search_result = cli_runner(["mail", "search", full_query])

    assert search_result["returncode"] == 0, f"Search failed: {search_result['stderr']}"
    assert search_result["json"] is not None, "Invalid JSON response"
    assert len(search_result["json"]) > 0, (
        f"No {test_label}-labeled emails found. Run test_mail_label_apply first."
    )

    # Step 2: Read email details BEFORE removing label
    read_before = cli_runner(["mail", "read", message_id])

    assert read_before["returncode"] == 0, f"Read command failed: {read_before['stderr']}"
    assert read_before["json"] is not None, "Invalid JSON response"

    message_before = read_before["json"]
    label_ids_before = message_before.get("labelIds", [])

    # Verify test label IS present before removal
    assert len(label_ids_before) > 0, "Message has no labels"

    # Step 3: Remove the test label
    remove_result = cli_runner(["mail", "label", message_id, test_label, "--remove"])

    assert remove_result["returncode"] == 0, f"Remove label command failed: {remove_result['stderr']}"
    assert remove_result["json"] is not None, "Invalid JSON response from remove command"

    # Step 4: Read email details AFTER removing label
    read_after = cli_runner(["mail", "read", message_id])

    assert read_after["returncode"] == 0, f"Read command failed: {read_after['stderr']}"
    assert read_after["json"] is not None, "Invalid JSON response"

    message_after = read_after["json"]
    label_ids_after = message_after.get("labelIds", [])

    # Verify test label is NOT present after removal
    assert len(label_ids_after) < len(label_ids_before), (
        "Label was not removed from message"
    )

    # Verify other fields unchanged
    assert message_before["id"] == message_after["id"], "Message ID changed"
    assert message_before["subject"] == message_after["subject"], "Subject changed"
    assert message_before["from"] == message_after["from"], "From changed"
    assert message_before["date"] == message_after["date"], "Date changed"
