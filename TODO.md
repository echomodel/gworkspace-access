### Enhance 403 Error Message in MCP Server for Google Docs

**Description:**
When the `gwsa-mcp` server's `read_doc` tool encounters an `HttpError` with a 403 status code (Permission Denied) from the Google Docs API, the error message returned to the MCP client should be more informative. It should explicitly suggest that the user check their `gwsa` profile for correct permissions.

**Location:**
`gwsa/mcp/server.py`, within the `read_doc` async function.

**Proposed Change:**
Modify the `read_doc` function's exception handling to specifically catch `HttpError` (importing it from `googleapiclient.errors`). If the error status is 403, return a custom error message that includes a hint about checking/switching `gwsa` profiles.

**Code Snippet (to be applied in `gwsa/mcp/server.py`):**

```python
# Add this import at the top of the file
from googleapiclient.errors import HttpError
# ... other imports ...

@mcp.tool()
async def read_doc(doc_id: str, format: str = "content") -> str:
    """
    Read a Google Doc by ID.
    # ... (existing docstring) ...
    """
    try:
        if format == "text":
            text = docs.get_document_text(doc_id)
            return json.dumps({"text": text}, indent=2)
        elif format == "raw":
            doc = docs.get_document(doc_id)
            return json.dumps(doc, indent=2)
        else:
            content = docs.get_document_content(doc_id)
            return json.dumps(content, indent=2)
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error reading doc: {e}")
            return json.dumps({
                "error": "The caller does not have permission.",
                "details": str(e),
                "hint": "The active gwsa profile may not have access to this document. "
                        "Try switching profiles with the `switch_profile` tool or "
                        "running `gwsa setup --new-user` to re-authenticate."
            })
        raise  # Re-raise other HttpErrors
    except Exception as e:
        logger.error(f"Error reading doc: {e}")
        return json.dumps({"error": str(e)})
```

**Reasoning:**
Currently, a 403 error for Google Docs results in a generic "The caller does not have permission" message. This can be unhelpful for users, as the most common cause in an MCP setup is an incorrect or unauthenticated `gwsa` profile. By adding a specific hint to check profiles, the user can more quickly diagnose and resolve the issue.
