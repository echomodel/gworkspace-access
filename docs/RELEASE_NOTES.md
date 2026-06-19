# Release Notes

## v0.23.0 — security: host-path Drive I/O is stdio-only

Closes an arbitrary server-side file read/write on the **hosted (HTTP)**
deployment. `drive_upload` / `drive_update` accepted a `local_path` and
`drive_download` a `save_to` that the server read/wrote off its **own**
filesystem. Over HTTP the server is multi-tenant and reachable by untrusted
callers, so a caller could name `/proc/self/environ` (the signing key lives
in the process env) or another user's data file and exfiltrate it — or
overwrite server files. The transport was inferred from whether the path
existed on the server, a check a caller bypasses by naming a real server
path.

- **The network-exposed tools no longer touch the server filesystem.**
  `drive_upload` / `drive_update` take `content_base64` (small) or return a
  direct-to-Google resumable URL (any size); `drive_download` returns inline
  bytes or a Drive link.
- **Host-path I/O moved to stdio-only tools** —
  `drive_upload_local`, `drive_update_local`, `drive_download_to_path`,
  annotated `@mcp_transport("stdio")` (requires mcp-app ≥ 0.9.0). The
  framework never registers them on the HTTP surface, so they aren't even
  advertised to remote clients. On stdio the server runs as the local user,
  so touching their own disk is no escalation.
- **Migration:** callers using `drive_upload(local_path=…)` →
  `drive_upload_local(local_path=…)`; `drive_update(local_path=…)` →
  `drive_update_local(…)`; `drive_download(save_to=…)` →
  `drive_download_to_path(save_to=…)`. These work over stdio only. Over HTTP,
  use `content_base64` / the resumable URL / the Drive link.

## v0.22.0 — custom Drive properties (tag files for discovery)

Adds the ability to attach custom key/value metadata to any Drive file
or folder, so a file can be **found by tag instead of a hardcoded ID**.

- **New SDK `gwsa.sdk.drive.set_properties`** + MCP tool
  `drive_set_properties` + CLI `gwsa drive set-properties`. Sets public
  `properties` and/or app-private `appProperties`.
- **Per-key merge in a single `files.update` call** — a key in the map
  is added/updated, a `null` value deletes a key, and keys not mentioned
  are left untouched (never clobbers other apps' or earlier tags). No
  read-before-write.
- **Discovery** uses the existing `drive_search` with Drive's native
  query, e.g. `properties has { key='myapp' and value='…' }`.
- Tags are API-only: they don't appear in the Drive/Docs/Sheets UI and
  don't travel with a downloaded copy of the file.
- Guidance: prefer **public `properties` with a namespaced key** for
  discovery that must work across different OAuth clients (a cloud
  deployment and a local CLI don't share each other's `appProperties`).

## v0.21.0 — Sheets MCP tools + SDK (create, read, write, tail)

Sheets graduates from CLI-only to a full SDK domain with MCP tools,
shaped around append-style logs:

- **New SDK module `gwsa.sdk.sheets`**: `create_spreadsheet` (with
  optional Drive `folder_id` and first-tab title), `read_values`,
  `read_tail`, `update_values`, `append_rows`, `list_spreadsheets`,
  `get_spreadsheet`.
- **7 new MCP tools**: `sheets_create`, `sheets_list`,
  `sheets_get_metadata`, `sheets_read`, `sheets_read_tail`,
  `sheets_update`, `sheets_append` (server total: 52).
- **`sheets_read_tail`** reads the last N data rows without loading
  the whole sheet (anchor-column extent probe + bounded range read)
  and reports row numbers, enabling targeted updates of recent rows.
  It also supports **cursor pagination newest → oldest**: pass the
  previous response's `start_row` as `before_row` to fetch the next-
  older N rows (a single bounded read per page) and repeat while
  `has_more` is true.
- **CLI additions**: `gwsa sheets create / info / tail / append`;
  existing `list` / `read` / `update-cell` are now thin wrappers over
  the SDK. Writes default to `USER_ENTERED` parsing (`update-cell`
  keeps its historical `RAW` behavior; `append --raw` opts out).

## v0.20.0 — large-file Drive upload & download (transport-aware)

`drive_upload`, `drive_update`, and `drive_download` now move files of
any size, adapting to how the server is reached — without base64 size
limits and without any new HTTP endpoints or auth.

- **Upload / update**: pass `content_base64` for a small inline upload
  (any transport), or `local_path` for a file. On a local (stdio) server
  the file is read and uploaded directly, any size. On a hosted (HTTP)
  server the tool returns a **direct-to-Google resumable upload URL** —
  you PUT the bytes straight to Google, no size cap, bytes never pass
  through the server.
- **Download**: small files come back inline; pass `save_to` on a local
  server to stream a file of any size straight to disk; a large file on a
  hosted server returns the file's **Drive download link** (open it in a
  browser signed in to that account). No server proxy, no token.
- Transport is detected automatically by whether the server can see the
  path you named — no configuration.

**Breaking changes:**

- `drive_upload` / `drive_update` no longer take the `source` discriminated
  union. Use `content_base64=` (inline) or `local_path=` instead.
- `drive_download` no longer takes `max_size_bytes`; size handling is
  automatic (inline / `save_to` / Drive link).

(Pre-1.0: breaking changes ride a minor bump.)

## v0.18.1 — fix `gwsa mail read`

Fix `gwsa mail read FILE_ID`, which raised `AttributeError` because it
called a nonexistent `mail.get_message`. It now calls `mail.read_message`
and returns the message as documented.

## v0.18.0 — `gwsa drive revisions match` (find/pin the revision by content hash)

Adds `gwsa drive revisions match FILE_ID LOCAL_PATH [--pin]` (issue #39).
It hashes a local file and finds the revision whose `md5Checksum` equals
it — answering "is this exact content already backed up, and which
revision is it?" without the caller hashing and parsing `revisions list`
JSON by hand. The motivating workflow: using Drive as a version store,
confirm a local file is synced and pin that exact revision by content
hash — never by upload timing or "the latest revision."

- **Exit-code contract** (CLI): `0` if a matching revision is found, `1`
  if not, `2` on error (e.g. a native Google file, which has no
  checksum). The exit code *is* the "is this content backed up?" check —
  there's no separate `verify` command; `match`'s exit code covers it.
- **`--pin`**: pins the matched revision (`keepForever`) in the same
  call — match-and-pin atomically. Pairs with content written outside
  the CLI (a save into a Drive-synced folder): confirm the upload landed
  and pin the exact revision by hash, no reliance on upload timing.
- **CLI-only**: `match` is intentionally not exposed as an MCP tool. It
  is a local-file operation; a remote MCP server can't read the agent's
  filesystem, and shipping the whole file inline just to hash it defeats
  the "match by hash without moving bytes" purpose. (MCP tool count
  stays at 45.)

## v0.17.0 — `gwsa drive revisions` (Drive as a version store)

Adds a `gwsa drive revisions` subcommand group and matching MCP tools
that turn an uploaded file's Drive revision history into a lightweight,
server-side version store.

- `gwsa drive revisions list FILE_ID` — enumerate revisions (id,
  modified time, keepForever, size, md5, mimeType, last modifier).
- `gwsa drive revisions get FILE_ID REVISION_ID [--out PATH]` — fetch a
  past revision's content (streams to stdout, or writes to `--out`).
- `gwsa drive revisions keep|unkeep FILE_ID REVISION_ID` — pin/unpin a
  revision (`keepForever`) so milestones survive auto-pruning.

`gwsa drive upload` and `gwsa drive update` also gain a `--keep` flag
(`keep_revision_forever` on the SDK and MCP tools) that pins the
resulting revision in the same call via the Drive API's
`keepRevisionForever`, so a milestone version can be saved and pinned in
one step rather than update-then-`revisions keep`.

MCP tools: `drive_list_revisions`, `drive_get_revision`,
`drive_keep_revision`, `drive_unkeep_revision` (45 tools total).

Behavior captured at the point of use: revision **content** is
retrievable only for uploaded (non-native) files — native Google files
(Docs/Sheets/Slides) can be listed but their historical content is not
exportable, and the SDK raises a typed `NativeFileRevisionError` that
the CLI/MCP layers surface clearly. Drive prunes non-pinned revisions
(~100 versions / 30 days), `keepForever` is capped at ~200 per file,
and the API has no writable revision name — a human "commit message"
must live inside the file content.

One Drive asymmetry is enforced explicitly: `keepForever` can be toggled
both ways only on the **head (current)** revision. A pinned **non-head**
revision cannot be un-pinned (`illegalKeepForeverModification`); the SDK
raises a typed `KeepForeverUnsetError` and the CLI/MCP surface it
clearly. Pin older milestones deliberately.

## v0.16.0 — `forward_email` + Content-ID-aware part fidelity

Adds a faithful **forward** capability and closes the inline-image
fidelity gap that also affected reply quoting.

`forward_email(message_id, to, note=None, html_note=None, cc=None,
bcc=None, as_draft=False)` rebuilds the forward from the source's full
raw MIME (`messages.get?format=raw`), preserving every regular
attachment byte-for-byte, every inline image with its **original
Content-ID** (so the quoted HTML's `cid:` references still render), and
both the HTML and plain-text body alternatives — then prepends the
caller's note. A forward starts a new thread.

The same part-rebinding now applies to **reply** quoting: when the
quoted tail contains inline `cid:` images, `reply_email` re-attaches the
matching Content-ID parts so they render. A reply carries only those
inline parts, not the original's file attachments (matching native mail
clients).

New `read_email_structure(message_id)` accessor exposes a message's full
per-part MIME structure — `mime_type`, `content_id`, `disposition`
(inline vs attachment), `filename`, `size`, and whether the HTML body
references each part via `cid:` — for callers that need the structure
behind a faithful rebuild rather than the decoded body `read_email`
returns.

Why this matters: forward was previously impossible, and any
reconstruction that quoted HTML containing `cid:` references without
re-attaching the matching Content-ID parts showed broken inline images.
Both gaps stem from the same root cause — reply and forward are
client-side reconstructions, and a faithful one must rebuild from raw
MIME and re-bind `cid:` parts by Content-ID. See CONTRIBUTING.md for the
preserved design rules.

## v0.15.0 — `gwsa --account` per-invocation account override

The `gwsa` domain CLI now accepts `--account <name-or-email>` on the
top-level command, overriding the user's `default_account` for that one
invocation (e.g. `gwsa --account work drive upload ...`). This completes
the per-call selection the README previously listed as planned, and
makes the CLI symmetric with the MCP tools, which already accept an
`account` argument per call.

Selection precedence in the SDK credential resolver is now: an explicit
per-call `account=` argument > the CLI `--account` override > the
profile's `default_account` > the sole account if only one exists. The
CLI override is recorded via `gwsa.sdk.auth.set_cli_account()` (a
process-scoped ContextVar set once by the top-level CLI callback); it is
unused under HTTP/MCP transport, where each tool call passes its own
`account` argument.

This matters because `gwsa drive upload` (and every other domain
command) previously always used `default_account`, with no way to target
a different account per call — so an upload destined for a folder only
shared with a non-default account would fail with a Drive 404 that looked
like a missing folder.

## v0.14.2 — drop dead `validated_scopes` / `last_validated` profile fields

Removed the `validated_scopes` and `last_validated` fields from
`GoogleAccount`. They were only ever populated by the legacy-vault
`migrate` path; `accounts add` never set them, so every normally-added
account carried `validated_scopes: []` regardless of the token's real
scopes. An empty list read as "no scopes granted" when it actually
meant "never recorded" — actively misleading for diagnosis. The token
blob already carries its own `scopes`, and the authoritative check is a
live `tokeninfo` call, so the cached metadata had no correct use.

No migration needed: existing stored profiles that still contain these
keys load fine (the model ignores unknown keys), and nothing read the
fields.

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
