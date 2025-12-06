# TODO

## CURRENT PRIORITIES

**Goal:** Complete the authentication and setup overhaul. The majority of the feature work is complete and has been merged to `main`, but unit test coverage is incomplete. The immediate priority is to finish the unit tests for the new, critical logic before considering the feature truly done.

**Completed:**

-   **Unit Testing for Token Setup:** Robust unit tests for the token-based setup flow are complete.
    -   **File:** `tests/unit/test_token_setup.py`
    -   **Tests implemented:**
        -   `test_client_creds_flow_success` - Verifies the happy path where new credentials replace existing ones
        -   `test_client_creds_flow_rollback` - Verifies the atomic rollback: when OAuth fails, original credentials remain untouched
    -   **Mocking approach:** Tests mock only `InstalledAppFlow.run_local_server()` (the browser interaction), allowing `from_client_secrets_file()` to execute normally. This exercises more real library code and validates our test fixtures have correct JSON structure.

**Why We Are Doing This:**

The authentication logic is the most critical and complex part of the application. The new atomic setup and scope validation decorators must be highly reliable. These unit tests are essential to:
1.  Verify the complex logic of the atomic "write-and-rename" pattern for both success and failure cases.
2.  Ensure that a user's existing, working configuration can never be corrupted by a failed setup attempt.
3.  Prevent future regressions in this core part of the application.

---

## Testing (Future Work)

This section captures test cases that should be implemented after the current priorities are complete.

### Scope Validation (`@require_scopes` decorator)

-   **Positive Case:** A test that calls a decorated function when the `config.yaml` contains the required scopes, and asserts that the function executes.
-   **Negative Case:** A test that calls a decorated function when the `config.yaml` is missing the required scopes. It should assert that `SystemExit` is called and that the error message contains the expected "Required: ..." and "Found: ..." strings.
-   **Implicit Grant Case:** A test that calls a function decorated with `@require_scopes('mail-read')` when the config only contains the `mail-modify` scope, and asserts that the function executes successfully.

---

## Future Enhancement: Application Default Credentials (ADC) Support

Consider adding ADC as an alternative to the current OAuth token flow. See [AUTHENTICATION.md](AUTHENTICATION.md) for detailed compatibility testing results.

### Implementation Plan

Support both paths - ADC with fallback to token file:

```python
def load_credentials(token_path=None):
    # Try explicit token file first
    if token_path and os.path.exists(token_path):
        return Credentials.from_authorized_user_file(token_path, SCOPES)

    # Fall back to ADC
    credentials, _ = google.auth.default(scopes=SCOPES)
    return credentials
```

### When to Implement

- When simplifying onboarding for new users
- When majority of users are on Workspace or regular Gmail (not APP)
- Keep `create-token` as fallback for APP users and Gmail with security keys