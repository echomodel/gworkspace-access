# TODO

## Open Items

### Refactor MCP Tools to Return Objects Instead of JSON Strings

**Priority:** Medium

The current MCP server tools manually serialize responses using `json.dumps()` and return strings. This can cause formatting issues in Claude. FastMCP supports returning objects directly, which it serializes properly.

**Current Pattern (problematic):**
```python
@mcp.tool()
async def search_emails(...) -> str:
    return json.dumps({"messages": messages}, indent=2)  # Creates literal \n
```

**Recommended Pattern:**
```python
@mcp.tool()
async def search_emails(...) -> dict:
    return {"messages": messages}  # FastMCP handles serialization
```

**Files:** `gwsa/mcp/server.py` - All 12 tool functions

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

### Add Google Drive Tools to MCP Server

**Priority:** Future

Extend MCP server with Google Drive capabilities:

| Tool | Description |
|------|-------------|
| `drive_search` | Search for files/folders |
| `drive_list_folder` | List contents of a folder |
| `drive_create_folder` | Create a new folder |
| `drive_upload` | Upload a file |
| `drive_download` | Download a file |

**Requires:** SDK layer in `gwsa/sdk/drive.py` first, then MCP tools.

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

- ✅ Implement `gwsa client import` / `gwsa client show` commands
- ✅ Remove `--client-creds` from profiles add/refresh
- ✅ Add `profiles rename` command
- ✅ Enhance 403 error message in MCP server for Google Docs
- ✅ Validate MCP server prerequisites in documentation
- ✅ CLI command cleanup (`gwsa setup` → `gwsa status`, profiles commands)
- ✅ Add unit tests for profiles/client CLI validation
- ✅ Update all docs with new client import workflow
