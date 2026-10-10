"""Position map, find, and expectation checks for Google Docs.

The Docs API addresses every edit by a numeric index into a segment (a
tab's body, header, footer, or footnote). Indices count UTF-16 code
units, and *every* index belongs to exactly one thing in the document
returned by ``documents.get``: a text character (paragraph breaks are a
real ``\\n``), or a single-index non-text element (chip, image, footnote
reference, page/section break), or a table / row / cell start marker.

This module reads those start/end indices verbatim and lays them out as a
list of *units* — one entry per index — so callers can:

- render a **position map** that prints each paragraph's exact range,
- **find** text and get its exact range,
- **check expectations** ("the text at 54–63 is ``Q3 Plan``") against
  the document before a write, so a miscalculated index is refused
  instead of applied.

Nothing here edits a document or invents positions; it only mirrors the
API's own numbering. Non-text items appear as markers such as
``⟦person⟧`` or ``⟦cell⟧`` so they are visible, countable, and can be
named in expectations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from .expect import ELEMENT_KINDS, EXPECTATION_KEYS

#: Placeholder for the second UTF-16 code unit of a supplementary
#: character (e.g. most emoji). Such characters occupy two indices.
CONTINUATION = "\x00"

#: Paragraph elements that occupy index space but carry no text run.
_INLINE_MARKERS = {
    "person": "⟦person⟧",
    "richLink": "⟦link-chip⟧",
    "dateElement": "⟦date⟧",
    "inlineObjectElement": "⟦image⟧",
    "pageBreak": "⟦page-break⟧",
    "columnBreak": "⟦column-break⟧",
    "footnoteReference": "⟦footnote-ref⟧",
    "horizontalRule": "⟦hr⟧",
    "equation": "⟦equation⟧",
    "autoText": "⟦auto-text⟧",
}

_MARKER_RE = re.compile(r"⟦[^⟦⟧]*⟧")


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------


def text_to_units(text: str) -> list[str]:
    """Split text into one unit per UTF-16 code unit.

    ``⟦...⟧`` marker tokens become single units, so expectations can name
    non-text elements (``"⟦person⟧ on ⟦date⟧"``).
    """
    units: list[str] = []
    pos = 0
    for m in _MARKER_RE.finditer(text):
        units.extend(_chars_to_units(text[pos:m.start()]))
        units.append(m.group(0))
        pos = m.end()
    units.extend(_chars_to_units(text[pos:]))
    return units


def _chars_to_units(text: str) -> list[str]:
    out: list[str] = []
    for ch in text:
        out.append(ch)
        if ord(ch) > 0xFFFF:
            out.append(CONTINUATION)
    return out


def units_to_text(units: list[str]) -> str:
    """Join units back into display text (continuations dropped)."""
    return "".join(u for u in units if u != CONTINUATION)


def _display(units: list[str]) -> str:
    return units_to_text(units).replace("\n", "⏎")


#: How the position map displays a paragraph break.
PARAGRAPH_BREAK_GLYPH = "⏎"


def expected_units(text: str) -> list[str]:
    """Units for caller-supplied text (expectations, find).

    The position map displays each paragraph break as ``⏎``; a caller who
    copies text from the map means the break itself, so ``⏎`` is read as
    ``\\n`` here.
    """
    return text_to_units(text.replace(PARAGRAPH_BREAK_GLYPH, "\n"))


def _describe_mismatch(expected: list[str], found: list[str]) -> str:
    """Name the difference when two unit lists display identically."""
    if _display(expected) != _display(found):
        return ""
    for k, (a, b) in enumerate(zip(expected, found)):
        if a != b:
            return (f" They display the same but differ at unit {k}: expected "
                    f"U+{ord(a[0]):04X}, found U+{ord(b[0]):04X}.")
    return (f" They display the same but have different lengths: expected "
            f"{len(expected)} units, found {len(found)}.")


# ---------------------------------------------------------------------------
# segment maps
# ---------------------------------------------------------------------------


@dataclass
class Line:
    """One paragraph (or structural marker) and its exact index range."""

    start: int
    end: int
    tags: list[str]

    def render(self, seg: "Segment") -> str:
        tag = "".join(f"[{t}]" for t in self.tags)
        text = _display(seg.slice(self.start, self.end))
        return f"{self.start}-{self.end} {tag + ' ' if tag else ''}{text}"


@dataclass
class Segment:
    """Index map for one segment: a tab's body, header, footer, or footnote."""

    tab_id: str
    tab_title: str
    segment_id: str  # "" for the body
    kind: str  # body | header | footer | footnote
    units: dict[int, str] = field(default_factory=dict)
    lines: list[Line] = field(default_factory=list)
    start: int = 0
    end: int = 0
    unmapped: list[int] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.kind == "body":
            return f"tab {self.tab_id} body"
        return f"tab {self.tab_id} {self.kind} {self.segment_id}"

    def slice(self, start: int, end: int) -> list[str]:
        return [self.units.get(i, "⟦?⟧") for i in range(start, end)]

    def unit_list(self) -> list[str]:
        return self.slice(self.start, self.end)

    def render(self) -> list[str]:
        return [ln.render(self) for ln in self.lines]


def _walk(content: list, seg: Segment, cell_tag: Optional[str] = None) -> None:
    for el in content:
        s = el.get("startIndex", 0)
        e = el.get("endIndex", s)
        if "sectionBreak" in el:
            for i in range(s, e):
                seg.units[i] = "⟦section⟧"
            seg.lines.append(Line(s, e, ["section"]))
        elif "paragraph" in el:
            para = el["paragraph"]
            for pe in para.get("elements", []):
                ps = pe.get("startIndex", s)
                pend = pe.get("endIndex", ps)
                if "textRun" in pe:
                    units = _chars_to_units(pe["textRun"].get("content", ""))
                    for k, u in enumerate(units[: max(pend - ps, 0)]):
                        seg.units[ps + k] = u
                else:
                    marker = next(
                        (m for key, m in _INLINE_MARKERS.items() if key in pe),
                        "⟦element⟧",
                    )
                    for i in range(ps, pend):
                        seg.units[i] = marker
            tags = []
            if cell_tag:
                tags.append(cell_tag)
            style = para.get("paragraphStyle", {}).get("namedStyleType")
            if style and style != "NORMAL_TEXT":
                tags.append(style)
            if "bullet" in para:
                level = para["bullet"].get("nestingLevel", 0)
                tags.append(f"list L{level}")
            seg.lines.append(Line(s, e, tags))
        elif "table" in el:
            table = el["table"]
            seg.units[s] = "⟦table⟧"
            rows = table.get("tableRows", [])
            cols = table.get("columns", len(rows[0].get("tableCells", [])) if rows else 0)
            seg.lines.append(Line(s, s + 1, [f"table {len(rows)}x{cols}"]))
            for r, row in enumerate(rows):
                rs = row.get("startIndex", s)
                seg.units[rs] = "⟦row⟧"
                seg.lines.append(Line(rs, rs + 1, [f"row {r}"]))
                for c, cell in enumerate(row.get("tableCells", [])):
                    cs = cell.get("startIndex", s)
                    seg.units[cs] = "⟦cell⟧"
                    seg.lines.append(Line(cs, cs + 1, [f"cell {r},{c}"]))
                    _walk(cell.get("content", []), seg, f"cell {r},{c}")
            for i in range(s, e):
                if i not in seg.units:
                    seg.units[i] = "⟦table-end⟧"
                    seg.lines.append(Line(i, i + 1, ["table end"]))
        elif "tableOfContents" in el:
            seg.units[s] = "⟦toc⟧"
            seg.lines.append(Line(s, s + 1, ["table of contents"]))
            _walk(el["tableOfContents"].get("content", []), seg, "toc")
            for i in range(s, e):
                if i not in seg.units:
                    seg.units[i] = "⟦toc-end⟧"
                    seg.lines.append(Line(i, i + 1, ["table of contents end"]))
        else:
            for i in range(s, e):
                seg.units[i] = "⟦element⟧"
            seg.lines.append(Line(s, e, ["element"]))


def _build_segment(content: list, **kw) -> Segment:
    seg = Segment(**kw)
    _walk(content, seg)
    if content:
        seg.start = content[0].get("startIndex", 0)
        seg.end = content[-1].get("endIndex", seg.start)
    seg.unmapped = [i for i in range(seg.start, seg.end) if i not in seg.units]
    seg.lines.sort(key=lambda ln: (ln.start, ln.end))
    return seg


def iter_tabs(doc: dict) -> Iterator[tuple[dict, Optional[str], int]]:
    """Yield ``(tab, parent_tab_id, depth)`` for every tab, depth-first."""

    def walk(tabs, parent, depth):
        for tab in tabs or []:
            yield tab, parent, depth
            yield from walk(
                tab.get("childTabs"),
                tab.get("tabProperties", {}).get("tabId"),
                depth + 1,
            )

    yield from walk(doc.get("tabs"), None, 0)


def list_tabs(doc: dict) -> list[dict]:
    """Tab inventory: ``tab_id``, ``title``, ``parent_tab_id``, ``depth``."""
    return [
        {
            "tab_id": tab.get("tabProperties", {}).get("tabId"),
            "title": tab.get("tabProperties", {}).get("title"),
            "parent_tab_id": parent,
            "depth": depth,
        }
        for tab, parent, depth in iter_tabs(doc)
    ]


def build_segments(doc: dict, tab_id: Optional[str] = None) -> list[Segment]:
    """Build index maps for every segment of every tab (or one tab).

    ``doc`` must come from ``documents.get`` with ``includeTabsContent``.
    """
    segments: list[Segment] = []
    for tab, _parent, _depth in iter_tabs(doc):
        props = tab.get("tabProperties", {})
        tid = props.get("tabId")
        if tab_id is not None and tid != tab_id:
            continue
        dtab = tab.get("documentTab", {})
        common = {"tab_id": tid, "tab_title": props.get("title", "")}
        segments.append(_build_segment(
            dtab.get("body", {}).get("content", []),
            segment_id="", kind="body", **common))
        for kind, key in (("header", "headers"), ("footer", "footers"),
                          ("footnote", "footnotes")):
            for sid, part in (dtab.get(key) or {}).items():
                segments.append(_build_segment(
                    part.get("content", []), segment_id=sid, kind=kind, **common))
    return segments


def first_tab_id(doc: dict) -> Optional[str]:
    for tab, _p, _d in iter_tabs(doc):
        return tab.get("tabProperties", {}).get("tabId")
    return None


def _find_segment(segments: list[Segment], tab_id: Optional[str],
                  segment_id: str, default_tab: Optional[str]) -> Optional[Segment]:
    tid = tab_id or default_tab
    for seg in segments:
        if seg.tab_id == tid and seg.segment_id == (segment_id or ""):
            return seg
    return None


# ---------------------------------------------------------------------------
# map + find
# ---------------------------------------------------------------------------


def render_map(doc: dict, tab_id: Optional[str] = None) -> dict:
    """The position map: every segment's lines with exact index ranges."""
    segments = build_segments(doc, tab_id=tab_id)
    return {
        "document_id": doc.get("documentId"),
        "revision_id": doc.get("revisionId"),
        "tabs": list_tabs(doc),
        "segments": [
            {
                "tab_id": seg.tab_id,
                "tab_title": seg.tab_title,
                "segment": seg.kind,
                "segment_id": seg.segment_id,
                "start": seg.start,
                "end": seg.end,
                "lines": seg.render(),
            }
            for seg in segments
        ],
    }


def find_text(doc: dict, text: str, tab_id: Optional[str] = None,
              match_case: bool = True) -> dict:
    """Every occurrence of ``text`` with its exact index range."""
    needle = expected_units(text)
    if not needle:
        raise ValueError("text must not be empty")
    norm = (lambda u: u) if match_case else (lambda u: u.lower())
    needle_n = [norm(u) for u in needle]
    matches = []
    for seg in build_segments(doc, tab_id=tab_id):
        hay = [norm(u) for u in seg.unit_list()]
        n = len(needle_n)
        for i in range(len(hay) - n + 1):
            if hay[i:i + n] == needle_n:
                matches.append({
                    "tab_id": seg.tab_id,
                    "segment": seg.kind,
                    "segment_id": seg.segment_id,
                    "start": seg.start + i,
                    "end": seg.start + i + n,
                })
    return {"revision_id": doc.get("revisionId"), "matches": matches}


# ---------------------------------------------------------------------------
# expectations
# ---------------------------------------------------------------------------


@dataclass
class Target:
    kind: str  # "range" | "point"
    start: int
    end: int
    tab_id: Optional[str]
    segment_id: str


#: Index-addressed requests that never add or remove content, so they
#: never move any index.
NON_SHIFTING = frozenset({
    "updateTextStyle", "updateParagraphStyle", "deleteParagraphBullets",
    "createNamedRange", "updateTableCellStyle", "updateTableColumnProperties",
    "updateTableRowStyle", "pinTableHeaderRows", "updateSectionStyle",
})

#: Point inserts that add exactly one index holding a known element.
SINGLE_INDEX_INSERTS = {
    "insertPerson": "⟦person⟧",
    "insertDate": "⟦date⟧",
    "insertInlineImage": "⟦image⟧",
}

#: Requests that address no index but can add or remove content anywhere.
GLOBAL_SHIFTING = frozenset({"replaceAllText", "replaceNamedRangeContent"})


def _find_key(obj: Any, key: str) -> Optional[dict]:
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], dict):
            return obj[key]
        for v in obj.values():
            hit = _find_key(v, key)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_key(v, key)
            if hit is not None:
                return hit
    return None


def request_target(request: dict) -> Optional[Target]:
    """The index position a request addresses, or None if it has none.

    Requests anchored by text (``replaceAllText``), name
    (``replaceNamedRangeContent``), end of segment
    (``endOfSegmentLocation``), or object id address no index.
    """
    if not isinstance(request, dict) or len(request) != 1:
        return None
    body = next(iter(request.values()))
    if not isinstance(body, dict):
        return None
    rng = body.get("range")
    if isinstance(rng, dict) and "startIndex" in rng and "endIndex" in rng:
        return Target("range", rng["startIndex"], rng["endIndex"],
                      rng.get("tabId"), rng.get("segmentId", ""))
    loc = body.get("location")
    if isinstance(loc, dict) and "index" in loc:
        return Target("point", loc["index"], loc["index"],
                      loc.get("tabId"), loc.get("segmentId", ""))
    tsl = _find_key(body, "tableStartLocation")
    if tsl is not None and "index" in tsl:
        return Target("point", tsl["index"], tsl["index"],
                      tsl.get("tabId"), tsl.get("segmentId", ""))
    return None


#: Markers that are not part of any paragraph (structure around paragraphs).
_STRUCTURAL = frozenset({"⟦section⟧", "⟦table⟧", "⟦row⟧", "⟦cell⟧",
                         "⟦table-end⟧", "⟦toc⟧", "⟦toc-end⟧"})


class _Sim:
    """A segment's units as they will be when each request in a batch runs.

    Replays the requests whose effect on indices is exact by definition:
    ``insertText`` adds exactly its text's UTF-16 units at the index,
    ``deleteContentRange`` removes exactly ``[start, end)``, and single-index
    element inserts add one unit. After any other content-changing request
    the indices at and after its position are not tracked (``barrier``).
    """

    def __init__(self, seg: Segment):
        self.seg = seg
        self.offset = seg.start
        self.units = seg.unit_list()
        self.barrier: Optional[tuple[int, int, str]] = None  # (index, req no, name)

    @property
    def end(self) -> int:
        return self.offset + len(self.units)

    def slice(self, start: int, end: int) -> list[str]:
        lo, hi = start - self.offset, end - self.offset
        out = []
        for k in range(lo, hi):
            out.append(self.units[k] if 0 <= k < len(self.units) else "⟦out-of-range⟧")
        return out

    def insert(self, index: int, units: list[str]) -> None:
        k = index - self.offset
        self.units[k:k] = units
        if self.barrier and index <= self.barrier[0]:
            self.barrier = (self.barrier[0] + len(units),) + self.barrier[1:]

    def delete(self, start: int, end: int) -> None:
        del self.units[start - self.offset:end - self.offset]
        if self.barrier and end <= self.barrier[0]:
            self.barrier = (self.barrier[0] - (end - start),) + self.barrier[1:]

    def remove_leading_tabs(self, start: int, end: int) -> None:
        """Replay ``createParagraphBullets``: Google removes each covered
        paragraph's leading tab characters (they set its nesting level)."""
        para_starts = []
        k = 0
        while k < len(self.units):
            idx = self.offset + k
            if self.units[k] in _STRUCTURAL:
                k += 1
                continue
            is_start = k == 0 or self.units[k - 1] == "\n" or self.units[k - 1] in _STRUCTURAL
            if is_start:
                # paragraph [idx, next newline] overlaps [start, end)?
                j = k
                while j < len(self.units) and self.units[j] != "\n":
                    j += 1
                pend = self.offset + j + 1
                if idx < end and pend > start and self.units[k] == "\t":
                    para_starts.append(idx)
                k = j + 1
            else:
                k += 1
        for idx in reversed(para_starts):
            k = idx - self.offset
            n = 0
            while k + n < len(self.units) and self.units[k + n] == "\t":
                n += 1
            self.delete(idx, idx + n)

    def set_barrier(self, index: int, n: int, name: str) -> None:
        if self.barrier is None or index < self.barrier[0]:
            self.barrier = (index, n, name)


def check_expectations(doc: dict, requests: list, expectations: Optional[list]) -> list[str]:
    """Check every index-based request against the document; return failures.

    Requests are evaluated in order, as Google applies them: each request's
    indices and expectation refer to the document as it is after the
    requests before it in the same batch. Each failure is a plain statement
    of fact. An empty list means the batch may be written.
    """
    return _run_checks(doc, requests, expectations)[0]


#: Requests whose effect on text the checker replays exactly.
TEXT_REPLAYED = frozenset({"insertText", "deleteContentRange",
                           *SINGLE_INDEX_INSERTS})


def preview(doc: dict, requests: list, expectations: Optional[list],
            max_lines: int = 60) -> dict:
    """What a batch would change, without writing it.

    Returns ``failures`` (as :func:`check_expectations`), ``changes`` — the
    paragraphs whose text the batch changes, before and after, with ranges
    (same shape as a write's change report, without style tags) — and
    ``not_shown``: requests whose effect the preview does not render
    (styles, bullets, tables, ``replaceAllText``, ...). Those are still
    checked; only their result is not drawn.
    """
    import difflib

    failures, sims, segments = _run_checks(doc, requests, expectations)
    changes: list[dict] = []
    truncated = False
    emitted = 0
    if not failures:
        for seg in segments:
            sim = sims.get((seg.tab_id, seg.segment_id))
            if sim is None:
                continue
            old = _unit_lines(seg.unit_list(), seg.start)
            new = _unit_lines(sim.units, sim.offset)
            sm = difflib.SequenceMatcher(
                a=[t for _, t in old], b=[t for _, t in new], autojunk=False)
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op == "equal":
                    continue
                if emitted >= max_lines:
                    truncated = True
                    break
                changes.append({
                    "segment": seg.label,
                    "before": [f"{r} {t}" for r, t in old[i1:i2]],
                    "after": [f"{r} {t}" for r, t in new[j1:j2]],
                })
                emitted += (i2 - i1) + (j2 - j1)
    not_shown = [
        f"request {i + 1} ({next(iter(r))})"
        for i, r in enumerate(requests)
        if isinstance(r, dict) and r and next(iter(r)) not in TEXT_REPLAYED
    ]
    return {"failures": failures, "changes": changes,
            "truncated": truncated, "not_shown": not_shown}


def _unit_lines(units: list[str], offset: int) -> list[tuple[str, str]]:
    """Split units into display lines: one per paragraph or structural marker."""
    lines: list[tuple[str, str]] = []
    start = 0
    for k, u in enumerate(units):
        if u in _STRUCTURAL:
            if k > start:
                lines.append((f"{offset + start}-{offset + k}", _display(units[start:k])))
            lines.append((f"{offset + k}-{offset + k + 1}", u))
            start = k + 1
        elif u == "\n":
            lines.append((f"{offset + start}-{offset + k + 1}", _display(units[start:k + 1])))
            start = k + 1
    if start < len(units):
        lines.append((f"{offset + start}-{offset + len(units)}", _display(units[start:])))
    return lines


def _run_checks(doc: dict, requests: list, expectations: Optional[list]):
    failures: list[str] = []
    segments = build_segments(doc)
    sims: dict[tuple, _Sim] = {}
    if expectations is not None and len(expectations) != len(requests):
        return [
            f"expectations has {len(expectations)} entries but requests has "
            f"{len(requests)}; they must align one-to-one (use null for "
            f"requests that address no position)."
        ], sims, segments
    default_tab = first_tab_id(doc)
    global_shift: Optional[tuple[int, str]] = None

    def sim_for(seg: Segment) -> _Sim:
        key = (seg.tab_id, seg.segment_id)
        if key not in sims:
            sims[key] = _Sim(seg)
        return sims[key]

    for i, req in enumerate(requests):
        n = i + 1
        name = next(iter(req)) if isinstance(req, dict) and req else "request"
        body = req.get(name) if isinstance(req, dict) else None
        target = request_target(req)
        exp = expectations[i] if expectations is not None else None

        if target is None:
            if name in GLOBAL_SHIFTING and global_shift is None:
                global_shift = (n, name)
            eos = _find_key(req, "endOfSegmentLocation")
            if eos is not None:
                eseg = _find_segment(segments, eos.get("tabId"),
                                     eos.get("segmentId", ""), default_tab)
                if eseg is not None:
                    sim = sim_for(eseg)
                    at = max(sim.end - 1, sim.offset)
                    if name == "insertText" and isinstance(body, dict):
                        sim.insert(at, _chars_to_units(body.get("text", "")))
                    elif name in SINGLE_INDEX_INSERTS:
                        sim.insert(at, [SINGLE_INDEX_INSERTS[name]])
                    else:
                        sim.set_barrier(at, n, name)
            continue

        seg = _find_segment(segments, target.tab_id, target.segment_id, default_tab)
        where = (
            f"{target.start}-{target.end}" if target.kind == "range"
            else f"position {target.start}"
        )
        if seg is None:
            failures.append(
                f"Request {n} ({name}) addresses tab {target.tab_id or default_tab} "
                f"segment '{target.segment_id}', which does not exist."
            )
            continue
        sim = sim_for(seg)

        if global_shift is not None:
            failures.append(
                f"Request {n} ({name}, {where}) comes after request "
                f"{global_shift[0]} ({global_shift[1]}), which can change content "
                f"anywhere; its position cannot be checked in the same call."
            )
            continue
        if sim.barrier is not None and target.end > sim.barrier[0]:
            at, m, mname = sim.barrier
            failures.append(
                f"Request {n} ({name}, {where}) comes after request {m} "
                f"({mname}) at position {at} in {seg.label}; positions at or "
                f"after that point cannot be checked in the same call."
            )
            continue

        ok = _check_one(failures, n, name, target, where, seg, sim, exp)

        # Replay the request's effect on indices.
        if name == "insertText" and isinstance(body, dict):
            sim.insert(target.start, _chars_to_units(body.get("text", "")))
        elif name == "deleteContentRange":
            sim.delete(target.start, target.end)
        elif name in SINGLE_INDEX_INSERTS:
            sim.insert(target.start, [SINGLE_INDEX_INSERTS[name]])
        elif name == "createParagraphBullets":
            sim.remove_leading_tabs(target.start, target.end)
        elif name not in NON_SHIFTING:
            sim.set_barrier(target.start, n, name)
        if not ok:
            # Positions after a failed request are meaningless; stop here.
            break
    return failures, sims, segments


def _check_one(failures, n, name, target, where, seg, sim, exp) -> bool:
    if not isinstance(exp, dict) or not exp:
        forms = (
            '{"text": <the exact content of the range>}, or {"element": '
            '"paragraph"} / {"element": "table"} when the range is exactly one '
            'whole paragraph or table'
            if target.kind == "range" else
            '{"before": <text just before>} and/or {"after": <text just after>}'
        )
        failures.append(
            f"Request {n} ({name}) addresses {where} in {seg.label} but has "
            f"no expectation. A {target.kind} takes {forms}."
        )
        return False
    if exp.get("unchecked") is True:
        return True
    unknown = sorted(set(exp) - EXPECTATION_KEYS)
    if unknown:
        failures.append(
            f"Request {n} ({name}) has unknown expectation key(s) "
            f"{unknown}; valid keys are {sorted(EXPECTATION_KEYS)}."
        )
        return False
    if target.kind == "range":
        if "text" not in exp and "element" not in exp:
            failures.append(
                f"Request {n} ({name}) addresses range {where}; its "
                f"expectation needs a 'text' value (or 'element' when the "
                f"range is exactly one whole paragraph or table)."
            )
            return False
        if "element" in exp:
            problem = _check_element(sim, target.start, target.end, exp["element"])
            if problem:
                failures.append(
                    f"Request {n} ({name}) expects {where} in {seg.label} to be "
                    f"one whole {exp['element']}; {problem}"
                )
                return False
        if "text" in exp:
            expected = expected_units(exp["text"])
            found = sim.slice(target.start, target.end)
            if found != expected:
                failures.append(
                    f"Request {n} ({name}) expected {_display(expected)!r} at "
                    f"{where} in {seg.label}; found {_display(found)!r}."
                    + _describe_mismatch(expected, found)
                )
                return False
        return True
    if "before" not in exp and "after" not in exp:
        failures.append(
            f"Request {n} ({name}) addresses {where}; its expectation "
            f"needs 'before' and/or 'after'."
        )
        return False
    ok = True
    if "before" in exp:
        expected = expected_units(exp["before"])
        found = sim.slice(target.start - len(expected), target.start)
        if found != expected:
            failures.append(
                f"Request {n} ({name}) expected {_display(expected)!r} "
                f"immediately before {where} in {seg.label}; found "
                f"{_display(found)!r}." + _describe_mismatch(expected, found)
            )
            ok = False
    if "after" in exp:
        expected = expected_units(exp["after"])
        found = sim.slice(target.start, target.start + len(expected))
        if found != expected:
            failures.append(
                f"Request {n} ({name}) expected {_display(expected)!r} "
                f"immediately after {where} in {seg.label}; found "
                f"{_display(found)!r}." + _describe_mismatch(expected, found)
            )
            ok = False
    return ok



def _check_element(sim: "_Sim", start: int, end: int, kind: Any) -> str:
    """Empty if ``[start, end)`` is exactly one whole element; else the facts.

    Boundaries come from the units as they are when the request runs, so
    earlier inserts and deletes in the same batch are accounted for.
    """
    if kind not in ELEMENT_KINDS:
        return f"'element' must be one of {list(ELEMENT_KINDS)}, got {kind!r}."
    u, off = sim.units, sim.offset
    k0, k1 = start - off, end - off
    if not (0 <= k0 < k1 <= len(u)):
        return f"the range is outside the segment ({off}-{off + len(u)})."
    if kind == "table":
        if u[k0] != "⟦table⟧":
            return f"no table starts at {start} (found {_display([u[k0]])!r})."
        depth = 0
        for k in range(k0, len(u)):
            if u[k] == "⟦table⟧":
                depth += 1
            elif u[k] == "⟦table-end⟧":
                depth -= 1
                if depth == 0:
                    table_end = off + k + 1
                    if table_end != end:
                        return f"the table at {start} spans {start}-{table_end}."
                    return ""
        return f"the table at {start} has no end marker."
    # paragraph: [start, end) runs from a paragraph start to its own newline.
    ps = k0
    while ps > 0 and u[ps - 1] != "\n" and u[ps - 1] not in _STRUCTURAL:
        ps -= 1
    pe = k0
    while pe < len(u) and u[pe] != "\n" and u[pe] not in _STRUCTURAL:
        pe += 1
    if pe >= len(u) or u[pe] != "\n" or u[k0] in _STRUCTURAL:
        return f"{start} is not inside a paragraph (found {_display([u[k0]])!r})."
    para = f"{off + ps}-{off + pe + 1}"
    if ps != k0 or pe + 1 != k1:
        return f"the paragraph containing {start} is {para}."
    return ""


# ---------------------------------------------------------------------------
# change report
# ---------------------------------------------------------------------------


def diff_documents(before: dict, after: dict, max_lines: int = 60) -> dict:
    """Line-level changes between two reads, with each side's exact ranges."""
    import difflib

    def keyed(doc):
        return {(s.tab_id, s.segment_id): s for s in build_segments(doc)}

    b, a = keyed(before), keyed(after)
    changes: list[dict] = []
    emitted = 0
    truncated = False

    def body(seg, ln):
        return ln.render(seg).split(" ", 1)[1] if " " in ln.render(seg) else ""

    for key in list(b.keys()) + [k for k in a.keys() if k not in b]:
        sb, sa = b.get(key), a.get(key)
        if sb is None or sa is None:
            seg = sa or sb
            changes.append({
                "segment": seg.label,
                "change": "segment added" if sb is None else "segment removed",
            })
            continue
        old = [body(sb, ln) for ln in sb.lines]
        new = [body(sa, ln) for ln in sa.lines]
        sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            if emitted >= max_lines:
                truncated = True
                break
            changes.append({
                "segment": sa.label,
                "before": [sb.lines[k].render(sb) for k in range(i1, i2)],
                "after": [sa.lines[k].render(sa) for k in range(j1, j2)],
            })
            emitted += (i2 - i1) + (j2 - j1)
    return {"changes": changes, "truncated": truncated}
