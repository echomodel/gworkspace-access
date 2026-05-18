# Release Notes

## v0.7.0 — mcp-app framework adoption

`gwsa` is now built on the
[mcp-app](https://github.com/echomodel/mcp-app) framework, which
unifies the CLI / MCP server / admin surfaces around a single
`App(...)` composition root, a typed user profile model, and a
filesystem user store. The same binary serves local stdio (one
human) and (in Phase 2) a hosted HTTP multi-user deployment.

### What changed for users

**Identity model.** Each gwsa user record represents one human; the
human's profile holds a list of Google accounts. The "active
profile" pointer is gone — there's a `default_account` on the
user's profile instead.

**CLI split.**

- `gwsa` is now Google Workspace domain operations only
  (`mail`, `drive`, `docs`, `sheets`, `chat`).
- `gwsa-admin` owns everything else: account setup
  (`accounts add/list/get/remove/use`), OAuth token acquisition
  (`acquire-token`), local/remote routing (`connect`), one-shot
  migration (`migrate`), plus the framework-provided
  `users / tokens / probe / health / register` surface.

**One-step solo install.** On a fresh box,
`gwsa-admin accounts add <name> --email <e> --token=@<f>`
auto-creates the user record using the account's email — no
separate `users add` ceremony.

**Stdin token piping.** `gwsa-admin acquire-token` writes the
token JSON to stdout (progress chatter to stderr), so

```
gwsa-admin acquire-token --client-secrets ~/cs.json |
  gwsa-admin accounts add personal --email me@example.com --token=-
```

works as one shell pipeline. The legacy `gwsa profiles add`
interactive wizard is gone; the new flow is composable instead.

**Gcloud-issued vs. user-owned OAuth.** The system detects which
OAuth client issued a token from its `client_id` and enforces
`--quota-project` only for gcloud-issued tokens (which have no
host project of their own). No `--refresh-method` flag — the
client identity drives all behavior that used to need an explicit
label.

### Storage paths

| Path | Purpose |
|------|---------|
| `~/.local/share/gwsa/users/<email>/auth.json`    | Per-user auth record (mcp-app store). |
| `~/.local/share/gwsa/users/<email>/profile.json` | Per-user profile (accounts list). |
| `~/.config/gwsa/setup.json`                      | `connect local` / `connect <url>` config. |
| `~/.config/gworkspace-access/profiles/<name>/`   | **Legacy** vault. Read-only after migration. |

### Upgrading from a pre-mcp-app install

```bash
gwsa-admin connect local
gwsa-admin migrate --dry-run    # preview
gwsa-admin migrate              # do it
gwsa-admin accounts list        # verify
rm -rf ~/.config/gworkspace-access/profiles    # cleanup when satisfied
```

Each legacy profile becomes one `GoogleAccount` on a single user
record; the active legacy profile becomes `default_account`. The
legacy directory is left in place until you remove it.

### Removed

| Removed | Replacement |
|---------|-------------|
| `gwsa profiles add/use/remove/list/refresh/path/apply/export/rename` | `gwsa-admin accounts add/use/remove/list` + `gwsa-admin acquire-token` |
| `gwsa client import/show`                | Now passed as `--client-secrets` to `gwsa-admin acquire-token`. |
| `gwsa token generate`                    | `gwsa-admin acquire-token` (writes to stdout). |
| `gwsa config ...`                        | Configuration lives in the mcp-app store; not user-facing. |
| `gwsa setup` (interactive wizard)        | Composable shell commands instead. |
| `gwsa status`                            | `gwsa-admin accounts list`; framework-side `gwsa-admin probe` (cloud). |
| MCP tool `switch_profile`                | Identity is established at session start; account selection is a per-call argument (planned). |

### Migration plan and Phase 2

See [Cloud Multi-User Architecture](CLOUD-MULTI-USER.md) for the
locked design, the phased migration plan, and the Phase 2 cloud
HTTP deployment story.
