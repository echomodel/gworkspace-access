# Google Workspace Access (`gwsa`)

A CLI and MCP server for working with Gmail, Google Drive, Docs, Sheets,
Chat, and Calendar from the command line or from AI agents. Built on the
[mcp-app](https://github.com/echomodel/mcp-app) framework so the same
binary works locally (stdio, one human) and as a hosted multi-user
service (HTTP, JWT-authenticated).

> **Status:** local stdio is the documented one-human path. Cloud
> HTTP deployment is supported via [gapp](https://github.com/echomodel/gapp)
> (Cloud Run + custom domain + JWT auth via mcp-app); see
> [Cloud deployment](#cloud-deployment) below for the abstract
> walkthrough.

## Prerequisites

- **Python 3.10+** (3.11 recommended).
- **A Google Cloud project you can configure.** gwsa needs an OAuth
  2.0 Client ID — either one you create in the Cloud Console (the
  default path, gives you control over billing and scopes) or
  gcloud's well-known client (faster setup, billed via
  `--quota-project`). The
  [Authenticating with Google](#authenticating-with-google) section
  below walks through the Console steps.
- **For the gcloud variant:** the `gcloud` CLI installed and
  authenticated (`gcloud auth application-default login`).

> **Workspace (corp) accounts:** if your Google identity is part of a
> Workspace org with strict OAuth policies (allowlisted clients,
> sensitive-scope review, Context-Aware Access), the Cloud-Console
> OAuth-client path may not work for that identity. See
> [Workspace org constraints](#workspace-org-constraints) before
> spending time creating a client.

## Install

```bash
pipx install git+https://github.com/echomodel/gworkspace-access.git@v0.16.0
```

Installs three commands:

| Command       | What it does |
|---------------|--------------|
| `gwsa`        | Google Workspace domain operations (mail, drive, docs, sheets, chat). |
| `gwsa-mcp`    | MCP server for AI assistant integration. |
| `gwsa-admin`  | Setup, credentials, user/account management. |

## Quick start (one Google account)

This is the headline path. If you have one Google identity you want to
access, do exactly this.

### 1. Authenticating with Google

Pick **one** of the two paths.

#### Path A — Your own OAuth client (default, recommended)

In the [Google Cloud Console](https://console.cloud.google.com/):

1. **Select or create a project.** This project becomes the billing
   home for every API call gwsa makes for this account; no
   `--quota-project` is needed for tokens issued by this client.
2. **Enable APIs** you'll use: Gmail API, Google Drive API, Google
   Docs API, Sheets API, Google Calendar API, and (if you want chat
   tools) Google Chat API and People API. `APIs & Services → Enabled
   APIs → ENABLE APIS AND SERVICES`.
3. **Configure the OAuth consent screen** (only on first OAuth client
   in the project): set publishing status to *Testing*, add your
   Google email under *Test users*. This lets your own account
   consent without app verification. Submit nothing.
4. **Create the OAuth client.** `APIs & Services → Credentials →
   Create credentials → OAuth client ID → Application type: Desktop
   app`. Download the JSON; this is your `client_secrets.json`. Put
   it anywhere on disk — gwsa reads it once, on demand.

#### Path B — gcloud's well-known client

If you don't want to manage a Cloud Console OAuth client:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_GCP_PROJECT
```

This produces a token at
`~/.config/gcloud/application_default_credentials.json` issued by
gcloud's well-known OAuth client. Skip step 3 below and jump to the
[gcloud variant](#gcloud-variant) in step 4 — you don't run
`acquire-token`, you hand the existing blob directly to
`accounts add`.

### 2. Tell `gwsa-admin` where to look on local disk

```bash
gwsa-admin connect local
```

This writes a one-line setup file so subsequent admin commands know to
read and write the local user store (not a remote URL).

### 3. Acquire a token and register an account

```bash
gwsa-admin acquire-token --client-secrets /path/to/client_secrets.json |
  gwsa-admin accounts add personal --email me@example.com --token=-
```

`acquire-token` opens a browser, runs the OAuth consent flow, and writes
the resulting token JSON to stdout. `accounts add` reads it from stdin
and stores it. On a fresh install the user record is auto-created from
`--email` and the new account becomes the default — no separate "users
add" ceremony.

### 4. Confirm it worked

```bash
gwsa-admin accounts list
gwsa mail search "newer_than:1d"
```

That's it. Everything below is optional — adding more accounts,
registering the MCP server with an AI client, or operating on the
cloud variant.

### gcloud variant

If you'd rather use a token issued by `gcloud auth
application-default login`:

```bash
gcloud auth application-default login
gwsa-admin accounts add gcloud-account \
  --email me@example.com \
  --token=@~/.config/gcloud/application_default_credentials.json \
  --quota-project YOUR_GCP_PROJECT
```

`--quota-project` is required because gcloud's well-known OAuth client
has no host project of its own; API calls need a billing project. If
you ran `gcloud auth application-default set-quota-project` first, the
project is already in the blob and `--quota-project` becomes optional.

## Adding more Google accounts

A gwsa **user** is one human (you). Inside your user record is a list
of **accounts** — one entry per Google identity you own (personal,
work, etc.). One of them is marked as `default_account`; gwsa CLI calls
and MCP tools use it implicitly.

Add a second account the same way as the first, plus a name to tell
them apart later:

```bash
gwsa-admin acquire-token --client-secrets /path/to/work.json |
  gwsa-admin accounts add work --email me@example.org --token=-
```

Switch which account is the default:

```bash
gwsa-admin accounts use work    # now 'work' is implicit
```

Inspect, remove, or override:

```bash
gwsa-admin accounts list        # see all accounts, marked with (default)
gwsa-admin accounts get work    # detail one
gwsa-admin accounts remove personal
```

For per-call override on the gwsa CLI, pass the `--account` flag on the
top-level command (e.g. `gwsa --account work mail search "..."`). It
takes an account name or email and overrides the user's
`default_account` for that invocation; omit it to use the default.

## Daily usage

### CLI

Single-user installs (one user in the local store) need nothing
extra — every command resolves credentials through that user's
default account:

```bash
gwsa mail search "from:bob after:2026-01-01"
gwsa drive list
gwsa docs read DOC_ID
gwsa chat spaces list
gwsa calendar events --time-min 2026-06-01T00:00:00Z
```

If the local store has multiple users, pass `--user` once on the
top-level command:

```bash
gwsa --user me@example.com mail search "newer_than:1d"
```

The `--user` flag selects the gwsa user; the user's `default_account`
selects which Google identity inside that user's profile to use. To
override the account for a single invocation, add `--account
<name-or-email>` on the top-level command (e.g.
`gwsa --account work drive upload ...`).

### Calendar events and Free/Busy

Calendar tools cover listing calendars, listing/searching events, and
creating, updating, and deleting events:

```bash
gwsa calendar calendars
gwsa calendar events --time-min 2026-06-01T00:00:00Z --time-max 2026-07-01T00:00:00Z
gwsa calendar create "Team sync" 2026-06-02T09:00:00-05:00 2026-06-02T09:30:00-05:00
gwsa calendar create "Conference" 2026-06-10 2026-06-12 --all-day
gwsa calendar update EVENT_ID --availability free
gwsa calendar delete EVENT_ID
```

An event's **availability** is its Free/Busy state, mapped to the
Calendar API `transparency` field. Pass `--availability free|busy`
(CLI) or `availability="free"|"busy"` (MCP) on create and update.

**Defaults mirror the Google Calendar web UI, with one deliberate
asymmetry:**

- **All-day events default to Free.** A multi-day "Conference" or an
  "Out of office" marker won't block your availability unless you say
  `--availability busy`.
- **Timed events default to Busy** — the Calendar API's own default.

The returned event always carries an explicit, normalized
`transparency` plus an `availability` alias (`free`/`busy`), even
though the raw API omits `transparency` when it is the default
`opaque`. That means you can always confirm what was set without
guessing.

`update` never changes Free/Busy unless you pass `--availability` — it
only touches the fields you give it, so it won't silently flip an
existing event.

> **New scopes — re-authenticate.** Calendar uses the
> `calendar.readonly` and `calendar.events` OAuth scopes. If you
> configured gwsa before Calendar support landed, re-run
> `acquire-token` and `accounts add` (see
> [Rotating tokens](#rotating-tokens-when-refresh-fails)) so your
> stored token carries the Calendar scopes.

### Drive revisions as a version store

`gwsa drive` can use an uploaded file's Drive **revision history** as a
lightweight, server-side version store — list prior versions, fetch the
content of any past version to diff, and pin milestones so they are
never auto-pruned:

```bash
gwsa drive revisions list FILE_ID
gwsa drive revisions get FILE_ID REVISION_ID            # streams content to stdout
gwsa drive revisions get FILE_ID REVISION_ID --out v1.json
gwsa drive revisions keep FILE_ID REVISION_ID           # pin (keepForever)
gwsa drive revisions unkeep FILE_ID REVISION_ID         # unpin
```

A new file's revisions only stack when you **update the same file by id**
— `drive upload` always creates a *new* file. So the version-store loop
is: `upload` once (keep the returned `id`), then `update <id>` for each
new version. Pin a milestone in the same step with `--keep`:

```bash
gwsa drive upload data.json                     # → {"id": "FILE_ID", ...}  (v1)
gwsa drive update FILE_ID data.json             # v2
gwsa drive update FILE_ID data.json --keep      # v3, pinned in one call
gwsa drive upload data.json --keep              # pin the initial revision too
```

`--keep` sets `keepForever` on the resulting revision atomically (via the
Drive API's `keepRevisionForever`), so you don't need a separate
`revisions keep` call.

Behavior to know:

- **Content is retrievable only for uploaded (non-native) files** —
  JSON, CSV, DOCX, PDF, images, etc. **Native Google files**
  (Docs/Sheets/Slides) can be *listed* but their historical content is
  not exportable; `revisions get` surfaces a clear error for them.
- **Auto-pruning.** Drive prunes non-pinned revisions roughly after 100
  versions or 30 days. `revisions keep` sets `keepForever` so a milestone
  persists. Drive caps pinned revisions at ~200 per file.
- **Pinning an old revision is one-way.** Drive only lets you toggle
  `keepForever` both ways on the **head (current)** revision. Once a
  **non-head (older)** revision is pinned, the API refuses to un-pin it
  — `revisions unkeep` returns a clear error in that case. Pin older
  milestones deliberately.
- **No revision name.** The API has no writable name/description on a
  revision — only the pin flag, timestamps, checksums, and size. Treat
  any human "commit message" as something to put *inside* the file
  content, not on the revision.

The same operations are exposed as MCP tools: `drive_list_revisions`,
`drive_get_revision`, `drive_keep_revision`, `drive_unkeep_revision`.

### MCP server (AI assistants)

`gwsa-mcp` is a stdio MCP server exposing 45 tools across mail,
docs, drive, chat, calendar, and account discovery. (Sheets is
CLI-only for now.) Tools are discovered by mcp-app from
`gwsa.mcp.tools.{accounts,mail,docs,drive,chat,calendar}`.

Every Google-touching MCP tool accepts an optional `account`
argument — the account `name` (e.g. `"work"`) or its Google
`email` (e.g. `"me@example.org"`) — so an AI client can pick a
specific account per call when the user has more than one. Omit
`account` to use the user's `default_account`, or the sole
account when only one is configured. The `list_google_accounts`
tool exposes the names and emails the agent should pass.

#### Forwarding and message part fidelity

`forward_email(message_id, to, note=None, html_note=None, cc=None,
bcc=None, as_draft=False)` forwards a message rebuilt from its full
source MIME, preserving:

- every regular **attachment**, byte-for-byte,
- every **inline image** with its original Content-ID, so the quoted
  HTML's `cid:` references (signature logos, embedded charts) still
  render,
- both the HTML and plain-text body alternatives,

then prepends your `note` / `html_note`. A forward starts a new thread.

The same part-rebinding now applies to **reply** quoting: when the
quoted tail contains inline `cid:` images, `reply_email` re-attaches
the matching Content-ID parts so they still render (it does not
re-carry the original's file attachments — only the inline images the
quoted body points at).

`read_email_structure(message_id)` exposes the full per-part MIME
structure behind a message — each part's `mime_type`, `content_id`,
`disposition` (inline vs attachment), `filename`, `size`, and whether
the HTML body references it via `cid:` — for callers that need the
structure rather than the decoded body that `read_email` returns.

The stdio entry point takes a `--user KEY` selector identifying
which registered local user it should run as. The key is an opaque
local-store handle — **not a Google email**. The Google account
emails live on each `GoogleAccount` inside the user's profile and
never need to surface in MCP registrations.

`gwsa-admin migrate` creates a single user keyed `local` by default.
Use that key in all registrations below.

Register with your client:

**Claude Code:**
```bash
claude mcp add --scope user gwsa -- gwsa-mcp stdio --user local
claude mcp list                           # verify
```

**Gemini CLI / Gemini Code Assist:**
```bash
gemini mcp add gwsa gwsa-mcp stdio --user local --scope user
gemini mcp list                           # verify
```

**Claude.ai web (custom connector):** requires the cloud HTTP
variant. After cloud deploy (see below), generate a one-shot
connector URL with a long-lived token via:

```bash
gwsa-admin register --user me@example.com --client claude.ai
```

Paste the resulting `https://<your-cloud-domain>/?token=<jwt>`
URL into **claude.ai → Settings → Connectors → Add custom
connector**. Local stdio doesn't apply to this client.

Client-specific quirks, troubleshooting, and detailed transport
options live in [Claude Code Configuration](docs/CLAUDE-CODE.md) and
[Gemini CLI Configuration](docs/GEMINI-CLI.md). The combined story
across all clients is in [MCP Server Setup](MCP-SERVER.md).

## Reference

### Storage paths

| Path | Purpose |
|------|---------|
| `~/.local/share/gwsa/users/<email>/auth.json`    | Per-user auth record. |
| `~/.local/share/gwsa/users/<email>/profile.json` | Per-user profile (accounts list). |
| `~/.config/gwsa/setup.json`                      | `connect local` / `connect <url>` config. |
| `~/.config/gworkspace-access/profiles/<name>/`   | **Legacy** vault (pre-mcp-app). Read-only after `gwsa-admin migrate`; delete manually when satisfied. |

### Profile schema

```python
class GoogleAccount(BaseModel):
    name: str                 # 'personal', 'work', ...
    email: str                # Google account email
    token: dict               # authorized_user blob (refresh_token, client_id, scopes, ...)
    quota_project: str | None # required for gcloud-issued tokens; optional otherwise

class Profile(BaseModel):
    accounts: list[GoogleAccount]
    default_account: str | None
```

### `gwsa-admin` command surface

```
gwsa-admin connect local
gwsa-admin connect <url> --signing-key <key>     # for hosted instance (Phase 2)
gwsa-admin acquire-token --client-secrets PATH [--scopes ...] [--out FILE]
gwsa-admin accounts add NAME --email EMAIL --token=<-|@FILE|JSON> [--quota-project ID] [--user KEY]
gwsa-admin accounts list   [--user KEY]
gwsa-admin accounts get    NAME [--user KEY] [--show-token]
gwsa-admin accounts remove NAME [--user KEY]
gwsa-admin accounts use    NAME [--user KEY]
gwsa-admin migrate [--user-key KEY] [--skip-broken] [--dry-run]    # one-shot legacy → mcp-app
gwsa-admin users list
gwsa-admin users revoke KEY
```

`gwsa-admin --help` lists every command. Each subcommand has its own
`--help`.

## Upgrading from the legacy vault

If you used gwsa before this branch (profiles in
`~/.config/gworkspace-access/profiles/`), run:

```bash
gwsa-admin migrate --dry-run   # preview
gwsa-admin migrate             # do it
gwsa-admin accounts list       # verify
rm -rf ~/.config/gworkspace-access/profiles   # delete when satisfied
```

Each legacy profile becomes one `GoogleAccount` on a single user
record (one human, many accounts). The active legacy profile becomes
`default_account`. The legacy directory is left in place until you
remove it.

## Workspace org constraints

If the Google identity you want to register is a corporate Workspace
account (not a free `@gmail.com` consumer account), the
Console-OAuth-client path (Path A above) may be blocked by your
org's policies. The common failure modes:

- **OAuth client allowlist.** Many corp orgs only allow IT-blessed
  app IDs to request user consent. Your personal-project OAuth
  client gets refused at the consent screen.
- **Sensitive-scope review.** Gmail/Drive/Calendar scopes are
  classified "sensitive" by Google; many orgs require admin
  allowlisting per app even when the client itself is permitted.
- **Context-Aware Access.** Policies that gate auth flows on device
  posture or network can refuse the flow entirely.

What actually works varies by org:

- **gcloud variant (Path B) sometimes routes around the OAuth
  allowlist** because gcloud uses Google's own well-known client.
  Context-Aware Access can still block it.
- **You may have one GCP project for your personal identity and
  zero for your corp identity.** Phase-2 cloud deployments shouldn't
  assume "the user's GCP project" as a singular thing.

This is one of the reasons each account on a gwsa user's profile
carries its own `quota_project` and was acquired with its own
OAuth client config — different identities may *have* to use
different projects, not just prefer to. See §5 of
[Cloud Multi-User Architecture](docs/CLOUD-MULTI-USER.md) for the
phase-2 design implications.

## Rotating tokens (when refresh fails)

OAuth refresh tokens can die without warning. The most common
cause on personal-use installs is the **Testing-mode 7-day
expiry**: if the OAuth client whose `client_secrets.json` you
used is set to "Testing" in the Google Cloud Console, every
refresh token it issues expires exactly 7 days after consent,
regardless of use.

**Symptom:** any gwsa CLI or MCP tool call fails with
`invalid_grant: Bad Request` from `google-auth`'s token refresh.

### Diagnose: what mode is your OAuth client in?

Find the project number — it's the leading digits of any
`client_id` in your stored token, and also of the
`installed.client_id` field in your `client_secrets.json`.
Then open:

```
https://console.cloud.google.com/auth/audience?project=<project-number>
```

If the page shows **Publishing status: Testing**, you're on the
7-day clock. If it shows **In production**, refresh tokens last
indefinitely (or until manually revoked) — the failure is from
something else (the client was deleted, the secret was rotated,
or the user revoked access at myaccount.google.com).

### Stop the bleeding: publish to Production

In the audience page above, click **Publish app**. New refresh
tokens minted after that won't expire from the 7-day rule. Apps
that request sensitive scopes (Gmail, Drive, Docs, Sheets) can
publish without going through Google's verification; users see
an "unverified app" warning at consent but the token works fine
for personal use.

Tokens that already died from the 7-day clock stay dead — only
new tokens minted post-publish benefit. You still need to
re-acquire.

### Re-acquire and replace

Single-user installs auto-resolve to the only user in the store,
so `--user` is unnecessary in every step below. Add
`--user <key>` only if you have multiple users locally.

```bash
gwsa-admin accounts remove personal
gwsa-admin acquire-token \
  --client-secrets ~/.config/gworkspace-access/client_secrets.json \
  --out /tmp/gwsa-token.json
gwsa-admin accounts add personal --email you@example.com \
  --token=@/tmp/gwsa-token.json
rm /tmp/gwsa-token.json
```

`acquire-token` opens a browser, you consent, the fresh token
JSON lands in `/tmp/gwsa-token.json`, and `accounts add` reads it
from there. The pipe form (`acquire-token | accounts add
--token=-`) is equivalent and supported as of version 0.10.1;
earlier versions had a stdout-flush bug that could swallow the
token mid-pipe.

Verify with any read:

```bash
gwsa mail search "newer_than:1d" --max-results 1
```

## Multi-user on one local machine

Rare. If you genuinely have multiple humans sharing one workstation
and one gwsa install, add `--user <key>` to every `gwsa-admin`
command that's not unambiguous. The [cloud variant](#cloud-deployment)
is the right answer when multi-user is the actual deployment shape.

## Cloud deployment

gwsa runs as a hosted multi-user HTTP service on Google Cloud
Run via [gapp](https://github.com/echomodel/gapp). The same
binary that serves stdio for a single human serves HTTP for
many — mcp-app handles transport, JWT auth, admin REST, and
GCS-backed user state automatically.

### Architecture

- **Cloud Run service** runs `gwsa` (the mcp-app App entry
  point). gapp builds the container, deploys with Terraform,
  binds a custom domain, and provisions the SSL certificate.
- **GCS bucket** (managed by gapp) backs the per-user
  profiles directory at `/mnt/data/users` via GCS FUSE.
- **GCP Secret Manager** holds the JWT signing key as a
  gapp-managed secret; gapp injects it into Cloud Run as the
  `SIGNING_KEY` env var.
- **Custom domain (optional)** is bound at deploy time via
  gapp's `domain:` field; the `.run.app` URL keeps working
  in parallel.
- **Auth model:** every MCP and admin request carries a JWT
  signed by the deployment's signing key. `gwsa-admin` mints
  per-user tokens from the same key; `gwsa-admin register`
  packages them into client-specific registration commands.

### Deploy

From a clone of this repo:

```bash
pipx install gapp
gapp init                                       # writes gapp.yaml (already in repo)
gapp setup <your-gcp-project-id>                # one-time
gapp deploy                                     # build + terraform apply
gapp status                                     # service URL
```

The committed `gapp.yaml` declares:
- `public: true` (mcp-app handles its own JWT auth)
- a generated `SIGNING_KEY` secret
- `APP_USERS_PATH={{SOLUTION_DATA_PATH}}/users` (GCS-backed)

A custom domain is opt-in — either edit `gapp.yaml`'s
`domain:` before `gapp deploy`, or do it via CI scalar
overlay (see CONTRIBUTING.md). Leaving it absent serves
on the assigned `.run.app` URL only.

### Post-deploy: connect, register users, verify

Once `gapp status` reports the URL:

```bash
# Fetch signing key (run from this repo so gapp resolves
# the solution from the working directory)
gwsa-admin connect https://<your-cloud-domain> \
  --signing-key "$(gapp secrets get signing-key --plaintext)"

# Probe the deployment end-to-end
gwsa-admin probe

# Add a user and seed their first Google account
gwsa-admin acquire-token \
  --client-secrets /path/to/client_secrets.json |
  gwsa-admin users add me@example.com --token=-

# Generate client registration commands
gwsa-admin register --user me@example.com
```

`gwsa-admin register` emits Claude Code, Gemini CLI, and
Claude.ai registration commands/URLs scoped to that user.
For a multi-account human, add more accounts to the same
user via `gwsa-admin accounts add ...` and pass `account=...`
on per-tool-call MCP invocations to select between them.

### CI/CD

gapp supports GitHub Actions deploys via a reusable
workflow. Pin your deployment workflow to a released gapp
tag and pass `solution-repo`, WIF identity, and any scalar
overlays (e.g. `domain`) as inputs. See the gapp deploy
skill (`plugin:gapp:deploy`) for the full pattern.

### Design background

[Cloud Multi-User Architecture](docs/CLOUD-MULTI-USER.md)
captures the locked design — user/profile/account model,
credential resolution flow, and open Phase 2 questions
(refresh-token rotation cadence, audit logging, BYOC vs.
service-OAuth-client tradeoffs).

## Troubleshooting

**"No active profile" / "User not found":** you haven't run
`gwsa-admin connect local` yet, or you haven't added any accounts.

**"This token was issued by gcloud's well-known OAuth client...":**
pass `--quota-project YOUR_GCP_PROJECT` (or run `gcloud auth
application-default set-quota-project` and re-export the blob).

**Token refresh errors during a CLI call** (`invalid_grant: Bad
Request`): the stored refresh_token died — revoked, expired, or
caught by the Testing-mode 7-day clock. See
[Rotating tokens](#rotating-tokens-when-refresh-fails) for
diagnosis (including how to check the OAuth client's publishing
status) and the exact recovery sequence.

**Old `gwsa profiles` / `gwsa client` / `gwsa setup` commands gone:**
intentional. See [Upgrading from the legacy vault](#upgrading-from-the-legacy-vault).

## Architecture and design

[Cloud Multi-User Architecture](docs/CLOUD-MULTI-USER.md) is the
canonical design doc — covers the user/profile/account model, the
mcp-app framework adoption, the credential resolution flow, and the
phased migration plan from the legacy per-profile vault.

## Release history

See [Release Notes](docs/RELEASE_NOTES.md) for per-version highlights,
breaking changes, and migration steps.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, repo
layout, architecture rules (SDK-first), test conventions, and the
version-management workflow.
