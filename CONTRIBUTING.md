# Contributing

## Project structure

```
gworkspace-access/
├── README.md                     # User-facing overview, install, quick start.
├── CONTRIBUTING.md               # This file — dev workflow + repo layout.
├── MCP-SERVER.md                 # MCP client registration.
├── pyproject.toml                # Build + entry points + dependencies.
├── gwsa/
│   ├── __init__.py               # App composition root (declares mcp-app App, profile model, admin extensions).
│   ├── sdk/                      # All behavior. Layered access to Google APIs.
│   │   ├── auth.py               # Credential resolution (bridges mcp-app + legacy vault).
│   │   ├── mail/, docs/, drive/, chat/, calendar/, people/
│   │   └── profiles.py, config.py    # Legacy vault — read path during migration.
│   ├── cli/                      # Thin Click wrappers over the SDK. Domain commands only.
│   │   ├── __main__.py           # gwsa entry point (mail / sheets / docs / drive / chat / calendar).
│   │   ├── mail/, docs_commands.py, drive_commands.py, sheets_commands.py, chat.py, calendar_commands.py
│   │   └── decorators.py         # require_scopes, status formatting.
│   ├── mcp/
│   │   ├── tools.py              # mcp-app-native tool module (auto-discovered).
│   │   └── server.py             # Legacy FastMCP server. Still serves gwsa-mcp during migration.
│   └── admin/                    # gwsa-admin extensions (accounts subgroup, acquire-token, migrate).
├── tests/
│   ├── framework/                # mcp-app conformance test pack (App wiring, auth, tool protocol).
│   ├── unit/                     # SDK + admin CLI unit tests.
│   └── integration/              # Live-API tests (Gmail, Drive, Docs). Require valid token.
└── docs/
    └── CLOUD-MULTI-USER.md       # Locked architecture + migration plan.
```

## Architecture rules

**All behavior lives in the SDK** (`gwsa/sdk/`). CLI commands and MCP
tools are thin wrappers that parse input, call the SDK, and format
output. If you find yourself writing logic in `gwsa/cli/` or
`gwsa/mcp/`, move it to the SDK.

**Profile / account / token management lives exclusively in
`gwsa-admin`.** The user-facing `gwsa` CLI is Google Workspace
domain operations only.

**MCP tool surface lives in `gwsa/mcp/tools.py`.** Plain async
functions, no decorators — name becomes tool name, docstring becomes
schema description, type hints drive parameter schemas. mcp-app
discovers them automatically.

### Byte-producing tools: control plane carries references, data plane is out-of-band

Tools that produce binary output (email attachments, Drive downloads,
generated reports) must work under any MCP transport — including HTTP,
where the agent and the server do not share a filesystem. A parameter
like `save_path: str` is therefore an antipattern: under HTTP transport
the file lands on the server container and is unreachable from the
agent.

The convention in this repo is the **`destination` parameter** defined
in `gwsa.sdk.destinations`:

- `InlineDestination` — return the bytes as a content block
  (`EmbeddedResource` + `TextContent` summary). Subject to a size cap
  (default 100KB) because tool responses have practical client limits.
- `DriveDestination` — upload to the user's Google Drive and return a
  file id + URL. The user already has tools to retrieve files from
  Drive, so the data plane is out-of-band of the MCP response.

The `materialize()` helper handles the discrimination. Any new tool
that produces bytes should accept a `Destination` parameter and return
either `list[ContentBlock]` (inline) or a plain dict (Drive). Never
introduce a server-local-path parameter on a byte-producing tool.

The `gwsa.sdk` layer stays transport-agnostic: byte-producing SDK
helpers expose `*_bytes` and `*_file` variants. The CLI uses
`download_file(save_path)`-style helpers because the CLI is stdio-only.
The MCP layer always uses the `*_bytes` variants and the destination
plumbing.

### Byte-consuming tools: the `source` parameter is the mirror image

The same filesystem-sharing problem applies in reverse to tools that
*accept* binary input (Drive upload, Drive update). A `local_path: str`
parameter only works under stdio, where the server runs on the agent's
machine. Under HTTP the server cannot read the agent's files, so a path
the agent names fails with `FileNotFoundError` even though the file
exists on the agent side.

The convention is the **`source` parameter** defined in
`gwsa.sdk.sources`:

- `InlineSource` — the bytes travel in-band as base64
  (`data_base64` + optional `name`/`mime_type`). Works under any
  transport. Subject to a raw-byte cap (default 700KB) because
  tool-call arguments have a practical client ceiling.
- `LocalPathSource` — read from the server's filesystem. Correct only
  under stdio.

The `resolve_source()` helper returns `(data, name, mime_type)`
regardless of kind. Any new tool that consumes bytes should accept a
`Source` parameter and pass the resolved bytes to a `*_bytes` SDK
helper. Never introduce a bare server-local-path parameter on a
byte-consuming tool — for the same reason `save_path` is banned on the
producing side.

### Reply and forward are client-side MIME reconstructions

Reply and forward are **not** Gmail API primitives. Both are assembled
client-side over `drafts.create` / `messages.send`, where the caller
hands Gmail a fully-formed raw MIME message. The only natively
reply-specific affordance is **threading** (`threadId` plus the
`In-Reply-To` / `References` headers); everything else — quoting,
attachments, inline images — is a rebuild we own.

A faithful rebuild must work from the source's **full raw MIME**
(`messages.get?format=raw`), not from the decoded convenience view
`read_message` returns. That view (`body.html` / `body.text` plus a
flat attachment list) is lossy: it drops the per-part Content-ID and
the inline-vs-attachment disposition. Critically, an inline image only
renders when the HTML's `<img src="cid:XXX">` is matched by a MIME part
carrying `Content-ID: <XXX>`. Re-attaching that part with a
freshly-generated CID does **not** match the quoted HTML's `cid:`
token, so the image breaks. This bites a reconstructed *reply* exactly
as it bites a forward whenever the quoted body contains inline images.

The reconstruction lives in `gwsa/sdk/mail/mime.py`:

- `fetch_raw_message` / `split_parts` pull the raw MIME and split it
  into text/html bodies, inline (`cid:`-referenced) parts, and
  attachment parts.
- `assemble_message` rebuilds the nested
  `multipart/mixed[ multipart/alternative[ text, multipart/related[
  html, inline ] ], attachments ]` shape, **re-attaching each inline
  part with its original Content-ID** so the quoted HTML still resolves.

Rules to preserve if you touch this code:

1. **Always rebuild from raw MIME for forward**, and for reply whenever
   the quoted HTML carries inline `cid:` parts. Never hand-assemble a
   forward/reply from decoded parts — Content-IDs are lost.
2. **A reply re-carries only inline parts, not file attachments.** A
   forward carries both. This matches native mail clients.
3. **Preserve Content-IDs verbatim** (with angle brackets). The HTML
   references `cid:XXX`; the part header must read `Content-ID: <XXX>`.

### Drive revisions (version store for uploaded files)

`gwsa/sdk/drive/revisions.py` wraps Drive's `revisions` resource so an
uploaded file's history can serve as a minimal version store. Rules to
preserve if you touch this code:

1. **Content download is gated to non-native files.** Native Google
   files (mimeType `application/vnd.google-apps.*`) can be *listed* but
   their historical content is not exportable via `alt=media`.
   `_fetch_revision_bytes` checks the revision's mimeType and raises
   `NativeFileRevisionError` **before** attempting `get_media`, so the
   CLI/MCP layers can surface the limitation explicitly instead of
   failing opaquely. Don't remove that guard.
2. **Byte variants mirror the download convention.**
   `download_revision_bytes` (in-memory, for MCP) and
   `download_revision_file` (disk, for the CLI) parallel
   `download_bytes` / `download_file`. The MCP tool `drive_get_revision`
   returns bytes inline via `materialize()` + `inline_payload_to_blocks`;
   the CLI streams to stdout or `--out PATH`. Never add a server-local
   path parameter to the MCP tool (see the byte-producing-tools rule
   above).
3. **No writable revision name.** The API exposes only `keepForever`
   (plus `published`, timestamps, checksums, size). Don't invent a
   revision-name field — a human "commit message" belongs in the file
   content. `keep_revision` / `unkeep_revision` toggle `keepForever`;
   that is the only writable knob.
4. **Unpinning is head-only (verified against the live API).** Drive
   lets you toggle `keepForever` both ways only on the **head** revision.
   A pinned **non-head** revision cannot be un-pinned — the API returns
   `illegalKeepForeverModification`, which `_set_keep_forever` translates
   into the typed `KeepForeverUnsetError`. Preserve that translation so
   the CLI/MCP layers can surface the limitation instead of leaking a
   raw `HttpError`. The integration test asserts this behavior; don't
   "fix" it to expect symmetric toggling.

### Calendar event availability (Free/Busy)

Calendar event create/update map an `availability` value (`free`/`busy`)
to the Calendar API `transparency` field (`transparent`/`opaque`) in
`gwsa/sdk/calendar/events.py`. Two design rules must be preserved if you
touch this code:

1. **All-day events default to Free; timed events default to Busy.**
   This mirrors the Google Calendar web UI. `create_event` applies the
   all-day default; `update_event` does **not** apply any default — an
   update only changes `transparency` when `availability` is passed, so
   it never silently flips a user's existing event.
2. **Always echo a normalized `transparency` + `availability` back.**
   The raw API omits `transparency` when it is the default `opaque`, so
   `_normalize()` fills it in. Don't return raw API events for calendar
   operations — callers rely on the explicit value to confirm what was
   set.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Testing

**Unit + framework tests** run offline with no credentials:

    make setup       # bootstrap venv (once)
    pytest           # run unit + framework tests

Or from a fresh clone:

    make test        # creates venv + runs unit + framework tests

Bare `pytest` ignores `tests/integration/` by default (see
`pyproject.toml` `[tool.pytest.ini_options]`).

**Integration tests** require additional setup:

| Suite | Path | Prerequisites |
|-------|------|--------------|
| real-user | `tests/integration/real-user/` | A configured local gwsa account (`gwsa-admin connect local` + `gwsa-admin accounts add`). Each contributor uses their own Google identity. |

Run explicitly:

    make integration-test
    # or:
    pytest tests/integration/real-user/

### Test philosophy (sociable)

Tests run real collaborators end-to-end against isolated temp
directories. The only mocked boundaries are uncontrollable network
calls (e.g., `InstalledAppFlow.run_local_server` in
`test_acquire_token.py`). CLI tests use Click's `CliRunner` —
in-process invocation against `gwsa.app.admin_cli`, not subprocess.

Storage isolation uses `monkeypatch.setenv` to redirect
`HOME` / `XDG_CONFIG_HOME` / `XDG_DATA_HOME` / `APP_USERS_PATH` /
`GWSA_CONFIG_DIR` to per-test `tmp_path` directories. Nothing touches
the real filesystem.

The mcp-app test pack lives under `tests/framework/` and verifies the
`App` declaration, auth enforcement, and tool protocol compliance
against our actual `App` instance.

## Pre-commit

A precommit hook scans for credentials and PII before allowing the
commit. Don't bypass it; if a finding is a false positive, surface it
and we'll work around it.

## Version management

**Single source of truth:** `gwsa/__init__.py` `__version__`.

| Change type | Bump | Example |
|-------------|------|---------|
| Bug fix | Patch | 0.7.0 → 0.7.1 |
| Backwards-compatible feature | Minor | 0.7.0 → 0.8.0 |
| Breaking change | Major | 0.7.0 → 1.0.0 |

Don't bump to 1.0.0 without explicit approval — 0.x → 1.0.0 is a
product decision, not a mechanical version increment.

**Release:**

```bash
# 1. Bump version in gwsa/__init__.py and pyproject.toml (keep in sync).
git add gwsa/__init__.py pyproject.toml
git commit -m "chore: bump version to X.Y.Z"

# 2. Tag and push.
git tag vX.Y.Z
git push && git push --tags
```

Editable installs (`pip install -e .`) always use the working tree
regardless of version, so dev iteration doesn't need bumps.
