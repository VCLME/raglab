"""Rule-based reading of Brazilian federal laws: articles, sections, references.

The "laws" profile of the structured graph (phase 9.9) is built from these
rules, without any language model: legal references are explicit in the text
("nos termos do art. 5º", "art. 3º da Lei nº 8.666", "(Redação dada pela Lei
nº 13.129, de 2015)"), so a pattern is cheaper and more predictable than a
model guessing them. Every function here is pure (text in, records out); the
graph builder resolves law numbers against the corpus and writes Neo4j.

What is read:

- articles: a line opening with "Art. 5º", "Art. 4º-A", "Art 40." (the same
  line-start rule as the citation resolver). Amending laws quote other laws'
  articles; those quotes open with a quotation mark and are skipped, and the
  few unquoted ones are dropped because they break the law's own increasing
  numbering (longest increasing run of article numbers);
- sections: "LIVRO", "TÍTULO", "CAPÍTULO", "SEÇÃO", "SUBSEÇÃO" headings
  outside quotes;
- citations (`CITES`): "art. 12", "arts. 3º e 4º", "arts. 10 a 15", "artigo
  anterior", attributed to this law unless a qualifier follows ("da Lei nº
  X", "do Decreto ...", "da Constituição ...");
- amendments (`AMENDS` / `REVOKES`): the markers left by the compiled text
  ("Redação dada pela Lei nº X", "Incluído pela Lei nº X", "(Revogado pela
  Lei nº X)") and this law's own amending provisions ("A Lei nº X passa a
  vigorar ...", "Ficam revogados ... da Lei nº X").

Text quoted inside an amending provision belongs to the amended law: its
article headings, references and markers are not read as this law's.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field

# Ordinal marks after a number: "5º", "5°", "5o", "5ª".
_ORD = "º°oª"
# An article number: "49", "1.228" (thousands dot), optionally lettered:
# "4º-A". No space after the hyphen: "Art. 1º - O contribuinte" is article 1.
_ART_NUM = rf"(\d{{1,3}}(?:\.\d{{3}})+|\d{{1,4}})\s*(?:[{_ORD}](?![^\W\d_]))?(?:\s?-([A-Z])(?![^\W\d_]))?"
_ARTICLE_START_RE = re.compile(rf"^[ \t]*Art\.?\s*{_ART_NUM}", re.MULTILINE)
# A quoted placeholder: `Art. 4º ......` stands for an unchanged article of
# the amended law.
_PLACEHOLDER_RE = re.compile(r"\s*[.…]{4,}")
_SECTION_RE = re.compile(
    r"^[ \t]*(LIVRO|T[ÍI]TULO|CAP[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O)\s+([IVXLCDM]+(?:-[A-Z])?|[ÚU]NIC[OA]|\d+)\b",
    re.MULTILINE | re.IGNORECASE,
)
_SECTION_LEVEL = {"livro": 0, "titulo": 1, "capitulo": 2, "secao": 3, "subsecao": 4}
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(\S[^\n]*)$", re.MULTILINE)
_END_OF_BODY_RE = re.compile(r"^[ \t]*(?:Bras[íi]lia\s*,|ANEXO\b)", re.MULTILINE)

# A law: "Lei nº 8.078", "Lei n. 8078/90", "Lei no 9.504", "Lei 13.445",
# "Lei Complementar nº 101". Group 1: "complementar", 2: number, 3: /year.
_LAW_NUMBER = r"(\d{1,2}\.\d{3}|\d{4,5}|\d{1,3})"
_LAW_RE = re.compile(
    rf"\bLei(\s+Complementar)?\s*(?:n(?:[{_ORD}.]|\s*[{_ORD}]|[ú]mero)?\.?\s*)?{_LAW_NUMBER}(?![\d.]\d)(?:\s*/\s*(\d{{2,4}})\b)?",
    re.IGNORECASE,
)
_LAW_YEAR_AFTER_RE = re.compile(
    r"\s*,?\s*de\s+(?:\d{1,2}[º°o]?\s+de\s+[a-zç]+\s+de\s+|\d{1,2}\.\d{1,2}\.)?((?:19|20)\d{2}|\d{2})\b",
    re.IGNORECASE,
)
# "art. 5º", "arts. 3º e 4º", "artigos 10 a 15", "art. 4º-A".
_REF_RE = re.compile(
    rf"\b(art(?:igo)?s?)\b\.?\s*({_ART_NUM}(?:\s*(?:,|\be\b|\ba\b|\bou\b|\baté\b)\s*{_ART_NUM})*)",
    re.IGNORECASE,
)
_REF_ITEM_RE = re.compile(rf"(,|\be\b|\ba\b|\bou\b|\baté\b)?\s*{_ART_NUM}", re.IGNORECASE)
_RELATIVE_RE = re.compile(r"\b(?:no|do|ao|pelo|o)\s+artigo\s+(anterior|seguinte)\b", re.IGNORECASE)

# What may sit between an article number and the text it belongs to:
# "art. 5º, § 2º, inciso III, da Lei nº ...".
_GAP_TOKEN_RE = re.compile(
    rf"^(?:caput|e|ou|c/c|do|da|dos|das|no|na|nos|nas|todos|seu|sua|seus|suas|respectivo|respectivos|§+|§?\d+[{_ORD}]?(?:-[A-Z])?|"
    r"par[áa]grafos?|[úu]nico|incisos?|al[íi]neas?|itens?|[IVXLCDM]+(?:-[A-Z])?|[\"“”']?[a-z][\"“”']?)$",
    re.IGNORECASE,
)
_SAME_LAW_RE = re.compile(
    r"^(?:desta|nesta|dessa|nessa)\s+(?:Lei|Medida\s+Provis[óo]ria)\b|^(?:deste|neste)\s+(?:diploma|C[óo]digo|Estatuto)\b",
    re.IGNORECASE,
)
_OTHER_LAW_RE = re.compile(r"^(?:da|na|à|a)\s+(?=Lei\b)", re.IGNORECASE)
_ANAPHORA_RE = re.compile(
    r"^(?:da|na)\s+(?:referida|mencionada|citada|aludida)\s+Lei\b|^(?:daquela|naquela)\s+Lei\b", re.IGNORECASE
)
_EXTERNAL_RE = re.compile(
    r"^(?:da|do|na|no|das|dos)\s+(?:Constitui[çc][ãa]o|Decreto|Medida\s+Provis[óo]ria|C[óo]digo|Consolida[çc][ãa]o|"
    r"Ato\s+das\s+Disposi[çc][õo]es|Regimento|Resolu[çc][ãa]o|Portaria|Instru[çc][ãa]o|Estatuto|Emenda|Conven[çc][ãa]o|"
    r"Lei\s+(?:Org[âa]nica|de\s|das\s|do\s|dos\s|da\s|Geral)|Anexo|Regulamento|Tratado|Acordo|Protocolo)",
    re.IGNORECASE,
)
# A list item: "I - ...", "a) ...", "1. ...".
_LIST_ITEM_RE = re.compile(r"^\s*(?:[IVXLCDM]+(?:-[A-Z])?\s*[-–—]|[a-z]\)|\d+\.\s)")
# Characters opening a quoted amendment ("Art. 1º ..." of the amended law).
_QUOTES = {"“", '"', "‘", "'"}
# "... com a redação dada pela Lei nº X": X is not the amended law.
_NOT_AMENDED_RE = re.compile(
    r"(?:reda[çc][ãa]o\s+dada|alterad[oa]s?|inclu[íi]d[oa]s?|acrescid[oa]s?|introduzid[oa]s?|convertid[oa]s?|"
    r"institu[íi]d[oa]s?|criad[oa]s?|nos\s+termos|na\s+forma|previst[oa]s?|revogad[oa]s?|vide)\s+(?:pel[oa]s?|n[ao]s?|em)?\s*$",
    re.IGNORECASE,
)
# Amending sentences of this law: "A Lei nº X ... passa a vigorar ...".
_AMENDING_VERB_RE = re.compile(
    r"passa(?:m)?\s+a\s+vigorar|acrescid[oa]s?\s+d[oa]s?|fica(?:m)?\s+acrescid|com\s+a\s+seguinte\s+reda[çc][ãa]o",
    re.IGNORECASE,
)
_ALTERING_RE = re.compile(r"(?<!não )\baltera(?:m)?\s+(?:a|as|o|os)\s+(?=Leis?\b)", re.IGNORECASE)
_REVOKING_RE = re.compile(r"\bfica(?:m)?\s+revogad[oa]s?\b|\brevoga(?:m)?-se\b|\brevogam-se\b", re.IGNORECASE)
# Markers of the compiled text: "(Redação dada pela Lei nº 13.129, de 2015)".
_MARKER_RE = re.compile(
    r"\((Reda[çc][ãa]o\s+dada|Inclu[íi]d[oa]s?|Acrescid[oa]s?|Revogad[oa]s?)"
    r"(?:\s+(?:pel[oa]s?|por)\s+([^)]{0,160}))?\)",
    re.IGNORECASE,
)
_MARKER_KIND = {"redacao": "rewritten", "incluid": "inserted", "acrescid": "inserted", "revogad": "revoked"}
_REVOKED_LINE_RE = re.compile(r"\(\s*Revogad[oa]s?\b", re.IGNORECASE)
_VETOED_LINE_RE = re.compile(r"\(\s*VETAD[OA]\s*\)", re.IGNORECASE)

MAX_RANGE = 10
"""Longest article range expanded ("arts. 10 a 15"); a longer one is a weak
signal and only its last article is kept (the first is a mention of its own)."""


@dataclass(slots=True, frozen=True)
class LawMention:
    number: str
    year: int | None = None
    complementar: bool = False

    @property
    def key(self) -> str:
        return f"LC{self.number}" if self.complementar else self.number

    def label(self) -> str:
        kind = "Lei Complementar" if self.complementar else "Lei"
        return f"{kind} nº {format_law_number(self.number)}" + (f"/{self.year}" if self.year else "")


@dataclass(slots=True)
class LegalSection:
    key: str
    kind: str
    label: str
    title: str
    level: int
    start: int
    end: int
    parent: str | None = None


@dataclass(slots=True)
class LegalArticle:
    number: str
    label: str
    order: int
    start: int
    end: int
    revoked: bool = False
    vetoed: bool = False
    section: str | None = None


@dataclass(slots=True, frozen=True)
class ArticleCitation:
    """`source` (an article of this law) refers to `target_article` of
    `law` (None = this law)."""

    source: str
    target_article: str
    law: LawMention | None
    start: int
    end: int
    relative: bool = False


@dataclass(slots=True, frozen=True)
class Amendment:
    """`by` (None = this law) amends or revokes `target_article` of
    `target_law` (None = this law; no article = the whole law).

    relation: AMENDS or REVOKES. kind: rewritten, inserted, revoked (markers
    of the compiled text) or amends_law, revokes_law (this law's own
    amending provisions). scope: what the evidence touches (article caput,
    paragraph, inciso, alinea, or the law).
    """

    relation: str
    kind: str
    by: LawMention | None
    target_law: LawMention | None
    target_article: str | None
    scope: str
    via_article: str | None
    start: int
    end: int


@dataclass(slots=True)
class LawStructure:
    articles: list[LegalArticle] = field(default_factory=list)
    sections: list[LegalSection] = field(default_factory=list)
    citations: list[ArticleCitation] = field(default_factory=list)
    amendments: list[Amendment] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    def article_at(self, offset: int) -> LegalArticle | None:
        starts = [article.start for article in self.articles]
        index = bisect_right(starts, offset) - 1
        if index < 0:
            return None
        article = self.articles[index]
        return article if offset < article.end else None


def format_law_number(number: str) -> str:
    """ "8078" -> "8.078" (the way laws are written)."""
    return f"{int(number):,}".replace(",", ".") if number.isdigit() else number


def canonical_article(number: str, letter: str | None = None) -> str:
    """ "1.228" -> "1228", ("4", "a") -> "4-A"."""
    digits = str(int(number.replace(".", "")))
    return f"{digits}-{letter.upper()}" if letter else digits


def article_sort_key(article: str) -> tuple[int, int]:
    number, _, letter = article.partition("-")
    return int(number), (ord(letter) - 64) if letter else 0


def article_label(article: str) -> str:
    number, _, letter = article.partition("-")
    ordinal = "º" if int(number) < 10 else ""
    return f"Art. {number}{ordinal}" + (f"-{letter}" if letter else "")


def looks_like_law(text: str, *, min_articles: int = 2) -> bool:
    """LexML-like text: at least `min_articles` line-start "Art. N" headings."""
    count = 0
    for _ in _ARTICLE_START_RE.finditer(text):
        count += 1
        if count >= min_articles:
            return True
    return False


def parse_law_mention(text: str, match: re.Match[str]) -> LawMention:
    number = match.group(2).replace(".", "")
    year: int | None = None
    raw_year = match.group(3)
    if raw_year is None:
        after = _LAW_YEAR_AFTER_RE.match(text, match.end())
        raw_year = after.group(1) if after else None
    if raw_year:
        value = int(raw_year)
        year = value if value > 999 else (1900 + value if value > 30 else 2000 + value)
    return LawMention(number=str(int(number)), year=year, complementar=bool(match.group(1)))


def quoted_spans(text: str) -> list[tuple[int, int]]:
    """Spans of text quoted inside amending provisions.

    A quote opens at a line starting with a quotation mark and closes at the
    first line ending with a closing quote (optionally followed by "(NR)",
    other notes or punctuation). Inline quotes ("caput", “a”) are short and
    harmless, so only line-opening quotes are tracked. A quote left open (a
    missing closing mark) ends at the heading of this law's next article:
    the article after the last one seen outside quotes, so the quoted law's
    own "Art. 25." lines inside the block do not end it.
    """
    spans: list[tuple[int, int]] = []
    lines = _lines(text)
    last_own: tuple[int, int] = (0, 0)
    index = 0
    while index < len(lines):
        start, _, line = lines[index]
        stripped = line.lstrip()
        if stripped[:1] not in _QUOTES:
            heading = _ARTICLE_START_RE.match(line)
            if heading is not None and not _PLACEHOLDER_RE.match(line, heading.end()):
                key = article_sort_key(canonical_article(heading.group(1), heading.group(2)))
                last_own = max(last_own, key)
            index += 1
            continue
        close = index
        while close < len(lines):
            body = lines[close][2]
            if _closes_quote(body if close != index else stripped[1:]):
                break
            heading = _ARTICLE_START_RE.match(body) if close > index else None
            if heading is not None and _follows(last_own, canonical_article(heading.group(1), heading.group(2))):
                close -= 1
                break
            close += 1
        close = min(close, len(lines) - 1)
        spans.append((start, lines[close][1]))
        index = close + 1
    return spans


def _follows(previous: tuple[int, int], article: str) -> bool:
    """`article` can be the next one of a law whose last article is `previous`."""
    number, letter = article_sort_key(article)
    return number in (previous[0] + 1, previous[0] + 2) or (number == previous[0] and letter > previous[1])


def _closes_quote(line: str) -> bool:
    return bool(_CLOSING_QUOTE_RE.search(line))


_CLOSING_QUOTE_RE = re.compile(r"[”\"’']\s*(?:\([^)]*\)\s*)*[.;,:]?\s*(?:\([^)]*\)\s*)*$")


def _lines(text: str) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    position = 0
    for line in text.split("\n"):
        out.append((position, position + len(line), line))
        position += len(line) + 1
    return out


class _Spans:
    """Membership test for sorted, non-overlapping spans."""

    def __init__(self, spans: list[tuple[int, int]]):
        self.spans = spans
        self.starts = [start for start, _ in spans]

    def __contains__(self, offset: int) -> bool:
        index = bisect_right(self.starts, offset) - 1
        return index >= 0 and offset < self.spans[index][1]


def _longest_increasing(keys: list[tuple[int, int]]) -> list[int]:
    """Indices of a longest strictly increasing subsequence (first such in
    reading order on ties, so a law's own early articles win)."""
    if not keys:
        return []
    tails: list[int] = []
    tail_keys: list[tuple[int, int]] = []
    previous = [-1] * len(keys)
    for index, key in enumerate(keys):
        position = _bisect_left_keys(tail_keys, key)
        if position > 0:
            previous[index] = tails[position - 1]
        if position == len(tails):
            tails.append(index)
            tail_keys.append(key)
        else:
            tails[position] = index
            tail_keys[position] = key
    chain = []
    index = tails[-1]
    while index != -1:
        chain.append(index)
        index = previous[index]
    return chain[::-1]


def _bisect_left_keys(keys: list[tuple[int, int]], key: tuple[int, int]) -> int:
    low, high = 0, len(keys)
    while low < high:
        middle = (low + high) // 2
        if keys[middle] < key:
            low = middle + 1
        else:
            high = middle
    return low


def parse_sections(text: str, quoted: _Spans | None = None) -> list[LegalSection]:
    sections: list[LegalSection] = []
    stack: list[LegalSection] = []
    for match in _SECTION_RE.finditer(text):
        start = match.start(1)
        if quoted is not None and start in quoted:
            continue
        kind = _fold(match.group(1))
        level = _SECTION_LEVEL[kind]
        line_end = text.find("\n", match.end())
        line_end = len(text) if line_end == -1 else line_end
        rest = text[match.end() : line_end].strip(" -–—.")
        title = rest
        if not title:
            following = text[
                line_end + 1 : text.find("\n", line_end + 1) if text.find("\n", line_end + 1) != -1 else len(text)
            ]
            following = following.strip()
            if (
                following
                and len(following) < 200
                and not _ARTICLE_START_RE.match(following)
                and not _SECTION_RE.match(following)
            ):
                title = following
        while stack and stack[-1].level >= level:
            stack.pop()
        label = f"{match.group(1).capitalize()} {match.group(2).upper()}"
        key = "/".join([*(section.label for section in stack), label])
        section = LegalSection(
            key=key,
            kind=kind,
            label=label,
            title=title,
            level=level,
            start=start,
            end=len(text),
            parent=stack[-1].key if stack else None,
        )
        sections.append(section)
        stack.append(section)
    _close_sections(sections)
    return sections


def _close_sections(sections: list[LegalSection]) -> None:
    """A section ends where the next one of the same or a higher level starts."""
    for index, current in enumerate(sections):
        for following in sections[index + 1 :]:
            if following.level <= current.level:
                current.end = following.start
                break


def parse_markdown_sections(text: str) -> list[LegalSection]:
    """Generic profile: markdown headings ("# Title") as sections."""
    sections: list[LegalSection] = []
    stack: list[LegalSection] = []
    for match in _MARKDOWN_HEADING_RE.finditer(text):
        level = len(match.group(1))
        while stack and stack[-1].level >= level:
            stack.pop()
        title = match.group(2).strip()
        key = "/".join([*(section.label for section in stack), title])
        section = LegalSection(
            key=key,
            kind=f"h{level}",
            label=title,
            title=title,
            level=level,
            start=match.start(),
            end=len(text),
            parent=stack[-1].key if stack else None,
        )
        sections.append(section)
        stack.append(section)
    _close_sections(sections)
    return sections


def _fold(word: str) -> str:
    table = str.maketrans("ÍÇÃíçã", "ICAica")
    return word.translate(table).lower()


def parse_articles(text: str, quoted: _Spans | None = None) -> tuple[list[LegalArticle], dict[str, int]]:
    quoted = quoted if quoted is not None else _Spans(quoted_spans(text))
    candidates: list[tuple[int, str, str, re.Match[str]]] = []
    raw = 0
    for match in _ARTICLE_START_RE.finditer(text):
        raw += 1
        if match.start(1) in quoted or _PLACEHOLDER_RE.match(text, match.end()):
            continue
        article = canonical_article(match.group(1), match.group(2))
        label = text[match.start() : match.end()].strip()
        candidates.append((match.start(), article, label, match))
    keys = [article_sort_key(article) for _, article, _, _ in candidates]
    kept = [candidates[index] for index in _longest_increasing(keys)]
    body_end = len(text)
    articles: list[LegalArticle] = []
    for order, (start, number, label, match) in enumerate(kept, start=1):
        end = kept[order][0] if order < len(kept) else body_end
        if order == len(kept):
            # The last article stops before the signature or the annexes.
            tail = _END_OF_BODY_RE.search(text, match.end())
            if tail is not None:
                end = tail.start()
        line_end = text.find("\n", match.end())
        first_line = text[match.end() : line_end if line_end != -1 else len(text)]
        articles.append(
            LegalArticle(
                number=number,
                label=label,
                order=order,
                start=start if text[start] != "\n" else start + 1,
                end=end,
                revoked=bool(_REVOKED_LINE_RE.search(first_line[:80])),
                vetoed=bool(_VETOED_LINE_RE.search(first_line[:40])),
            )
        )
    stats = {"article_starts": raw, "articles": len(articles), "article_starts_dropped": len(candidates) - len(kept)}
    stats["article_starts_quoted"] = raw - len(candidates)
    return articles, stats


def parse_law(text: str) -> LawStructure:
    """Articles, sections, citations and amendments of one law's text."""
    quoted = _Spans(quoted_spans(text))
    articles, stats = parse_articles(text, quoted)
    structure = LawStructure(articles=articles, sections=parse_sections(text, quoted), stats=stats)
    for article in articles:
        for section in reversed(structure.sections):
            if section.start <= article.start < section.end:
                article.section = section.key
                break
    structure.citations = _parse_citations(text, structure, quoted)
    structure.amendments = _parse_markers(text, structure, quoted) + _parse_amending_provisions(text, structure, quoted)
    stats["citations"] = len(structure.citations)
    stats["amendments"] = len(structure.amendments)
    return structure


def _parse_citations(text: str, structure: LawStructure, quoted: _Spans) -> list[ArticleCitation]:
    citations: list[ArticleCitation] = []
    own = {article.number for article in structure.articles}
    by_order = {article.order: article for article in structure.articles}
    for article in structure.articles:
        body = text[article.start : article.end]
        heading = _ARTICLE_START_RE.match(body)
        skip_until = heading.end() if heading else 0
        mentions = [m for m in _REF_RE.finditer(body) if m.start() >= skip_until]
        # Right to left: "o art. 5º e o § 2º do art. 7º da Lei nº X" gives
        # art. 5º the qualifier of art. 7º.
        following: _Owner = _Owner("implicit")
        found: list[ArticleCitation] = []
        for position in range(len(mentions) - 1, -1, -1):
            match = mentions[position]
            next_start = mentions[position + 1].start() if position + 1 < len(mentions) else len(body)
            owner = _qualifier(body, match.end(), next_start)
            if owner.kind == "inherit":
                owner = following
            following = owner
            if owner.kind == "implicit":
                owner = _context_owner(body, match.start(), skip_until)
            absolute = article.start + match.start()
            if absolute in quoted or owner.kind == "external":
                continue
            law = owner.law if owner.kind == "law" else None
            for target in _expand_reference(match):
                if law is None and (target == article.number or target not in own):
                    continue
                found.append(
                    ArticleCitation(
                        source=article.number,
                        target_article=target,
                        law=law,
                        start=absolute,
                        end=article.start + match.end(),
                    )
                )
        citations.extend(sorted(found, key=lambda citation: citation.start))
        for match in _RELATIVE_RE.finditer(body):
            absolute = article.start + match.start()
            if absolute in quoted:
                continue
            neighbour = by_order.get(article.order + (-1 if match.group(1).lower() == "anterior" else 1))
            if neighbour is not None:
                citations.append(
                    ArticleCitation(
                        source=article.number,
                        target_article=neighbour.number,
                        law=None,
                        start=absolute,
                        end=article.start + match.end(),
                        relative=True,
                    )
                )
    return citations


def _expand_reference(match: re.Match[str]) -> list[str]:
    plural = match.group(1).lower() in {"arts", "artigos"}
    items = list(_REF_ITEM_RE.finditer(match.group(2)))
    if not plural:
        items = items[:1]
    targets: list[str] = []
    previous: str | None = None
    for item in items:
        article = canonical_article(item.group(2), item.group(3))
        separator = (item.group(1) or "").lower()
        if separator in {"a", "até"} and previous is not None and "-" not in previous and "-" not in article:
            low, high = int(previous), int(article)
            if low < high:
                # A long range is a weak signal: only its bounds are kept.
                span = range(low + 1, high + 1) if high - low <= MAX_RANGE else [high]
                targets.extend(str(number) for number in span)
                previous = article
                continue
        targets.append(article)
        previous = article
    return list(dict.fromkeys(targets))


@dataclass(slots=True, frozen=True)
class _Owner:
    """Which text an article number belongs to.

    kind: "this" (explicit "desta Lei"), "implicit" (no qualifier: this law
    unless the context says otherwise), "law" (another numbered law),
    "external" (Constitution, decree, code, provisional measure ...: no
    article node to point to) or "inherit" (only connectors before the next
    article number, whose owner applies).
    """

    kind: str
    law: LawMention | None = None


def _qualifier(body: str, start: int, stop: int) -> _Owner:
    """Read the words after an article number: "da Lei nº X", "desta Lei",
    "do Decreto-Lei ...", or connectors ("§ 2º, inciso III,") first."""
    window_end = min(stop, start + 160)
    newline = body.find("\n", start)
    if newline != -1:
        window_end = min(window_end, newline)
    window = body[start:window_end]
    position = 0
    while position < len(window):
        rest = window[position:]
        stripped = rest.lstrip(" ,;")
        offset = position + len(rest) - len(stripped)
        if not stripped:
            break
        if _SAME_LAW_RE.match(stripped):
            return _Owner("this")
        if _EXTERNAL_RE.match(stripped):
            return _Owner("external")
        other = _OTHER_LAW_RE.match(stripped)
        if other is not None:
            law = _LAW_RE.match(stripped, other.end())
            return _Owner("law", parse_law_mention(stripped, law)) if law is not None else _Owner("external")
        if _ANAPHORA_RE.match(stripped):
            previous = list(_LAW_RE.finditer(body, 0, start))
            return _Owner("law", parse_law_mention(body, previous[-1])) if previous else _Owner("external")
        token = re.match(r"[^\s,;]+", stripped)
        if token is None or not _GAP_TOKEN_RE.match(token.group(0).rstrip(".")):
            return _Owner("implicit")
        position = offset + token.end()
    if window_end == stop and stop < len(body):
        return _Owner("inherit")
    return _Owner("implicit")


# "Decreto-Lei nº 1.940, de 25 de maio de 1982, art. 1º": the designation
# comes first, the article number after it.
_DESIGNATION_BEFORE_RE = re.compile(
    r"(?:(Lei(?:\s+Complementar)?)\s*(?:n\S{0,2}\s*)?[\d.]+(?:/\d{2,4})?|(Decreto(?:-Lei)?|Medida\s+Provis[óo]ria|"
    r"Constitui[çc][ãa]o(?:\s+Federal)?|C[óo]digo\s+[A-Za-zÀ-ú ]{3,40}|Consolida[çc][ãa]o\s+[A-Za-zÀ-ú ]{3,40})"
    r"[^,;()]{0,20})(?:\s*,\s*de\s+[^,;()]{1,30})?\s*,\s*$",
    re.IGNORECASE,
)
# A list header naming the text its items belong to: "II - da Medida
# Provisória nº 2.158-35, de 24 de agosto de 2001:", "A Lei nº X passa a
# vigorar com as seguintes alterações:".
_HEADER_DESIGNATION_RE = re.compile(
    r"\b(?:d[ao]s?|n[ao]s?|à|a|o)\s+(Lei(?:\s+Complementar)?\s*(?:n\S{0,2}\s*)?\d|Decreto|Medida\s+Provis[óo]ria|"
    r"Constitui[çc][ãa]o|C[óo]digo|Consolida[çc][ãa]o)",
    re.IGNORECASE,
)


def _context_owner(body: str, position: int, heading_end: int) -> _Owner:
    """Owner of an unqualified article number, from what precedes it.

    1. the same clause names a text just before it ("Decreto-Lei nº 1.940,
       de 1982, art. 1º");
    2. the same line is an amending provision of another law ("A Lei nº X
       passa a vigorar acrescida do seguinte art. 4º-A");
    3. a list header above names another text ("II - da Medida Provisória
       nº ...:" then "a) os §§ 2º e 3º do art. 50").
    Otherwise the article belongs to this law.
    """
    clause_start = max(body.rfind(mark, heading_end, position) for mark in ("(", ";", "\n", ":"))
    clause = body[max(clause_start + 1, heading_end) : position]
    designation = _DESIGNATION_BEFORE_RE.search(clause)
    if designation is not None:
        return _designated(clause, designation.start())

    line_start = body.rfind("\n", 0, position) + 1
    line_end = body.find("\n", position)
    line = body[line_start : line_end if line_end != -1 else len(body)]
    if _AMENDING_VERB_RE.search(line) or _REVOKING_RE.search(line) or _ALTERING_RE.search(line):
        laws = [law for law in _LAW_RE.finditer(body, max(line_start, heading_end), position)]
        if laws:
            return _Owner("law", parse_law_mention(body, laws[-1]))

    if not _LIST_ITEM_RE.match(line):
        return _Owner("this")
    cursor = line_start - 1
    while cursor > heading_end:
        previous_start = body.rfind("\n", 0, cursor) + 1
        previous = body[max(previous_start, heading_end) : cursor].strip()
        if previous.endswith(":"):
            named = _HEADER_DESIGNATION_RE.search(previous)
            verb = _AMENDING_VERB_RE.search(previous) or _REVOKING_RE.search(previous)
            if named is not None and (verb is not None or previous[: named.start()].strip(" -–—IVXLCDM.") == ""):
                return _designated(previous, named.start(1))
        if (
            previous
            and not _LIST_ITEM_RE.match(previous)
            and previous[:1] not in _QUOTES
            and not previous.endswith(":")
        ):
            # A paragraph or the article's own text: the list ended.
            break
        cursor = previous_start - 1
    return _Owner("this")


def _designated(text: str, start: int) -> _Owner:
    law = _LAW_RE.match(text, start) if text[start:].lower().startswith("lei") else None
    if law is None:
        # Not a numbered law (decree, Constitution, provisional measure,
        # code ...): the corpus has no article to point to.
        return _Owner("external")
    return _Owner("law", parse_law_mention(text, law))


def _line_scope(line: str) -> str:
    stripped = line.lstrip(' “"')
    if _ARTICLE_START_RE.match(stripped):
        return "article"
    if stripped.startswith("§") or re.match(r"par[áa]grafo\s+[úu]nico", stripped, re.IGNORECASE):
        return "paragraph"
    if re.match(r"[IVXLCDM]+(?:-[A-Z])?\s*[-–—]", stripped):
        return "inciso"
    if re.match(r"[a-z](?:-[A-Z])?\s*\)", stripped):
        return "alinea"
    return "text"


def _parse_markers(text: str, structure: LawStructure, quoted: _Spans) -> list[Amendment]:
    amendments: list[Amendment] = []
    for match in _MARKER_RE.finditer(text):
        if match.start() in quoted:
            continue
        article = structure.article_at(match.start())
        if article is None:
            continue
        verb = _fold(match.group(1)).replace(" ", "")
        kind = next(value for prefix, value in _MARKER_KIND.items() if verb.startswith(prefix))
        source = match.group(2) or ""
        law = _LAW_RE.match(source.strip())
        if law is None or not source.strip().lower().startswith("lei"):
            # "(Revogado)", "(Redação dada pela Medida Provisória nº ...)":
            # no amending law to point from.
            continue
        line_start = text.rfind("\n", 0, match.start()) + 1
        scope = _line_scope(text[line_start : match.start()])
        amendments.append(
            Amendment(
                relation="REVOKES" if kind == "revoked" else "AMENDS",
                kind=kind,
                by=parse_law_mention(source.strip(), law),
                target_law=None,
                target_article=article.number,
                scope=scope,
                via_article=None,
                start=match.start(),
                end=match.end(),
            )
        )
    return amendments


def _parse_amending_provisions(text: str, structure: LawStructure, quoted: _Spans) -> list[Amendment]:
    """This law's own provisions amending or revoking other laws."""
    amendments: list[Amendment] = []
    for article in structure.articles:
        body = text[article.start : article.end]
        heading = _ARTICLE_START_RE.match(body)
        heading_end = heading.end() if heading else 0
        for line_start, line_end, line in _lines(body):
            absolute = article.start + line_start
            if absolute in quoted or not line.strip():
                continue
            amending = _AMENDING_VERB_RE.search(line)
            altering = _ALTERING_RE.search(line)
            revoking = _REVOKING_RE.search(line)
            if not amending and not altering and not revoking:
                continue
            relation = "REVOKES" if revoking and not amending and not altering else "AMENDS"
            clause_end = _list_end(body, line_end) if relation == "REVOKES" else line_end
            clause = body[line_start:clause_end]
            for law_match in _LAW_RE.finditer(clause):
                clause_offset = article.start + line_start + law_match.start()
                if clause_offset in quoted:
                    continue
                if relation == "AMENDS":
                    # "A Lei nº X passa a vigorar ..." (X before the verb) or
                    # "Esta Lei altera a Lei nº X" (X after "altera"); "...
                    # passa a vigorar com a redação da Lei nº Y" names no
                    # amended law after the verb.
                    before_verb = amending is not None and law_match.start() < amending.start()
                    after_altera = altering is not None and law_match.start() >= altering.start()
                    if not (before_verb or after_altera):
                        continue
                # The article's own heading ("Art. 1º A Lei nº X ...") is not
                # an article of law X.
                before_start = max(0, law_match.start() - 80, heading_end - line_start)
                before = clause[before_start : law_match.start()]
                if _NOT_AMENDED_RE.search(before):
                    continue
                law = parse_law_mention(clause, law_match)
                targets = _articles_before(before)
                if targets:
                    for target in targets:
                        amendments.append(
                            Amendment(
                                relation=relation,
                                kind="revokes_law" if relation == "REVOKES" else "amends_law",
                                by=None,
                                target_law=law,
                                target_article=target,
                                scope="article",
                                via_article=article.number,
                                start=clause_offset,
                                end=clause_offset + law_match.end() - law_match.start(),
                            )
                        )
                else:
                    amendments.append(
                        Amendment(
                            relation=relation,
                            kind="revokes_law" if relation == "REVOKES" else "amends_law",
                            by=None,
                            target_law=law,
                            target_article=None,
                            scope="law",
                            via_article=article.number,
                            start=clause_offset,
                            end=clause_offset + law_match.end() - law_match.start(),
                        )
                    )
    return amendments


def _list_end(body: str, line_end: int) -> int:
    """End of a revoking clause: "Ficam revogados:" and its list items
    ("I - a Lei nº X;", "II - os arts. 3º e 4º da Lei nº Y")."""
    end = line_end
    while end < len(body):
        next_end = body.find("\n", end + 1)
        next_end = len(body) if next_end == -1 else next_end
        line = body[end + 1 : next_end]
        if not _LIST_ITEM_RE.match(line):
            break
        end = next_end
    return end


def _articles_before(before: str) -> list[str]:
    """Articles named right before a law mention: "o art. 5º da Lei ...",
    "os arts. 3º e 4º, da Lei ..."."""
    matches = list(_REF_RE.finditer(before))
    if not matches:
        return []
    last = matches[-1]
    gap = before[last.end() :]
    tokens = [token.rstrip(".,;") for token in gap.split()]
    tokens = [token for token in tokens if token]
    if tokens[-1:] and tokens[-1].lower() in {"da", "na"}:
        tokens = tokens[:-1]
    if all(_GAP_TOKEN_RE.match(token) for token in tokens):
        return _expand_reference(last)
    return []
