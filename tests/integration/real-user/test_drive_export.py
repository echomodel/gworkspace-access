"""Integration tests for exporting native Google files (issue #55).

Self-contained: creates a scratch multi-tab Sheet and a scratch Doc,
exports them, checks the exports, and trashes both. Proves against the
live API that:

- a multi-tab Sheet exports as XLSX with every tab present;
- a Doc exports as DOCX and as Markdown, with its text;
- download of a native file is refused with the export hint, before
  Drive's own 403.

Needs a configured local gwsa account, like the rest of this suite.
"""

from __future__ import annotations

import io
import re
import time
import zipfile

import pytest

from gwsa.sdk import docs, drive, sheets


def _unique(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def _safe_trash(file_id: str) -> None:
    if not file_id:
        return
    try:
        drive.delete_file(file_id=file_id)
    except Exception:
        pass


@pytest.mark.integration
def test_multi_tab_sheet_exports_as_xlsx_with_every_tab(tmp_path):
    created = sheets.create_spreadsheet(_unique("export-xlsx"), sheet_title="First")
    sheet_id = created["id"]
    try:
        sheets.add_tab(sheet_id, "Second")
        sheets.add_tab(sheet_id, "Third")
        sheets.update_values(sheet_id, "First!A1:B1", [["alpha", 1]])
        sheets.update_values(sheet_id, "Third!A1", [["gamma"]])

        dest = tmp_path / "out.xlsx"
        result = drive.export_file(sheet_id, str(dest), "xlsx")
        assert result["format"] == "xlsx"
        assert result["size"] == dest.stat().st_size > 0

        with zipfile.ZipFile(dest) as book:
            workbook = book.read("xl/workbook.xml").decode("utf-8")
            # Cell text sits in sharedStrings.xml or inline in the sheets.
            cells = "".join(
                book.read(n).decode("utf-8") for n in book.namelist()
                if n.startswith("xl/") and n.endswith(".xml"))
        tabs = re.findall(r'<sheet [^>]*name="([^"]+)"', workbook)
        assert tabs == ["First", "Second", "Third"]
        assert "alpha" in cells and "gamma" in cells

        # In memory, the same export, named with the extension.
        fetched = drive.export_bytes(sheet_id, "xlsx")
        assert fetched["name"].endswith(".xlsx")
        assert zipfile.is_zipfile(io.BytesIO(fetched["data"]))
    finally:
        _safe_trash(sheet_id)


@pytest.mark.integration
def test_doc_exports_as_docx_and_markdown(tmp_path):
    marker = _unique("export-doc-marker")
    created = docs.create_document(_unique("export-doc"), body_text=f"{marker}\n")
    doc_id = created["id"]
    try:
        dest = tmp_path / "out.docx"
        drive.export_file(doc_id, str(dest), "docx")
        with zipfile.ZipFile(dest) as package:
            assert marker in package.read("word/document.xml").decode("utf-8")

        md = drive.export_bytes(doc_id, "md")
        assert md["mime_type"] == "text/markdown"
        assert marker in md["data"].decode("utf-8")

        # The string read in the Docs SDK runs on the same mapping.
        assert marker in docs.get_document_markdown(doc_id)
    finally:
        _safe_trash(doc_id)


@pytest.mark.integration
def test_download_of_native_file_is_refused_with_export_hint(tmp_path):
    created = sheets.create_spreadsheet(_unique("export-refuse"))
    sheet_id = created["id"]
    try:
        with pytest.raises(drive.NativeFileDownloadError) as exc:
            drive.download_file(sheet_id, str(tmp_path / "x"))
        assert "gwsa drive export" in str(exc.value)
        assert "xlsx" in exc.value.available
    finally:
        _safe_trash(sheet_id)
