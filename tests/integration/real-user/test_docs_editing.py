"""Live integration tests for guarded Google Docs editing.

Self-contained: each test builds its own rich scratch document (two tabs,
a header, a heading, a nested list, an emoji, a person chip, a date chip,
a 2x2 table) and trashes it afterwards.

Proves against the real API that:
- the position map accounts for every index of every segment,
- a wrong position is refused and nothing is written,
- correct guarded edits change exactly the targeted paragraph,
- edits work in table cells, headers, and other tabs, around emoji,
- an exact copy matches its original, and edits to it leave the original
  untouched,
- Google's exports include every tab.
"""

from __future__ import annotations

import time

import pytest

from gwsa.sdk import docs, drive
from gwsa.sdk.docs import positions
from gwsa.sdk.docs.service import get_docs_service
from gwsa.sdk.drive.service import get_drive_service


def _safe_trash(file_id):
    if not file_id:
        return
    try:
        drive.delete_file(file_id=file_id)
    except Exception:
        pass


def _raw(svc, doc_id, reqs):
    return svc.documents().batchUpdate(documentId=doc_id, body={"requests": reqs}).execute()


def _body(doc, i=0):
    return doc["tabs"][i]["documentTab"]["body"]["content"]


def _para(doc, needle, i=0):
    for el in _body(doc, i):
        if "paragraph" in el and needle in "".join(
            r.get("textRun", {}).get("content", "") for r in el["paragraph"]["elements"]
        ):
            return el
    raise AssertionError(needle)


def _build_rich_doc() -> dict:
    """Create the scratch document using raw API calls (setup only)."""
    svc = get_docs_service()
    me = get_drive_service().about().get(fields="user(emailAddress)").execute()["user"]["emailAddress"]
    doc_id = svc.documents().create(body={"title": f"gwsa-it-docs-{int(time.time()*1000)}"}).execute()["documentId"]
    get = lambda: docs.get_document(doc_id)
    end = lambda: _body(get())[-1]["endIndex"] - 1

    _raw(svc, doc_id, [{"insertText": {"location": {"index": 1}, "text":
        "Plan heading\nIntro with emoji 🙂 here.\nAlpha\n\tBeta nested\nGamma\nMeeting with "}}])
    d = get()
    h, a, g = _para(d, "Plan heading"), _para(d, "Alpha"), _para(d, "Gamma")
    _raw(svc, doc_id, [
        {"createParagraphBullets": {"range": {"startIndex": a["startIndex"], "endIndex": g["endIndex"]},
                                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}},
        {"updateParagraphStyle": {"range": {"startIndex": h["startIndex"], "endIndex": h["endIndex"]},
                                  "paragraphStyle": {"namedStyleType": "HEADING_1"},
                                  "fields": "namedStyleType"}}])
    m = _para(get(), "Meeting with")
    _raw(svc, doc_id, [{"deleteParagraphBullets": {"range": {"startIndex": m["startIndex"], "endIndex": m["endIndex"]}}}])
    _raw(svc, doc_id, [{"insertPerson": {"personProperties": {"email": me}, "location": {"index": end()}}}])
    _raw(svc, doc_id, [{"insertText": {"location": {"index": end()}, "text": " on "}}])
    _raw(svc, doc_id, [{"insertDate": {"dateElementProperties": {"timestamp": "2026-10-03T15:00:00Z"},
                                       "location": {"index": end()}}}])
    _raw(svc, doc_id, [{"insertText": {"location": {"index": end()}, "text": "\nBefore table\n"}}])
    _raw(svc, doc_id, [{"insertTable": {"rows": 2, "columns": 2, "endOfSegmentLocation": {"segmentId": ""}}}])
    tbl = [el for el in _body(get()) if "table" in el][0]["table"]
    cells = [c for r in tbl["tableRows"] for c in r["tableCells"]]
    _raw(svc, doc_id, [{"insertText": {"location": {"index": c["content"][0]["startIndex"]}, "text": t}}
                       for c, t in sorted(zip(cells, ["Fruit", "Qty", "Apples", "3"]),
                                          key=lambda x: -x[0]["content"][0]["startIndex"])])
    _raw(svc, doc_id, [{"insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": "After table"}}])
    header_id = _raw(svc, doc_id, [{"createHeader": {"type": "DEFAULT"}}])["replies"][0]["createHeader"]["headerId"]
    _raw(svc, doc_id, [{"insertText": {"location": {"segmentId": header_id, "index": 0}, "text": "Header text"}}])
    tab2 = _raw(svc, doc_id, [{"addDocumentTab": {"tabProperties": {"title": "Second Tab"}}}])[
        "replies"][0]["addDocumentTab"]["tabProperties"]["tabId"]
    _raw(svc, doc_id, [{"insertText": {"location": {"index": 1, "tabId": tab2},
                                       "text": "Second tab text.\nPlan heading again"}}])
    return {"id": doc_id, "tab2": tab2, "header": header_id}


@pytest.fixture(scope="module")
def base_doc():
    """Built once per run (the Docs API allows ~60 writes/minute/user)."""
    info = _build_rich_doc()
    yield info
    _safe_trash(info["id"])


@pytest.fixture
def rich_doc(base_doc):
    """A fresh Drive copy of the base document for each test."""
    copy_id = drive.copy_file(base_doc["id"], name=f"gwsa-it-docs-{int(time.time()*1000)}")["id"]
    doc = docs.get_document(copy_id)
    tab = doc["tabs"][0]["documentTab"]
    info = {
        "id": copy_id,
        "tab2": doc["tabs"][1]["tabProperties"]["tabId"],
        "header": next(iter(tab["headers"])),
    }
    yield info
    _safe_trash(copy_id)


def _one(doc_id, text, **kw):
    m = docs.find_in_document(doc_id, text, **kw)["matches"]
    assert len(m) == 1, (text, m)
    return m[0]


def _write(doc_id, requests, expectations=None, dry_run=False):
    """batch_update with the revision id of a fresh read, as a caller would."""
    rev = docs.get_document(doc_id)["revisionId"]
    return docs.batch_update(doc_id, requests, expectations, rev, None, dry_run)


def _lines(doc_id):
    """Map lines without index prefixes, per segment (for content equality)."""
    out = []
    for seg in docs.get_document_map(doc_id)["segments"]:
        out.append((seg["segment"], [ln.split(" ", 1)[1] for ln in seg["lines"]]))
    return out


@pytest.mark.integration
def test_map_accounts_for_every_index(rich_doc):
    doc = docs.get_document(rich_doc["id"])
    segs = positions.build_segments(doc)
    assert [s.kind for s in segs] == ["body", "header", "body"]
    for seg in segs:
        assert seg.unmapped == [], seg.label
        assert len(seg.unit_list()) == seg.end - seg.start
        covered = set()
        for ln in seg.lines:
            covered.update(range(ln.start, ln.end))
        assert covered == set(range(seg.start, seg.end)), seg.label
    body = segs[0].render()
    assert any("[HEADING_1] Plan heading⏎" in ln for ln in body)
    assert any("[list L1] Beta nested⏎" in ln for ln in body)
    assert any("Meeting with ⟦person⟧ on ⟦date⟧⏎" in ln for ln in body)
    assert any("[cell 1,0] Apples⏎" in ln for ln in body)


@pytest.mark.integration
def test_wrong_position_is_refused_and_nothing_written(rich_doc):
    did = rich_doc["id"]
    m = _one(did, "Plan heading", tab_id="t.0")
    before = docs.get_document(did)["revisionId"]
    for off in (1, -1):
        with pytest.raises(docs.ExpectationError):
            _write(did, [{"deleteContentRange": {"range": {
                "startIndex": m["start"] + off, "endIndex": m["end"] + off}}}],
                [{"text": "Plan heading"}])
    with pytest.raises(docs.ExpectationError):
        chip = _one(did, "⟦person⟧")
        _write(did, [{"deleteContentRange": {"range": {
            "startIndex": chip["start"], "endIndex": chip["end"] + 3}}}],
            [{"text": "Meet"}])
    assert docs.get_document(did)["revisionId"] == before


@pytest.mark.integration
def test_guarded_edit_changes_only_the_target(rich_doc):
    did = rich_doc["id"]
    m = _one(did, "Gamma")
    before = _lines(did)
    out = _write(did, [
        {"deleteContentRange": {"range": {"startIndex": m["start"], "endIndex": m["end"]}}},
        {"insertText": {"location": {"index": m["start"]}, "text": "Gamma ray"}},
    ], [{"text": "Gamma"}, {"after": "\n"}])
    assert len(out["changes"]) == 1
    assert out["changes"][0]["after"][0].endswith("[list L0] Gamma ray⏎")
    after = _lines(did)
    diffs = [(seg, i) for (seg, a), (_, b) in zip(before, after)
             for i, (x, y) in enumerate(zip(a, b)) if x != y]
    assert len(diffs) == 1
    assert len(before[0][1]) == len(after[0][1])


@pytest.mark.integration
def test_edits_around_emoji_in_table_header_and_second_tab(rich_doc):
    did, tab2, hid = rich_doc["id"], rich_doc["tab2"], rich_doc["header"]
    here = _one(did, "here.")
    cell = _one(did, "Apples")
    head = _one(did, "Header text")
    t2 = _one(did, "Second tab", tab_id=tab2)
    out = _write(did, [
        {"deleteContentRange": {"range": {"startIndex": cell["start"], "endIndex": cell["end"]}}},
        {"insertText": {"location": {"index": cell["start"]}, "text": "Pears"}},
        {"insertText": {"location": {"index": here["end"]}, "text": "!"}},
        {"insertText": {"location": {"index": head["start"], "segmentId": hid}, "text": "My "}},
        {"insertText": {"location": {"index": t2["start"], "tabId": tab2}, "text": "The "}},
    ], [
        {"text": "Apples"}, {"after": "\n"},
        {"before": "🙂 here."},
        {"after": "Header"},
        {"after": "Second"},
    ])
    md = docs.get_document_map(did)
    flat = [ln for seg in md["segments"] for ln in seg["lines"]]
    assert any(ln.endswith("Intro with emoji 🙂 here.!⏎") for ln in flat)
    assert any(ln.endswith("[cell 1,0] Pears⏎") for ln in flat)
    assert any(ln.endswith("My Header text⏎") for ln in flat)
    assert any(ln.endswith("The Second tab text.⏎") for ln in flat)
    assert len(out["changes"]) == 4


@pytest.mark.integration
def test_unpositioned_requests_append_and_scoped_replace(rich_doc):
    did, tab2 = rich_doc["id"], rich_doc["tab2"]
    out = _write(did, [
        {"insertText": {"endOfSegmentLocation": {"tabId": tab2}, "text": "\nAppended line"}},
        {"replaceAllText": {"containsText": {"text": "Plan heading", "matchCase": True},
                            "replaceText": "Plan title", "tabsCriteria": {"tabIds": [tab2]}}},
    ])
    assert out["replies"][1]["replaceAllText"]["occurrencesChanged"] == 1
    assert len(docs.find_in_document(did, "Plan heading")["matches"]) == 1
    assert _one(did, "Appended line", tab_id=tab2)


@pytest.mark.integration
def test_style_new_text_in_follow_up_call(rich_doc):
    did = rich_doc["id"]
    after = _one(did, "After table")
    _write(did, [{"insertText": {"location": {"index": after["end"]}, "text": "\nNew section"}}],
                      [{"before": "After table"}])
    new = _one(did, "New section")
    _write(did, [{"updateParagraphStyle": {
        "range": {"startIndex": new["start"], "endIndex": new["end"]},
        "paragraphStyle": {"namedStyleType": "HEADING_2"}, "fields": "namedStyleType"}}],
        [{"text": "New section"}])
    lines = docs.get_document_map(did)["segments"][0]["lines"]
    assert any(ln.endswith("[HEADING_2] New section⏎") for ln in lines)


@pytest.mark.integration
def test_insert_and_style_in_one_call(rich_doc):
    did = rich_doc["id"]
    after = _one(did, "After table")
    start = after["end"] + 1  # after the inserted "\n"
    _write(did, [
        {"insertText": {"location": {"index": after["end"]}, "text": "\nNext steps"}},
        {"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": start + 10},
                                  "paragraphStyle": {"namedStyleType": "HEADING_2"},
                                  "fields": "namedStyleType"}},
    ], [{"before": "After table"}, {"text": "Next steps"}])
    lines = docs.get_document_map(did)["segments"][0]["lines"]
    assert any(ln.endswith("[HEADING_2] Next steps⏎") for ln in lines)
    assert any(ln.endswith("After table⏎") and "HEADING" not in ln for ln in lines)


@pytest.mark.integration
def test_nested_outline_bullets_and_style_in_one_call(rich_doc):
    """createParagraphBullets removes leading tabs; positions after it are
    replayed exactly, so styling text after the bullets lands precisely."""
    did = rich_doc["id"]
    after = _one(did, "After table")
    p0 = after["end"] + 1
    text = "\nShip v2\n\tWrite notes\nPlan v3"
    body = text[1:]
    tab_ix = body.index("\t")
    write_notes = p0 + tab_ix          # after the tab is removed
    out = _write(did, [
        {"insertText": {"location": {"index": after["end"]}, "text": text}},
        {"createParagraphBullets": {"range": {"startIndex": p0, "endIndex": p0 + len(body)},
                                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}},
        {"updateTextStyle": {"range": {"startIndex": write_notes, "endIndex": write_notes + 11},
                             "textStyle": {"bold": True}, "fields": "bold"}},
    ], [{"before": "After table"}, {"text": body}, {"text": "Write notes"}])
    lines = docs.get_document_map(did)["segments"][0]["lines"]
    assert any(ln.endswith("[list L0] Ship v2⏎") for ln in lines)
    assert any(ln.endswith("[list L1] Write notes⏎") for ln in lines)
    raw = docs.get_document(did)
    bold = [pe["textRun"]["content"] for el in raw["tabs"][0]["documentTab"]["body"]["content"]
            for pe in el.get("paragraph", {}).get("elements", [])
            if pe.get("textRun", {}).get("textStyle", {}).get("bold")]
    # Google extends a whole-paragraph style to the paragraph's newline.
    assert [b.rstrip("\n") for b in bold] == ["Write notes"], bold


@pytest.mark.integration
def test_stale_revision_is_refused(rich_doc):
    did = rich_doc["id"]
    old = docs.get_document(did)["revisionId"]
    _write(did, [{"insertText": {"endOfSegmentLocation": {}, "text": "\nx"}}])
    m = _one(did, "Plan heading", tab_id="t.0")
    with pytest.raises(docs.DocumentChangedError):
        docs.batch_update(did, [{"deleteContentRange": {"range": {
            "startIndex": m["start"], "endIndex": m["end"]}}}],
            [{"text": "Plan heading"}], required_revision_id=old)


def _range_of(doc_id, predicate):
    """(start, end) of the first body map line matching ``predicate``."""
    for ln in docs.get_document_map(doc_id)["segments"][0]["lines"]:
        if predicate(ln):
            s, e = ln.split(" ", 1)[0].split("-")
            return int(s), int(e)
    raise AssertionError("no matching map line")


@pytest.mark.integration
def test_missing_revision_is_refused_and_nothing_written(rich_doc):
    did = rich_doc["id"]
    before = docs.get_document(did)["revisionId"]
    with pytest.raises(ValueError, match="required_revision_id is required"):
        docs.batch_update(did, [{"insertText": {"endOfSegmentLocation": {}, "text": "\nx"}}])
    assert docs.get_document(did)["revisionId"] == before


@pytest.mark.integration
def test_delete_whole_table_by_element(rich_doc):
    did = rich_doc["id"]
    t0, _ = _range_of(did, lambda ln: "[table " in ln)
    _, t1 = _range_of(did, lambda ln: "[table end]" in ln)
    with pytest.raises(docs.ExpectationError, match="one whole table"):
        _write(did, [{"deleteContentRange": {"range": {"startIndex": t0, "endIndex": t1 - 1}}}],
               [{"element": "table"}])
    _write(did, [{"deleteContentRange": {"range": {"startIndex": t0, "endIndex": t1}}}],
           [{"element": "table"}])
    lines = docs.get_document_map(did)["segments"][0]["lines"]
    assert not any("⟦table⟧" in ln or "Apples" in ln for ln in lines)
    assert any(ln.endswith("After table⏎") for ln in lines)


@pytest.mark.integration
def test_delete_whole_paragraph_by_element_and_shift_is_refused(rich_doc):
    did = rich_doc["id"]
    s, e = _range_of(did, lambda ln: ln.endswith("Before table⏎"))
    before = docs.get_document(did)["revisionId"]
    with pytest.raises(docs.ExpectationError, match=f"the paragraph containing {s + 1} is {s}-{e}"):
        _write(did, [{"deleteContentRange": {"range": {"startIndex": s + 1, "endIndex": e + 1}}}],
               [{"element": "paragraph"}])
    assert docs.get_document(did)["revisionId"] == before
    _write(did, [{"deleteContentRange": {"range": {"startIndex": s, "endIndex": e}}}],
           [{"element": "paragraph"}])
    assert not docs.find_in_document(did, "Before table")["matches"]


@pytest.mark.integration
def test_expectation_copied_from_the_map_with_glyph(rich_doc):
    did = rich_doc["id"]
    s, e = _range_of(did, lambda ln: ln.endswith("Before table⏎"))
    out = _write(did, [{"updateTextStyle": {"range": {"startIndex": s, "endIndex": e},
                                            "textStyle": {"italic": True}, "fields": "italic"}}],
                 [{"text": "Before table⏎"}])
    assert out["revision_id"] != out["previous_revision_id"]


@pytest.mark.integration
def test_dry_run_writes_nothing_and_predicts_the_change(rich_doc):
    did = rich_doc["id"]
    m = _one(did, "Gamma")
    before = docs.get_document(did)["revisionId"]
    reqs = [{"deleteContentRange": {"range": {"startIndex": m["start"], "endIndex": m["end"]}}},
            {"insertText": {"location": {"index": m["start"]}, "text": "Delta"}}]
    exps = [{"text": "Gamma"}, {"after": "\n"}]
    pv = _write(did, reqs, exps, dry_run=True)
    assert pv["dry_run"] is True and pv["revision_id"] == before
    assert docs.get_document(did)["revisionId"] == before
    assert pv["changes"][0]["after"][0].endswith("Delta⏎")
    out = _write(did, reqs, exps)
    assert out["changes"][0]["after"][0].endswith("[list L0] Delta⏎")


@pytest.mark.integration
def test_two_call_styled_append_recipe(rich_doc):
    """The documented recipe: append with a leading newline, then style the
    new paragraph using call 1's change-report range and revision id."""
    did = rich_doc["id"]
    rev0 = docs.get_document(did)["revisionId"]
    out1 = docs.batch_update(did, [{"insertText": {"endOfSegmentLocation": {"tabId": "t.0"},
                                                   "text": "\nAppendix heading"}}], None, rev0)
    new_line = next(ln for ch in out1["changes"] for ln in ch["after"]
                    if ln.endswith("Appendix heading⏎"))
    s, e = (int(x) for x in new_line.split(" ", 1)[0].split("-"))
    docs.batch_update(did, [{"updateParagraphStyle": {
        "range": {"startIndex": s, "endIndex": e},
        "paragraphStyle": {"namedStyleType": "HEADING_2"}, "fields": "namedStyleType"}}],
        [{"element": "paragraph"}], out1["revision_id"])
    lines = docs.get_document_map(did)["segments"][0]["lines"]
    assert any(ln.endswith("[HEADING_2] Appendix heading⏎") for ln in lines)
    assert any(ln.endswith("After table⏎") and "HEADING" not in ln for ln in lines)


@pytest.mark.integration
def test_append_without_leading_newline_joins_last_paragraph(rich_doc):
    """Why the recipe starts the appended text with a newline."""
    did = rich_doc["id"]
    _write(did, [{"insertText": {"endOfSegmentLocation": {"tabId": "t.0"}, "text": " more"}}])
    lines = docs.get_document_map(did)["segments"][0]["lines"]
    assert lines[-1].endswith("After table more⏎")


@pytest.mark.integration
def test_copy_is_exact_and_edits_leave_original_untouched(rich_doc):
    did = rich_doc["id"]
    copy_id = None
    try:
        copy_id = drive.copy_file(did, name=f"gwsa-it-docs-copy-{int(time.time()*1000)}")["id"]
        assert _lines(copy_id) == _lines(did)
        m = _one(copy_id, "Beta nested")
        _write(copy_id, [
            {"deleteContentRange": {"range": {"startIndex": m["start"], "endIndex": m["end"]}}},
            {"insertText": {"location": {"index": m["start"]}, "text": "Beta changed"}},
        ], [{"text": "Beta nested"}, {"after": "\n"}])
        orig, cp = _lines(did), _lines(copy_id)
        assert orig != cp
        assert any("[list L1] Beta changed⏎" in ln for ln in cp[0][1])
        assert any("[list L1] Beta nested⏎" in ln for ln in orig[0][1])
    finally:
        _safe_trash(copy_id)


@pytest.mark.integration
def test_exports_include_every_tab_and_render_chips(rich_doc):
    md = docs.get_document_markdown(rich_doc["id"])
    assert "Second Tab" in md and "Second tab text." in md
    assert "Oct 3, 2026" in md
    assert "| Fruit | Qty |" in md
    txt = docs.get_document_text(rich_doc["id"])
    assert "Second tab text." in txt and not txt.startswith("﻿")
    content = docs.get_document_content(rich_doc["id"])
    assert [t["title"] for t in content["tabs"]] == ["Tab 1", "Second Tab"]
