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
| Google Workspace (corporate/org-managed) | ✓ Works | Tested with restrictive org policies |
| Gmail with Advanced Protection Program | ✗ Blocked | Google's own gcloud OAuth client is blocked by APP |
| Regular Gmail | Expected to work | Not yet tested |

### Advanced Protection Program Limitation

Accounts enrolled in Google's [Advanced Protection Program](https://landing.google.com/advancedprotection/) block the gcloud OAuth client (`764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com`) as an untrusted third-party app.

**Workaround:** Users with APP can:
1. Create token before enabling APP (token persists)
2. Temporarily disable APP, authenticate, re-enable
3. Use existing `create-token` flow with their own OAuth client

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
