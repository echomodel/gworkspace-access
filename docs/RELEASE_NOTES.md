# Release Notes

## v0.12.0 — hosted-safe attachment download + Drive move/delete

Resolves [#30](https://github.com/echomodel/gworkspace-access/issues/30)
and [#31](https://github.com/echomodel/gworkspace-access/issues/31).

### Breaking changes

**`download_email_attachment` and `drive_download`** no longer accept
`save_path: str`. The old shape only worked under stdio transport;
under HTTP transport the file landed on the server container and was
unreachable from the agent. Both tools now use a hosted-safe
`destination` parameter:

- `download_email_attachment(message_id, attachment_id, destination,
  account?)` — `destination` is a discriminated union
  (`{kind: "drive", folder_id?, name?}` or
  `{kind: "inline", max_size_bytes?}`). Default is Drive (My Drive
  root) with the attachment's original filename.
- `drive_download(file_id, max_size_bytes?, account?)` — inline-only
  (the file is already in Drive; moving to a different folder is
  `drive_move`). Returns an `EmbeddedResource` + JSON summary
  `TextContent`. Default inline cap is 100,000 bytes.

Oversized inline responses return an error envelope hinting at the
Drive destination rather than risking a tool response that exceeds
client limits.

### New tools

- **`drive_search(query, max_results?, corpora?, account?)`** — the
  general Drive search primitive over ``files.list``. Accepts a Drive
  query string directly (`name contains 'x'`, `mimeType = '...'`,
  `'<folder>' in parents`, `fullText contains '...'`, etc.). Backs
  the convenience tools (`drive_list_folder`, `drive_search_folders`)
  conceptually and lets the agent express any query they don't cover.
- **`drive_get_metadata(file_id, account?)`** — single-file lookup
  over ``files.get``. Returns `size`, `mime_type`, `parents`,
  `modified_time`, `url`, `trashed`. Use before `drive_download` to
  pre-flight size against the inline cap.
- **`drive_move(file_id, destination_folder_id, account?)`** — move a
  Drive file to a different folder. One API call (`addParents` +
  `removeParents`).
- **`drive_delete(file_id, account?)`** — move a Drive file to Trash.
  Trash semantics, not hard-delete: the user can restore from Drive's
  Trash UI for ~30 days.

### SDK additions

`gwsa.sdk.destinations` — reusable `Destination` discriminated union,
`materialize()` helper, and `InlineTooLargeError`. Lifted out of the
mail tool so future byte-producing tools inherit the pattern. The SDK
itself remains transport-agnostic; the MCP layer translates
`InlinePayload` → MCP content blocks via `gwsa.mcp.content`.

`gwsa.sdk.drive` adds `upload_bytes`, `download_bytes`, `move_file`,
`delete_file`. The existing `upload_file` / `download_file` helpers
are unchanged — the CLI continues to use them.

### Migration

Replace any caller using `save_path` with a `destination` parameter:

```python
# Before
download_email_attachment(message_id, attachment_id, save_path="/tmp/x.pdf")

# After — for the inline path
download_email_attachment(
    message_id, attachment_id,
    destination={"kind": "inline"},
)

# After — for the Drive path (recommended; works under any transport)
download_email_attachment(
    message_id, attachment_id,
    destination={"kind": "drive", "folder_id": "<folder-id-or-omit>"},
)
```

The Drive default makes the simplest call site work under HTTP
transport with no agent changes.

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
