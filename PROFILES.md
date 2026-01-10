# Profile Management

This document describes the profile system used by `gwsa` for managing multiple Google account identities.

## Overview

Profiles allow you to switch between multiple Google accounts without re-running OAuth consent flows. Each profile stores its own credentials and metadata.

```
~/.config/gworkspace-access/
├── config.yaml              # Active profile pointer
├── adc_cache.yaml           # ADC metadata cache
└── profiles/
    ├── default/
    │   ├── user_token.json  # OAuth credentials
    │   └── profile.yaml     # Metadata (email, scopes, validation timestamp)
    └── work/
        ├── user_token.json
        └── profile.yaml
```

## Profile Types

### Token Profiles

Standard OAuth-based profiles created via browser login.

- Created with: `gwsa profiles add <name>`
- Re-authenticated with: `gwsa profiles refresh <name>`
- Requires: `client_secrets.json` (OAuth client credentials)
- Stored in: `~/.config/gworkspace-access/profiles/<name>/`

### ADC Profile

Built-in virtual profile using Google Cloud Application Default Credentials.

- Always listed (built-in, cannot be deleted)
- Re-authenticated with: `gwsa profiles refresh adc`
- Runs: `gcloud auth application-default login`
- Requires: Google Cloud SDK installed
- Credentials stored by gcloud at: `~/.config/gcloud/application_default_credentials.json`
- Metadata cached at: `~/.config/gworkspace-access/adc_cache.yaml`

**Note:** `gwsa profiles add adc` is never valid since ADC always exists.

## Profile States

| State | Description | Can Use? |
|-------|-------------|----------|
| **valid** | Credentials validated, ready to use | Yes |
| **stale** | ADC credentials changed since last validation | No |
| **unvalidated** | Never been validated with tokeninfo | No |
| **missing** | Profile directory doesn't exist | No |
| **error** | Token file corrupted or unreadable | No |

View profile states with `gwsa profiles list`:

```
PROFILE            STATUS         EMAIL                          VALIDATED
------------------------------------------------------------------------------
  adc              unvalidated    -                              never
* home             valid          user@gmail.com                 2h ago
  work             valid          worker@company.com             1d ago
------------------------------------------------------------------------------
Ready to use.
```

## Commands Reference

### `gwsa profiles list`

List all profiles with their status.

- Shows all token profiles plus the built-in ADC profile
- Marks active profile with `*`
- Shows validation status and timestamp
- Provides guidance if no valid/active profile

### `gwsa profiles current`

Show the currently active profile details.

```
Active profile: default
  Type: OAuth Token
  Status: valid
  Email: user@gmail.com
  Scopes: 6
```

### `gwsa profiles add <name>`

Create a new token profile.

- Requires client credentials configured first (`gwsa client import`)
- Profile must NOT already exist
- Opens browser for OAuth consent
- Validates credentials with tokeninfo before saving
- Atomic operation: no partial state on failure

```bash
gwsa profiles add work
gwsa profiles add personal
```

### `gwsa profiles refresh <name>`

Re-authenticate an existing profile.

- Profile MUST already exist (use `add` for new profiles)
- For token profiles: Opens browser for OAuth consent
- For ADC: Runs `gcloud auth application-default login`
- Validates credentials before overwriting
- Atomic operation: existing profile preserved on failure

```bash
gwsa profiles refresh default    # Re-auth token profile
gwsa profiles refresh adc        # Re-auth via gcloud
```

### `gwsa profiles use <name>`

Switch to a different profile.

- Validates credentials with tokeninfo before switching
- Blocks switching to invalid/stale/unvalidated profiles
- Use `--no-recheck` to trust cached status (skip network call)

```bash
gwsa profiles use work
gwsa profiles use adc --no-recheck  # Trust cached status
```

### `gwsa profiles rename <old_name> <new_name>`

Rename a profile.

- Cannot rename the built-in `adc` profile
- Cannot rename TO `adc` (reserved name)
- New name must be valid (alphanumeric, hyphens, underscores)
- Atomic operation with rollback on failure
- If renaming active profile, config is updated automatically

```bash
gwsa profiles rename default personal
gwsa profiles rename work work-old
```

### `gwsa profiles delete <name>`

Delete a profile.

- Cannot delete the built-in `adc` profile
- Prompts for confirmation (use `-y` to skip)
- If deleting active profile, no profile becomes active

```bash
gwsa profiles delete old-profile
gwsa profiles delete temp -y  # Skip confirmation
```

### `gwsa status`

Show current configuration and profile status.

```
==================================================
gwsa Status
==================================================

Active Profile: default
  Type: OAuth Token
  Status: valid
  Email: user@gmail.com
  Scopes: 6

==================================================
Ready to use.
```

Use `--check` for deep validation with live API calls.

## Validation Behavior

### On `profiles use`

By default, `profiles use` calls Google's tokeninfo API to verify credentials:

1. Check profile exists
2. Check profile is valid (not stale/unvalidated)
3. Call tokeninfo API to verify credentials work
4. Update cached metadata with fresh email/scopes
5. Switch active profile

With `--no-recheck`:
- Steps 1-2 still run (cached status must be valid)
- Steps 3-4 skipped (no network call)
- Useful for offline scenarios or scripting

### On `profiles add` / `profiles refresh`

Both commands validate BEFORE writing:

1. Run OAuth flow (browser login)
2. Call tokeninfo to validate credentials
3. Only if validation succeeds: write token file and metadata
4. On failure: no changes made, existing profile preserved

## Error Scenarios and Recovery

### No Active Profile

**Symptom:** "No active profile configured" on product commands

**Causes:**
- Fresh install, no profile selected yet
- Active profile was deleted
- Config points to non-existent profile (deleted from disk)

**Recovery:**
```bash
gwsa profiles list              # See available profiles
gwsa profiles use <name>        # Activate a valid profile
# OR
gwsa profiles add <name>        # Create new profile
gwsa profiles refresh adc       # Or use ADC via gcloud
```

### Invalid/Stale Profile

**Symptom:** "Active profile is not valid" error

**Causes:**
- Token expired and refresh failed
- ADC credentials changed since validation
- Token file corrupted

**Recovery:**
```bash
gwsa profiles refresh <name>    # Re-authenticate
# OR
gwsa profiles use <other>       # Switch to different valid profile
```

### Profile Not Found

**Symptom:** "Profile not found" on `profiles use` or `profiles refresh`

**Cause:** Profile directory doesn't exist

**Recovery:**
```bash
gwsa profiles add <name>        # Create the profile
```

### Corrupted Token File

**Symptom:** Profile shows "ERROR" status in `profiles list`

**Recovery:**
```bash
gwsa profiles refresh <name>    # Overwrites corrupted file
# OR
gwsa profiles delete <name>     # Remove and recreate
gwsa profiles add <name>
```

### Corrupted Config Directory

**Last Resort Recovery:**
```bash
rm -rf ~/.config/gworkspace-access
gwsa profiles add <name>        # Start fresh
```

## Edge Cases

### Active Profile Deleted from Disk

If a profile folder is manually deleted while it's active:
- `get_active_profile()` returns `None`
- Treated as "no active profile"
- All commands show appropriate guidance
- User must `profiles use` another profile or `profiles add` a new one

### Same Email Under Multiple Profiles

Currently allowed. Each profile maintains separate credentials.
Use case: Different OAuth scopes (not yet supported) or testing.

**Note:** This may cause confusion. Future versions may warn or block duplicates.

### Switching Profiles While Offline

Use `--no-recheck` to switch without network validation:
```bash
gwsa profiles use work --no-recheck
```

The profile must already show as "valid" in `profiles list`.

## Product Command Behavior

All product commands (mail, docs, sheets) check profile validity before executing:

1. Get active profile
2. If none: fail with "No active profile configured"
3. Check profile status (valid/stale/unvalidated)
4. If invalid: fail with status and recovery guidance
5. Check required scopes
6. If missing scopes: fail with guidance to refresh

This ensures fast failure with clear error messages rather than cryptic API errors.

## MCP Server Behavior

The MCP server (`gwsa-mcp`) uses the same profile system:

- Tools that access Google APIs require a valid active profile
- `list_profiles` and `get_active_profile` work without active profile
- `switch_profile` validates before switching
- Errors include hints about profile configuration

## Related Documentation

- [README.md](./README.md) - Getting started and CLI usage
- [MCP-SERVER.md](./MCP-SERVER.md) - MCP server setup
- [GOOGLE-API-ACCESS.md](./GOOGLE-API-ACCESS.md) - OAuth setup and GCP project configuration
