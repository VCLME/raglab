"""Article references in French codes: "article L. 221-18", "aux articles
L. 221-23 à L. 221-25", "l'article L. 312-1 du code monétaire et financier".

Codes cite each other explicitly, so references are read by rules, not by a
model. The same rules serve three purposes: the cross-reference statistics
of a collected code, the `references` metadata of each article (the input of
a citation graph), and the citation resolver, which reads the article cited
by a question (`raglab.retrieval.citations`).

Article numbers are normalised to the form Légifrance uses ("L221-18",
"R212-1", "1240"): the part letter (L législative, R / D réglementaire,
A arrêté, LO organique) glued to hyphenated digits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from raglab.legifrance.codes import find_code_mentions, fold

_DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-"})

# An article of a modern code: part letter + hyphenated digits ("L. 221-18",
# "R.212-1", "L221-18", "D. 312-8"). The hyphen is required, so "A 4" or
# "L 2" in running text is not taken for an article.
PREFIXED_ARTICLE = r"(?<![\w.])(?P<prefix>LO|L|R|D|A)(?:\s?\.\s?|\s)?\*?\s?(?P<digits>\d+(?:\s?-\s?\d+)+)(?![\w-])"
# "article 1240", "art. 1231-1", "article 1er": only an article when a code
# is named right after it ("du code civil"), since laws and decrees number
# their articles the same way.
PLAIN_ARTICLE = r"\b(?:articles?|art\.)\s+(?P<plain>\d+(?:-\d+)*|1er|premier)(?![\w-])"

_PREFIXED_RE = re.compile(PREFIXED_ARTICLE)
_PLAIN_RE = re.compile(PLAIN_ARTICLE, re.IGNORECASE)
# Between two references of one enumeration: ", ", " et ", " à ", " ou ",
# " et de l'article ", ...
_LIST_GAP_RE = re.compile(
    r"^[\s,]*(?:(?:et|ou|à|ainsi\s+que)\s+)?(?:(?:à|au|aux|de|du|des)\s+)?(?:l'|les\s+)?(?:articles?\s+)?[\s,]*$",
    re.IGNORECASE,
)
_RANGE_GAP_RE = re.compile(r"^\s*à\s*$", re.IGNORECASE)
# What follows an enumeration and says which code it belongs to.
_QUALIFIER_RE = re.compile(
    r"^\s*,?\s*(?:du|de\s+la|de\s+l'|des|dudit|de\s+ce|au)\s+(?P<kind>pr[ée]sent\s+code|m[êe]me\s+code|code\b)",
    re.IGNORECASE,
)
_MAX_RANGE = 40


@dataclass(slots=True, frozen=True)
class ArticleReference:
    article: str
    #: Slug of the code named after the reference; None when the reference
    #: points into the citing code itself (unqualified or "du présent code"),
    #: "other" for a code raglab does not know.
    code: str | None
    start: int
    end: int
    #: Implied by a range ("L. 221-23 à L. 221-25" implies L221-24).
    from_range: bool = False


def normalize_article_number(raw: str) -> str:
    """ "L. 221-18" -> "L221-18", "R*112-1" -> "R112-1", "1er" -> "1"."""
    text = raw.translate(_DASHES).strip().replace("*", "")
    text = re.sub(r"^(?:articles?|art\.?)\s+", "", text, flags=re.IGNORECASE)
    match = re.match(r"^(LO|L|R|D|A)\s*\.?\s*(\d.*)$", text)
    prefix, rest = (match.group(1), match.group(2)) if match else ("", text)
    rest = re.sub(r"\s*-\s*", "-", rest).strip()
    if rest.lower() in ("1er", "premier"):
        rest = "1"
    return prefix + rest


def article_label(number: str) -> str:
    """Citation style: "L221-18" -> "L. 221-18"."""
    match = re.match(r"^(LO|L|R|D|A)(\d.*)$", number)
    return f"{match.group(1)}. {match.group(2)}" if match else number


def find_prefixed_article(text: str) -> tuple[str, int, int] | None:
    """First article with a part letter in `text`: (number, start, end)."""
    match = _PREFIXED_RE.search(text.translate(_DASHES))
    if match is None:
        return None
    return match.group("prefix") + re.sub(r"\s", "", match.group("digits")), match.start(), match.end()


def find_plain_article(text: str) -> tuple[str, int, int] | None:
    """First "article 1240" in `text`: (number, start, end)."""
    match = _PLAIN_RE.search(text.translate(_DASHES))
    if match is None:
        return None
    return normalize_article_number(match.group("plain")), match.start(), match.end()


def _qualifier(text: str, position: int, previous_code: str | None) -> tuple[bool, str | None]:
    """(qualified, code) for the words right after an enumeration."""
    match = _QUALIFIER_RE.match(text[position : position + 120])
    if match is None:
        return False, None
    kind = fold(match.group("kind")).lower()
    if kind.startswith("present"):
        return True, None
    if kind.startswith("meme"):
        return True, previous_code
    code_start = position + match.start("kind")
    for mention in find_code_mentions(text[code_start : code_start + 80]):
        if mention.start == 0:
            return True, mention.slug
    return True, "other"


def _expand_range(first: str, last: str) -> list[str]:
    """ "L221-23" .. "L221-25" -> ["L221-24"]; nothing when the two ends
    differ by more than their last number."""
    head_first, _, tail_first = first.rpartition("-")
    head_last, _, tail_last = last.rpartition("-")
    if not head_first or head_first != head_last or not (tail_first.isdigit() and tail_last.isdigit()):
        return []
    low, high = int(tail_first), int(tail_last)
    if not 0 < high - low <= _MAX_RANGE:
        return []
    return [f"{head_first}-{value}" for value in range(low + 1, high)]


def extract_references(text: str) -> list[ArticleReference]:
    """Article references with a part letter found in an article's text.

    References are grouped into enumerations ("L. 221-5, L. 221-6 et
    L. 221-11"); the code named after the last one applies to the whole
    group. Ranges are expanded when both ends share their stem.
    """
    normalized = text.translate(_DASHES)
    matches = list(_PREFIXED_RE.finditer(normalized))
    groups: list[list[re.Match[str]]] = []
    for match in matches:
        if groups and _LIST_GAP_RE.match(normalized[groups[-1][-1].end() : match.start()]):
            groups[-1].append(match)
        else:
            groups.append([match])

    references: list[ArticleReference] = []
    previous_code: str | None = None
    for group in groups:
        qualified, code = _qualifier(normalized, group[-1].end(), previous_code)
        if qualified and code is not None:
            previous_code = code
        for index, match in enumerate(group):
            number = match.group("prefix") + re.sub(r"\s", "", match.group("digits"))
            if index and _RANGE_GAP_RE.match(normalized[group[index - 1].end() : match.start()]):
                first = references[-1].article
                references.extend(
                    ArticleReference(implied, code, group[index - 1].start(), match.end(), from_range=True)
                    for implied in _expand_range(first, number)
                )
            references.append(ArticleReference(number, code, match.start(), match.end()))
    return references
