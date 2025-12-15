# Google API Access Guide

This guide covers setting up access to Google Workspace APIs (Gmail, Docs, Sheets, Drive, Chat) with `gwsa`.

For profile management (creating, switching, deleting profiles), see **[PROFILES.md](PROFILES.md)**.

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

## GCP Project Setup

You need a Google Cloud Platform project with APIs enabled. There are two things to understand:

1. **Which APIs** to enable (depends on which features you use)
2. **Which project** to enable them in (depends on your authentication method)

### Step 1: Which APIs to Enable

| Feature | API |
|---------|-----|
| Gmail | `gmail.googleapis.com` |
| Google Drive | `drive.googleapis.com` |
| Google Docs | `docs.googleapis.com` |
| Google Sheets | `sheets.googleapis.com` |
| Google Chat | `chat.googleapis.com` |

### Step 2: Which Project to Enable Them In

| If you use... | Enable APIs in... |
|---------------|-------------------|
| Token Profile | The OAuth client project |
| ADC with `--client-id-file` | The OAuth client project |
| Pure ADC | Your quota project |

**How to find your project:**

- **OAuth client project**: The GCP project where you created `client_secrets.json` (Google Cloud Console → APIs & Services → Credentials)
- **Quota project**: Run `cat ~/.config/gcloud/application_default_credentials.json | jq -r '.quota_project_id'`

> **Note:** `gcloud config get-value project` returns gcloud's CLI config project, which is *not* related to API enablement.

### Step 3: Enable the APIs

```bash
gcloud services enable gmail.googleapis.com --project=YOUR_PROJECT_ID
gcloud services enable drive.googleapis.com --project=YOUR_PROJECT_ID
gcloud services enable docs.googleapis.com --project=YOUR_PROJECT_ID
gcloud services enable sheets.googleapis.com --project=YOUR_PROJECT_ID
gcloud services enable chat.googleapis.com --project=YOUR_PROJECT_ID
```

---

## Authentication Methods

### Token Profiles (Recommended)

Uses your own OAuth client credentials. Works with all account types.

**Setup:**
1. Go to [Google Cloud Console](https://console.developers.google.com/) → APIs & Services → Credentials
2. Click "Create Credentials" → "OAuth client ID"
3. Select **"Desktop app"**
4. Download the JSON file
5. Import into gwsa:
   ```bash
   gwsa client import /path/to/client_secrets.json
   gwsa profiles add default
   gwsa profiles use default
   ```

### ADC Profiles

Uses gcloud's authentication.

#### Pure ADC

Uses Google's built-in OAuth client.

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/userinfo.email

gwsa profiles refresh adc
gwsa profiles use adc
```

> **Note:** Pure ADC may be blocked for Workspace scopes on some accounts. If you see "This app is blocked", use a Token Profile instead.

#### ADC with Your Own Client

Uses your own OAuth client via the ADC system. APIs must be enabled in the **OAuth client project** (the project where `client_secrets.json` was created), not the quota project.

```bash
gcloud auth application-default login \
  --client-id-file=/path/to/client_secrets.json \
  --scopes=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/userinfo.email
```

### Quota Project (Pure ADC only)

When using **pure ADC** (without `--client-id-file`), Google needs to know which GCP project to use for API access. This is the **quota project**.

> **Note:** If you use ADC with `--client-id-file`, the OAuth client project is used instead - see [Which Project to Enable Them In](#step-2-which-project-to-enable-them-in).

**When do you need a quota project?**
- Corporate/Workspace accounts: Required
- Personal Gmail: Usually not required

**How it gets set:**
- `gcloud auth application-default login` may prompt you to set one
- Or set it manually (see below)
- If not set, API calls may fail with "API not enabled" errors

**Set the quota project:**
```bash
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

**Check current quota project:**
```bash
cat ~/.config/gcloud/application_default_credentials.json | jq -r '.quota_project_id'
```

> **Important:** `gcloud config get-value project` returns gcloud's CLI config project, which is **not** the ADC quota project.

---

## Quotas and Billing

**Good news:** All Google Workspace APIs are free. No charges for API requests.

### Quota Limits

| API | Read | Write |
|-----|------|-------|
| Docs | 300/min per user | 60/min per user |
| Sheets | 300/min per user | 60/min per user |
| Gmail | 250 quota units/sec | Varies |
| Drive | 12,000/min per user | 600/min per user |

If you exceed limits, you get HTTP 429 (not billed). Use exponential backoff and retry.

---

## gwsa Configuration

### Directory Structure

```
~/.config/gworkspace-access/
├── config.yaml              # Active profile setting
├── client_secrets.json      # OAuth client credentials
└── profiles/
    └── <profile-name>/
        ├── user_token.json  # OAuth token
        └── profile.yaml     # Metadata
```

### Checking Your Setup

```bash
gwsa status
```

---

## Scope Aliases

| Alias | Full Scope |
|-------|------------|
| `mail-read` | `https://www.googleapis.com/auth/gmail.readonly` |
| `mail`, `mail-modify` | `https://www.googleapis.com/auth/gmail.modify` |
| `sheets-read` | `https://www.googleapis.com/auth/spreadsheets.readonly` |
| `sheets` | `https://www.googleapis.com/auth/spreadsheets` |
| `docs-read` | `https://www.googleapis.com/auth/documents.readonly` |
| `docs` | `https://www.googleapis.com/auth/documents` |
| `drive-read` | `https://www.googleapis.com/auth/drive.readonly` |
| `drive` | `https://www.googleapis.com/auth/drive` |

---

## Troubleshooting

### "API not enabled" Error

The API needs to be enabled in the correct project:

1. **Identify your project** (see [Which Project to Enable Them In](#step-2-which-project-to-enable-them-in))
2. **Enable the API**: `gcloud services enable <api> --project=<your-project>`

### "This app is blocked" (Pure ADC only)

Google's OAuth client is blocked for Workspace scopes on your account. Use a **Token Profile** or **ADC with your own client** instead.

### "No active profile configured"

```bash
gwsa client import /path/to/client_secrets.json
gwsa profiles add default
gwsa profiles use default
```

### Credentials expired

```bash
gwsa profiles refresh <name>
```

For more, see **[PROFILES.md](PROFILES.md)**.

---

## References

- [Quota project overview](https://cloud.google.com/docs/quotas/quota-project)
- [Troubleshoot ADC setup](https://cloud.google.com/docs/authentication/troubleshoot-adc)
- [API-TESTING.md](API-TESTING.md) - Test methodology for API enablement requirements
