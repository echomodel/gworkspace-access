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

| If you use...                                  | Enable APIs in...         |
|------------------------------------------------|---------------------------|
| **`gwsa` Profile (User-Provided OAuth Client)**  | The **OAuth client project** |
| **ADC with Google's Built-in OAuth Client**    | Your **quota project**      |
| **ADC with a User-Provided OAuth Client**      | Your **quota project**      |

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

There are three primary authentication flows, distinguished by the origin of the OAuth 2.0 Client ID.

### 1. `gwsa` Profiles (User-Provided OAuth Client)

This method uses a user-provided OAuth client (`client_secrets.json`) but manages the token flow independently of `gcloud`'s ADC file. It is the most flexible and recommended method.

-   **Pivotal Project for API Enablement:** The **OAuth client project** (where `client_secrets.json` was created).

-   **Setup:**
    1.  Go to [Google Cloud Console](https://console.developers.google.com/) → APIs & Services → Credentials
    2.  Click "Create Credentials" → "OAuth client ID"
    3.  Select **"Desktop app"**
    4.  Download the JSON file
    5.  Import into `gwsa`:
        ```bash
        gwsa client import /path/to/client_secrets.json
        gwsa profiles add default
        gwsa profiles use default
        ```

### 2. ADC with Google's Built-in OAuth Client

This method is initiated by running `gcloud auth application-default login` **without** the `--client-id-file` flag. It uses Google's own internal OAuth client.

-   **Pivotal Project for API Enablement:** The **ADC quota project**.

-   **Setup:**
    ```bash
    gcloud auth application-default login --scopes=...
    gcloud auth application-default set-quota-project YOUR_QUOTA_PROJECT
    gwsa profiles refresh adc
    gwsa profiles use adc
    ```

### 3. ADC with a User-Provided OAuth Client

This method is initiated by running `gcloud auth application-default login` **with** the `--client-id-file` flag. It uses your own OAuth client but stores the credentials in the `gcloud` ADC file.

-   **Pivotal Project for API Enablement:** The **ADC quota project**. (Note: This is counter-intuitive; the OAuth client project is *not* used for API checks in this flow.)

-   **Setup:**
    ```bash
    gcloud auth application-default login \
      --client-id-file=/path/to/client_secrets.json \
      --scopes=...
    gcloud auth application-default set-quota-project YOUR_QUOTA_PROJECT
    gwsa profiles refresh adc
    gwsa profiles use adc
    ```

### Quota Project (for ADC flows)

When using any ADC-based flow (`gcloud auth application-default login`), Google needs a **quota project** to associate with your API usage for billing and quota enforcement.

-   **When is it required?** It's required for both ADC with Google's client and ADC with a user-provided client, especially for corporate/Workspace accounts.
-   **How to set it:** Use `gcloud auth application-default set-quota-project YOUR_PROJECT_ID`.

> **Important: `gcloud config set project` vs. `gcloud auth application-default set-quota-project`**
> -   `gcloud config set project <PROJECT_ID>` changes only the default project for the **`gcloud` CLI**. It performs a permissive check for general project visibility (e.g., `resourcemanager.projects.get`). It allows the operation even if the user has limited permissions, issuing only a warning.
> -   `gcloud auth application-default set-quota-project <PROJECT_ID>` directly configures **ADC**. It performs a strict, mandatory check for the `serviceusage.services.use` permission. This command will **fail** if the authenticated ADC user lacks this specific permission, as it has direct billing and quota implications.

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
