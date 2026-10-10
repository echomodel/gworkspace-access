"""Unit tests for guarded Google Docs editing: position map, find,
expectation checks, guarded batch_update, exports, drive_copy.

The fixture ``fixtures/docs_rich.json`` is a real ``documents.get``
response (identities replaced with placeholders) for a document with two
tabs, a header, a heading, a nested list, an emoji, a person chip, a date
chip, and a 2x2 table — so index layout is Google's, not assumed.

Sociable tests: real SDK / MCP / CLI code against fake Docs and Drive
services injected at the service-factory boundary. The fake Docs service
records every batchUpdate so tests can assert that nothing was written.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from googleapiclient.errors import HttpError

from gwsa.cli.docs_commands import docs as docs_cli
from gwsa.cli.drive_commands import drive_group as drive_cli
from gwsa.mcp.tools import docs as docs_tools
from gwsa.mcp.tools import drive as drive_tools
from gwsa.sdk import docs
from gwsa.sdk.docs import positions

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "docs_rich.json").read_text()
)
DOC_ID = "test-doc-1234567890"
REV = "rev-1"  # the fixture's revisionId
TAB1 = "t.0"
TAB2 = FIXTURE["tabs"][1]["tabProperties"]["tabId"]
HEADER_ID = next(iter(FIXTURE["tabs"][0]["documentTab"]["headers"]))


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeResp(dict):
    def __init__(self, status):
        super().__init__()
        self.status = status
        self.reason = "fake"


class Exec:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeDocs:
    """documents().get returns queued states; batchUpdate is recorded."""

    def __init__(self):
        self.states = [copy.deepcopy(FIXTURE)]
        self.gets = []
        self.batches = []
        self.fail_status = None

    def documents(self):
        return self

    def get(self, documentId, includeTabsContent=False, fields=None):
        self.gets.append({"includeTabsContent": includeTabsContent, "fields": fields})
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return Exec(lambda: copy.deepcopy(state))

    def batchUpdate(self, documentId, body):
        def run():
            if self.fail_status:
                raise HttpError(FakeResp(self.fail_status), b"rejected")
            self.batches.append(copy.deepcopy(body))
            return {"documentId": documentId,
                    "replies": [{} for _ in body["requests"]],
                    "writeControl": {"requiredRevisionId": "rev-2"}}
        return Exec(run)


class FakeDrive:
    def __init__(self):
        self.exports = []
        self.copies = []

    def files(self):
        return self

    def get(self, fileId, fields=None, supportsAllDrives=None):
        return Exec(lambda: {"mimeType": "application/vnd.google-apps.document"})

    def export(self, fileId, mimeType):
        self.exports.append(mimeType)
        body = {"text/markdown": "# Tab 1\n\n# Plan heading\n",
                "text/plain": "﻿Tab 1\nPlan heading\n"}[mimeType]
        return Exec(lambda: body.encode("utf-8"))

    def copy(self, fileId, body, supportsAllDrives=None, fields=None):
        self.copies.append({"fileId": fileId, "body": body})
        return Exec(lambda: {"id": "copy-1", "name": body.get("name", "Copy of x"),
                             "mimeType": "application/vnd.google-apps.document",
                             "parents": body.get("parents", ["root"]),
                             "webViewLink": "https://docs.google.com/document/d/copy-1/edit"})


@pytest.fixture
def fakes(monkeypatch):
    d, dr = FakeDocs(), FakeDrive()
    monkeypatch.setattr("gwsa.sdk.docs.read.get_docs_service", lambda account=None: d)
    monkeypatch.setattr("gwsa.sdk.docs.read.get_drive_service", lambda account=None: dr)
    monkeypatch.setattr("gwsa.sdk.docs.update.get_docs_service", lambda account=None: d)
    monkeypatch.setattr("gwsa.sdk.drive.files.get_drive_service", lambda account=None: dr)
    return d, dr


def edited(fn):
    """A copy of the fixture with ``fn`` applied (for 'after' states)."""
    doc = copy.deepcopy(FIXTURE)
    fn(doc)
    doc["revisionId"] = "rev-2"
    return doc


def set_run(doc, old, new):
    """Replace a text run's content in place (same length keeps indices valid)."""
    assert len(old) == len(new)
    for tab, _p, _d in positions.iter_tabs(doc):
        for el in tab["documentTab"]["body"]["content"]:
            for pe in el.get("paragraph", {}).get("elements", []):
                tr = pe.get("textRun")
                if tr and tr["content"] == old:
                    tr["content"] = new
                    return
    raise AssertionError(f"run {old!r} not found")


# ---------------------------------------------------------------------------
# position map
# ---------------------------------------------------------------------------


def test_map_covers_every_index_of_every_segment():
    for seg in positions.build_segments(FIXTURE):
        assert seg.unmapped == [], seg.label
        assert len(seg.unit_list()) == seg.end - seg.start, seg.label
        assert "⟦?⟧" not in seg.unit_list(), seg.label


def test_map_segments_tabs_and_header():
    labels = [(s.tab_id, s.kind) for s in positions.build_segments(FIXTURE)]
    assert labels == [(TAB1, "body"), (TAB1, "header"), (TAB2, "body")]


def test_map_lines_render_ranges_styles_and_markers():
    body = positions.build_segments(FIXTURE)[0].render()
    assert body[0] == "0-1 [section] ⟦section⟧"
    assert "1-14 [HEADING_1] Plan heading⏎" in body
    assert "14-40 Intro with emoji 🙂 here.⏎" in body
    assert "46-58 [list L1] Beta nested⏎" in body
    assert "64-84 Meeting with ⟦person⟧ on ⟦date⟧⏎" in body
    assert "98-99 [table 2x2] ⟦table⟧" in body
    assert "99-100 [row 0] ⟦row⟧" in body
    assert "101-107 [cell 0,0] Fruit⏎" in body
    assert body[-1] == "125-137 After table⏎"


def test_lines_are_contiguous_and_cover_segment():
    for seg in positions.build_segments(FIXTURE):
        covered = set()
        for ln in seg.lines:
            covered.update(range(ln.start, ln.end))
        assert covered == set(range(seg.start, seg.end)), seg.label


def test_emoji_occupies_two_indices():
    seg = positions.build_segments(FIXTURE)[0]
    assert seg.slice(31, 33) == ["🙂", positions.CONTINUATION]


def test_render_map_tab_filter_and_tab_inventory():
    out = positions.render_map(FIXTURE, tab_id=TAB2)
    assert [s["tab_id"] for s in out["segments"]] == [TAB2]
    assert out["revision_id"] == "rev-1"
    assert [t["title"] for t in out["tabs"]] == ["Tab 1", "Second Tab"]


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------


def test_find_accounts_for_emoji_width():
    m = positions.find_text(FIXTURE, "here.")["matches"]
    assert [(x["start"], x["end"]) for x in m] == [(34, 39)]


def test_find_across_tabs_and_segments():
    m = positions.find_text(FIXTURE, "Plan heading")["matches"]
    assert [(x["tab_id"], x["start"], x["end"]) for x in m] == [
        (TAB1, 1, 13), (TAB2, 18, 30)]
    h = positions.find_text(FIXTURE, "Header text")["matches"]
    assert h[0]["segment"] == "header" and h[0]["segment_id"] == HEADER_ID


def test_find_with_markers_case_and_tab_filter():
    m = positions.find_text(FIXTURE, "⟦person⟧ on ⟦date⟧")["matches"]
    assert [(x["start"], x["end"]) for x in m] == [(77, 83)]
    assert positions.find_text(FIXTURE, "plan HEADING", match_case=False)["matches"]
    assert positions.find_text(FIXTURE, "plan HEADING")["matches"] == []
    only2 = positions.find_text(FIXTURE, "Plan heading", tab_id=TAB2)["matches"]
    assert [x["tab_id"] for x in only2] == [TAB2]


def test_find_rejects_empty_text():
    with pytest.raises(ValueError):
        positions.find_text(FIXTURE, "")


# ---------------------------------------------------------------------------
# expectations
# ---------------------------------------------------------------------------


def delete(s, e, **loc):
    return {"deleteContentRange": {"range": {"startIndex": s, "endIndex": e, **loc}}}


def insert(i, text="X", **loc):
    return {"insertText": {"location": {"index": i, **loc}, "text": text}}


def check(reqs, exps):
    return positions.check_expectations(FIXTURE, reqs, exps)


def test_correct_range_expectation_passes():
    assert check([delete(1, 13)], [{"text": "Plan heading"}]) == []


def test_off_by_one_range_is_refused_with_actual_content():
    f = check([delete(2, 14)], [{"text": "Plan heading"}])
    assert len(f) == 1
    assert "expected 'Plan heading' at 2-14" in f[0]
    assert "found 'lan heading⏎'" in f[0]


@pytest.mark.parametrize("s,e,shown", [
    (13, 15, "⏎I"),            # spans a paragraph break
    (77, 78, "⟦person⟧"),      # lands on a chip
    (100, 102, "⟦cell⟧F"),     # lands on a cell marker
    (31, 32, "🙂"),            # half of an emoji
])
def test_wrong_targets_show_structural_markers(s, e, shown):
    f = check([delete(s, e)], [{"text": "zzz"}])
    assert f and f"found {shown!r}" in f[0]


def test_point_expectations_before_and_after():
    assert check([insert(14)], [{"before": "Plan heading\n", "after": "Intro"}]) == []
    f = check([insert(15)], [{"before": "heading\n"}])
    assert "immediately before position 15" in f[0] and "found 'eading⏎I'" in f[0]


def test_table_operation_expects_table_marker():
    req = {"insertTableRow": {"tableCellLocation": {
        "tableStartLocation": {"index": 98}, "rowIndex": 0, "columnIndex": 0},
        "insertBelow": True}}
    assert check([req], [{"after": "⟦table⟧"}]) == []
    req["insertTableRow"]["tableCellLocation"]["tableStartLocation"]["index"] = 97
    assert check([req], [{"after": "⟦table⟧"}])


def test_missing_expectation_is_refused_and_unchecked_is_allowed():
    f = check([delete(1, 13)], None)
    assert "has no expectation" in f[0]
    assert check([delete(1, 13)], [{"unchecked": True}]) == []


def test_unpositioned_requests_need_no_expectation():
    reqs = [
        {"replaceAllText": {"containsText": {"text": "x", "matchCase": True},
                            "replaceText": "y"}},
        {"insertText": {"endOfSegmentLocation": {"tabId": TAB1}, "text": "z"}},
    ]
    assert check(reqs, None) == []
    assert check(reqs, [None, None]) == []


def test_expectation_list_must_align():
    f = check([delete(1, 13)], [{"text": "a"}, None])
    assert "must align" in f[0]


def test_wrong_expectation_shape():
    assert "needs a 'text'" in check([delete(1, 13)], [{"after": "x"}])[0]
    assert "needs 'before'" in check([insert(14)], [{"text": "x"}])[0]


def style(s, e, **loc):
    return {"updateTextStyle": {"range": {"startIndex": s, "endIndex": e, **loc},
                                "textStyle": {"bold": True}, "fields": "bold"}}


def test_requests_are_checked_in_order_like_the_api():
    # After deleting "Plan heading" (12 units), "After table" moves from
    # 125-136 to 113-124 — exactly as Google applies the batch.
    reqs = [delete(1, 13), delete(113, 124)]
    assert check(reqs, [{"text": "Plan heading"}, {"text": "After table"}]) == []
    f = check([delete(1, 13), delete(125, 136)],
              [{"text": "Plan heading"}, {"text": "After table"}])
    assert "expected 'After table' at 125-136" in f[0]


def test_delete_then_insert_sees_the_deletion():
    reqs = [delete(58, 63), insert(58, "Gamma ray")]
    assert check(reqs, [{"text": "Gamma"}, {"after": "\n"}]) == []
    f = check(reqs, [{"text": "Gamma"}, {"after": "Gamma"}])
    assert "immediately after position 58" in f[0]


def test_insert_then_style_new_text_in_same_call():
    reqs = [insert(136, "\nNext steps"), style(137, 147)]
    assert check(reqs, [{"before": "After table"}, {"text": "Next steps"}]) == []


def test_inserted_emoji_and_chip_units_are_replayed():
    reqs = [insert(1, "🙂 "), {"insertPerson": {"personProperties": {"email": "a@example.com"},
                                              "location": {"index": 4}}},
            style(1, 5)]
    assert check(reqs, [{"after": "Plan"}, {"before": "🙂 "}, {"text": "🙂 ⟦person⟧"}]) == []


def test_style_requests_move_nothing():
    reqs = [style(1, 13), style(40, 63), style(50, 70), style(1, 5)]
    assert check(reqs, [{"unchecked": True}] * 4) == []


def test_bullets_replay_removes_leading_tabs():
    # Insert a 3-item outline at the end, bullet it, then bold "Two" —
    # "Two" moves back by the one tab that createParagraphBullets removes.
    text = "\nOne\n\tTwo\nThree"
    ins = insert(136, text)               # new paragraphs start at 137
    bullets = {"createParagraphBullets": {"range": {"startIndex": 137, "endIndex": 151},
                                          "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}}
    reqs = [ins, bullets, style(141, 144)]
    exps = [{"before": "After table"}, {"text": "One\n\tTwo\nThree"}, {"text": "Two"}]
    assert check(reqs, exps) == []
    f = check(reqs, exps[:2] + [{"text": "\tTw"}])
    assert "found 'Two'" in f[0]


def test_bullets_without_tabs_move_nothing():
    bullets = {"createParagraphBullets": {"range": {"startIndex": 84, "endIndex": 97},
                                          "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}}
    assert check([bullets, style(84, 96)], [{"text": "Before table\n"}, {"text": "Before table"}]) == []


def test_untracked_request_ends_checking_after_its_position():
    table = {"insertTable": {"rows": 1, "columns": 1, "location": {"index": 97}}}
    f = check([table, style(98, 99)], [{"before": "Before table\n"}, {"unchecked": True}])
    assert "comes after request 1 (insertTable) at position 97" in f[0]
    assert check([table, style(1, 13)], [{"before": "Before table\n"}, {"text": "Plan heading"}]) == []


def test_barrier_moves_with_earlier_text_changes():
    table = {"insertTable": {"rows": 1, "columns": 1, "location": {"index": 97}}}
    reqs = [table, insert(14, "ABC"), style(1, 13)]
    assert check(reqs, [{"unchecked": True}, {"before": "\n"}, {"text": "Plan heading"}]) == []


def test_nothing_index_based_may_follow_replace_all_text():
    rat = {"replaceAllText": {"containsText": {"text": "a", "matchCase": True},
                              "replaceText": "b"}}
    f = check([rat, style(1, 13)], [None, {"text": "Plan heading"}])
    assert "can change content anywhere" in f[0]
    assert check([style(1, 13), rat], [{"text": "Plan heading"}, None]) == []


def test_end_of_segment_insert_is_replayed():
    eos = {"insertText": {"endOfSegmentLocation": {}, "text": "\nNew"}}
    reqs = [eos, style(137, 140)]
    assert check(reqs, [None, {"text": "New"}]) == []
    assert check([eos, delete(1, 13)], [None, {"text": "Plan heading"}]) == []


def test_first_failure_stops_checking():
    f = check([delete(2, 14), delete(1, 2)], [{"text": "Plan heading"}, {"text": "zzz"}])
    assert len(f) == 1


def test_segments_are_ordered_independently():
    reqs = [delete(1, 13), insert(36, tabId=TAB2)]
    assert check(reqs, [{"text": "Plan heading"}, {"before": "again"}]) == []


def test_tab_and_header_targets():
    assert check([delete(18, 30, tabId=TAB2)], [{"text": "Plan heading"}]) == []
    assert check([delete(0, 6, segmentId=HEADER_ID)], [{"text": "Header"}]) == []
    f = check([delete(1, 2, tabId="t.nope")], [{"text": "x"}])
    assert "does not exist" in f[0]


def test_range_with_emoji():
    assert check([delete(31, 33)], [{"text": "🙂"}]) == []


# -- paragraph-break glyph -------------------------------------------------


def test_map_glyph_is_read_as_paragraph_break():
    # Text copied from the map (``⏎``) means the paragraph break itself.
    assert check([delete(1, 14)], [{"text": "Plan heading⏎"}]) == []
    assert check([insert(14)], [{"before": "heading⏎", "after": "Intro"}]) == []
    assert positions.find_text(FIXTURE, "heading⏎Intro")["matches"]


def test_mismatch_that_displays_identically_names_the_difference():
    # A real "⏎" character in the document vs a paragraph break: both
    # display as ⏎, so the error must say what actually differs.
    doc = copy.deepcopy(FIXTURE)
    set_run(doc, "Gamma\n", "Gamm⏎\n")
    f = positions.check_expectations(doc, [delete(58, 63)], [{"text": "Gamm\n"}])
    assert "display the same but differ at unit 4" in f[0]
    assert "U+000A" in f[0] and "U+23CE" in f[0]


# -- whole-element expectations --------------------------------------------


def test_whole_paragraph_passes_and_shifted_range_is_refused():
    assert check([delete(84, 97)], [{"element": "paragraph"}]) == []
    for s, e in ((85, 98), (83, 96), (84, 96), (85, 97)):
        f = check([delete(s, e)], [{"element": "paragraph"}])
        assert f and "one whole paragraph" in f[0], (s, e)
    f = check([delete(85, 98)], [{"element": "paragraph"}])
    assert "the paragraph containing 85 is 84-97" in f[0]


def test_whole_paragraph_inside_a_table_cell_and_empty_paragraph():
    assert check([style(101, 107)], [{"element": "paragraph"}]) == []
    assert check([delete(97, 98)], [{"element": "paragraph"}]) == []


def test_range_spanning_two_paragraphs_is_not_one_element():
    f = check([delete(40, 58)], [{"element": "paragraph"}])
    assert "the paragraph containing 40 is 40-46" in f[0]


def test_whole_table_passes_and_partial_or_shifted_table_is_refused():
    assert check([delete(98, 125)], [{"element": "table"}]) == []
    f = check([delete(98, 124)], [{"element": "table"}])
    assert "the table at 98 spans 98-125" in f[0]
    f = check([delete(97, 124)], [{"element": "table"}])
    assert "no table starts at 97" in f[0]
    f = check([delete(99, 126)], [{"element": "table"}])
    assert "no table starts at 99" in f[0]


def test_element_boundaries_follow_earlier_requests_in_the_batch():
    # After deleting "Plan heading" (12 units) the table moves to 86-113.
    reqs = [delete(1, 13), delete(86, 113)]
    assert check(reqs, [{"text": "Plan heading"}, {"element": "table"}]) == []
    f = check([delete(1, 13), delete(98, 125)],
              [{"text": "Plan heading"}, {"element": "table"}])
    assert f and "one whole table" in f[0]


def test_element_and_text_together_must_both_hold():
    assert check([delete(58, 64)], [{"element": "paragraph", "text": "Gamma\n"}]) == []
    f = check([delete(58, 64)], [{"element": "paragraph", "text": "Delta\n"}])
    assert "expected 'Delta⏎'" in f[0]


def test_unknown_expectation_key_is_named():
    f = check([insert(14)], [{"text_before": "Plan heading\n"}])
    assert "unknown expectation key(s) ['text_before']" in f[0]


def test_unknown_element_kind_is_refused():
    f = check([delete(58, 64)], [{"element": "list"}])
    assert "'element' must be one of ['paragraph', 'table']" in f[0]


def test_partial_range_still_needs_text():
    f = check([delete(58, 61)], [{"element": "paragraph"}])
    assert "one whole paragraph" in f[0]
    f = check([delete(58, 61)], [{}])
    assert "has no expectation" in f[0]


# -- preview (dry run) -----------------------------------------------------


def test_preview_draws_text_changes_and_lists_what_it_does_not_draw():
    reqs = [delete(58, 63), insert(58, "Delta"), style(1, 13)]
    pv = positions.preview(FIXTURE, reqs, [{"text": "Gamma"}, {"after": "\n"},
                                           {"text": "Plan heading"}])
    assert pv["failures"] == []
    assert pv["changes"] == [{"segment": "tab t.0 body",
                              "before": ["58-64 Gamma⏎"],
                              "after": ["58-64 Delta⏎"]}]
    assert pv["not_shown"] == ["request 3 (updateTextStyle)"]


def test_preview_of_failed_check_has_no_changes():
    pv = positions.preview(FIXTURE, [delete(2, 14)], [{"text": "Plan heading"}])
    assert pv["failures"] and pv["changes"] == []


# ---------------------------------------------------------------------------
# guarded batch_update (SDK)
# ---------------------------------------------------------------------------


def x(request, expect):
    """A request item carrying its ``expect``."""
    return {**request, "expect": expect}


def test_expect_is_removed_before_sending(fakes):
    d, _ = fakes
    req = delete(1, 13)
    docs.batch_update(DOC_ID, [x(req, {"text": "Plan heading"})], REV)
    assert d.batches[0]["requests"] == [req]
    assert "expect" not in d.batches[0]["requests"][0]


def test_index_request_without_expect_is_refused(fakes):
    d, _ = fakes
    for items in ([delete(1, 13)], [{**delete(1, 13), "expect": None}]):
        with pytest.raises(docs.ExpectationError) as ei:
            docs.batch_update(DOC_ID, items, REV)
        assert "has no expectation" in ei.value.failures[0]
    assert d.batches == []


def test_unknown_expect_key_is_refused(fakes):
    d, _ = fakes
    with pytest.raises(docs.ExpectationError) as ei:
        docs.batch_update(DOC_ID, [x(delete(1, 13), {"textInRange": "Plan heading"})], REV)
    assert "unknown expectation key(s) ['textInRange']" in ei.value.failures[0]
    assert d.batches == []


def test_failed_expectation_writes_nothing(fakes):
    d, _ = fakes
    with pytest.raises(docs.ExpectationError) as ei:
        docs.batch_update(DOC_ID, [x(delete(2, 14), {"text": "Plan heading"})], REV)
    assert d.batches == []
    assert ei.value.revision_id == "rev-1"
    assert "found 'lan heading⏎'" in ei.value.failures[0]


def test_success_sends_requests_unchanged_with_read_revision(fakes):
    d, _ = fakes
    d.states = [copy.deepcopy(FIXTURE),
                edited(lambda doc: set_run(doc, "Gamma\n", "Delta\n"))]
    reqs = [delete(58, 63), insert(58, "Delta")]
    out = docs.batch_update(DOC_ID, [x(reqs[0], {"text": "Gamma"}),
                                     x(reqs[1], {"after": "\n"})], REV)
    assert d.batches == [{"requests": reqs,
                          "writeControl": {"requiredRevisionId": "rev-1"}}]
    assert out["previous_revision_id"] == "rev-1"
    assert out["revision_id"] == "rev-2"
    assert out["changes"] == [{
        "segment": "tab t.0 body",
        "before": ["58-64 [list L0] Gamma⏎"],
        "after": ["58-64 [list L0] Delta⏎"],
    }]


def test_unchanged_document_reports_no_changes(fakes):
    d, _ = fakes
    out = docs.batch_update(DOC_ID, [{"replaceAllText": {
        "containsText": {"text": "nomatch", "matchCase": True}, "replaceText": "y"}}], REV)
    assert out["changes"] == []
    assert len(d.batches) == 1


def test_stale_required_revision_writes_nothing(fakes):
    d, _ = fakes
    with pytest.raises(docs.DocumentChangedError):
        docs.batch_update(DOC_ID, [x(delete(1, 13), {"text": "Plan heading"})],
                          required_revision_id="rev-0")
    assert d.batches == []


@pytest.mark.parametrize("rev", [None, ""])
def test_missing_required_revision_is_refused(fakes, rev):
    d, _ = fakes
    with pytest.raises(ValueError) as ei:
        docs.batch_update(DOC_ID, [x(delete(1, 13), {"text": "Plan heading"})], rev)
    assert "required_revision_id is required" in str(ei.value)
    assert d.batches == [] and d.gets == []


def test_stale_revision_error_carries_current_id(fakes):
    with pytest.raises(docs.DocumentChangedError) as ei:
        docs.batch_update(DOC_ID, [x(delete(1, 13), {"text": "Plan heading"})], "rev-0")
    assert ei.value.current == "rev-1"
    assert "Read it again" in str(ei.value)


def test_dry_run_writes_nothing_and_returns_predicted_changes(fakes):
    d, _ = fakes
    out = docs.batch_update(DOC_ID, [x(delete(84, 97), {"element": "paragraph"})],
                            REV, dry_run=True)
    assert d.batches == []
    assert out["dry_run"] is True and out["revision_id"] == REV
    assert out["changes"][0]["before"] == ["84-97 Before table⏎"]
    assert out["not_shown"] == []


def test_dry_run_with_failed_check_raises(fakes):
    d, _ = fakes
    with pytest.raises(docs.ExpectationError):
        docs.batch_update(DOC_ID, [x(delete(2, 14), {"text": "Plan heading"})],
                          REV, dry_run=True)
    assert d.batches == []


@pytest.mark.parametrize("bad", [[], {}, [{}], [{"a": 1, "b": 2}], ["x"],
                                 [{"expect": {"text": "a"}}],
                                 [{"a": 1, "b": 2, "expect": {"text": "a"}}]])
def test_malformed_requests_rejected(fakes, bad):
    d, _ = fakes
    with pytest.raises(ValueError):
        docs.batch_update(DOC_ID, bad, REV)
    assert d.batches == []


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_failed_check_envelope(fakes):
    d, _ = fakes
    out = await docs_tools.batch_update_doc(DOC_ID, [x(delete(2, 14), {"text": "Plan heading"})], REV)
    assert out["success"] is False
    assert out["error"] == "Expectation check failed. Nothing was written."
    assert out["failures"] and out["revision_id"] == "rev-1"
    assert d.batches == []


@pytest.mark.asyncio
async def test_tool_success_envelope(fakes):
    out = await docs_tools.batch_update_doc(DOC_ID, [x(delete(1, 13), {"text": "Plan heading"})], REV)
    assert out["success"] is True and out["document_id"] == DOC_ID
    assert "changes" in out and "replies" in out


@pytest.mark.asyncio
async def test_tool_google_rejection_envelope(fakes):
    d, _ = fakes
    d.fail_status = 400
    out = await docs_tools.batch_update_doc(DOC_ID, [x(delete(1, 13), {"text": "Plan heading"})], REV)
    assert out["success"] is False
    assert out["error"] == "Google rejected the batch. Nothing was written."


@pytest.mark.asyncio
async def test_tool_stale_revision_envelope(fakes):
    out = await docs_tools.batch_update_doc(DOC_ID, [x(delete(1, 13), {"text": "Plan heading"})], "old")
    assert out["success"] is False and "Nothing was written" in out["error"]


@pytest.mark.asyncio
async def test_tool_dry_run_envelope(fakes):
    d, _ = fakes
    out = await docs_tools.batch_update_doc(DOC_ID, [x(delete(98, 125), {"element": "table"})], REV, dry_run=True)
    assert out["success"] is True and out["dry_run"] is True
    assert d.batches == []


@pytest.mark.asyncio
async def test_tool_requires_revision_id(fakes):
    out = await docs_tools.batch_update_doc(DOC_ID, [x(delete(1, 13), {"text": "Plan heading"})], "")
    assert out["success"] is False and "required_revision_id is required" in out["error"]


@pytest.mark.asyncio
async def test_read_doc_formats(fakes):
    d, dr = fakes
    content = await docs_tools.read_doc(DOC_ID)
    assert content["text"].startswith("# Tab 1")
    assert [t["tab_id"] for t in content["tabs"]] == [TAB1, TAB2]
    assert dr.exports[-1] == "text/markdown"
    assert (await docs_tools.read_doc(DOC_ID, format="text"))["text"] == "Tab 1\nPlan heading\n"
    assert dr.exports[-1] == "text/plain"
    assert (await docs_tools.read_doc(DOC_ID, format="markdown"))["text"].startswith("# Tab 1")
    m = await docs_tools.read_doc(DOC_ID, format="map", tab_id=TAB2)
    assert m["segments"][0]["lines"][1] == "1-18 Second tab text.⏎"
    raw = await docs_tools.read_doc(DOC_ID, format="raw", tab_id=TAB2, fields="tabs,revisionId")
    assert [t["tabProperties"]["tabId"] for t in raw["tabs"]] == [TAB2]
    assert d.gets[-1]["fields"] == "tabs,revisionId"


@pytest.mark.asyncio
async def test_read_doc_argument_errors(fakes):
    assert "format must be" in (await docs_tools.read_doc(DOC_ID, format="html"))["error"]
    assert "tab_id applies" in (await docs_tools.read_doc(DOC_ID, format="markdown", tab_id=TAB1))["error"]
    assert "fields applies" in (await docs_tools.read_doc(DOC_ID, format="map", fields="x"))["error"]
    assert "no tab" in (await docs_tools.read_doc(DOC_ID, format="map", tab_id="t.nope"))["error"]


@pytest.mark.asyncio
async def test_find_in_doc_tool(fakes):
    out = await docs_tools.find_in_doc(DOC_ID, "here.")
    assert out["revision_id"] == "rev-1"
    assert (out["matches"][0]["start"], out["matches"][0]["end"]) == (34, 39)
    assert "error" in await docs_tools.find_in_doc(DOC_ID, "")


@pytest.mark.asyncio
async def test_drive_copy_tool(fakes):
    _, dr = fakes
    out = await drive_tools.drive_copy("orig-1", name="Copy A", folder_id="f-1")
    assert dr.copies == [{"fileId": "orig-1", "body": {"name": "Copy A", "parents": ["f-1"]}}]
    assert out["id"] == "copy-1" and out["parents"] == ["f-1"]
    await drive_tools.drive_copy("orig-1")
    assert dr.copies[-1]["body"] == {}


def test_only_one_docs_write_tool():
    for removed in ("append_to_doc", "insert_in_doc", "replace_in_doc"):
        assert not hasattr(docs_tools, removed), removed
    for gone in ("append_text", "insert_text", "replace_text"):
        assert not hasattr(docs, gone), gone


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_read_map_and_find(fakes):
    r = CliRunner().invoke(docs_cli, ["read", DOC_ID, "--format", "map", "--tab", TAB2])
    assert r.exit_code == 0, r.output
    assert "1-18 Second tab text.⏎" in r.output and "# revision rev-1" in r.output
    r = CliRunner().invoke(docs_cli, ["find", DOC_ID, "here."])
    assert r.exit_code == 0 and json.loads(r.output)["matches"][0]["start"] == 34


def test_cli_read_markdown_default(fakes):
    r = CliRunner().invoke(docs_cli, ["read", DOC_ID])
    assert r.exit_code == 0 and r.output.startswith("# Tab 1")


def test_cli_batch_update_refusal_and_success(fakes):
    d, _ = fakes
    r = CliRunner().invoke(docs_cli, [
        "batch-update", DOC_ID, "-r", json.dumps([x(delete(2, 14), {"text": "Plan heading"})]),
        "--required-revision-id", REV])
    assert r.exit_code != 0
    assert "Nothing was written" in r.output and "found 'lan heading⏎'" in r.output
    assert d.batches == []
    r = CliRunner().invoke(docs_cli, [
        "batch-update", DOC_ID, "-r", json.dumps([x(delete(1, 13), {"text": "Plan heading"})]),
        "--required-revision-id", REV])
    assert r.exit_code == 0, r.output
    assert len(d.batches) == 1


def test_cli_commands(fakes):
    assert sorted(docs_cli.commands) == ["batch-update", "create", "find", "list", "read"]
    r = CliRunner().invoke(drive_cli, ["copy", "orig-1", "--name", "C"])
    assert r.exit_code == 0 and json.loads(r.output)["id"] == "copy-1"


def test_published_schema_lists_the_expect_fields():
    """Agents see expect's fields in the parameter list, not only in prose."""
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from gwsa.sdk.docs.expect import EXPECTATION_KEYS

    server = FastMCP("t")
    server.add_tool(docs_tools.batch_update_doc)
    schema = asyncio.run(server.list_tools())[0].inputSchema
    assert "expectations" not in schema["properties"]
    expect = schema["$defs"]["Expect"]
    assert set(expect["properties"]) == set(EXPECTATION_KEYS)
    assert expect["additionalProperties"] is False
    assert all(p.get("description") for p in expect["properties"].values())
    assert schema["$defs"]["DocsRequest"]["additionalProperties"] is True
