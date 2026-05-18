"""gwsa-admin extensions.

Exposes Click commands/groups that the App composition root hangs off
the framework's admin CLI. See ``gwsa.__init__`` for the wiring.
"""

from gwsa.admin.accounts import accounts_group
from gwsa.admin.acquire_token import acquire_token
from gwsa.admin.migrate import migrate

__all__ = ["accounts_group", "acquire_token", "migrate"]
