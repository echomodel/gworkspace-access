# Authentication Guide

This guide covers the authentication flow for `gwsa`, including the different configuration modes, how to test your setup, and advanced utilities.

## How `gwsa` Handles Authentication

`gwsa` can be configured in one of two modes. The chosen mode is stored in the `config.yaml` file (`~/.config/gworkspace-access/config.yaml`) under the `auth.mode` key.

### 1. Token Mode (`auth.mode: token`)

This is the recommended and most robust method. It uses a dedicated `user_token.json` file that is generated specifically for `gwsa` using your own private OAuth Client ID.

- **Pros:** Works with all account types (including personal Gmail with advanced security), gives you full control over the OAuth client, and is self-contained within the `gwsa` configuration directory.
- **Cons:** Requires you to create an OAuth Client ID in the Google Cloud Console first.

### 2. ADC Mode (`auth.mode: adc`)

This method uses Google's Application Default Credentials (ADC). It's a fast way to get started if you already use the `gcloud` CLI.

- **Pros:** Very simple one-command setup if you already have `gcloud` configured.
- **Cons:** May be blocked by certain high-security account configurations (like Advanced Protection). It also relies on a global credential that can be affected by other applications.

---

## Initial Setup (`gwsa setup`)

The `gwsa setup` command is the primary way to configure authentication for the tool.

### Configuring for Token Mode

This is the most common setup flow. You will need a `client_secrets.json` file from your Google Cloud project.

1.  **Run the setup command:**
    ```bash
    gwsa setup --client-creds /path/to/your/client_secrets.json
    ```
2.  **Authorize in Browser:** Your web browser will open, asking you to grant permission for your application.
3.  **Completion:** Upon success, the tool will create a `user_token.json` file, set `auth.mode: token` in `config.yaml`, and cache the validated scopes.

This process is **atomic**. If the browser authentication is cancelled or fails, your previous configuration (if any) will be left untouched.

### Configuring for ADC Mode

If you have already logged in with the `gcloud` CLI, you can configure `gwsa` to use those credentials.

1.  **Log in with `gcloud`:** Make sure you request all the necessary scopes.
    ```bash
    gcloud auth application-default login --scopes=https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/spreadsheets
    ```
2.  **Run the setup command:**
    ```bash
    gwsa setup --use-adc
    ```
3.  **Completion:** The tool will test the ADC credentials and, on success, set `auth.mode: adc` in `config.yaml` and cache the validated scopes.

---

## Checking Your Configuration

`gwsa` provides two commands to check your authentication and authorization status.

### Quick Status Check (`gwsa setup`)

Running `gwsa setup` with no flags provides a quick, offline status check. It reads your `config.yaml` and validates your credentials and cached scopes without making any live API calls.

**Example Output (Configured but with issues):**
```
$ gwsa setup

Google Workspace Access (gwsa)
------------------------------

Configuration Status: CONFIGURED (Mode: adc)

---
Credential source: Application Default Credentials (from config) (project: my-gcp-project)

Credential Status:
  ✗ Invalid
  - Expired: True
  - Refreshable: Yes

Feature Support (based on scopes):
  ✓ Mail
  ✓ Sheets
  ✓ Docs
  ✗ Drive
---

RESULT: NOT READY
```

### Deep Diagnostic Check (`gwsa access check`)

The `gwsa access check` command runs a full diagnostic, including live API calls to each Google service to ensure you have actual access. This is the best way to confirm your permissions are working as expected.

**Example Output (Fully working):**
```
$ gwsa access check

Google Workspace Access (gwsa)
------------------------------

Configuration Status: CONFIGURED (Mode: token)

---
Credential source: Token file: /home/user/.config/gworkspace-access/user_token.json

Credential Status:
  ✓ Valid
  - Expired: False
  - Refreshable: Yes

Feature Support (based on scopes):
  ✓ Mail
  ✓ Sheets
  ✓ Docs
  ✓ Drive

Live API Access (Deep Check):
  ✓ mail       OK (123 labels)
  ✓ sheets     OK
  ✓ docs       OK
  ✓ drive      OK
---

RESULT: READY
```

---

## Advanced: Standalone Token Creation

The `gwsa access token` command is a standalone utility for creating OAuth tokens. **It does not affect `gwsa`'s own configuration.** This is useful for creating tokens for other scripts or applications.

```bash
gwsa access token \
  --scope mail-read \
  --scope sheets \
  --client-creds /path/to/client_secrets.json \
  --output /path/to/save/my_token.json
```

---

## Scope Aliases

For convenience, `gwsa` supports short aliases for common Google API scopes. You can use these aliases with the `gwsa access token` command and in the `validated_scopes` section of your `config.yaml`.

| Alias                 | Full Google API Scope URL                                       |
|-----------------------|-----------------------------------------------------------------|
| `mail-read`           | `https://www.googleapis.com/auth/gmail.readonly`                |
| `mail-modify`         | `https://www.googleapis.com/auth/gmail.modify`                  |
| `mail-labels`         | `https://www.googleapis.com/auth/gmail.labels`                  |
| `mail`                | `https://www.googleapis.com/auth/gmail.modify`                  |
| `sheets-read`         | `https://www.googleapis.com/auth/spreadsheets.readonly`         |
| `sheets`              | `https://www.googleapis.com/auth/spreadsheets`                  |
| `docs-read`           | `https://www.googleapis.com/auth/documents.readonly`            |
| `docs`                | `https://www.googleapis.com/auth/documents`                     |
| `drive-read`          | `https://www.googleapis.com/auth/drive.readonly`                |
| `drive-metadata-read` | `https://www.googleapis.com/auth/drive.metadata.readonly`       |
| `drive`               | `https://www.googleapis.com/auth/drive`                         |

---

## Understanding the Configuration File (`config.yaml`)

The `config.yaml` file stores the authentication mode and caches the scopes that were validated during setup.

- **`auth.mode`**: Can be `token` or `adc`. This tells `gwsa` which credential type to load.
- **`auth.validated_scopes`**: A list of the Google API scopes that were confirmed to be granted to your credentials the last time you ran `gwsa setup`. 
- **`auth.last_scope_check`**: A timestamp of when the scopes were last checked.

This caching allows the tool to fail fast if you try to run a command for a feature you haven't granted scopes for, without having to make a network call every time.

---

## Troubleshooting

### "Configuration Status: NOT CONFIGURED"

This means `config.yaml` has not been created or is empty. Run one of the `gwsa setup` commands to configure the tool.

### "ERROR: Credentials Not Found or Invalid"

This means the tool is configured for a specific mode, but the credentials for that mode are broken.

- **If Mode is `adc`**: Your ADC credentials may be expired or missing. Try running `gcloud auth application-default login` again, then re-run `gwsa setup --use-adc`.
- **If Mode is `token`**: Your `user_token.json` may be missing, corrupted, or its refresh token was revoked. You need to generate a new one by re-running the setup with your `client_secrets.json`:
  ```bash
  gwsa setup --client-creds /path/to/your/client_secrets.json
  ```
This will trigger a new browser-based authentication and create a fresh, valid token.