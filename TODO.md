# TODO

## Future Enhancement: Application Default Credentials (ADC) Support

### Overview

Consider shifting from custom OAuth token generation (`create-token` command) to Google's Application Default Credentials (ADC) pattern:

```bash
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/gmail.readonly
```

This would simplify setup - users run one gcloud command instead of managing OAuth client credentials and token files.

### Compatibility Testing Results

| Account Type | ADC Login | Notes |
|--------------|-----------|-------|
| Google Workspace (corporate/org-managed) | ✓ Works | Tested with restrictive org policies, 2FA with security keys |
| Gmail with Advanced Protection Program | ✗ Blocked | Google's gcloud OAuth client blocked by APP |
| Gmail with 2FA (security keys) | ✗ Blocked | Even without APP enrolled, gcloud client blocked |
| Regular Gmail (basic or no 2FA) | Unknown | Not yet tested |

### Gmail Blocking Behavior

Google blocks the gcloud OAuth client (`764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com`) for some consumer Gmail accounts, even without Advanced Protection Program enabled.

**Observed pattern:**
- Workspace accounts with 2FA + security keys: Works
- Gmail accounts with 2FA + security keys: Blocked
- Gmail accounts previously enrolled in APP (then unenrolled): Still blocked

This suggests Google applies stricter third-party app policies to consumer Gmail accounts with hardware security keys, separate from the APP enrollment status.

### Token Persistence with APP

**Verified behavior:** Tokens created *before* enabling Advanced Protection Program continue to work after APP is enabled.

| Action | Result |
|--------|--------|
| Create token → Enable APP → Use token | ✓ Works (Docs and Gmail tested) |
| Enable APP → Try to create new token | ✗ Blocked (`error 400: policy_enforced`) |

This applies to both:
- gcloud ADC tokens
- Custom OAuth client tokens (via `create-token` command)

**Workaround for APP users:**
1. Create token *before* enabling APP (token persists indefinitely)
2. Or: Temporarily disable APP → authenticate → re-enable APP
3. Store token securely - it's your long-term access credential

### Implementation Plan

If implemented, support both paths:

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
- Keep `create-token` as fallback for APP users
