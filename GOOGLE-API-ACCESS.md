# Google API Access Guide

Reference for the GCP project setup behind `gwsa` — which Google APIs
to enable, which scopes you'll need, and how billing flows for OAuth
clients vs. gcloud-issued tokens.

For step-by-step account setup, see the
[README quick start](README.md#quick-start-one-google-account). For
account management commands (`gwsa-admin accounts ...`), see the
[README's `gwsa-admin` command surface](README.md#gwsa-admin-command-surface).

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

### 1. User-Owned OAuth Client (default, recommended)

Token issued by an OAuth client the user created in the Cloud
Console. Tokens are stored in the mcp-app user store; refresh is
automatic via the stored refresh_token.

-   **Pivotal Project for API Enablement:** The **OAuth client project** (where `client_secrets.json` was created).

-   **Setup:**
    1.  Cloud Console → APIs & Services → Credentials → Create credentials → OAuth client ID → Desktop app.
    2.  Download the JSON.
    3.  Acquire and register:
        ```bash
        gwsa-admin acquire-token --client-secrets /path/to/client_secrets.json |
          gwsa-admin accounts add personal --email me@example.com --token=-
        ```

### 2. Gcloud's Well-Known Client

A token issued by `gcloud auth application-default login` (no
`--client-id-file` flag). Uses Google's built-in OAuth client.

-   **Pivotal Project for API Enablement:** The **ADC quota project**.

-   **Setup:**
    ```bash
    gcloud auth application-default login
    gcloud auth application-default set-quota-project YOUR_QUOTA_PROJECT
    gwsa-admin accounts add gcloud-account \
      --email me@example.com \
      --token=@~/.config/gcloud/application_default_credentials.json
    ```

    `--quota-project` is required if you skipped
    `set-quota-project`. gcloud's well-known client has no host
    project of its own, so the API call needs a billing project
    explicitly.

    > [!IMPORTANT]
    > **Synchronizing Scope Updates:** `gwsa` stores a static copy of the token at the time of `accounts add`. If you re-authenticate `gcloud` with new scopes (e.g. adding Chat scopes via `gcloud auth application-default login --scopes=...`), the updated scopes will **not** take effect in `gwsa` until you remove the old account (`gwsa-admin accounts remove <name>`) and re-add it.


### 3. User-Owned OAuth Client via Gcloud (BYOC-ADC)

`gcloud auth application-default login --client-id-file=PATH` — uses
your own OAuth client but writes through gcloud's ADC path.

-   **Pivotal Project for API Enablement:** The **ADC quota project**. (Note: counter-intuitive; the OAuth client project is *not* used for API checks in this flow.)

-   **Setup:**
    ```bash
    gcloud auth application-default login \
      --client-id-file=/path/to/client_secrets.json
    gcloud auth application-default set-quota-project YOUR_QUOTA_PROJECT
    gwsa-admin accounts add my-account \
      --email me@example.com \
      --token=@~/.config/gcloud/application_default_credentials.json
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

### "This app is blocked" (gcloud's well-known client only)

Workspace org policy is rejecting gcloud's well-known OAuth client
for sensitive scopes. Use a user-owned OAuth client instead — either
flow 1 (own client, own management) or flow 3 (own client via gcloud
ADC). See [Workspace org constraints in README](README.md#workspace-org-constraints).

### "No user registered" / "no accounts" errors

The gwsa account store is empty. Walk through the
[README quick start](README.md#quick-start-one-google-account) or
run `gwsa-admin migrate` if you have a legacy vault.

### Credentials expired (refresh_token died)

Re-acquire the token (`gwsa-admin acquire-token ...` or re-run
`gcloud auth application-default login` for gcloud-issued tokens),
remove the stale account
(`gwsa-admin accounts remove <name>`), and add the fresh one
(`gwsa-admin accounts add <name> ...`).

### "Request had insufficient authentication scopes" after gcloud login

If you re-authenticated `gcloud` with new scopes, the updated token will not propagate to `gwsa` automatically. You must replace the stored account:
1. Remove the old cached account: `gwsa-admin accounts remove <name>`
2. Add the updated token back: `gwsa-admin accounts add <name> --email <email> --token=@~/.config/gcloud/application_default_credentials.json --quota-project <project>`

---

## References

- [Quota project overview](https://cloud.google.com/docs/quotas/quota-project)
- [Troubleshoot ADC setup](https://cloud.google.com/docs/authentication/troubleshoot-adc)
- [API Testing Methodology](API-TESTING.md) — test methodology for API enablement requirements.
