# Authentication Guide

This guide covers authentication options for Google Workspace APIs, including compatibility with different account types and security configurations.

## Authentication Methods

### 1. OAuth User Token (Recommended)

Create a token using your own OAuth client credentials:

```bash
gwsa access token \
  --scope https://www.googleapis.com/auth/gmail.readonly \
  --client-creds ~/.config/gworkspace-access/client_secrets.json \
  --output user_token.json
```

**Pros:**
- Works with most account types
- Token persists indefinitely (auto-refreshes)
- You control the OAuth client

**Cons:**
- Requires setting up OAuth client in Google Cloud Console
- Initial setup more complex than ADC

### 2. Application Default Credentials (ADC)

Use Google's gcloud CLI to authenticate:

```bash
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/gmail.readonly
```

**Pros:**
- Simple one-command setup
- No need to manage OAuth client credentials
- Standard Google pattern

**Cons:**
- Uses Google's OAuth client ID (not under your control)
- Blocked by some account security configurations (see below)

### 3. Service Account

For server-to-server authentication without user interaction:

```python
from google.oauth2 import service_account

credentials = service_account.Credentials.from_service_account_file(
    'service-account.json',
    scopes=['https://www.googleapis.com/auth/gmail.readonly']
)
```

**Pros:**
- No user interaction required
- Ideal for CI/CD and automated jobs

**Cons:**
- Cannot access regular Gmail accounts (only Workspace with domain-wide delegation)
- Requires Workspace admin to configure delegation

---

## Account Type Compatibility

### Google Workspace (Corporate/Org-Managed)

| Method | Compatibility | Notes |
|--------|---------------|-------|
| OAuth User Token | ✓ Works | May require admin approval for OAuth client |
| ADC (gcloud) | ✓ Works | Even with restrictive org policies |
| Service Account | ✓ Works | Requires domain-wide delegation setup |

Workspace admins can restrict which OAuth clients are allowed. If your OAuth client is blocked, ask your admin to allowlist it.

### Regular Gmail (@gmail.com)

| Method | Compatibility | Notes |
|--------|---------------|-------|
| OAuth User Token | ✓ Works | Standard flow |
| ADC (gcloud) | ✓ Usually works | May be blocked with security keys (see below) |
| Service Account | ✗ Not supported | No mechanism to grant access |

### Gmail with Advanced Protection Program (APP)

| Method | Compatibility | Notes |
|--------|---------------|-------|
| OAuth User Token | ⚠ Pre-existing only | Tokens created before APP still work |
| ADC (gcloud) | ✗ Blocked | `error 400: policy_enforced` |
| Service Account | ✗ Not supported | N/A for consumer accounts |

### Gmail with 2FA + Hardware Security Keys

| Method | Compatibility | Notes |
|--------|---------------|-------|
| OAuth User Token | ✓ Works | Custom OAuth client not blocked |
| ADC (gcloud) | ✗ Often blocked | Google's gcloud client treated as untrusted |
| Service Account | ✗ Not supported | N/A for consumer accounts |

---

## Advanced Protection Program (APP)

Google's [Advanced Protection Program](https://landing.google.com/advancedprotection/) provides the strongest account security but restricts third-party app access.

### Key Behaviors

1. **New OAuth flows blocked** - Cannot authorize new apps after APP is enabled
2. **Pre-existing tokens persist** - Tokens created before enabling APP continue to work
3. **Google's own clients affected** - Even gcloud CLI is blocked

### Verified Test Results

| Scenario | Result |
|----------|--------|
| Create token → Enable APP → Use token | ✓ Works |
| Enable APP → Create new token | ✗ Blocked |
| Enable APP → Use gcloud ADC | ✗ Blocked |

### Workarounds for APP Users

1. **Create tokens before enabling APP**
   - Plan ahead: create and store tokens before enrollment
   - Tokens persist indefinitely with auto-refresh

2. **Temporarily disable APP**
   - Unenroll from APP → Create token → Re-enroll
   - Note: Some blocking behavior may persist after unenrollment

3. **Use a separate account**
   - Use non-APP account for development/automation
   - Keep APP on your primary account

### Token Storage for APP Users

Since you can't easily regenerate tokens with APP enabled, treat your token file as a critical credential:

- Store securely (encrypted, limited access)
- Back up to secure location
- Consider storing in a secrets manager for cloud deployments

---

## Gmail with Hardware Security Keys

Even without APP enrollment, Gmail accounts with hardware security keys (FIDO2/WebAuthn) may block some OAuth clients.

### Observed Behavior

- **Custom OAuth clients**: Usually work
- **Google's gcloud OAuth client**: Often blocked with "This app is blocked" error

### Why This Happens

Google applies stricter third-party app policies to accounts with hardware security keys, treating them as high-security accounts even without formal APP enrollment.

### Recommendation

For Gmail accounts with security keys, use the **OAuth User Token** method with your own OAuth client rather than ADC.

---

## Choosing the Right Method

| Your Situation | Recommended Method |
|----------------|-------------------|
| Workspace account, simple setup | ADC (gcloud) |
| Workspace account, need control | OAuth User Token |
| Regular Gmail | Either works |
| Gmail + security keys | OAuth User Token |
| Gmail + APP | OAuth User Token (create before APP) |
| CI/CD with Workspace | Service Account |
| CI/CD with Gmail | OAuth User Token (store in secrets) |

---

## Testing Your Credentials

Use `gwsa access check` to verify your credentials work:

```bash
# Auto-detect credentials (checks token files, then falls back to ADC)
gwsa access check

# Test a specific token file
gwsa access check --token-file ./my_token.json

# Test Application Default Credentials
gwsa access check --application-default

# Test only specific APIs
gwsa access check --only gmail,docs
```

The command will:
1. Report which credential source it's using
2. Show token validity and expiration status
3. Test credential refresh
4. Test API access (Gmail, Docs, Sheets, Drive by default)

Example output:
```
Credential source: Token file: /home/user/.config/gworkspace-access/user_token.json
--------------------------------------------------
Valid: False
Expired: True
Has refresh token: True
Scopes: https://www.googleapis.com/auth/gmail.modify
--------------------------------------------------
Testing credential refresh...
✓ Refresh successful
--------------------------------------------------
API Access:

  ✓ gmail      OK (47 labels)
  ✗ docs       FAILED
  ✗ sheets     FAILED
  ✗ drive      FAILED

--------------------------------------------------
✗ Some checks failed
```

---

## Troubleshooting

### "This app is blocked"

**Cause:** Account security settings blocking the OAuth client.

**Solutions:**
- Use OAuth User Token method instead of ADC
- Check if APP is enabled
- For Workspace: ask admin to allowlist the client

### "error 400: policy_enforced"

**Cause:** Advanced Protection Program blocking new OAuth flows.

**Solutions:**
- Use a pre-existing token (created before APP)
- Temporarily disable APP to create token
- Use a different account

### "Access blocked: Authorization Error"

**Cause:** OAuth client not authorized for the requested scopes, or scopes not enabled in Cloud Console.

**Solutions:**
- Enable the required API in Google Cloud Console
- Add the scope to your OAuth consent screen
- For Workspace: ensure admin has approved the scopes

### Token refresh fails

**Cause:** Refresh token revoked or expired.

**Solutions:**
- Re-run the OAuth flow to get a new token
- Check if you revoked access at https://myaccount.google.com/connections
- For APP users: may need to temporarily disable APP
