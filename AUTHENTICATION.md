# Authentication Guide

This guide covers how to set up OAuth credentials and Application Default Credentials (ADC) for `gwsa`.

For profile management (creating, switching, deleting profiles), see **[PROFILES.md](PROFILES.md)**.

## Overview

`gwsa` uses a **profile-based** authentication system. You need:

1. **OAuth Client Credentials** (`client_secrets.json`) - For token profiles
2. **OR Google Cloud SDK** - For ADC profile

---

## Quick Start

### Option 1: Token Profile (Recommended)

```bash
# Import client credentials (one-time)
gwsa client import /path/to/client_secrets.json

# Create a profile
gwsa profiles add default
gwsa profiles use default
```

### Option 2: ADC Profile

```bash
# Authenticate with gcloud (with required scopes)
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/userinfo.email

# Activate ADC profile
gwsa profiles refresh adc
gwsa profiles use adc
```

---

## Corporate & Google Workspace Accounts
When using Application Default Credentials (ADC) with a corporate or Google Workspace account, Google requires you to specify a **Quota Project**. This project is used for billing and API usage tracking. Without it, API calls will fail.

You must perform two additional steps:

**1. Set the Quota Project:**
Identify a Google Cloud Project where your user has the `Service Usage Consumer` role (or `Owner`) and set it as the quota project.

```bash
# Replace 'your-quota-project-id' with a project you own or have access to
gcloud auth application-default set-quota-project 'your-quota-project-id'
```

**2. Enable APIs in the Quota Project:**
The quota project must have the necessary Google Workspace APIs enabled. The tests or commands will fail if the corresponding API is not enabled.

```bash
# Example for enabling the Gmail API
gcloud services enable gmail.googleapis.com --project='your-quota-project-id'

# You may also need to enable other APIs depending on your usage
gcloud services enable drive.googleapis.com --project='your-quota-project-id'
gcloud services enable sheets.googleapis.com --project='your-quota-project-id'
gcloud services enable docs.googleapis.com --project='your-quota-project-id'
```

---

## Checking Your Setup

```bash
gwsa status
```

Shows the active profile and validation status. Use `--check` for deep validation with live API calls.

For profile management commands, see **[PROFILES.md](PROFILES.md)**.

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

## Troubleshooting

### "No active profile configured"

Create and activate a profile:
```bash
gwsa client import /path/to/client_secrets.json  # If not already done
gwsa profiles add default
gwsa profiles use default
```

### ADC profile shows unexpected account

The `adc` profile uses whatever ADC is currently configured. Check with:
```bash
gcloud auth application-default print-access-token
```

If you need a stable identity, create a token profile instead.

### Credentials invalid or expired

Re-authenticate the profile:
```bash
gwsa profiles refresh <name>    # For token profiles
gwsa profiles refresh adc       # For ADC
```

For more error scenarios and recovery steps, see **[PROFILES.md](PROFILES.md)**.
