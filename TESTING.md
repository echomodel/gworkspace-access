# Integration Testing Guide

This document outlines the comprehensive integration testing strategy for the Google Workspace Access CLI (`gwsa`).

## Overview

The integration tests validate the end-to-end functionality of the `gwsa` CLI tool by executing real operations against the Gmail API. These tests are designed to:

- Verify all CLI commands work correctly (search, read, label)
- Confirm JSON output parsing and correctness
- Validate Gmail API interactions
- Ensure proper error handling
- Test the complete user workflow

## Test Dependencies

### Development Dependency: pytest

`pytest` is introduced as a **development-only dependency** and should be added to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
]
```

Install with: `pip install -e ".[dev]"`

## Test Directory Structure

```
/gworkspace-access/
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    # Pytest configuration and fixtures
│   └── integration/
│       ├── __init__.py
│       ├── test_mail_search.py        # Search functionality tests
│       ├── test_mail_modify.py        # Label and archive tests
│       └── test_mail_read.py          # Message reading tests
```

## Test Configuration

### Profile-Based Test Settings: test-config.yaml

The `tests/test-config.yaml` file maps gwsa profile names to test-specific settings. This allows different email accounts to use different search queries for finding test emails.

**File Location**: `tests/test-config.yaml`

**Structure**:
```yaml
profiles:
  # Profile name must match a gwsa profile name
  default:
    search_query: 'subject:"Your Daily Digest" from:"USPS Informed Delivery"'
    test_label: "Test"
    min_results: 2
    days_range: 60

  adc:
    search_query: 'subject:"Daily Newsletter"'
    test_label: "Test"
    min_results: 3
    days_range: 7
```

**Settings**:
- `search_query`: Gmail search query for finding routine, low-risk test emails
- `test_label`: Label name used for add/remove tests (default: "Test")
- `min_results`: Minimum emails expected from search (default: 2)
- `days_range`: Number of days back to search (default: 60)

**How It Works**:
1. `conftest.py` reads the active gwsa profile via `gwsa profiles list`
2. Looks up test settings for that profile in `test-config.yaml`
3. If found, integration tests run with those settings
4. If not found, tests requiring specific emails are skipped with helpful instructions

**Adding a New Profile**:
Add a section under `profiles:` with your gwsa profile name as the key:
```yaml
profiles:
  my_profile:
    search_query: 'from:newsletters@example.com'
    test_label: "Test"
    min_results: 2
    days_range: 30
```

### conftest.py

The `tests/conftest.py` file serves as the pytest configuration and setup/teardown for all integration tests.

### Responsibilities:

1. **Profile Status Validation**
   - Checks that gwsa has a valid, configured profile
   - Verifies credentials are valid and not expired
   - Exits with clear error message if profile not ready

2. **Test Config Loading**
   - Loads `tests/test-config.yaml`
   - Looks up settings for the active gwsa profile
   - Skips tests gracefully if profile not in config

3. **CLI Installation Verification**
   - Validates that `gwsa` is installed and available
   - Executes `python -m gwsa.cli --help` to verify the current codebase is being tested
   - Exits with code 1 if the tool is not properly installed

4. **Session-Level Fixtures**
   - `cli_runner`: Fixture that invokes CLI commands via subprocess
   - `search_query`: Search query from test config for active profile
   - `test_label`: Label name from test config
   - `test_email_id`: Message ID of a test email (found via search_query)
   - `today_minus_n_days`: Date string based on profile's days_range

### Implementation Notes:

- The conftest uses subprocess to invoke the CLI (via `python -m gwsa.cli`) rather than importing the module directly, ensuring the test environment mimics real user usage
- All CLI commands output JSON, which is parsed using Python's `json` module for assertions
- If `gwsa setup` has not been run, tests will fail with a clear message about missing credentials
- If the active profile is not in test-config.yaml, email-related tests are skipped with instructions

---

## Integration Tests: test_mail_search.py

**Purpose**: Validate email search functionality and confirm test data availability.

### Test Case: `test_mail_search_usps_digests`

**Description**:
Searches for USPS Informed Delivery digest emails from the past 60 days.

**Search Criteria**:
```
subject:"Your Daily Digest" from:"USPS Informed Delivery" after:YYYY-MM-DD
```

Where `YYYY-MM-DD` is calculated as today minus 60 days (from the `today_minus_60_days` fixture).

**Execution**:
```bash
gwsa mail search 'subject:"Your Daily Digest" from:"USPS Informed Delivery" after:2025-09-29'
```

**Expected Behavior**:
1. Command executes successfully (exit code 0)
2. Output is valid JSON
3. Response is a list of message objects

**Assertions**:
1. Result set contains **between 2 and 20 messages** (validates test data availability without being brittle)
2. Each message object contains required fields:
   - `id` (string)
   - `subject` (string, contains "Your Daily Digest")
   - `sender` (string, contains "USPS Informed Delivery")
   - `date` (string)
3. Messages are returned in descending date order (most recent first)

**Test Data Output**:
- Extracts and stores the first message's ID (`test_email_id`) for use by other test modules
- This ID is passed to `test_mail_modify.py` and `test_mail_read.py` via a conftest fixture

**Rationale**:
- Tests against real emails from a common, reliable source (USPS)
- 60-day window ensures sufficient test data across different scenarios
- 2-20 message range is realistic and avoids brittle exact counts
- Confirms search query parsing, API interaction, and JSON serialization all work

---

## Integration Tests: test_mail_modify.py

**Purpose**: Validate label modification and archive operations.

**Setup**:
- Uses `test_email_id` fixture (populated by `test_mail_search.py`) to identify a target USPS email
- Additional search filter: `-label:Test` ensures the email doesn't already have the test label

### Test Case 1: `test_mail_label_apply`

**Description**:
Applies the "Test" label to a USPS email and verifies the change.

**Pre-Conditions**:
1. A USPS email exists matching the search criteria
2. Email does NOT currently have the "Test" label

**Execution Steps**:

1. **Search for target email**:
   ```bash
   gwsa mail search 'subject:"Your Daily Digest" from:"USPS Informed Delivery" after:2025-09-29 -label:Test'
   ```
   - Confirms at least one email exists without the label

2. **Read email details (before)**:
   ```bash
   gwsa mail read {message_id}
   ```
   - Parse JSON response
   - Assert `labelIds` array does NOT contain "Test" label ID

3. **Apply label**:
   ```bash
   gwsa mail label {message_id} Test
   ```
   - Command executes successfully
   - Output is valid JSON

4. **Read email details (after)**:
   ```bash
   gwsa mail read {message_id}
   ```
   - Parse JSON response
   - Assert `labelIds` array now CONTAINS "Test" label ID
   - Verify all other fields unchanged

**Assertions**:
1. Label absent before operation
2. Label present after operation
3. No other message properties changed
4. All JSON fields validated

**Rationale**:
- Validates complete label addition workflow
- Tests both label application and verification
- Ensures API properly updates message state
- Confirms JSON serialization of label data

---

### Test Case 2: `test_mail_label_remove`

**Description**:
Removes the "Test" label from the same email used in `test_mail_label_apply`.

**Dependencies**:
- Must run AFTER `test_mail_label_apply` (same message ID)
- Requires the label to exist on the message (result of previous test)

**Execution Steps**:

1. **Search for target email**:
   ```bash
   gwsa mail search 'subject:"Your Daily Digest" from:"USPS Informed Delivery" after:2025-09-29 label:Test'
   ```
   - Confirms email currently has the "Test" label

2. **Read email details (before)**:
   ```bash
   gwsa mail read {message_id}
   ```
   - Parse JSON response
   - Assert `labelIds` array CONTAINS "Test" label ID

3. **Remove label**:
   ```bash
   gwsa mail label {message_id} Test --remove
   ```
   - Command executes successfully
   - Output is valid JSON

4. **Read email details (after)**:
   ```bash
   gwsa mail read {message_id}
   ```
   - Parse JSON response
   - Assert `labelIds` array does NOT contain "Test" label ID

**Assertions**:
1. Label present before operation
2. Label absent after operation
3. No other message properties changed
4. All JSON fields validated

**Test Ordering**:
- pytest is configured to run `test_mail_label_apply` before `test_mail_label_remove`
- Both tests use the same `message_id` from conftest
- Second test reverses the effects of the first (maintaining clean state)

**Rationale**:
- Validates label removal workflow
- Tests the `--remove` flag
- Confirms reversibility of label operations
- Leaves test email in original state (no label)

---

### Test Case 3: `test_mail_archive`

**Description**:
Archives a USPS email by removing it from the inbox.

**Execution Steps**:

1. **Search for unarchived target email**:
   ```bash
   gwsa mail search 'subject:"Your Daily Digest" from:"USPS Informed Delivery" after:2025-09-29 -label:Archive'
   ```
   - Identifies an email not yet archived

2. **Read email details (before)**:
   ```bash
   gwsa mail read {message_id}
   ```
   - Parse JSON response
   - Assert `labelIds` does NOT contain Archive label or INBOX label

3. **Apply Archive label**:
   ```bash
   gwsa mail label {message_id} Archive
   ```
   - (or alternatively, remove INBOX label depending on Gmail label semantics)

4. **Read email details (after)**:
   ```bash
   gwsa mail read {message_id}
   ```
   - Parse JSON response
   - Assert `labelIds` contains Archive label or no longer contains INBOX

**Assertions**:
1. Email not archived before operation
2. Email archived after operation
3. All other fields unchanged

**Rationale**:
- Tests a common user workflow (archiving emails)
- Validates label-based archival mechanism
- Ensures bulk operations can be built on this foundation

---

## Integration Tests: test_mail_read.py

**Purpose**: Validate email reading and JSON response structure.

### Test Case: `test_mail_read_full_details`

**Description**:
Reads a USPS email and validates all expected fields are present in the JSON response.

**Execution**:
```bash
gwsa mail read {message_id}
```

Where `{message_id}` is from the `test_email_id` fixture (same email used in other tests).

**Expected JSON Structure**:
```json
{
  "id": "string",
  "subject": "string (contains 'Your Daily Digest')",
  "sender": "string (contains 'USPS Informed Delivery')",
  "date": "string (RFC 2822 format)",
  "snippet": "string (first ~100 chars of body)",
  "body": "string (full plain text body)",
  "labelIds": ["array", "of", "label", "IDs"],
  "raw": "string (full JSON representation of Gmail API message object)"
}
```

**Assertions**:

1. **All required fields present**:
   - `id` is a non-empty string
   - `subject` is a non-empty string
   - `sender` is a non-empty string
   - `date` is a non-empty string
   - `snippet` is a string (may be empty)
   - `body` is a string (non-empty for USPS digests)
   - `labelIds` is an array (may be empty)
   - `raw` is a non-empty string (valid JSON)

2. **Field values are appropriate**:
   - `subject` contains expected text ("Your Daily Digest")
   - `sender` contains expected source ("USPS Informed Delivery")
   - `date` is parseable as RFC 2822 format
   - `labelIds` is a valid array of Gmail label IDs
   - `raw` can be parsed as JSON

3. **Body content is populated**:
   - USPS Informed Delivery emails should have substantial body text
   - Confirms that plain text extraction works correctly

4. **No extraneous fields**:
   - Response contains exactly the expected fields (no extra undocumented fields)

**Rationale**:
- Validates complete message retrieval
- Tests text extraction from complex MIME structures
- Confirms label ID population
- Ensures JSON serialization of all data types is correct
- Provides contract for downstream tools consuming the JSON output

---

## Running the Tests

### Prerequisites

Before running tests, ensure:

1. **`gwsa setup` has been completed**:
   ```bash
   gwsa setup
   ```
   This ensures `user_token.json` and `credentials.json` are in place.

2. **Test dependencies are installed**:
   ```bash
   pip install -e ".[dev]"
   ```

3. **Python 3.9+ is available**:
   ```bash
   python3 --version
   ```

### Execution

Run all integration tests:
```bash
pytest tests/integration/ -v
```

Run specific test module:
```bash
pytest tests/integration/test_mail_search.py -v
```

Run specific test case:
```bash
pytest tests/integration/test_mail_modify.py::test_mail_label_apply -v
```

Run with debug logging:
```bash
LOG_LEVEL=DEBUG pytest tests/integration/ -v
```

### Expected Output

Successful test run:
```
tests/integration/test_mail_search.py::test_mail_search_usps_digests PASSED
tests/integration/test_mail_modify.py::test_mail_label_apply PASSED
tests/integration/test_mail_modify.py::test_mail_label_remove PASSED
tests/integration/test_mail_modify.py::test_mail_archive PASSED
tests/integration/test_mail_read.py::test_mail_read_full_details PASSED

====== 5 passed in 2.45s ======
```

---

## Test Execution Environment

### CLI Invocation Strategy

All tests invoke the CLI via subprocess using the following pattern:

```python
result = subprocess.run(
    ["python", "-m", "gwsa_cli", "mail", "search", query_string],
    capture_output=True,
    text=True,
    cwd=project_root
)
```

**Rationale**:
- Uses `python -m gwsa_cli` rather than the installed `gwsa` command
- Ensures tests run against the current codebase, not a previously installed version
- Mimics real user execution environment
- Requires `gwsa_cli` to be importable from the current directory

### JSON Parsing

All CLI output is parsed as JSON:

```python
response = json.loads(result.stdout)
```

**Assertions**:
- Output is valid JSON
- Response structure matches expected schema
- Field types are correct

---

## Test Dependencies and Fixtures

### conftest.py Fixtures

#### `today_minus_60_days`
- **Scope**: Session
- **Returns**: String in format `YYYY-MM-DD`
- **Calculation**: `datetime.now() - timedelta(days=60)`

#### `cli_runner`
- **Scope**: Session
- **Returns**: Callable function
- **Function signature**: `cli_runner(command_args: List[str]) -> Dict[str, Any]`
- **Return structure**:
  ```python
  {
      "returncode": int,
      "stdout": str,
      "stderr": str,
      "json": dict or list (if stdout is valid JSON)
  }
  ```

#### `test_email_id`
- **Scope**: Session
- **Returns**: String (Gmail message ID)
- **Population**: Extracted from `test_mail_search_usps_digests()` results
- **Usage**: Shared across `test_mail_modify.py` and `test_mail_read.py`
- **Storage**: Stored in session cache, not persisted to disk

### Test Markers

```python
@pytest.mark.integration
@pytest.mark.order(1)
def test_mail_search_usps_digests():
    """Runs first to populate test_email_id fixture."""
    pass

@pytest.mark.integration
@pytest.mark.order(2)
def test_mail_label_apply():
    """Depends on test_email_id from test_mail_search."""
    pass
```

The `pytest-ordering` plugin (optional) ensures test execution order.

---

## Error Handling and Edge Cases

### Expected Errors

Tests should gracefully handle:

1. **CLI not installed**:
   - Caught by conftest.py session setup
   - Error message: "gwsa CLI not found. Run `pip install -e .` first."
   - Exit code: 1

2. **Credentials not configured**:
   - Occurs when `gwsa setup` hasn't been run
   - CLI exits with error message about missing `user_token.json`
   - Test assertion: `returncode != 0`

3. **No test data available**:
   - `test_mail_search_usps_digests` returns < 2 results
   - Test fails with: "Insufficient test data: expected 2-20 USPS emails, found N"
   - Guidance: User should have USPS emails in their Gmail

4. **Gmail API quota exceeded**:
   - Rare but possible with repeated test runs
   - Tests will fail with API rate limit error
   - Mitigation: Space out test runs or use a dedicated Gmail test account

### Assertions on JSON Structure

All JSON assertions use defensive parsing:

```python
try:
    data = json.loads(output)
except json.JSONDecodeError as e:
    pytest.fail(f"CLI output is not valid JSON: {e}")

assert isinstance(data, list), "Expected response to be a list"
assert len(data) >= 2, f"Expected >= 2 results, got {len(data)}"
```

---

## CI/CD Integration

For future GitHub Actions or other CI systems:

### Workflow Considerations

1. **Test Account Setup**:
   - Use a dedicated Gmail test account
   - Pre-populate with USPS Informed Delivery emails
   - Set `WORKSPACE_ACCESS_PROJECT` via environment variable

2. **Credentials Management**:
   - Store `credentials.json` and `user_token.json` as GitHub secrets
   - Write files during CI job setup
   - Ensure sensitive files are not committed

3. **Test Isolation**:
   - Each test run should start with a clean label state
   - `test_mail_label_remove` ensures labels are cleaned up after `test_mail_label_apply`
   - No permanent modifications to test emails (all changes are reversed)

4. **Timeout Considerations**:
   - Gmail API calls may take 1-3 seconds each
   - Allow 30-60 second timeout for full test suite
   - Configure pytest timeout: `pytest --timeout=60`

### Example CI Workflow (GitHub Actions)

```yaml
name: Integration Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Setup credentials
        run: |
          echo "${{ secrets.CREDENTIALS_JSON }}" > credentials.json
          echo "${{ secrets.USER_TOKEN_JSON }}" > user_token.json
      - name: Run integration tests
        run: pytest tests/integration/ -v --timeout=60
      - name: Cleanup
        run: rm credentials.json user_token.json
        if: always()
```

---

## Future Test Expansion

### Additional Test Cases to Consider

1. **Batch Operations**:
   - Test labeling multiple emails at once
   - Test searching with complex query combinations

2. **Error Scenarios**:
   - Search with invalid query syntax
   - Read non-existent message ID
   - Label with invalid label name

3. **Performance Tests**:
   - Large search result sets (1000+ emails)
   - Memory usage validation
   - API response time tracking

4. **Label Management**:
   - Create custom labels via CLI
   - Verify label case sensitivity
   - Test special characters in label names

5. **Edge Cases**:
   - Emails with no body content
   - Emails with non-UTF8 encoding
   - Extremely long subject lines
   - Multiple labels on single email

---

## Troubleshooting

### Common Issues

#### "gwsa: command not found"
**Solution**: Run `pip install -e .` in the project root directory.

#### "User credentials file 'user_token.json' not found"
**Solution**: Run `gwsa setup` to authenticate and generate credentials.

#### "No messages found matching the criteria"
**Solution**: Ensure you have USPS Informed Delivery emails in your Gmail account. If not, tests will need to be adjusted or skipped.

#### "JSON decode error: Expecting value"
**Solution**: Check that the CLI is installed from the current code (not an old version). Run `python -m gwsa_cli --help` to verify.

#### "404 Not Found: The requested entity was not found"
**Solution**: Message ID may have been deleted or is invalid. Run test_mail_search.py again to get a fresh message ID.

---

## Test Maintenance

### When to Update Tests

- When CLI command syntax changes → Update command strings in tests
- When Gmail API scope requirements change → Update test setup instructions
- When JSON response schema changes → Update assertions
- When label behavior changes → Update label tests

### Keeping Tests Reliable

1. Avoid hard-coded message IDs (use dynamic search)
2. Don't assume specific label names exist (create them if needed)
3. Use flexible assertion ranges (2-20 messages instead of exactly 5)
4. Clean up test modifications (remove labels after apply/remove tests)
5. Use descriptive assertion messages for debugging

---

## Summary

The integration test suite validates the complete `gwsa` CLI workflow using real Gmail data and operations. Tests are organized into three modules:

- **test_mail_search.py**: Validates search functionality and provides test data
- **test_mail_modify.py**: Validates label modification and archive operations
- **test_mail_read.py**: Validates message reading and JSON response structure

All tests use subprocess to invoke the CLI, ensuring real-world usage patterns are tested. Tests parse JSON output and validate response structure comprehensively.

Before running tests, ensure `gwsa setup` has been completed and development dependencies are installed with `pip install -e ".[dev]"`.
