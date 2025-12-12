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

## Future Enhancement: Multi-Profile / Multi-Identity Support

### Overview

Support multiple Google account identities that can be quickly switched without re-running OAuth consent flows. This enables workflows like:
- Switching between work and personal accounts
- Testing with different account configurations
- Sharing a machine between multiple users

### Design Goals

1. **Token Isolation:** Profile tokens must be independent of ADC/gcloud state. Running `gcloud auth application-default login` or changing `GOOGLE_APPLICATION_CREDENTIALS` should not affect gwsa profiles.

2. **No Re-Auth on Switch:** Switching profiles should be instant - just update a pointer to the active profile. No browser OAuth flow unless creating a new profile.

3. **Self-Contained Profiles:** Each profile stores everything needed to authenticate and validate: the token, cached scopes, user email, and validation timestamp.

4. **Future CLI Compatibility:** Design should support `--profile <name>` flag on any command to override the default profile for that invocation.

### Proposed Directory Structure

```
~/.config/gworkspace-access/
├── config.yaml              # Root config (active_profile pointer, global settings)
├── client_secrets.json      # OAuth client credentials (shared across profiles)
└── profiles/
    ├── work/
    │   ├── user_token.json  # OAuth token for this identity
    │   └── profile.yaml     # Profile metadata (email, cached scopes, timestamps)
    ├── personal/
    │   ├── user_token.json
    │   └── profile.yaml
    └── testing/
        ├── user_token.json
        └── profile.yaml
```

**Root `config.yaml`:**
```yaml
active_profile: work        # Currently selected profile
# Global settings that apply across all profiles can go here
```

**Profile `profile.yaml`:**
```yaml
email: user@example.com           # Cached from tokeninfo during setup/validation
validated_scopes:                 # Cached scopes from last validation
  - https://www.googleapis.com/auth/gmail.modify
  - https://www.googleapis.com/auth/drive
  - https://www.googleapis.com/auth/documents
  - https://www.googleapis.com/auth/spreadsheets
last_validated: 2025-01-15T10:30:00
created: 2025-01-10T08:00:00
```

### Alternative: Flat File Structure

If folder-per-profile feels heavyweight, an alternative is flat files with naming convention:

```
~/.config/gworkspace-access/
├── config.yaml
├── client_secrets.json
├── profile_work.json         # Combined token + metadata
├── profile_personal.json
└── profile_testing.json
```

**Tradeoffs:**
- Flat: Simpler filesystem, but mixes token and metadata in one file
- Folders: Cleaner separation, easier to backup/copy individual profiles, consistent `user_token.json` naming

**Recommendation:** Folder structure. It's more extensible and keeps the token file format unchanged.

### Proposed CLI Commands

**List profiles:**
```bash
$ gwsa profiles list
  work (active)      user@work.com         4 scopes   validated 2h ago
  personal           user@gmail.com        4 scopes   validated 1d ago
  testing            test@example.com      2 scopes   validated 5d ago
```

**Switch active profile:**
```bash
$ gwsa profiles use personal
Switched to profile: personal (user@gmail.com)

$ gwsa profiles use work
Switched to profile: work (user@work.com)
```

**Create new profile:**
```bash
# Using existing client_secrets.json
$ gwsa profiles create staging
Creating profile 'staging'...
[Browser opens for OAuth consent]
Profile 'staging' created for staging@example.com

# Or with explicit client secrets
$ gwsa profiles create staging --client-creds /path/to/client_secrets.json
```

**Show current profile:**
```bash
$ gwsa profiles current
work (user@work.com)
```

**Delete a profile:**
```bash
$ gwsa profiles delete testing
Delete profile 'testing' (test@example.com)? [y/N]: y
Profile 'testing' deleted.
```

**Per-command override (future):**
```bash
$ gwsa mail search --profile personal "subject:invoice"
# Uses 'personal' profile for this command only, doesn't change active profile
```

### Migration Path

For users with existing single-token setup:

1. On first run after upgrade, if `profiles/` doesn't exist but `user_token.json` does:
   - Create `profiles/default/`
   - Move `user_token.json` to `profiles/default/user_token.json`
   - Create `profiles/default/profile.yaml` from existing `auth.*` values in config.yaml
   - Set `active_profile: default` in root config.yaml
   - Remove old `auth.mode`, `auth.validated_scopes` etc. from root config

2. `gwsa setup` without profile flags operates on the active profile (backward compatible)

### Implementation Notes

- **Profile ID validation:** Alphanumeric + hyphen/underscore, no spaces, reasonable length limit
- **get_active_credentials():** Updated to load from `profiles/<active_profile>/user_token.json`
- **Scope caching:** Moves from root `config.yaml` to per-profile `profile.yaml`
- **Status display:** Always show which profile is active and the associated email
- **ADC consideration:** Profiles are always token-based. ADC mode could be a special "profile" or handled separately. Need to decide if `--use-adc` creates a pseudo-profile or remains a separate mode.

### Open Questions

1. **ADC as a profile?** Should ADC mode be represented as a special profile (e.g., `_adc`) or remain a separate `auth.mode` concept?

2. **Profile-specific client secrets?** Should each profile be able to use different OAuth client credentials, or always share the root `client_secrets.json`?

3. **MCP server integration:** When we add the MCP server, should it respect `active_profile` from config, require explicit profile in request, or have its own config?

