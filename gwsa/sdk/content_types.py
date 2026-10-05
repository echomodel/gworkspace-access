"""Content type of a file, from its name.

Python's ``mimetypes`` table depends on the Python version and the host
(``/etc/mime.types``): older Pythons and slim container images don't know
``.yaml`` or ``.md``, so the same file would upload as
``application/octet-stream`` on a server and as text on a laptop. gwsa
resolves the types it relies on — text formats it returns as text and
formats Drive converts — from this fixed table first, and falls back to
``mimetypes`` for everything else.
"""

from __future__ import annotations

import mimetypes
import os
from typing import Optional

#: Extensions gwsa must resolve the same way on every host.
_KNOWN = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".toml": "application/toml",
    ".xml": "application/xml",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def guess_content_type(name: Optional[str]) -> Optional[str]:
    """The content type for a file name, or ``None`` if unknown."""
    if not name:
        return None
    ext = os.path.splitext(name)[1].lower()
    if ext in _KNOWN:
        return _KNOWN[ext]
    guessed, _ = mimetypes.guess_type(name)
    return guessed
