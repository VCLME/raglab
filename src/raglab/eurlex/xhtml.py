"""Split the XHTML of an EU act into its units: recitals, articles, annexes.

CELLAR serves two XHTML flavours, both well-formed XML written by the
Publications Office converter (CONVEX), and both mark the units with ELI ids:

* the Official Journal text (`oj-*` classes): preamble citations `cit_N`
  ("Having regard to ... Article 15 thereof"), recitals `rct_N`, articles
  `art_N`, annexes `anx_X`; points are two-column tables (label, text);
* the consolidated text (other classes): articles and annexes only (no
  preamble), points as `grid-list` columns, paragraph numbers in
  `span.no-parag`, and amendment markers (`▼M1`, `►C1 … ◄`) whose link title
  names the amending act ("32026R1744: INSERTED").

Each unit is rendered as plain text, one paragraph or point per line, the
point label kept in front of its text ("(a) the data subject has given
consent…"), footnote calls and amendment markers dropped. The structure of
an article (paragraph numbers, first-level points) is recorded on the side.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_NS = "{http://www.w3.org/1999/xhtml}"
_UNIT_ID = re.compile(r"^(rct|art|anx|cit)_([0-9A-Za-z]+)$")
_UNIT_KINDS = {"rct": "recital", "art": "article", "anx": "annex", "cit": "citation"}
_BLOCK_TAGS = {"p", "div", "table", "tbody", "thead", "tr", "li", "ul", "ol", "h1", "h2", "h3", "h4", "br", "hr", "dl"}
_SKIP_CLASSES = {"oj-note-tag", "modref", "arrow", "disclaimer", "reference", "separator", "footnote", "oj-note"}
# Amendment markers in consolidated texts: "▼M1", "►C1", "◄", "▼B".
_MARKER_RE = re.compile(r"^[►▼◄]\s*(?:[A-Z]\d*)?$")
_MARKER_CHARS = re.compile(r"[►▼◄]")
_PARAGRAPH_RE = re.compile(r"^(\d+[a-z]?)\.\s")
_POINT_LABEL_RE = re.compile(r"^\(?([a-z]{1,3}|\d{1,3}|[ivxlc]+)\)$|^(\d{1,3}[a-z]?)\.$|^[—–-]$")
_TITLE_CLASSES = {"oj-ti-art", "title-article-norm"}
_SUBTITLE_CLASSES = {"oj-sti-art", "stitle-article-norm"}
# Portuguese ordinals written as superscripts: "artigo 6.<sup>o</sup>".
_ORDINALS = {"o": "º", "os": "ºs", "a": "ª", "as": "ªs"}
_SPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class Unit:
    #: "recital", "article", "annex" or "citation" (preamble "Having regard to")
    kind: str
    #: "39", "6", "4a", "III"; for a single annex, its id in the text ("1")
    number: str
    heading: str
    title: str
    body: str
    #: Article structure: [{"number": "1", "points": ["a", "b"]}, ...]
    paragraphs: list[dict] = field(default_factory=list)
    #: Amendment markers inside the unit (consolidated texts): CELEX of the
    #: amending act or corrigendum -> what it did ("inserted", "replaced"...).
    markers: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedAct:
    title: str
    oj_date: str | None
    units: list[Unit]

    def of_kind(self, kind: str) -> list[Unit]:
        return [unit for unit in self.units if unit.kind == kind]


def _tag(element: ET.Element) -> str:
    return element.tag.removeprefix(_NS)


def _classes(element: ET.Element) -> set[str]:
    return set((element.get("class") or "").split())


def _clean(text: str) -> str:
    text = _SPACE_RE.sub(" ", _MARKER_CHARS.sub("", text))
    return re.sub(r" ?\( ?\)", "", text).strip()


def inline_text(element: ET.Element) -> str:
    """All the text of an element on one line (markers and footnote calls dropped)."""
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        if _skipped(node):
            if node.tail:
                parts.append(node.tail)
            return
        if _classes(node) & {"oj-super", "superscript"} and (node.text or "").strip() in _ORDINALS and not len(node):
            parts.append(_ORDINALS[(node.text or "").strip()])
            if node.tail and node is not element:
                parts.append(node.tail)
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if _tag(child) in _BLOCK_TAGS:
                parts.append(" ")
        if node.tail and node is not element:
            parts.append(node.tail)

    walk(element)
    return _clean("".join(parts))


def _skipped(node: ET.Element) -> bool:
    if _classes(node) & _SKIP_CLASSES:
        return True
    if _tag(node) == "a" and _MARKER_RE.match("".join(node.itertext()).strip()):
        return True
    # Footnote calls: <a href="#ntr1-…">(1)</a> (Official Journal),
    # (<a href="#E0001">1</a>) (consolidated; the empty brackets are removed
    # by `_clean`).
    if _tag(node) == "a" and re.match(r"#(?:ntr|E\d)", node.get("href") or ""):
        return True
    # Footnote text inside a table (consolidated): a block opening on the
    # footnote anchor <a id="E0030">(1)</a>.
    if any(_tag(child) == "a" and re.match(r"E\d", child.get("id") or "") and not child.get("href") for child in node):
        return True
    return _tag(node) in {"script", "style", "col", "colgroup", "img"}


class _Lines:
    """Text builder: `newline()` ends the current line unless a point label
    was just written, so the label stays in front of its text."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.current: list[str] = []
        self.glue = False

    def text(self, value: str) -> None:
        if value:
            self.current.append(value)

    def newline(self) -> None:
        if self.glue:
            return
        line = _clean("".join(self.current))
        if line:
            self.lines.append(line)
        self.current = []

    def label(self, value: str) -> None:
        self.newline()
        self.current.append(value + " ")
        self.glue = True

    def unglue(self) -> None:
        if self.glue and _clean("".join(self.current)):
            # Text written after the label: next block starts a new line.
            self.glue = False

    def result(self) -> list[str]:
        self.glue = False
        self.newline()
        return self.lines


class _Renderer:
    def __init__(self) -> None:
        self.out = _Lines()
        self.depth = 0
        self.points: list[tuple[int, str]] = []  # (depth, label) of each point line

    def render(self, element: ET.Element) -> list[str]:
        self._children(element)
        return self.out.result()

    def _children(self, element: ET.Element) -> None:
        if element.text:
            self._text(element.text)
        for child in element:
            self._node(child)
            if child.tail:
                self._text(child.tail)

    def _text(self, value: str) -> None:
        if value.strip():
            self.out.text(value)
            self.out.unglue()
        elif value:
            self.out.text(" ")

    def _row(self, label_cell: ET.Element, content: ET.Element) -> bool:
        label = inline_text(label_cell)
        if not _POINT_LABEL_RE.match(label) and not (label.startswith("(") and len(label) <= 6):
            return False
        self.out.label(label)
        self.points.append((self.depth, label))
        self.depth += 1
        self._children(content)
        self.depth -= 1
        self.out.newline()
        return True

    def _node(self, node: ET.Element) -> None:
        if _skipped(node):
            return
        tag, classes = _tag(node), _classes(node)
        if tag == "tr":
            cells = [cell for cell in node if _tag(cell) in {"td", "th"}]
            if len(cells) == 2 and self._row(cells[0], cells[1]):
                return
            # A real table: one line per row, cells separated by " | ".
            self.out.newline()
            self.out.text(" | ".join(inline_text(cell) for cell in cells))
            self.out.newline()
            return
        if "grid-container" in classes:
            columns = [child for child in node if _tag(child) == "div"]
            if len(columns) == 2 and self._row(columns[0], columns[1]):
                return
        if classes & {"oj-super", "superscript"} and (node.text or "").strip() in _ORDINALS and not len(node):
            self.out.text(_ORDINALS[(node.text or "").strip()])
            return
        if "no-parag" in classes:
            label = inline_text(node)
            self.out.label(label)
            return
        if tag in _BLOCK_TAGS:
            self.out.newline()
            self._children(node)
            self.out.newline()
            return
        self._children(node)


def render(element: ET.Element) -> tuple[list[str], list[tuple[int, str]]]:
    renderer = _Renderer()
    lines = renderer.render(element)
    return lines, renderer.points


def paragraph_structure(lines: list[str]) -> list[dict]:
    """Numbered paragraphs ("1. …") and the points under them ("(a) …",
    "a) …"), read from the rendered lines of an article."""
    paragraphs: list[dict] = []
    current: dict | None = None
    for line in lines:
        paragraph = _PARAGRAPH_RE.match(line)
        if paragraph:
            current = {"number": paragraph.group(1), "points": []}
            paragraphs.append(current)
            continue
        point = re.match(r"^\(?([a-z]{1,2})\)\s", line)
        if point:
            if current is None:
                current = {"number": None, "points": []}
                paragraphs.append(current)
            label = point.group(1)
            points = current["points"]
            # (i), (ii)... under a letter are sub-points, not letters (except
            # "i" right after "h").
            if re.fullmatch(r"[ivx]+", label) and not (label == "i" and points and points[-1] == "h"):
                continue
            if label not in points:
                points.append(label)
    return paragraphs


def _markers(element: ET.Element) -> dict[str, list[str]]:
    """Amending acts named by the markers inside a unit: {"32026R1744": ["inserted"]}."""
    found: dict[str, list[str]] = {}
    for anchor in element.iter(f"{_NS}a"):
        text = "".join(anchor.itertext()).strip()
        if not _MARKER_RE.match(text) or text.startswith("◄"):
            continue
        title = anchor.get("title") or ""
        celex, _, action = title.partition(":")
        celex = celex.strip()
        if not celex:
            continue
        actions = found.setdefault(celex, [])
        action = action.strip().lower() or ("corrected" if text.startswith("►C") else "amended")
        if action not in actions:
            actions.append(action)
    return found


def _preceding_markers(parent_map: dict[ET.Element, ET.Element], element: ET.Element) -> dict[str, list[str]]:
    """The `▼M1` marker written just before a unit (as a sibling paragraph)
    applies to the whole unit."""
    parent = parent_map.get(element)
    if parent is None:
        return {}
    siblings = list(parent)
    index = siblings.index(element)
    for previous in reversed(siblings[:index]):
        if "modref" in _classes(previous):
            return _markers(previous)
        if _tag(previous) in {"p", "div"} and inline_text(previous):
            return {}
    return {}


def _split_heading(kind: str, lines: list[str], element: ET.Element) -> tuple[str, str, list[str]]:
    """(heading, title, body lines) of a unit."""
    if kind == "article":
        heading = ""
        title = ""
        for node in element.iter():
            classes = _classes(node)
            if not heading and classes & _TITLE_CLASSES:
                heading = inline_text(node)
            elif not title and classes & _SUBTITLE_CLASSES:
                title = inline_text(node)
        body = list(lines)
        for value in (heading, title):
            if value and body and body[0] == value:
                body.pop(0)
        return heading, title, body
    if kind == "annex":
        heading = lines[0] if lines else ""
        title = lines[1] if len(lines) > 1 and len(lines[1]) < 300 else ""
        return heading, title, lines[2 if title else 1 :]
    if kind == "recital":
        # "(39)" label glued to the text: keep it, it is how recitals are cited.
        return "", "", lines
    return "", "", lines


def parse_act(markup: bytes | str) -> ParsedAct:
    root = ET.fromstring(markup if isinstance(markup, bytes) else markup.encode("utf-8"))
    parent_map = {child: parent for parent in root.iter() for child in parent}

    def unit_ancestor(element: ET.Element) -> bool:
        parent = parent_map.get(element)
        while parent is not None:
            match = _UNIT_ID.match(parent.get("id") or "")
            if match and match.group(1) != "cit":
                return True
            parent = parent_map.get(parent)
        return False

    title_parts = [inline_text(node) for node in root.iter() if _classes(node) & {"oj-doc-ti", "title-doc-first"}]
    title = title_parts[0] if title_parts else ""
    oj_date = None
    for node in root.iter():
        if _classes(node) & {"oj-hd-date"}:
            match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", inline_text(node))
            if match:
                oj_date = f"{match.group(3)}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"
            break

    units: list[Unit] = []
    seen: set[tuple[str, str]] = set()
    for element in root.iter():
        match = _UNIT_ID.match(element.get("id") or "")
        if not match:
            continue
        kind, number = _UNIT_KINDS[match.group(1)], match.group(2)
        # Provisions quoted by an amending act sit inside its articles.
        if unit_ancestor(element) or (kind, number) in seen:
            continue
        seen.add((kind, number))
        lines, _ = render(element)
        heading, unit_title, body = _split_heading(kind, lines, element)
        markers = _preceding_markers(parent_map, element)
        for celex, actions in _markers(element).items():
            merged = markers.setdefault(celex, [])
            merged.extend(action for action in actions if action not in merged)
        units.append(
            Unit(
                kind=kind,
                number=number,
                heading=heading,
                title=unit_title,
                body="\n".join(body),
                paragraphs=paragraph_structure(body) if kind == "article" else [],
                markers=markers,
            )
        )
    return ParsedAct(title=title, oj_date=oj_date, units=units)
