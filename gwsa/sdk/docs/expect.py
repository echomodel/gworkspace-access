"""The shape of a ``batch_update`` request item and its ``expect`` key.

A request item is a Docs API request object (exactly one request type, sent
to Google unchanged) plus, when the request addresses an index, an
``expect`` key stating what is at that position. gwsa checks ``expect``
against the document and removes it before sending.

These types are the single definition of that shape: the MCP tool publishes
them as its parameter schema, and the expectation check takes its list of
valid keys from :class:`Expect`.
"""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field
from typing_extensions import TypedDict


class Expect(TypedDict, total=False):
    """What is at a request's position when it runs (see ``batch_update_doc``)."""

    __pydantic_config__ = ConfigDict(extra="forbid")

    text: Annotated[str, Field(
        description="Exact content of the request's range (startIndex..endIndex).")]
    element: Annotated[Literal["paragraph", "table"], Field(
        description="The range is exactly one whole paragraph or one whole table.")]
    before: Annotated[str, Field(
        description="Text immediately before the request's position.")]
    after: Annotated[str, Field(
        description="Text immediately after the request's position.")]
    unchecked: Annotated[bool, Field(
        description="true skips the check for this one request.")]


class DocsRequest(TypedDict, total=False):
    """A Docs API request object plus an optional ``expect``.

    Every key other than ``expect`` is the Docs API request type (e.g.
    ``insertText``) and is sent to Google unchanged.
    """

    __pydantic_config__ = ConfigDict(extra="allow")

    expect: Annotated[Expect, Field(
        description="Required when the request addresses an index: what is at "
                    "that position. Checked by gwsa and removed before sending.")]


#: Keys an ``expect`` may use.
EXPECTATION_KEYS = frozenset(Expect.__annotations__)

#: Values accepted by ``expect.element``.
ELEMENT_KINDS = ("paragraph", "table")
