"""Article versions: which ones apply on a date (phase 9.10, failure mode "versions").

A legal corpus keeps texts that no longer apply: the Code de la consommation
(`raglab legifrance fetch`) holds every version of every article, and the
compiled Brazilian laws of LexML keep repealed provisions in the text, marked
"(Revogado pela Lei nº ...)". A naive RAG ranks them like any other passage
and the model then cites, as if in force, a rule repealed years ago. The
classic trap: the old article L. 121-21 gave fourteen days to withdraw from a
contract; since the 2016 recodification that rule is article L. 221-18 and
the number L. 121-21 is about debt-collection fees.

The `versions` option says which versions retrieval may use:

* ``in_force`` (default): the versions in force at the reference date, today
  unless the question asks about the past ("avant 2016", "dans sa rédaction
  de 2014", "as of 2019-01-01"), in which case that date is used;
* ``as_of=YYYY-MM-DD``: the versions in force on that date;
* ``all``: every version, as a naive RAG sees them (the comparison baseline).

Two sources of version information:

* **metadata** (Légifrance, one document per article version): `etat`,
  `date_debut`, `date_fin`, `versions`, `ended_by`. Versions not in force at
  the reference date are filtered out in SQL, before ranking, so the top-k
  stays full (`RetrievalFilters.valid_at`);
* **markers** (LexML compiled texts, one document per law, no history): a
  chunk whose every provision is marked repealed ("(Revogado)", "(Revogada
  pela Lei nº ...)", "Vigência encerrada") is moved after the others; the
  wording in force is the one marked "(Redação dada pela Lei nº ...)", older
  wordings are not in the text. A past date cannot be honoured there.

Each returned chunk carries its version state (`RetrievedChunk.version`) and
the prompt tells the model ("version en vigueur depuis le ...", "abrogée le
..."), so the answer can say it. Chunking is untouched.

This module holds the rules (no database); `raglab.retrieval.versions`
applies them to a search.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from raglab.domain.schemas import ChunkVersion, RetrievedChunk

VERSION_MODES = ("in_force", "all", "as_of")
# Versions that never applied (annulled by a court).
_VOID_STATES = ("ANNULE",)


@dataclass(slots=True, frozen=True)
class VersionPolicy:
    """Which versions retrieval may use, and why."""

    mode: str
    #: Reference date; None only for `all`.
    on: date | None = None
    #: "default" (today), "request" (`as_of=` option), "question" (the
    #: question asks about the past).
    source: str = "default"
    #: The words of the question the date was read from.
    phrase: str | None = None

    @property
    def filters(self) -> bool:
        return self.mode != "all"

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "date": self.on.isoformat() if self.on else None,
            "source": self.source,
            "phrase": self.phrase,
        }


def parse_versions_option(value: str | None) -> tuple[str | None, date | None]:
    """ "in_force", "all", "as_of=2019-01-01" (or "as_of:..."), None.

    Raises ValueError on anything else (HTTP 422 / CLI error)."""
    if value is None or not str(value).strip():
        return None, None
    raw = str(value).strip()
    lowered = raw.lower()
    if lowered in ("in_force", "all"):
        return lowered, None
    match = re.fullmatch(r"as_of\s*[=:]\s*(\d{4}-\d{2}-\d{2})", raw, re.IGNORECASE)
    if match:
        try:
            return "as_of", date.fromisoformat(match.group(1))
        except ValueError as exc:
            raise ValueError(f"Date invalide dans l'option versions : {raw!r}") from exc
    raise ValueError(f"Option versions invalide : {raw!r} (attendu : in_force, all ou as_of=AAAA-MM-JJ)")


# --- Dates in questions --------------------------------------------------

_MONTHS = {
    # fr
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    # pt
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
    "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    # en
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}  # fmt: skip
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
# A date: ISO, dd/mm/yyyy, "1er janvier 2019", "1º de janeiro de 2019",
# "January 1, 2019", "1 January 2019", a month ("mars 2015", "março de
# 2015"), or a bare year.
_DATE = (
    r"(?:(?P<iso>\d{4}-\d{2}-\d{2})"
    r"|(?P<dmy>\d{1,2}[/.]\d{1,2}[/.]\d{4})"
    rf"|(?P<day>\d{{1,2}})(?:er|º|°|o)?\s+(?:de\s+)?(?P<month>{_MONTH_NAMES})\s+(?:de\s+)?(?P<year1>\d{{4}})"
    rf"|(?P<month2>{_MONTH_NAMES})\s+(?P<day2>\d{{1,2}}),?\s+(?P<year2>\d{{4}})"
    rf"|(?P<month3>{_MONTH_NAMES})\s+(?:de\s+)?(?P<year3>\d{{4}})"
    r"|(?P<year>(?:19|20)\d{2})(?![\d/.-]))"
)
# Cue words that make a date a reference date rather than a text's date
# ("loi n° 2014-344 du 17 mars 2014" names a law, it does not ask about
# 2014). `before`: the day before the date; `at`: the date itself.
_BEFORE_CUES = (
    r"avant(?:\s+(?:la\s+)?(?:r[ée]forme|recodification)\s+de)?",
    r"ant[ée]rieurement\s+(?:au|[àa])",
    r"(?:dans\s+sa|selon\s+sa|en\s+sa)\s+(?:version|r[ée]daction)\s+ant[ée]rieure\s+(?:au|[àa])(?:\s+la\s+r[ée]forme\s+de)?",
    r"antes\s+(?:de|do|da)(?:\s+reforma\s+de)?",
    r"(?:na|em\s+sua)\s+(?:reda[çc][ãa]o|vers[ãa]o)\s+anterior\s+(?:a|ao|[àa])",
    r"before(?:\s+the\s+\w+\s+of)?",
    r"prior\s+to",
)
_AT_CUES = (
    r"(?:dans\s+sa|selon\s+sa|en\s+sa)\s+(?:version|r[ée]daction)(?:\s+en\s+vigueur)?\s+(?:de|du|en|au|le|[àa]\s+la\s+date\s+du)",
    r"(?:version|r[ée]daction)\s+(?:en\s+vigueur|applicable)\s+(?:en|au|le)",
    r"(?:en\s+vigueur|applicable)\s+(?:en|au|le)",
    r"[àa]\s+la\s+date\s+du",
    r"au",
    r"(?:na|em\s+sua)\s+(?:reda[çc][ãa]o|vers[ãa]o)(?:\s+(?:vigente|em\s+vigor))?\s+(?:de|em)",
    r"(?:vigente|em\s+vigor)\s+em",
    r"as\s+(?:of|at)",
    r"(?:in\s+force|applicable)\s+(?:in|on)",
    r"as\s+it\s+stood\s+(?:in|on)",
    r"(?:version|wording)\s+(?:of|from|in\s+force\s+in)",
    # How a user dates a situation: "en 2015, j'ai signé...", "acheté en
    # mars 2015", "signé le 3 mars 2015", "em 2015", "in March 2015".
    r"(?:sign[ée]e?s?|achet[ée]e?s?|conclue?s?|souscrite?s?|command[ée]e?s?|pass[ée]e?s?)\s+le",
    r"en",
    r"em",
    r"in",
    r"on",
)
_CUE_RE = re.compile(
    rf"\b(?:(?P<before>{'|'.join(_BEFORE_CUES)})|(?P<at>{'|'.join(_AT_CUES)}))\s+(?:(?:le|o|the)\s+)?{_DATE}",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    """Lowercase without accents (month names), same length as `text`
    for the characters used here."""
    return "".join(char for char in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(char) != "Mn")


@dataclass(slots=True, frozen=True)
class QuestionDate:
    on: date
    phrase: str


def _match_date(match: re.Match[str]) -> tuple[date, str] | None:
    """(date, precision: "day", "month" or "year") of a `_DATE` match; a
    month or a year is given by its last day."""
    groups = match.groupdict()
    try:
        if groups.get("iso"):
            return date.fromisoformat(groups["iso"]), "day"
        if groups.get("dmy"):
            day, month, year = (int(part) for part in re.split(r"[/.]", groups["dmy"]))
            return date(year, month, day), "day"
        if groups.get("month"):
            return date(int(groups["year1"]), _MONTHS[_fold(groups["month"])], int(groups["day"])), "day"
        if groups.get("month2"):
            return date(int(groups["year2"]), _MONTHS[_fold(groups["month2"])], int(groups["day2"])), "day"
        if groups.get("month3"):
            year, month = int(groups["year3"]), _MONTHS[_fold(groups["month3"])]
            return date(year, month, calendar.monthrange(year, month)[1]), "month"
        if groups.get("year"):
            return date(int(groups["year"]), 12, 31), "year"
    except (ValueError, KeyError):
        return None
    return None


def parse_question_date(question: str, *, today: date | None = None) -> QuestionDate | None:
    """The date a question asks about, when it asks about the past.

    "avant 2016" -> 2015-12-31; "avant le 1er juillet 2016" -> 2016-06-30;
    "dans sa rédaction de 2014", "en vigueur en 2014", "na redação de 2014",
    "as of 2014" -> 2014-12-31 (a year means its last day: the latest
    wording of that year); "au 1er janvier 2019", "as of 2019-01-01" -> that
    day. A situation is dated the way a user says it: "en 2015, j'ai
    signé..." -> 2015-12-31, "acheté en mars 2015" -> 2015-03-31, "signé le 3
    mars 2015", "em 2015", "in March 2015". Dates of texts ("loi n° 2014-344
    du 17 mars 2014", "Lei nº 8.078, de 1990") are not cues; a date after
    `today` is ignored.
    """
    today = today or date.today()
    folded = _fold(question)
    for match in _CUE_RE.finditer(folded):
        parsed = _match_date(match)
        if parsed is None:
            continue
        day, precision = parsed
        if match.group("before"):
            # The day before the period starts.
            if precision == "year":
                day = date(day.year - 1, 12, 31)
            elif precision == "month":
                day = day.replace(day=1) - timedelta(days=1)
            else:
                day = day - timedelta(days=1)
        if day > today:
            continue
        return QuestionDate(on=day, phrase=question[match.start() : match.end()])
    return None


def resolve_policy(
    option: str | None,
    question: str,
    *,
    default_mode: str = "in_force",
    today: date | None = None,
) -> VersionPolicy:
    """The policy of one request: the option (None = `default_mode`), then
    the question's own date for `in_force`."""
    today = today or date.today()
    mode, on = parse_versions_option(option)
    if mode is None:
        mode, on = parse_versions_option(default_mode)
        mode = mode or "in_force"
        source = "default"
    else:
        source = "request"
    if mode == "all":
        return VersionPolicy(mode="all", source=source)
    if mode == "as_of" and on is not None:
        return VersionPolicy(mode="as_of", on=on, source=source)
    asked = parse_question_date(question, today=today)
    if asked is not None:
        return VersionPolicy(mode="as_of", on=asked.on, source="question", phrase=asked.phrase)
    return VersionPolicy(mode="in_force", on=today, source=source)


# --- Validity from metadata (Légifrance) ---------------------------------


def is_versioned(metadata: dict[str, Any] | None) -> bool:
    return bool(metadata) and "etat" in metadata  # type: ignore[operator]


def valid_at(metadata: dict[str, Any], on: date) -> bool:
    """A version applies on `on`: started on or before it, not ended yet.

    The dates decide, not `etat`, which is the state when the corpus was
    frozen (an ABROGE_DIFF version is still in force until its end date).
    """
    if metadata.get("etat") in _VOID_STATES:
        return False
    start = metadata.get("date_debut")
    end = metadata.get("date_fin")
    day = on.isoformat()
    return (not start or str(start) <= day) and (not end or str(end) > day)


def _text_title(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("title") or None
    return None


def metadata_version(metadata: dict[str, Any], on: date | None) -> ChunkVersion:
    """Version state of a Légifrance article version at `on` (None = today)."""
    on = on or date.today()
    versions = [row for row in metadata.get("versions") or [] if isinstance(row, dict)]
    legi_id = metadata.get("legi_id")
    position = next((index for index, row in enumerate(versions) if row.get("legi_id") == legi_id), None)
    following = versions[position + 1] if position is not None and position + 1 < len(versions) else None
    current = next((row for row in versions if valid_at(row, on)), None)
    return ChunkVersion(
        source="metadata",
        etat=metadata.get("etat"),
        in_force=valid_at(metadata, on),
        reference_date=on.isoformat(),
        date_debut=metadata.get("date_debut"),
        date_fin=metadata.get("date_fin"),
        article=metadata.get("article_label") or metadata.get("article_number"),
        legi_id=legi_id,
        amended_by=_text_title(metadata.get("amended_by")),
        ended_by=_text_title(metadata.get("ended_by")),
        replaced_by=(
            {"legi_id": following.get("legi_id"), "date_debut": following.get("date_debut")} if following else None
        ),
        in_force_version=(
            current.get("legi_id") if current is not None and current.get("legi_id") != legi_id else None
        ),
        version_count=int(metadata.get("version_count") or len(versions) or 1),
    )


# --- Markers in compiled texts (LexML) -----------------------------------

# "(Revogado)", "(Revogada pela Lei nº 11.907, de 2009)", "(Revogados ...)",
# "Vigência encerrada"; "(Vide ...)" and "(Incluído ...)" are not repeals.
_REVOKED_RE = re.compile(r"\(\s*Revogad[oa]s?\b[^)]*\)?|Vig[êe]ncia\s+encerrada", re.IGNORECASE)
_REWRITTEN_RE = re.compile(
    r"\(\s*Reda[çc][ãa]o\s+dada\s+pel[oa]\s+([^)]*?)\)",
    re.IGNORECASE,
)
_YEAR_IN_MARKER_RE = re.compile(r"\b((?:19|20)\d{2})\b")
# Lines without content of their own: headings, a provision number alone.
_HEADING_RE = re.compile(r"^(?:T[ÍI]TULO|CAP[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O|LIVRO|PARTE)\b", re.IGNORECASE)
_MAX_MARKERS = 3


def marker_version(text: str) -> ChunkVersion | None:
    """Version state of a compiled-law chunk read from its markers; None
    when the chunk has none.

    `revoked_only`: every provision of the chunk is marked repealed, so the
    chunk says nothing that is still in force.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    provisions = [line for line in lines if not _HEADING_RE.match(line)]
    revoked = [line for line in provisions if _REVOKED_RE.search(line)]
    rewritten = [match.group(1).strip() for match in _REWRITTEN_RE.finditer(text)]
    if not revoked and not rewritten:
        return None
    markers = [_REVOKED_RE.search(line).group(0).strip("() ") for line in revoked[:_MAX_MARKERS]]  # type: ignore[union-attr]
    years = sorted(int(year) for text_ in rewritten for year in _YEAR_IN_MARKER_RE.findall(text_))
    return ChunkVersion(
        source="markers",
        in_force=not (provisions and len(revoked) == len(provisions)),
        revoked_lines=len(revoked),
        rewritten_lines=len(rewritten),
        revoked_only=bool(provisions) and len(revoked) == len(provisions),
        amended_by=f"Redação dada pela {rewritten[-1]}" if rewritten else None,
        last_amended_year=years[-1] if years else None,
        markers=markers,
    )


def strip_revoked(text: str) -> str:
    """The chunk text with every provision marked repealed replaced by a
    short note: the model does not read repealed wording as in force."""
    output: list[str] = []
    for line in text.splitlines():
        match = _REVOKED_RE.search(line)
        if match is None:
            output.append(line)
            continue
        number = re.match(r"\s*((?:Art\.|§|[IVXLC]+\s*-|[a-z]\))\s*[\wº°-]*)", line)
        label = f"{number.group(1).strip()} " if number else ""
        output.append(f"{label}[disposition abrogée : {match.group(0).strip('() ')}]")
    return "\n".join(output)


def is_outdated(chunk: dict[str, Any] | RetrievedChunk, on: date | None = None) -> bool:
    """The chunk comes from a version that does not apply on `on` (metadata:
    re-checked at that date when the raw dates are known), or says only
    repealed provisions (markers)."""
    version = chunk.get("version") if isinstance(chunk, dict) else chunk.version
    if version is None:
        return False
    data = version if isinstance(version, dict) else version.model_dump()
    if data.get("source") == "metadata":
        if on is not None:
            return not valid_at(data, on)
        return data.get("in_force") is False
    return bool(data.get("revoked_only"))


# --- Prompt ---------------------------------------------------------------


def _fr_date(value: str | None) -> str:
    if not value:
        return "?"
    try:
        day = date.fromisoformat(str(value))
    except ValueError:
        return str(value)
    months = (
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    )  # fmt: skip
    return f"{'1er' if day.day == 1 else day.day} {months[day.month - 1]} {day.year}"


def prompt_line(version: ChunkVersion | None, *, today: date | None = None) -> str | None:
    """One line telling the model the version state of a passage.

    `today` freezes the clock: the reference date is only mentioned when it
    is not today, so replaying a recorded context needs the day it was shown."""
    if version is None or not version.in_prompt:
        return None
    if version.source == "markers":
        if version.revoked_only:
            return "Statut : dispositions abrogées (« Revogado ») — ne pas les présenter comme en vigueur."
        parts = []
        if version.revoked_lines:
            parts.append(f"{version.revoked_lines} disposition(s) abrogée(s), remplacées par une note")
        if version.amended_by:
            parts.append(f"rédaction actuelle : {version.amended_by}")
        return "Statut : texte consolidé ; " + " ; ".join(parts) + "." if parts else None
    label = f"article {version.article}" if version.article else "article"
    if version.in_force:
        since = f" depuis le {_fr_date(version.date_debut)}" if version.date_debut else ""
        until = f", jusqu'au {_fr_date(version.date_fin)}" if version.date_fin else ""
        reference = (
            f" (à la date du {_fr_date(version.reference_date)})"
            if version.reference_date and version.reference_date != (today or date.today()).isoformat()
            else ""
        )
        return f"Statut : version de l'{label} en vigueur{since}{until}{reference}."
    if version.etat in ("ABROGE", "ABROGE_DIFF", "TRANSFERE", "ANNULE") and not version.replaced_by:
        reason = {"TRANSFERE": "transférée", "ANNULE": "annulée"}.get(version.etat or "", "abrogée")
        by = f" par {version.ended_by}" if version.ended_by else ""
        return f"Statut : version de l'{label} {reason} le {_fr_date(version.date_fin)}{by} — plus en vigueur."
    period = f"du {_fr_date(version.date_debut)} au {_fr_date(version.date_fin)}"
    by = f", remplacée par {version.ended_by}" if version.ended_by else ""
    return f"Statut : ancienne version de l'{label} ({period}){by} — plus en vigueur."
