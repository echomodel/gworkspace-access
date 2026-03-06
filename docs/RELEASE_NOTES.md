# Release Notes

## v2.0 - Unified Identity Vault (Upcoming Release)

The upcoming v2.0 release marks a major architectural shift for `gwsa` (Google Workspace Access) from a simple CLI tool into the **Unified Identity Vault**. This shift allows for the secure, isolated management of multiple Google Cloud identities and scopes without polluting or overwriting global system state by default.

### Key Architectural Changes

Prior to v2.0, `gwsa` relied on the global Application Default Credentials file (`~/.config/gcloud/application_default_credentials.json`). Activating the "adc" profile would overwrite this global file, causing conflicts with other tools (like Terraform) that also rely on the global ADC state.

In v2.0, **all profiles are isolated**. When you create an active ADC profile in `gwsa`, it is generated and stored exclusively within the `~/.config/gworkspace-access/profiles/<name>` directory. 

External tools no longer rely on `gwsa` overwriting the global ADC file. Instead, they consume isolated credentials declaratively using standard Google Cloud environment variables via the new `gwsa profiles path` command.

### CLI Interface Changes

The CLI structure has been updated to explicitly support arbitrary ADC profiles, replacing the legacy built-in singleton `adc` profile.

| Command | v1.x (Legacy) | v2.x (Unified Vault) | Change Description |
| :--- | :--- | :--- | :--- |
| **Add Profile** | `gwsa profiles add <name>` | `gwsa profiles add <name> [--type=oauth|adc] [--quota-project=PROJECT_ID]` | Added the `--type` flag. You can now generate as many distinct ADC profiles as you need directly into the vault, passing the required `--quota-project`. |
| **Refresh Profile** | `gwsa profiles refresh adc` | `gwsa profiles refresh <name>` | The magical built-in `adc` name is gone. You now refresh specific ADC profiles by their user-defined names. |
| **Export Profile** | `gwsa profiles export adc` | `gwsa profiles export <name>` | Now exports the contents of the isolated vault token, rather than searching for the global standard file. |
| **Built-in `adc`** | `gwsa profiles use adc` | *Removed* | The hardcoded `adc` profile name is retired. You must explicitly create an ADC profile using `add --type=adc`. |
| **[NEW] Resolve Path**| *N/A* | `gwsa profiles path <name>` | A new command designed purely for Unix command substitution. It prints the absolute path to a profile's isolated token file. |
| **[NEW] Apply Globally**| *N/A* | `gwsa profiles apply <name>` | Sets the selected profile as the system's global ADC (`~/.config/gcloud/...`). This is a fully supported Google approach that provides native compatibility with software that doesn't utilize environment variables. |

### The `gwsa profiles path` Command

The new `gwsa profiles path <name>` command is the linchpin of v2.0's external tool integration.

**How it works:**
It accepts a profile name (or uses the active profile if omitted). It verifies that the profile exists and that its token is currently valid (not expired/stale). 

If valid, it outputs *only* the absolute string path to the token file (e.g., `/Users/<user>/.config/gworkspace-access/profiles/my-adc/user_token.json`) and exits with a `0` code. If invalid, it outputs nothing and exits with a `1`.

**How to use it:**
Because it outputs a raw path string, it is perfectly suited for Unix command substitution (`$()`). You use it to inject a specific profile path into the standard `GOOGLE_APPLICATION_CREDENTIALS` environment variable for external tools.

For Example, to run Terraform using an isolated profile named `dev-identity`:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=$(gwsa profiles path dev-identity)
terraform apply
```

This entirely eliminates the need for `gwsa` to overwrite global files, and ensures tools like Terraform consume credentials smoothly using native Google SDK mechanisms.

### Migration Guide

If you previously used the global built-in `adc` profile in v1.x:

1.  **Re-create your ADC Profile:** You must explicitly create a new profile in v2.x to replace it.
    ```bash
    gwsa profiles add my-adc --type=adc --quota-project=your-project-id
    ```
2.  **Update External Scripts (Isolated natively):** Any shell scripts that relied on `gwsa profiles use adc` should be updated to use declarative variable injection if possible:
    ```bash
    GOOGLE_APPLICATION_CREDENTIALS=$(gwsa profiles path my-adc) terraform apply
    ```
3.  **Use `apply` for System-wide Defaults:** If a tool does not respect `GOOGLE_APPLICATION_CREDENTIALS`, or if you simply prefer managing a single global system identity, use the new `apply` command to set your profile as the global standard before running your tools:
    ```bash
    gwsa profiles apply my-adc
    legacy-tool run
    ```
4.  **MCP Tooling:** The MCP server functionality remains unchanged. AI agents invoking tools (like `gmail.send`) will automatically use the currently active profile (`gwsa profiles use <name>`) just as before, natively reading the isolated vault tokens.
