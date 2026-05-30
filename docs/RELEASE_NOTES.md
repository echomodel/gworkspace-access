# Release Notes

## v0.14.1 — transport-safe Drive upload/update + Shared Drive support

**Breaking change to the `drive_upload` and `drive_update` MCP tools.**

Two related fixes so Drive uploads work for agent-on-laptop sessions and
for content in Shared Drives.

### Inline source (transport-safe input)

Previously both tools took a `local_path: str` — a path on the MCP
server's filesystem. That only works under stdio, where the server and
the agent are the same machine. Under HTTP transport the server cannot
read the agent's files, so every upload of a real local file failed with
a "No such file or directory" / 404 error even though the file existed
on the agent's side.

`drive_upload` and `drive_update` now take a `source` discriminated
union (defined in `gwsa.sdk.sources`):

- `{"kind": "inline", "data_base64": "...", "name": "...",
  "mime_type": "..."}` — bytes travel in-band; works under **any**
  transport. Subject to a raw-byte cap (default 700,000) with a
  per-call `max_size_bytes` override.
- `{"kind": "path", "path": "/abs/path"}` — reads from the server's
  filesystem; correct only under stdio.

This mirrors, on the input side, the `destination` convention that
byte-*producing* tools already use (see CONTRIBUTING "Byte-consuming
tools"). Oversize inline payloads and unreadable paths return
structured error envelopes.

Migration: callers passing `local_path="/path"` must switch to
`source={"kind": "path", "path": "/path"}` (stdio) or, preferably,
`source={"kind": "inline", "data_base64": ...}` (any transport).

### Shared Drive support

`upload_file`, `upload_bytes`, `update_file`, and `update_bytes` now pass
`supportsAllDrives=True` on their `files.create` / `files.update` calls,
matching every other Drive operation in the SDK (move, delete, get,
search, folder listing already set it). Without the flag, uploading a
file into — or updating a file that lives in — a Shared Drive (or a
folder shared from another account) failed with `HttpError 404 File not
found: <folder-id>`, indistinguishable from "the folder really doesn't
exist." Ordinary My Drive uploads were unaffected, which masked the gap.

## v0.13.1 — acquire-token requests Calendar by default

`gwsa-admin acquire-token` now includes `calendar` in its default
scope set (`mail,drive,docs,sheets,calendar`). v0.13.0 added the
Calendar tools and the `calendar` scope alias but left the
`acquire-token` default unchanged, so a token minted without an
explicit `--scopes` lacked Calendar access and every Calendar tool
call failed at runtime with a 403 "insufficient authentication
scopes." Re-acquire your token after upgrading to pick up the
Calendar scopes (see README "Rotating tokens").

## v0.13.0 — Google Calendar support (Free/Busy)

New Google Calendar feature across SDK, CLI, and MCP.

### Calendar tools

- `list_calendars`, `list_events`, `create_event`, `update_event`,
  `delete_event` — available as `gwsa calendar ...` CLI commands and
  as MCP tools.

### Free/Busy (availability)

Event availability maps to the Calendar API `transparency` field via an
`availability: free|busy` parameter on create/update. All-day events
default to **Free** (mirroring the Calendar web UI); timed events keep
the API default of **Busy**. The normalized `transparency` and
`availability` are always echoed back in the result so callers can
confirm what was set — the raw API omits `transparency` when it is the
default `opaque`. `update` never changes Free/Busy unless `availability`
is passed.

### OAuth scopes

Adds `calendar.readonly` and `calendar.events`. Existing installs must
re-acquire their token to pick up the new scopes (see README "Rotating
tokens").

## v0.12.1 — attachment metadata fast path + correct inline cap

Live-deployment fixes for two issues found while exercising v0.12.0
against a real Gmail + Drive account.

### Attachment filename/mime preservation

`download_email_attachment` now accepts optional `filename` and
`mime_type` parameters. When both are provided (the caller already
has them from `read_email`), the tool uses them directly and skips
the server-side metadata lookup.

Why: Gmail re-issues attachment IDs across `messages.get` requests.
The lookup that walked the message parts tree to recover filename and
MIME type was matching by attachment ID, which failed for many
real-world messages and fell back to a generic
`attachment-<id-prefix>` name + `application/octet-stream`. Files
uploaded to Drive then needed to be manually renamed.

The lookup remains as a fallback when the caller doesn't provide
both fields. Drive's automatic MIME sniffing also masks the mime
issue for the Drive destination — but the inline destination, and
the Drive filename, only get the right values when the caller passes
them explicitly.

### Inline size cap lowered

`DEFAULT_INLINE_SIZE_CAP_BYTES` is now **60,000** (was 100,000). The
old cap was on raw bytes and didn't account for base64 expansion (4/3)
plus the JSON envelope around the `EmbeddedResource`. A 78KB PDF
produced a ~105KB response that exceeded Claude Code's ~25K-token
tool-response budget; the client truncated and fell back to saving the
content to disk.

The new cap is sized so the encoded response (~80KB base64 + ~1KB
envelope ≈ 81KB) fits comfortably inside the budget. The
`max_size_bytes` per-call override remains for callers who know their
client can handle more.

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
