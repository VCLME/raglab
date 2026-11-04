"""Read references between EU acts, by rules, in French, English and Portuguese.

Two things are read in the text of a unit (article, recital, annex, preamble
citation):

* **acts**: "Regulation (EU) 2016/679", "règlement (UE) no 1093/2010",
  "Diretiva 95/46/CE", "Regulations (EU) 2016/679 and (EU) 2018/1725", and
  treaties ("TFEU", "traité sur le fonctionnement…", "Carta"); each numbered
  act gets its CELEX (32016R0679), whether it is in the corpus or not;
* **units**: "Article 6(1)(a)", "Articles 12 to 22", "point (a) of Article
  6(1)", "article 32, paragraphe 1, point b)", "artigo 6.o, n.o 1, alínea a)",
  "recital 39", "considérant (39)", "Annex III", "anexos I e II".

What follows a unit reference decides its act: "of this Regulation" / "du
présent règlement" / "do presente regulamento" (or nothing) → the act being
read; "of Regulation (EU) 2016/679" → that act; "of that Regulation",
"dudit règlement", "thereof", "do referido regulamento" → the last act named
before; "of the TFEU", "du traité", "da Carta" → a treaty (not an act of the
corpus, kept apart). Connectors between the number and the qualifier
(", point (b),", ", premier alinéa,", ", n.o 2,") are skipped.

Two contexts change the default act of an unqualified reference:

* a preamble citation ("Having regard to Regulation (EU) 2022/2554…, and in
  particular Article 15 thereof", "vu le règlement…, et notamment son article
  15") speaks about the act it names: that is the legal basis of a delegated
  or implementing act;
* an article of an amending act ("Regulation (EU) 2024/1689 is amended as
  follows: (1) in Article 2…") speaks about the act it amends.

Pure functions, no I/O: the collector stores the result in each document's
metadata, the graph and the question generator read it from there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from raglab.eurlex.acts import ACTS, BY_CELEX, celex_for

# Bumped when a rule changes: graph precision is measured per version
# (benchmarks/eurlex_compliance/graph_precision_v*_seed*.json).
RULES_VERSION = 5

# --- acts ---------------------------------------------------------------

_KIND_WORDS = {
    "regulation": r"regulations?|r[èe]glements?|regulamentos?",
    "directive": r"directives?|diretivas?",
    "decision": r"decisions?|d[ée]cisions?|decis(?:ão|ões)",
    "recommendation": r"recommendations?|recommandations?|recomenda(?:ção|ções)",
}
_KIND_RE = "|".join(f"(?P<{kind}>{words})" for kind, words in _KIND_WORDS.items())
# Words that may sit between the kind and its number: "Regulation (EU)",
# "Commission Delegated Regulation (EU)", "règlement délégué (UE)",
# "Regulamento de Execução (UE)", "Council Directive".
_QUALIFIER = r"(?:\s+(?:d[ée]l[ée]gu[ée]e?|d'ex[ée]cution|delegad[oa]|de\s+execu[çc][ãa]o|delegated|implementing))?"
_ORG = r"\((?:EU|UE|EC|CE|EEC|CEE|EGKS|CECA|Euratom)(?:\s*,\s*Euratom)?\)"
_NO = r"(?:No|no|n[o°º]|n\.o|n\.º)\.?"
_ACT_NUMBER = (
    rf"(?:{_ORG}\s*)?(?P<no>{_NO}\s*)?(?P<a>\d{{2,4}})/(?P<b>\d{{1,4}})"
    r"(?:/(?P<suffix>EU|UE|EC|CE|EEC|CEE|JHA|JAI|PESC|CFSP))?(?![\d/])"
)
_ACT_RE = re.compile(rf"\b(?:{_KIND_RE}){_QUALIFIER}\s+{_ACT_NUMBER}", re.IGNORECASE)
# "… and (EU) 2018/1725", "… et (UE) no 45/2001": further acts of a plural.
_ACT_MORE_RE = re.compile(
    rf"\s*(?:,|and|or|et|ou|e|bem\s+como)\s+(?:{_ORG}\s*)(?P<no>{_NO}\s*)?(?P<a>\d{{2,4}})/(?P<b>\d{{1,4}})(?![\d/])",
    re.IGNORECASE,
)
_TREATY_RE = re.compile(
    r"\b(?:TFEU|TEU|TFUE|TUE|TCE|Treaty\s+on\s+(?:the\s+Functioning\s+of\s+the\s+)?European\s+Union"
    r"|trait[ée]\s+sur\s+(?:le\s+fonctionnement\s+de\s+)?l'Union\s+europ[ée]enne"
    r"|Tratado\s+(?:sobre\s+o\s+Funcionamento\s+da|da)\s+Uni[ãa]o\s+Europeia"
    r"|Charter\s+of\s+Fundamental\s+Rights|[Cc]harte\s+des\s+droits\s+fondamentaux|Carta\s+dos\s+Direitos\s+Fundamentais)\b",
)


@dataclass(slots=True, frozen=True)
class ActMention:
    #: CELEX of a numbered act; None for a treaty or the Charter.
    celex: str | None
    start: int
    end: int
    text: str

    @property
    def treaty(self) -> bool:
        return self.celex is None

    @property
    def in_corpus(self) -> bool:
        return self.celex in BY_CELEX


def _year(raw: int) -> int:
    if raw >= 100:
        return raw
    return 2000 + raw if raw < 50 else 1900 + raw


def act_celex(kind: str, a: str, b: str, *, numbered_first: bool, suffix: str | None) -> str | None:
    """CELEX from the two numbers of an act. "No 1093/2010" (before 2015)
    is number/year; "2016/679" and "95/46/EC" are year/number."""
    first, second = int(a), int(b)
    if numbered_first:
        number, year = first, _year(second)
    else:
        year, number = _year(first), second
    if not 1950 <= year <= 2100 or number == 0:
        return None
    return celex_for(kind, year, number)


def find_acts(text: str) -> list[ActMention]:
    """Numbered acts and treaties named in `text`, in reading order."""
    mentions: list[ActMention] = []
    for match in _ACT_RE.finditer(text):
        kind = next(name for name in _KIND_WORDS if match.group(name))
        celex = act_celex(
            kind,
            match.group("a"),
            match.group("b"),
            numbered_first=bool(match.group("no")),
            suffix=match.group("suffix"),
        )
        if celex is not None:
            mentions.append(ActMention(celex, match.start(), match.end(), match.group(0)))
        end = match.end()
        while True:
            more = _ACT_MORE_RE.match(text, end)
            if more is None:
                break
            celex = act_celex(
                kind, more.group("a"), more.group("b"), numbered_first=bool(more.group("no")), suffix=None
            )
            if celex is not None:
                mentions.append(ActMention(celex, more.start(), more.end(), more.group(0).strip(" ,")))
            end = more.end()
    for match in _TREATY_RE.finditer(text):
        mentions.append(ActMention(None, match.start(), match.end(), match.group(0)))
    return sorted(mentions, key=lambda mention: mention.start)


# Short names of the corpus acts ("RGPD", "AI Act", "NIS 2"), for questions.
def _name_pattern(name: str) -> str:
    escaped = re.escape(name).replace(r"\ ", r"\s*") if name.replace(" ", "").isupper() else re.escape(name)
    return escaped.replace("'", "['’]")


_SHORT_NAMES: list[tuple[re.Pattern[str], str]] = []
for _act in ACTS:
    for _names in _act.names.values():
        for _name in _names:
            # Acronyms are case-sensitive ("DORA", not "dora"); names are not.
            flags = 0 if _name.replace(" ", "").replace("2", "").isupper() else re.IGNORECASE
            _SHORT_NAMES.append((re.compile(rf"(?<![\w-]){_name_pattern(_name)}(?![\w-])", flags), _act.celex))


def find_act_names(text: str) -> list[ActMention]:
    """Corpus acts named in `text` by number or by short name, longest
    match first at each position."""
    found = [mention for mention in find_acts(text) if mention.celex is not None]
    for pattern, celex in _SHORT_NAMES:
        for match in pattern.finditer(text):
            found.append(ActMention(celex, match.start(), match.end(), match.group(0)))
    found.sort(key=lambda mention: (mention.start, -(mention.end - mention.start)))
    kept: list[ActMention] = []
    for mention in found:
        if kept and mention.start < kept[-1].end:
            continue
        kept.append(mention)
    return kept


# --- units --------------------------------------------------------------

_ROMAN = r"[IVXLC]+"
_SUFFIXES = {"bis": "a", "ter": "b", "quater": "c", "quinquies": "d", "sexies": "e"}


def normalize_number(raw: str) -> str:
    """ "6", "4a", "4 bis" -> "4a", "4.o-A" -> "4a", "6.º" -> "6"."""
    raw = raw.strip()
    match = re.match(
        r"^(\d+)(?:\s*\.\s*[oº°])?(?:\s*-\s*([A-Za-z])\b|([a-z])\b|\s+(bis|ter|quater|quinquies|sexies)\b)?", raw
    )
    if not match:
        return raw
    number = match.group(1)
    letter = match.group(2) or match.group(3) or _SUFFIXES.get(match.group(4) or "", "")
    return number + letter.lower()


# Article number as written: "6", "4a", "4 bis", "6.o", "4.o-A", "6.º".
_NUM = r"\d{1,3}(?:\s*\.\s*[oº°](?![a-z]))?(?:\s*-\s*[A-Z]\b|[a-z]\b|\s+(?:bis|ter|quater|quinquies|sexies)\b)?"
_PT_PAR = r"(?:n\.\s*[oº°]s?|n[ºo°]s?)"


@dataclass(slots=True, frozen=True)
class _Lang:
    article: str
    recital: str
    annex: str
    list_sep: str
    range_sep: str
    # Text after the first number that still belongs to the reference.
    tail: str
    connectors: str
    own: str
    anaphora: str
    of: str
    treaty: str
    # Possessive right before the unit word: "its", "son / ses", "seu(s)".
    possessive: str
    # "point (a) of" / "paragraph 2 of" before "Article N" (English only).
    before: str | None = None


_EN = _Lang(
    article=r"\bArt(?:icles?|\.)\s+",
    recital=r"\b[Rr]ecitals?\s+",
    annex=r"\bAnnex(?:es)?\b",
    list_sep=r"\s*(?:,|\band\b|\bor\b)\s*",
    range_sep=r"\s+to\s+",
    tail=(
        r"(?:\(\d{1,3}[a-z]?\))?(?:\((?:[a-z]{1,3}|[ivx]+|\d{1,3})\))*"
        r"(?:,\s*(?:first|second|third|fourth|fifth|sixth|last|introductory)\s+(?:subparagraph|sentence|wording))?"
        r"(?:,\s*points?\s+\((?P<pt>\w{1,4})\)(?:\s*(?:,|and|or|to)\s*\(\w{1,4}\))*)?"
    ),
    connectors=(
        r"(?:\s*,?\s*(?:(?:and|or)\s+)?(?:(?:first|second|third|fourth|fifth|sixth|seventh|last|introductory)\s+"
        r"(?:subparagraph|sentence|indent|paragraph|wording)|points?\s+\(\w{1,4}\)(?:\s*(?:,|and|or|to)\s*\(\w{1,4}\))*"
        r"|paragraphs?\s+\d+[a-z]?(?:\s*(?:,|and|or|to)\s*\d+[a-z]?)*|\(\w{1,4}\)|respectively)\s*,?)*\s*"
    ),
    own=r"^(?:of|in|under|to|by)\s+this\s+(?:Regulation|Directive|Decision)\b",
    anaphora=(
        r"^(?:(?:of|in|under|to|by)\s+(?:the\s+Annex\s+to\s+)?(?:that|the\s+said|the\s+same|those)\s+"
        r"(?:Regulations?|Directives?|Decisions?|Recommendations?|Annex)\b|thereof\b)"
    ),
    of=r"^(?:of|in|under|to|by)\s+(?:the\s+)?(?:(?:Commission|Council|European\s+Parliament)\s+)?",
    treaty=r"^(?:(?:of|in|under)\s+(?:the\s+)?)?(?:TFEU|TEU|Treaty|Charter|Protocol|Statute)\b",
    possessive=r"\bits\s+$",
    before=(
        r"(?:(?:points?\s+\((?P<pt>\w{1,4})\)(?:\s*(?:,|and|or|to)\s*\(\w{1,4}\))*"
        r"(?:\s+of\s+(?:the\s+\w+\s+subparagraph\s+of\s+)?paragraph\s+(?P<par2>\d+[a-z]?))?"
        r"|(?:the\s+\w+\s+subparagraph\s+of\s+)?paragraph\s+(?P<par>\d+[a-z]?))\s+of\s+)$"
    ),
)
_FR = _Lang(
    article=r"\b[Aa]rt(?:icles?|\.)\s+",
    recital=r"\b[Cc]onsid[ée]rants?\s+",
    annex=r"\b[Aa]nnexes?\b",
    list_sep=r"\s*(?:,|\bet\b|\bou\b)\s*",
    range_sep=r"\s+à\s+",
    tail=(
        r"(?:,\s*paragraphes?\s+(?P<par>\d{1,3}[a-z]?)(?:\s*(?:,|et|à)\s*\d{1,3})*)?"
        r"(?:,\s*(?:premier|deuxième|troisième|quatrième|cinquième|sixième|dernier)\s+alinéa)?"
        r"(?:,\s*points?\s+(?P<pt>\w{1,3})\)?(?:\s*(?:,|et|ou|à)\s*(?:\w{1,3}\)|\d{1,3}\b))*)?"
    ),
    connectors=(
        r"(?:\s*,?\s*(?:(?:et|ou)\s+)?(?:(?:premier|deuxième|troisième|quatrième|cinquième|sixième|dernier)\s+(?:alinéa|tiret)"
        r"|points?\s+(?:\w{1,3}\)|\d{1,3}\b)(?:\s*(?:,|et|ou|à)\s*(?:\w{1,3}\)|\d{1,3}\b))*"
        r"|paragraphes?\s+\d+[a-z]?(?:\s*(?:,|et|ou|à)\s*\d+[a-z]?)*"
        r"|phrase\s+introductive|sous-point\s+\w+\)|\w{1,3}\)|respectivement)\s*,?)*\s*"
    ),
    own=r"^(?:du|de\s+la|de\s+l['’]|au|à\s+la)\s*présente?\s+(?:règlement|directive|décision)\b",
    anaphora=(
        r"^(?:(?:de\s+l['’]annexe\s+(?:de|à)\s+)?(?:dudit|de\s+ladite|du\s+même|de\s+la\s+même|de\s+ce|de\s+cette|"
        r"desdits|desdites|audit|à\s+ladite|ladite|cette)"
        r"\s+(?:règlements?|directives?|décisions?|recommandations?|annexe)\b)"
    ),
    of=r"^(?:du|de\s+la|de\s+l['’]|des|au|à\s+la)\s*",
    treaty=r"^(?:(?:du|de\s+la|au)\s+)?(?:traité|TFUE|TUE|[Cc]harte|protocole|statut)\b",
    possessive=r"\b(?:son|ses|sa)\s+$",
)
_PT = _Lang(
    article=r"\b[Aa]rt(?:igos?|\.)\s+",
    recital=r"\b[Cc]onsiderandos?\s+",
    annex=r"\b[Aa]nexos?\b",
    list_sep=r"\s*(?:,|\be\b|\bou\b)\s*",
    range_sep=r"\s+a\s+",
    tail=(
        rf"(?:,\s*{_PT_PAR}\s*(?P<par>\d{{1,3}}[a-z]?)(?:\s*(?:,|e|a)\s*\d{{1,3}})*)?"
        r"(?:,\s*(?:primeiro|segundo|terceiro|quarto|quinto|sexto|último)\s+parágrafo)?"
        r"(?:,\s*(?:alíneas?|pontos?)\s+(?P<pt>\w{1,4})\)?(?:\s*(?:,|e|ou|a)\s*(?:\w{1,3}\)|\d{1,3}\b))*)?"
    ),
    connectors=(
        rf"(?:\s*,?\s*(?:(?:e|ou)\s+)?(?:(?:primeiro|segundo|terceiro|quarto|quinto|sexto|último)\s+(?:parágrafo|travessão)"
        rf"|(?:alíneas?|pontos?)\s+(?:\w{{1,3}}\)|\d{{1,3}}\b)(?:\s*(?:,|e|ou|a)\s*(?:\w{{1,3}}\)|\d{{1,3}}\b))*"
        rf"|{_PT_PAR}\s*\d+[a-z]?(?:\s*(?:,|e|ou|a)\s*\d+[a-z]?)*|frase\s+introdutória|subalínea\s+\w+\)|\w{1, 3}\)|respetivamente)\s*,?)*\s*"
    ),
    own=r"^(?:do|da|no|na|pelo|pela)\s+presente\s+(?:regulamento|diretiva|decisão)\b",
    anaphora=(
        r"^(?:(?:do|da|no|na)\s+(?:anexo\s+d[ao]\s+)?(?:referid[oa]|mesm[oa])\s+"
        r"(?:regulamentos?|diretivas?|decis(?:ão|ões)|recomendaç(?:ão|ões)|anexo)\b"
        r"|(?:desse|dessa|deste|desta|nesse|nessa)\s+(?:regulamento|diretiva|decisão|recomendação|anexo)\b)"
    ),
    of=r"^(?:do|da|dos|das|no|na|pelo|pela)\s*",
    treaty=r"^(?:(?:do|da|no|na)\s+)?(?:Tratado|TFUE|TUE|Carta|Protocolo|Estatuto)\b",
    possessive=r"\b(?:seu|seus|sua|suas)\s+$",
)
LANGS = {"en": _EN, "fr": _FR, "pt": _PT}


@dataclass(slots=True, frozen=True)
class UnitReference:
    unit: str  # "article", "recital", "annex"
    #: "6", "4a", "39", "III"; None for "the Annex" of an act with one annex
    number: str | None
    #: CELEX of the act; None when the reference points into a treaty
    celex: str | None
    #: "same_act", "other_act" (named), "anaphora" ("that Regulation"),
    #: "context" (the act a citation or an amending article is about),
    #: "treaty"
    scope: str
    start: int
    end: int
    text: str
    paragraph: str | None = None
    point: str | None = None
    #: True when nothing around the reference names its act: it defaults to
    #: the act being read (or to the context act).
    implicit: bool = False

    def as_metadata(self) -> dict:
        row: dict[str, Any] = {"unit": self.unit, "number": self.number, "celex": self.celex, "scope": self.scope}
        if self.paragraph:
            row["paragraph"] = self.paragraph
        if self.point:
            row["point"] = self.point
        if self.implicit:
            row["implicit"] = True
        row["text"] = self.text
        return row


def _items(raw: str, lang: _Lang) -> list[str]:
    """ "12 to 22" -> 12..22 (at most 30), "13 and 14" -> 13, 14."""
    numbers: list[str] = []
    for part in re.split(lang.list_sep, raw):
        bounds = [bound.strip() for bound in re.split(lang.range_sep, part.strip())]
        if len(bounds) == 2:
            low, high = re.match(r"\d+", bounds[0]), re.match(r"\d+", bounds[1])
            if low and high and 0 < int(high.group(0)) - int(low.group(0)) <= 30:
                numbers.extend(str(value) for value in range(int(low.group(0)), int(high.group(0)) + 1))
                continue
        for bound in bounds:
            if re.match(r"^\d", bound):
                numbers.append(normalize_number(re.split(r"\(", bound)[0]))
    return list(dict.fromkeys(numbers))


def _qualifier(text: str, end: int, lang: _Lang, acts: list[ActMention]) -> tuple[str, ActMention | None, int]:
    """("own" | "anaphora" | "act" | "treaty" | "none", mention, end of qualifier)."""
    window_start = end
    connector = re.match(lang.connectors, text[end : end + 160])
    if connector:
        window_start = end + connector.end()
    # ", du règlement…" / ", do Regulamento…": the comma closing the connectors.
    closing = re.match(r"[\s,]*", text[window_start : window_start + 10])
    window_start += closing.end() if closing else 0
    window = text[window_start : window_start + 160]
    # "Article 16 TFEU" / "Articles 16 and 114 thereof"
    for kind, pattern, flags in (
        ("own", lang.own, re.IGNORECASE),
        ("anaphora", lang.anaphora, re.IGNORECASE),
        ("treaty", lang.treaty, 0),
    ):
        match = re.match(pattern, window, flags)
        if match:
            return kind, None, window_start + match.end()
    of = re.match(lang.of, window)
    if of is not None:
        position = window_start + of.end()
        for mention in acts:
            # "of Commission Delegated Regulation (EU) 2024/1774": the act
            # match starts at the kind word, possibly after a few words.
            if position <= mention.start <= position + 40 and re.fullmatch(
                r"[\w\s'’-]*", text[position : mention.start]
            ):
                return ("treaty" if mention.treaty else "act"), mention, mention.end
    return "none", None, end


def extract_references(
    text: str,
    language: str,
    *,
    own_celex: str,
    context_celex: str | None = None,
) -> list[UnitReference]:
    """Unit references of `text`, with their act resolved.

    `context_celex` is the act unqualified references point to instead of
    `own_celex` (a preamble citation, an amending article).
    """
    lang = LANGS[language]
    acts = find_acts(text)
    references: list[UnitReference] = []
    # References whose act was not written after them (default act).
    implicit: set[int] = set()

    def resolve(start: int, end: int) -> tuple[str | None, str, bool]:
        if re.search(lang.possessive, text[max(0, start - 14) : start]):
            # "its Articles 12 to 15", "son article 3", "nos seus artigos":
            # the act named before (in a preamble citation, the cited act).
            if context_celex is not None:
                return context_celex, "context", True
            previous = [mention for mention in acts if mention.end <= start]
            if previous:
                last = previous[-1]
                if last.celex is None:
                    return None, "treaty", True
                return last.celex, ("same_act" if last.celex == own_celex else "anaphora"), True
        kind, mention, _ = _qualifier(text, end, lang, acts)
        if kind == "own":
            return own_celex, "same_act", True
        if kind == "act" and mention is not None:
            return mention.celex, ("same_act" if mention.celex == own_celex else "other_act"), True
        if kind == "treaty":
            return None, "treaty", True
        if kind == "anaphora":
            # "Having regard to Regulation (EU) 2022/2554 … amending
            # Regulations … (EU) 2016/1011, and in particular Article 15
            # thereof": the cited act, not the last one of its title.
            if context_celex is not None and re.search(r"\bthereof\b", text[end : end + 80]):
                return context_celex, "context", True
            previous = [mention for mention in acts if mention.end <= start and mention.celex is not None]
            if previous:
                return previous[-1].celex, "anaphora", True
            if context_celex is not None:
                return context_celex, "context", True
            return None, "treaty", True
        bracket = _bracketed_act(text, start, acts)
        if bracket is not None:
            return bracket.celex, ("same_act" if bracket.celex == own_celex else "other_act"), True
        if context_celex is not None:
            return context_celex, "context", False
        return own_celex, "same_act", False

    def add(reference: UnitReference, explicit: bool) -> None:
        if not explicit:
            reference = replace(reference, implicit=True)
            implicit.add(id(reference))
        references.append(reference)

    # Articles: "Article 6(1)(a)", "Articles 12 to 22", "article 32, paragraphe 1, point b)".
    article_re = re.compile(
        rf"{lang.article}(?P<first>{_NUM}){lang.tail}"
        rf"(?P<more>(?:(?:{lang.list_sep}|{lang.range_sep})(?:{_NUM})(?:\(\d{{1,3}}[a-z]?\))?(?:\(\w{{1,4}}\))*)*)"
    )
    for match in article_re.finditer(text):
        groups = match.groupdict()
        first = normalize_number(groups["first"])
        paragraph = groups.get("par")
        point = groups.get("pt")
        if language == "en":
            nested = re.findall(r"\((\w{1,4})\)", text[match.end("first") : match.end("first") + 20].split(" ")[0])
            if nested:
                paragraph = nested[0] if re.fullmatch(r"\d+[a-z]?", nested[0]) else None
                rest = nested[1:] if paragraph else nested
                point = rest[0] if rest else point
            before = re.search(lang.before or "$^", text[max(0, match.start() - 90) : match.start()])
            if before:
                point = point or before.group("pt")
                paragraph = paragraph or before.group("par") or before.group("par2")
        numbers = [first]
        more = groups.get("more") or ""
        # "article 2, paragraphe 5, points 4) à 23)": what follows a
        # paragraph or a point lists points, not articles.
        if re.search(r"[^\W\d_]", text[match.end("first") : match.start("more")]):
            more = ""
        if more:
            numbers = _items(groups["first"] + more, lang) or [first]
        celex, scope, explicit = resolve(match.start(), match.end())
        for position, number in enumerate(numbers):
            add(
                UnitReference(
                    unit="article",
                    number=number,
                    celex=celex,
                    scope=scope,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0).strip(),
                    paragraph=paragraph if position == 0 else None,
                    point=point if position == 0 else None,
                ),
                explicit,
            )

    # Recitals: "recital 39", "considérants 39 et 40", "considerando (39)".
    recital_re = re.compile(
        rf"{lang.recital}\(?(?P<first>\d{{1,3}})\)?(?P<more>(?:(?:{lang.list_sep}|{lang.range_sep})\(?\d{{1,3}}\)?)*)"
    )
    for match in recital_re.finditer(text):
        numbers = _items(re.sub(r"[()]", "", match.group("first") + match.group("more")), lang) or [
            match.group("first")
        ]
        celex, scope, explicit = resolve(match.start(), match.end())
        for number in numbers:
            add(
                UnitReference("recital", number, celex, scope, match.start(), match.end(), match.group(0).strip()),
                explicit,
            )

    # Annexes: "Annex III", "annexes I et II", "the Annex" (single annex).
    annex_re = re.compile(
        rf"{lang.annex}(?:\s+(?P<first>{_ROMAN}|\d{{1,2}})\b(?P<more>(?:(?:{lang.list_sep}|{lang.range_sep}){_ROMAN}\b)*))?"
    )
    for match in annex_re.finditer(text):
        first = match.group("first")
        if first is None:
            # "Annex" alone: only "the Annex" / "l'annexe" / "o anexo" of this act.
            preceding = text[max(0, match.start() - 6) : match.start()].lower()
            if not re.search(r"(?:(?:^|[\s(])(?:the|o|ao|no|do)\s|l['’])$", preceding):
                continue
            annexes: list[str | None] = [None]
        else:
            more = match.group("more") or ""
            listed = [first, *re.findall(_ROMAN, more)]
            if re.search(lang.range_sep, more) and len(listed) == 2:
                listed = _roman_range(listed[0], listed[1]) or listed
            annexes = list(listed)
        celex, scope, explicit = resolve(match.start(), match.end())
        for annex in annexes:
            add(
                UnitReference("annex", annex, celex, scope, match.start(), match.end(), match.group(0).strip()),
                explicit,
            )
    references.sort(key=lambda reference: (reference.start, reference.unit))
    return _share_qualifiers(text, references, implicit)


# "Article 46(1) and Article 46(2)(c) of Regulation (EU) 2016/679", "à
# l'article 9 et à l'article 10 du règlement…": only the last reference of
# the pair names the act; the first one shares it.
def _bracketed_act(text: str, start: int, acts: list[ActMention]) -> ActMention | None:
    """The act named right before the bracket the reference sits in."""
    opening = text.rfind("(", max(0, start - 60), start)
    if opening == -1 or ")" in text[opening:start]:
        return None
    before = text[:opening].rstrip()
    return next((m for m in acts if m.celex is not None and m.end == len(before) and m.end > m.start), None)


_PAIR_GAP = re.compile(
    r"^[\s,]*(?:(?:and|or|et|ou|e|as\s+well\s+as|ainsi\s+qu['’]|bem\s+como)\s*)"
    r"(?:(?:à|a|de|du|des|aux?|ao|aos|do|dos|da|das|no|nos|na|nas|pelo|pela|pelos|pelas|par|in|to|of|under|with|by)\s+)?"
    r"(?:l['’]|the\s+|o\s+|os\s+)?$",
    re.IGNORECASE,
)


def _share_qualifiers(text: str, references: list[UnitReference], implicit: set[int]) -> list[UnitReference]:
    out = list(references)
    for index in range(len(out) - 2, -1, -1):
        current = out[index]
        if id(references[index]) not in implicit:
            continue
        following = next((ref for ref in out[index + 1 :] if ref.start > current.start), None)
        if following is None or following.unit != current.unit or following.start < current.end:
            continue
        if not _PAIR_GAP.match(text[current.end : following.start]):
            continue
        if following.celex == current.celex and following.scope == current.scope:
            continue
        for position in range(index, -1, -1):
            if out[position].start != current.start:
                break
            out[position] = replace(out[position], celex=following.celex, scope=following.scope, implicit=False)
    return out


_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman_to_int(value: str) -> int:
    total = 0
    for index, char in enumerate(value):
        current = _ROMAN_VALUES[char]
        following = _ROMAN_VALUES[value[index + 1]] if index + 1 < len(value) else 0
        total += -current if current < following else current
    return total


def int_to_roman(value: int) -> str:
    out = ""
    for number, letters in (
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ):
        while value >= number:
            out += letters
            value -= number
    return out


def _roman_range(low: str, high: str) -> list[str]:
    start, end = roman_to_int(low), roman_to_int(high)
    if not 0 < end - start <= 20:
        return []
    return [int_to_roman(value) for value in range(start, end + 1)]


# --- context of a unit -------------------------------------------------------

_AMENDING_RE = re.compile(
    r"(?:is|are)\s+(?:hereby\s+)?amended\s+as\s+follows|(?:est|sont)\s+modifi[ée]e?s?\s+comme\s+suit"
    r"|(?:é|são)\s+alterad[oa]s?\s+(?:do\s+seguinte\s+modo|da\s+seguinte\s+forma|como\s+segue)",
    re.IGNORECASE,
)


def amended_act(text: str) -> str | None:
    """CELEX of the act an amending article amends ("Regulation (EU)
    2024/1689 is amended as follows"), else None."""
    match = _AMENDING_RE.search(text)
    if match is None:
        return None
    before = [mention for mention in find_acts(text[: match.start()]) if mention.celex is not None]
    return before[-1].celex if before else None


def citation_act(text: str) -> str | None:
    """The act a preamble citation names first ("Having regard to
    Regulation (EU) 2022/2554…"); None for a treaty."""
    for mention in find_acts(text):
        return mention.celex
    return None
