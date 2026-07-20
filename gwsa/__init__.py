"""GWSA - Google Workspace Access.

Namespace package containing:
- gwsa.sdk: Core SDK for programmatic access to Google Workspace APIs
- gwsa.cli: Command-line interface
- gwsa.mcp: Model Context Protocol server for LLM integration
"""

from typing import Optional

from pydantic import BaseModel, Field

from mcp_app import App

from gwsa.mcp.tools import accounts as accounts_tools
from gwsa.mcp.tools import calendar as calendar_tools
from gwsa.mcp.tools import chat as chat_tools
from gwsa.mcp.tools import docs as docs_tools
from gwsa.mcp.tools import drive as drive_tools
from gwsa.mcp.tools import mail as mail_tools
from gwsa.mcp.tools import sheets as sheets_tools


__version__ = "0.25.0"


class GoogleAccount(BaseModel):
    """A single Google identity owned by the human user.

    Field descriptions drive ``gwsa-admin users add --help`` output, which
    is the re-discovery path for operators returning to the app months
    after initial setup. Keep descriptions explicit and specific.
    """

    name: str = Field(
        description=(
            "Friendly handle for this account ('personal', 'work', etc.). "
            "Alphanumeric, hyphen, underscore. 1-32 chars."
        )
    )
    email: str = Field(
        description="The Google account email, as reported by tokeninfo."
    )
    token: dict = Field(
        description=(
            "Google authorized_user blob (refresh_token, access_token, scopes, "
            "client_id, client_secret, token_uri, ...). Stored opaquely so it "
            "round-trips through google-auth-python's "
            "Credentials.from_authorized_user_info() without schema drift. "
            "Steady-state refresh is fully automatic (refresh_token + "
            "client_secret + token_uri are all in the blob); re-acquisition "
            "after the refresh_token dies is a manual operator step (browser "
            "flow or `gcloud auth application-default login` depending on "
            "which client_id the blob carries)."
        )
    )
    quota_project: Optional[str] = Field(
        default=None,
        description=(
            "GCP project billed for API usage (sets x-goog-user-project). "
            "Required for tokens issued by gcloud's well-known OAuth client "
            "(which has no host project of its own). Optional for user-owned "
            "OAuth clients (defaults to the OAuth client's host project; pass "
            "to redirect billing elsewhere)."
        ),
    )


class Profile(BaseModel):
    """One human user's profile.

    Contains the list of Google accounts this human owns plus a pointer
    to the default account used when a tool or CLI invocation doesn't
    specify one explicitly.

    See docs/CLOUD-MULTI-USER.md for the architectural rationale —
    one mcp-app user record per human, multiple Google identities
    inside the profile, account selection via per-tool-call argument.
    """

    accounts: list[GoogleAccount] = Field(
        default_factory=list,
        description="Google identities this human owns.",
    )
    default_account: Optional[str] = Field(
        default=None,
        description=(
            "Name of the account used when a tool/CLI omits an explicit "
            "account selector. Set via `gwsa-admin accounts use <name>`."
        ),
    )


app = App(
    name="gwsa",
    tools_modules=[
        accounts_tools,
        mail_tools,
        docs_tools,
        drive_tools,
        chat_tools,
        calendar_tools,
        sheets_tools,
    ],
    profile_model=Profile,
    profile_expand=False,
)

# Extend the framework's admin CLI with gwsa-specific subgroups.
# mcp-app's App constructor doesn't (yet) take admin extensions as a
# declarative arg, so we attach them imperatively at import time. The
# entry-point `gwsa-admin = "gwsa:app.admin_cli"` resolves after this
# module has finished loading, so by the time Click runs, the extra
# commands are in place. If mcp-app grows an `admin_commands=[...]`
# arg upstream, the line below becomes that arg and this comment goes
# away.
from gwsa.admin import accounts_group, acquire_token, migrate  # noqa: E402

app.admin_cli.add_command(accounts_group)
app.admin_cli.add_command(acquire_token)
app.admin_cli.add_command(migrate)
