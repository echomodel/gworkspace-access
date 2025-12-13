# TODO

## Open Items

### Google Docs API 500 Error on Shared Documents

**Priority:** High (Blocking)
**Discovered:** 2025-12-12

**Issue:** The Google Docs API returns a 500 Internal Server Error when attempting to write to a document that:
- Is shared with the user for editing (user can edit via browser)
- Is NOT owned by the user
- Location unclear (may be on another user's My Drive or corporate shared drive)

**Workaround:** Copy the document to the user's own My Drive. API writes succeed on the copy.

**Impact:** This significantly limits gwsa usefulness for work-related documents, which are often:
- Centrally located on shared drives
- Owned by other users or service accounts
- Shared for collaboration with varying permissions

**To Investigate:**
- [ ] Reproduce with specific document types/locations
- [ ] Check if this is a Shared Drive vs My Drive issue
- [ ] Check if this is an ownership/permission issue
- [ ] Check Google API documentation for limitations
- [ ] Consider error handling to detect this case and provide clear guidance

---

### Local Markdown ↔ Google Docs Workflow

**Priority:** Medium (Feature Request)

**Concept:** Enable working locally with markdown files (fast, agent-friendly) and syncing to Google Docs when ready.

**Use Cases:**
- Draft documents locally with CLI tools / AI agents
- Push to Google Docs for sharing/collaboration
- Pull from Google Docs for local editing
- Avoid slow browser-based editing for content creation

**Design Considerations:**
- Format compatibility: Markdown ↔ Google Docs (via pandoc or native conversion)
- Two-way sync vs one-way push
- Conflict resolution
- Metadata preservation (comments, suggestions, formatting)

**Potential Implementation:**
```python
from gwsa.sdk import docs

# Push local markdown to new doc
docs.create_from_markdown("local.md", title="My Document")

# Push to existing doc (replace content)
docs.update_from_markdown(doc_id, "local.md")

# Pull doc to local markdown
docs.export_to_markdown(doc_id, "local.md")
```

**Note:** This feature is partly blocked by the 500 error issue above for shared documents.

---

### Add User Identity Metadata to MCP Tool Outputs

**Priority:** Low

MCP tool responses could include the active user profile (email) to improve transparency. The LLM can then confirm which identity is performing an action.

```python
def _get_profile_metadata():
    profile = profiles.get_active_profile()
    return {"active_profile": {"name": profile.get("name"), "email": profile.get("email")}}

# Add to each tool response
result.update(_get_profile_metadata())
```

---

### ~~Add Google Drive Tools to MCP Server~~ (DONE - v0.4.0)

**Status:** Implemented

Implemented in v0.4.0:
- ✅ `drive_list_folder` - List contents of a folder
- ✅ `drive_create_folder` - Create a new folder
- ✅ `drive_upload` - Upload a file
- ✅ `drive_find_folder` - Find folder by path

**Remaining (future):**
- `drive_search` - Search for files/folders by query
- `drive_download` - Download a file

---

### Investigate MCP Server Status/Metadata Reporting

**Priority:** Low

Explore whether MCP provides mechanisms for servers to report status that clients display in their UI. Could help users see which gwsa profile is active without calling a tool.

---

### MCP Architecture Review

**Priority:** Low

As tool count grows, consider splitting `gwsa/mcp/server.py` into modules (e.g., `mail_tools.py`, `docs_tools.py`). Investigate if FastMCP supports a router/blueprint pattern.

---

## Deferred Design Considerations

These items were considered during the CLI cleanup but deferred for future reconsideration:

### Email-Based Profile Identity

Currently profiles use arbitrary names (`default`, `work`). An alternative would be email-based identity where the OAuth result determines the profile name. This would prevent duplicate emails but lose custom naming. **Deferred** - current name-based design works.

### Duplicate Email Detection

`profiles add` allows creating multiple profiles with the same email. Could add a warning or `--allow-duplicate` flag. **Deferred** - if email-based profiles are implemented later, this resolves naturally.

### "Token Profile" Terminology

The term "token profile" is misleading (ADC also uses tokens). Better terms might be "OAuth profile" vs "ADC profile". **Deferred** - current terminology works.

---

## Completed (Recently)

- ✅ Refactor MCP tools to return objects instead of JSON strings (14 tools updated)
- ✅ Implement `gwsa client import` / `gwsa client show` commands
- ✅ Remove `--client-creds` from profiles add/refresh
- ✅ Add `profiles rename` command
- ✅ Enhance 403 error message in MCP server for Google Docs
- ✅ Validate MCP server prerequisites in documentation
- ✅ CLI command cleanup (`gwsa setup` → `gwsa status`, profiles commands)
- ✅ Add unit tests for profiles/client CLI validation
- ✅ Update all docs with new client import workflow
