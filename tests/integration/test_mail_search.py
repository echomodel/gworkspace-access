"""
Integration tests for 'gwsa mail search' command.

Tests the email search functionality using profile-based configuration
from tests/test-config.yaml.
"""

import pytest


@pytest.mark.integration
def test_mail_search_results_found(cli_runner, search_query, today_minus_n_days, min_results, days_range):
    """
    Search for emails matching the profile's configured search query.

    This test validates:
    1. Search query parsing and Gmail API interaction
    2. JSON response format and field presence
    3. Sufficient test data availability

    Expected Results:
        - At least min_results emails returned
        - Valid JSON array response
        - Each message contains: id, subject, from, date
    """
    full_query = f'{search_query} after:{today_minus_n_days}'

    # Execute search
    result = cli_runner(["mail", "search", full_query])

    # Verify command executed successfully
    assert result["returncode"] == 0, f"Search command failed: {result['stderr']}"

    # Verify response is valid JSON
    assert result["json"] is not None, "Response is not valid JSON"

    # Verify response is a list
    assert isinstance(result["json"], list), "Expected response to be a list of messages"

    messages = result["json"]

    # Verify we have sufficient test data
    assert len(messages) >= min_results, (
        f"Expected at least {min_results} emails, found {len(messages)}. "
        f"Adjust search_query in test-config.yaml for this profile."
    )

    # Verify each message has required fields
    for idx, message in enumerate(messages):
        assert isinstance(message, dict), f"Message {idx} is not a dict: {message}"

        # Check required fields
        assert "id" in message, f"Message {idx} missing 'id' field"
        assert "subject" in message, f"Message {idx} missing 'subject' field"
        assert "from" in message, f"Message {idx} missing 'from' field"
        assert "date" in message, f"Message {idx} missing 'date' field"

        # Verify field types
        assert isinstance(message["id"], str), f"Message {idx}: id must be string"
        assert isinstance(message["subject"], str), f"Message {idx}: subject must be string"
        assert isinstance(message["from"], str), f"Message {idx}: from must be string"
        assert isinstance(message["date"], str), f"Message {idx}: date must be string"

        # Verify field values are non-empty
        assert message["id"], f"Message {idx}: id is empty"
        assert message["subject"], f"Message {idx}: subject is empty"
        assert message["from"], f"Message {idx}: from is empty"
        assert message["date"], f"Message {idx}: date is empty"

    # Verify no duplicate message IDs
    assert len(messages) == len(set(m["id"] for m in messages)), (
        "Duplicate message IDs in results"
    )


@pytest.mark.integration
def test_mail_search_empty_results(cli_runner):
    """
    Verify search handles empty results gracefully.

    This test confirms that when a search returns no results,
    the response is valid JSON (empty list) rather than an error.
    """
    # Use a query unlikely to match anything
    search_query = 'from:"nonexistent-email-address-xyz-12345@example.com"'

    result = cli_runner(["mail", "search", search_query])

    # Command should succeed
    assert result["returncode"] == 0, f"Search command failed: {result['stderr']}"

    # Response should be valid JSON
    assert result["json"] is not None, "Response is not valid JSON"

    # Should be empty list
    assert isinstance(result["json"], list), "Expected response to be a list"
    assert len(result["json"]) == 0, f"Expected empty results, got {len(result['json'])} messages"
