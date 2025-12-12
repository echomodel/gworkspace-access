# Authentication Guide

This guide covers the authentication flow for `gwsa`, including profiles for multi-identity support, how to test your setup, and advanced utilities.

## Overview

`gwsa` uses a **profile-based** authentication system that allows you to:

- **Switch between Google accounts** instantly without re-authenticating
- **Isolate credentials** from external changes (like `gcloud` commands)
- **Maintain multiple identities** for work, personal, and testing purposes

---

## Understanding Profiles

A **profile** represents a single Google account identity. Each profile has:
- A stored OAuth token (`user_token.json`)
- Cached metadata (email, validated scopes, timestamps)

### Profile Types

**Token Profiles** (e.g., `default`, `work`, `personal`)
- Stored in `~/.config/gworkspace-access/profiles/<name>/`
- Self-contained and isolated from external credential changes
- Persist until explicitly deleted

**Built-in ADC Profile** (`adc`)
- A virtual profile that uses Google's Application Default Credentials
- Not stored—always reads live ADC credentials from `gcloud`
- Affected by `gcloud auth application-default login` and environment variables

### Why Profiles?

**Problem:** Without profiles, running `gcloud auth application-default login` for a different project would silently change which account `gwsa` uses. This is confusing and error-prone.

**Solution:** Token profiles store credentials independently. Once you create a profile, it remains stable regardless of what `gcloud` commands you run or what `GOOGLE_APPLICATION_CREDENTIALS` is set to.

The `adc` profile exists for convenience when you want to use whatever ADC is currently configured, but token profiles are recommended for predictable behavior.

---

## Quick Start

### Option 1: Create a Token Profile (Recommended)

```bash
# Create the default profile using your OAuth client credentials
gwsa setup --client-creds /path/to/client_secrets.json
```

This creates a `default` profile with your Google account's token.

### Option 2: Use ADC Profile

```bash
# First, authenticate with gcloud (with required scopes)
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/userinfo.email

# Then configure gwsa to use ADC
gwsa setup --use-adc
```

This sets the `adc` profile as active.

---

## Managing Profiles

### List All Profiles

```bash
gwsa profiles list
```

Example output:
```
  adc                (built-in)         Uses Application Default Credentials
  default (active)   user@gmail.com     4 scopes   validated 2h ago
  work               user@company.com   4 scopes   validated 1d ago
```

### Create a New Profile

```bash
# Create a profile named "work"
gwsa profiles create work --client-creds /path/to/client_secrets.json
```

This opens a browser for OAuth consent and creates the profile.

### Switch Active Profile

```bash
# Switch to the "work" profile
gwsa profiles use work

# Switch to ADC
gwsa profiles use adc
```

After switching, all `gwsa` commands use the new profile's credentials.

### Show Current Profile

```bash
gwsa profiles current
```

### Delete a Profile

```bash
gwsa profiles delete work
```

---

## Checking Your Configuration

### Quick Status Check

```bash
gwsa setup
```

Shows the active profile's credential status without making API calls.

**Example Output:**
```
Google Workspace Access (gwsa)
------------------------------

Active Profile: default
Configuration Status: CONFIGURED

---
Credential source: Token file: ~/.config/gworkspace-access/profiles/default/user_token.json
Authenticated user: user@gmail.com

Credential Status:
  ✓ Valid
  - Expired: False
  - Refreshable: Yes

Feature Support (based on scopes):
  ✓ Mail
  ✓ Sheets
  ✓ Docs
  ✓ Drive
---

RESULT: READY
```

### Deep Diagnostic Check

```bash
gwsa access check
```

Runs live API calls to verify actual access to each Google service.

---

## Directory Structure

```
~/.config/gworkspace-access/
├── config.yaml              # Root config (active_profile, global settings)
├── client_secrets.json      # OAuth client credentials (shared)
└── profiles/
    ├── default/
    │   ├── user_token.json  # OAuth token
    │   └── profile.yaml     # Metadata (email, scopes, timestamps)
    └── work/
        ├── user_token.json
        └── profile.yaml
```

### Root `config.yaml`

```yaml
active_profile: default      # Currently active profile
```

### Profile `profile.yaml`

```yaml
email: user@gmail.com
validated_scopes:
  - https://www.googleapis.com/auth/gmail.modify
  - https://www.googleapis.com/auth/drive
  - https://www.googleapis.com/auth/documents
  - https://www.googleapis.com/auth/spreadsheets
  - https://www.googleapis.com/auth/userinfo.email
last_validated: 2025-01-15T10:30:00
created: 2025-01-10T08:00:00
```

---

## Migration from Legacy Configuration

If you used `gwsa` before the profile system was introduced, your existing `user_token.json` will be automatically migrated to a `default` profile on first run.

**What happens:**
1. `user_token.json` is moved to `profiles/default/user_token.json`
2. Cached scopes from `config.yaml` are moved to `profiles/default/profile.yaml`
3. `active_profile: default` is set in `config.yaml`

Your credentials continue to work—no re-authentication required.

---

## Scope Aliases

For convenience, `gwsa` supports short aliases for common Google API scopes:

| Alias                 | Full Google API Scope URL                                       |
|-----------------------|-----------------------------------------------------------------|
| `mail-read`           | `https://www.googleapis.com/auth/gmail.readonly`                |
| `mail-modify`, `mail` | `https://www.googleapis.com/auth/gmail.modify`                  |
| `sheets-read`         | `https://www.googleapis.com/auth/spreadsheets.readonly`         |
| `sheets`              | `https://www.googleapis.com/auth/spreadsheets`                  |
| `docs-read`           | `https://www.googleapis.com/auth/documents.readonly`            |
| `docs`                | `https://www.googleapis.com/auth/documents`                     |
| `drive-read`          | `https://www.googleapis.com/auth/drive.readonly`                |
| `drive`               | `https://www.googleapis.com/auth/drive`                         |

---

## Advanced: Standalone Token Creation

The `gwsa access token` command creates OAuth tokens without affecting `gwsa`'s configuration. Useful for other scripts:

```bash
gwsa access token \
  --scope mail-read \
  --scope sheets \
  --client-creds /path/to/client_secrets.json \
  --output /path/to/save/my_token.json
```

---

## Troubleshooting

### "No active profile configured"

Run `gwsa setup` with either `--client-creds` or `--use-adc` to create and activate a profile.

### "Profile not found: <name>"

The specified profile doesn't exist. Use `gwsa profiles list` to see available profiles.

### ADC profile shows unexpected account

The `adc` profile uses whatever ADC is currently configured. Check with:
```bash
gcloud auth application-default print-access-token
```

If you need a stable identity, create a token profile instead.

### "ERROR: Credentials Not Found or Invalid"

- **For token profiles:** The token may be corrupted or revoked. Delete and recreate the profile.
- **For ADC:** Run `gcloud auth application-default login` again.
