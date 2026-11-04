"""Build the frozen "versions" question set over a French code (phase 9.10).

The failure mode: a naive RAG answers from a version of an article that no
longer applies. The Code de la consommation (`raglab legifrance fetch`) keeps
every version of every article, one document each, so the traps are real and
can be found without a model. Four kinds, each a `question_type`:

* ``rewritten`` — the article in force was rewritten: a line of the current
  version and its counterpart in an older version differ ("quatorze jours"
  where it said "sept jours"). The question is answered by the current line;
  the older version is the trap, and its wording the outdated answer;
* ``reused_number`` — the 2016 recodification gave the number of a repealed
  article to another rule (old L. 121-21: fourteen days to withdraw; today's
  L. 121-21: debt-collection fees). The question cites the number about the
  current rule; the old article of the same number is the trap;
* ``moved`` — a repealed article whose rule lives on under another number
  (old L. 121-21 -> L. 221-18), found by text overlap. The question
  paraphrases the rule; the repealed article is the trap, and its number
  the outdated citation;
* ``as_of`` — the question asks about the past ("avant 2016", "avant le 14
  juin 2014"): the expected version is the one in force on that date, the
  current wording is the trap. It checks that the date is read and honoured.

Questions are situations, as a consumer, a company or a lawyer asks them
(« Mon client a sept jours pour se rétracter, c'est bien ça ? »): no article
number (except for `reused_number`, where the user cites the number they
were given), no code name, no wording copied from the article, a past date
said the way a user dates a situation ("en 2021", "en mai 2014").

Pairs are mined by rules (version history, line diff, word overlap); a
local model (Qwen3.6 via llama.cpp, `LocalLLMServer`) writes one question
per pair with the answer quoted from the expected version and, for
`rewritten` / `as_of`, the outdated answer quoted from the trap. A question
is kept only if both quotes are found where they must be (and not in the
other version), so every case is a trap by construction. Gold passages are
`expected_spans` on the expected version; `trap` names the misleading
version(s); `context.as_of` the date the question asks about; a seeded
`split` (`dev` / `heldout`) as for the other sets.
"""

from __future__ import annotations

import difflib
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from raglab.benchmarks.base import GroundTruthCase, write_ground_truth, write_metadata
from raglab.benchmarks.legi_questions import (
    _body_start,
    assign_splits,
    cites_reference,
    text_rejection_reason,
)
from raglab.benchmarks.lexml_questions import _parse, lexical_overlap
from raglab.benchmarks.squad_style import locate_span
from raglab.config import Settings, get_settings
from raglab.domain.versions import _fr_date, parse_question_date, valid_at
from raglab.legifrance.codes import find_code_mentions
from raglab.legifrance.collector import IN_FORCE_STATES
from raglab.legifrance.references import article_label
from raglab.llm.openai_compat import OpenAICompatibleChat
from raglab.logging_utils import log_event
from raglab.ollama.service import OllamaService
from raglab.retrieval.citations import parse_citation

LOGGER = logging.getLogger(__name__)

TRAP_KINDS = ("rewritten", "reused_number", "moved", "as_of")
# Share of each kind in the set (rounded; the remainder goes to `rewritten`).
KIND_SHARES = {"rewritten": 0.4, "reused_number": 0.2, "moved": 0.2, "as_of": 0.2}
_PREFIXED_NUMBER_RE = re.compile(r"^(?:LO|L|R|D|A)\d")
_WORD_RE = re.compile(r"\w+", re.UNICODE)
# A line worth asking about: a duration, an amount, a share, a count.
_QUANTITY_RE = re.compile(
    r"\d|\b(?:un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|quinze|vingt|trente|quarante|"
    r"cinquante|soixante|cent|mille)\b|\b(?:jours?|mois|ans?|ann[ée]es?|euros?|semaines?|heures?)\b",
    re.IGNORECASE,
)
MIN_LINE_CHARS = 60
# Old and new line are the same provision (word-level ratio >= MIN) but say
# something different: at least one word changed (ratio < 1; punctuation
# alone does not count, words are compared).
LINE_RATIO_MIN = 0.55
LINE_RATIO_MAX = 1.0
# Word-set Jaccard: same rule (rewritten) / another rule (reused number).
SAME_RULE_JACCARD = 0.45
OTHER_RULE_JACCARD = 0.15
# Word 3-gram shingles shared by a repealed article and its successor.
MOVED_SHINGLE_JACCARD = 0.5
PASSAGE_CHARS = 500


@dataclass(slots=True)
class Version:
    file_name: str
    legi_id: str
    code: str
    code_title: str
    article_number: str
    etat: str
    date_debut: str | None
    date_fin: str | None
    path: list[str]
    text: str
    body_start: int

    @property
    def body(self) -> str:
        return self.text[self.body_start :]

    @property
    def in_force(self) -> bool:
        return self.etat in IN_FORCE_STATES

    def lines(self) -> list[tuple[int, int, str]]:
        """(start, end, text) of each non-empty body line, offsets in `text`."""
        rows: list[tuple[int, int, str]] = []
        offset = self.body_start
        for line in self.body.split("\n"):
            if line.strip():
                rows.append((offset, offset + len(line), line))
            offset += len(line) + 1
        return rows

    def as_trap(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "legi_id": self.legi_id,
            "article": self.article_number,
            "etat": self.etat,
            "date_debut": self.date_debut,
            "date_fin": self.date_fin,
        }


@dataclass(slots=True)
class TrapCandidate:
    kind: str
    #: The version that answers (in force, or in force on `as_of`).
    expected: Version
    #: The versions that would mislead, most misleading first.
    traps: list[Version]
    #: Passage of `expected` the question is about.
    start: int
    end: int
    #: Counterpart of the passage in the first trap (rewritten / as_of).
    trap_passage: str | None = None
    as_of: date | None = None
    as_of_phrase: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def passage(self) -> str:
        return self.expected.text[self.start : self.end]


def load_versions(corpus_dir: Path) -> dict[tuple[str, str], list[Version]]:
    """Every article version of the corpus, by (code, article number), oldest first."""
    by_number: dict[tuple[str, str], list[Version]] = {}
    for sidecar in sorted(corpus_dir.glob("*.json")):
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        number = metadata.get("article_number")
        if not number or not _PREFIXED_NUMBER_RE.match(number):
            continue
        text = sidecar.with_suffix(".txt").read_text(encoding="utf-8")
        version = Version(
            file_name=sidecar.with_suffix(".txt").name,
            legi_id=str(metadata.get("legi_id", "")),
            code=str(metadata.get("code", "")),
            code_title=str(metadata.get("code_title", "")),
            article_number=number,
            etat=str(metadata.get("etat", "")),
            date_debut=metadata.get("date_debut"),
            date_fin=metadata.get("date_fin"),
            path=[str(title) for title in metadata.get("path") or []],
            text=text,
            body_start=_body_start(text),
        )
        by_number.setdefault((version.code, number), []).append(version)
    for rows in by_number.values():
        rows.sort(key=lambda row: (row.date_debut or "", row.legi_id))
    return by_number


def _words(text: str) -> set[str]:
    return {word.lower() for word in _WORD_RE.findall(text) if len(word) > 2}


def _jaccard(a: set[Any], b: set[Any]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def _shingles(text: str, size: int = 3) -> set[tuple[str, ...]]:
    words = [word.lower() for word in _WORD_RE.findall(text)]
    return {tuple(words[index : index + size]) for index in range(max(0, len(words) - size + 1))}


def _expand(version: Version, first: int, last: int, target: int = PASSAGE_CHARS) -> tuple[int, int]:
    """Grow a passage of whole lines around lines[first..last] to `target` chars."""
    lines = version.lines()
    while lines[last][1] - lines[first][0] < target and (first > 0 or last + 1 < len(lines)):
        if last + 1 < len(lines):
            last += 1
        elif first > 0:
            first -= 1
        if lines[last][1] - lines[first][0] >= target:
            break
    return lines[first][0], lines[last][1]


def changed_lines(new: Version, old: Version) -> list[tuple[int, str]]:
    """Lines of `new` (by index) whose best counterpart in `old` is the same
    provision reworded: (index in new.lines(), old line)."""
    # Compared word by word (fast, and a changed number is a changed word).
    old_lines = [(text, _WORD_RE.findall(text.lower())) for _, _, text in old.lines()]
    old_texts = {text for text, _ in old_lines}
    pairs: list[tuple[int, str]] = []
    for index, (_, _, line) in enumerate(new.lines()):
        if len(line) < MIN_LINE_CHARS or not _QUANTITY_RE.search(line) or line in old_texts:
            continue
        matcher = difflib.SequenceMatcher(None, autojunk=False)
        matcher.set_seq2(_WORD_RE.findall(line.lower()))
        best, best_ratio = "", 0.0
        for text, words in old_lines:
            matcher.set_seq1(words)
            if matcher.real_quick_ratio() <= best_ratio or matcher.quick_ratio() <= best_ratio:
                continue
            ratio = matcher.ratio()
            if ratio > best_ratio:
                best, best_ratio = text, ratio
        if LINE_RATIO_MIN <= best_ratio < LINE_RATIO_MAX and best not in new.body:
            pairs.append((index, best))
    return pairs


def mine_rewritten(by_number: dict[tuple[str, str], list[Version]]) -> list[TrapCandidate]:
    """Current version vs the latest older version of the same rule."""
    candidates: list[TrapCandidate] = []
    for rows in by_number.values():
        current = next((row for row in reversed(rows) if row.in_force), None)
        if current is None:
            continue
        current_words = _words(current.body)
        older = [row for row in rows if row is not current and not row.in_force]
        for old in reversed(older):
            if _jaccard(current_words, _words(old.body)) < SAME_RULE_JACCARD:
                continue
            pairs = changed_lines(current, old)
            if not pairs:
                continue
            index, old_line = pairs[0]
            start, end = _expand(current, index, index)
            candidates.append(TrapCandidate("rewritten", current, [old], start, end, trap_passage=old_line))
            break
    return candidates


def mine_as_of(by_number: dict[tuple[str, str], list[Version]], *, today: date | None = None) -> list[TrapCandidate]:
    """An older version, asked about on a date it applied; the current
    wording is the trap. The date phrase is "avant <année>" when the older
    version covered the whole previous year, else "avant le <date>"."""
    today = today or date.today()
    candidates: list[TrapCandidate] = []
    for rows in by_number.values():
        current = next((row for row in reversed(rows) if row.in_force), None)
        if current is None:
            continue
        older = [row for row in rows if not row.in_force and row.date_fin and row.date_debut]
        for old in reversed(older):
            if _jaccard(_words(current.body), _words(old.body)) < SAME_RULE_JACCARD:
                continue
            pairs = changed_lines(old, current)
            if not pairs:
                continue
            dated = situation_date(old)
            if dated is None or dated[1] > today:
                continue
            phrase, on = dated
            index, current_line = pairs[0]
            start, end = _expand(old, index, index)
            others = [row for row in rows if row is not old and not valid_at(_meta(row), on)]
            traps = [current, *(row for row in others if row is not current)]
            candidates.append(
                TrapCandidate("as_of", old, traps, start, end, trap_passage=current_line, as_of=on, as_of_phrase=phrase)
            )
            break
    return candidates


_MONTH_NAMES = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip


def situation_date(old: Version) -> tuple[str, date] | None:
    """How a user would date a situation the old version covers, and the
    date `parse_question_date` reads from it: "en 2021" (the old version
    still applied on 31 December), else "en mai 2014" (the month before it
    ended), else "avant le 14 juin 2014"."""
    if not old.date_fin:
        return None
    end_day = date.fromisoformat(str(old.date_fin))
    metadata = _meta(old)
    year_end = date(end_day.year - 1, 12, 31)
    if valid_at(metadata, year_end):
        return f"en {year_end.year}", year_end
    month_end = end_day.replace(day=1) - timedelta(days=1)
    if valid_at(metadata, month_end):
        return f"en {_MONTH_NAMES[month_end.month - 1]} {month_end.year}", month_end
    day_before = end_day - timedelta(days=1)
    if valid_at(metadata, day_before):
        return f"avant le {_fr_date(end_day.isoformat())}", day_before
    return None


def _meta(version: Version) -> dict[str, Any]:
    return {"etat": version.etat, "date_debut": version.date_debut, "date_fin": version.date_fin}


def mine_reused_numbers(by_number: dict[tuple[str, str], list[Version]]) -> list[TrapCandidate]:
    """A number whose old versions are about another rule than the current one."""
    candidates: list[TrapCandidate] = []
    for rows in by_number.values():
        current = next((row for row in reversed(rows) if row.in_force), None)
        if current is None or len(current.body) < 200:
            continue
        current_words = _words(current.body)
        others = [
            row for row in rows if not row.in_force and _jaccard(current_words, _words(row.body)) < OTHER_RULE_JACCARD
        ]
        if not others:
            continue
        lines = current.lines()
        start, end = _expand(current, 0, 0) if lines else (current.body_start, len(current.text))
        candidates.append(TrapCandidate("reused_number", current, list(reversed(others)), start, end))
    return candidates


def mine_moved(by_number: dict[tuple[str, str], list[Version]]) -> list[TrapCandidate]:
    """A repealed article whose text lives on in a current article of
    another number (the 2016 recodification renumbered most of the code)."""
    current_by_shingle: dict[tuple[str, ...], set[int]] = {}
    current: list[Version] = []
    for rows in by_number.values():
        version = next((row for row in reversed(rows) if row.in_force), None)
        if version is not None and len(version.body) >= 200:
            current.append(version)
    shingles = [_shingles(version.body) for version in current]
    for position, grams in enumerate(shingles):
        for gram in grams:
            current_by_shingle.setdefault(gram, set()).add(position)
    candidates: list[TrapCandidate] = []
    for rows in by_number.values():
        repealed = [row for row in rows if row.etat in ("ABROGE", "TRANSFERE") and len(row.body) >= 200]
        if not repealed:
            continue
        old = repealed[-1]
        old_grams = _shingles(old.body)
        counts: dict[int, int] = {}
        for gram in old_grams:
            for position in current_by_shingle.get(gram, ()):
                counts[position] = counts.get(position, 0) + 1
        best = max(counts, key=lambda position: counts[position], default=None)
        if best is None:
            continue
        successor = current[best]
        if successor.article_number == old.article_number:
            continue
        if _jaccard(old_grams, shingles[best]) < MOVED_SHINGLE_JACCARD:
            continue
        pairs = changed_lines(successor, old)
        lines = successor.lines()
        index = (
            pairs[0][0]
            if pairs
            else next((i for i, (_, _, text) in enumerate(lines) if len(text) >= MIN_LINE_CHARS), 0)
        )
        start, end = _expand(successor, index, index)
        candidates.append(
            TrapCandidate("moved", successor, [old], start, end, trap_passage=pairs[0][1] if pairs else None)
        )
    return candidates


def mine_candidates(corpus_dir: Path, *, today: date | None = None) -> dict[str, list[TrapCandidate]]:
    by_number = load_versions(corpus_dir)
    return {
        "rewritten": mine_rewritten(by_number),
        "reused_number": mine_reused_numbers(by_number),
        "moved": mine_moved(by_number),
        "as_of": mine_as_of(by_number, today=today),
    }


def kind_quotas(count: int) -> dict[str, int]:
    quotas = {kind: round(count * share) for kind, share in KIND_SHARES.items()}
    quotas["rewritten"] += count - sum(quotas.values())
    return quotas


# --- Questions -------------------------------------------------------------

_SYSTEM_PROMPT = """Tu crées des questions pièges pour évaluer un moteur de \
recherche sur un code juridique français qui contient aussi les anciennes \
versions de ses articles. Tu reçois la place de l'article dans le code \
(PLAN), un EXTRAIT de la version qui répond, parfois l'ANCIENNE RÉDACTION \
correspondante, et une CONSIGNE. Écris UNE question en français dont la \
réponse se trouve dans l'EXTRAIT, et la RÉPONSE courte copiée mot pour mot \
de l'EXTRAIT.

La question est celle d'un vrai utilisateur : un consommateur, une \
entreprise ou un avocat face à une situation concrète, en français naturel \
(ex. : « Mon client a acheté un canapé en ligne il y a dix jours, peut-il \
encore se rétracter ? », « Un vendeur peut-il me facturer des frais de \
recouvrement ? »). Elle peut affirmer l'ancienne règle comme une croyance à \
vérifier (« Mon client a sept jours pour se rétracter, c'est bien ça ? »).

Règles :
* La question doit avoir un sens seule, pour qui n'a pas lu l'extrait : \
la situation précise le sujet pour qu'une seule réponse existe dans tout le \
code. N'écris jamais « cet article », « cet extrait », « le présent code », \
« mentionné », « selon le texte ».
* Ne recopie pas la formulation de l'extrait : dis la situation avec tes mots.
* La réponse est une copie exacte d'un morceau de l'EXTRAIT (2 à 25 mots).
* Quand une ANCIENNE RÉDACTION est fournie, la question porte sur ce qui a \
changé entre les deux, et tu donnes aussi la RÉPONSE PÉRIMÉE : le morceau \
correspondant, copié mot pour mot de l'ANCIENNE RÉDACTION.

Réponds uniquement en JSON : {"question": "...", "answer": "...", "outdated_answer": "..."} \
(sans "outdated_answer" quand aucune ANCIENNE RÉDACTION n'est fournie)."""

_INSTRUCTIONS = {
    "rewritten": (
        "Une situation d'aujourd'hui, sans numéro d'article, sans nom de code ni date ; la réponse "
        "diffère de l'ancienne rédaction, que la question peut avancer comme une croyance à vérifier."
    ),
    "reused_number": (
        "Une situation dans laquelle l'utilisateur cite l'article indiqué en RÉFÉRENCE, comme on le "
        "lui a cité (ex. : « Un recouvreur me réclame des frais ; que dit l'article L. 121-21 du code "
        "de la consommation ? »)."
    ),
    "moved": "Une situation, sans numéro d'article ni nom de code.",
    "as_of": (
        "Une situation passée, datée comme le dirait l'utilisateur avec mot pour mot l'expression de "
        "DATE fournie (ex. : « J'ai signé {phrase} un contrat ... : de combien de temps disposais-je ? ») ; "
        "sans numéro d'article ni nom de code ; la réponse diffère de la rédaction actuelle (fournie comme "
        "ANCIENNE RÉDACTION)."
    ),
}
# A question that copies this many consecutive words of the article is a
# Ctrl+F, not a user's question.
MAX_COPIED_WORDS = 6


def copied_wording(question: str, *texts: str, size: int = MAX_COPIED_WORDS) -> bool:
    """The question repeats `size` consecutive words of one of the texts."""
    words = [word.lower() for word in _WORD_RE.findall(question)]
    grams = {tuple(words[index : index + size]) for index in range(len(words) - size + 1)}
    return any(grams & _shingles(text, size) for text in texts) if grams else False


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def rejection_reason(generated: dict[str, str] | None, candidate: TrapCandidate) -> str | None:
    """Why a written question is not a valid trap of its kind (None = keep)."""
    if generated is None:
        return "invalid_json"
    span = locate_span(candidate.passage, generated["answer"])
    if span is None:
        return "quote_not_found"
    question = generated["question"]
    reason = text_rejection_reason(question, span["text"])
    if reason is not None:
        return reason
    answer = _normalise(span["text"])
    trap_texts = [_normalise(trap.body) for trap in candidate.traps]
    if candidate.kind in ("rewritten", "as_of", "reused_number") and answer in trap_texts[0]:
        # The outdated version gives the same answer: no trap.
        return "answer_in_trap"
    if candidate.kind in ("rewritten", "as_of"):
        outdated = _normalise(generated.get("outdated_answer") or "")
        if not outdated or outdated not in trap_texts[0]:
            return "outdated_answer_not_found"
        if outdated in _normalise(candidate.expected.body):
            return "outdated_answer_in_expected"
    if copied_wording(question, candidate.expected.body, *(trap.body for trap in candidate.traps)):
        return "copies_wording"
    if candidate.kind == "reused_number":
        passage = _ReferencePassage(candidate.expected)
        if not cites_reference(question, passage):  # type: ignore[arg-type]
            return "reference_missing"
    elif parse_citation(question) is not None or re.search(r"\barticles?\s+(?:[LRDA]\.?\s*)?\d", question, re.I):
        return "leaks_reference"
    elif find_code_mentions(question):
        return "names_code"
    asked = parse_question_date(question)
    if candidate.kind == "as_of":
        if asked is None or not valid_at(_meta(candidate.expected), asked.on):
            return "date_missing"
    elif asked is not None:
        return "unexpected_date"
    return None


@dataclass(slots=True)
class _ReferencePassage:
    """What `cites_reference` reads from a passage."""

    version: Version

    @property
    def article_number(self) -> str:
        return self.version.article_number

    @property
    def code(self) -> str:
        return self.version.code


def build_case(case_id: str, candidate: TrapCandidate, generated: dict[str, str]) -> GroundTruthCase:
    span = locate_span(candidate.passage, generated["answer"])
    assert span is not None
    expected = candidate.expected
    outdated_answer = generated.get("outdated_answer") if candidate.kind in ("rewritten", "as_of") else None
    trap = {
        "kind": candidate.kind,
        "file_names": [version.file_name for version in candidate.traps],
        "versions": [version.as_trap() for version in candidate.traps],
        "article": candidate.traps[0].article_number,
        **({"answer": outdated_answer, "expected_answer": span["text"]} if outdated_answer else {}),
    }
    return GroundTruthCase(
        id=case_id,
        question=generated["question"],
        expected_file_names=[expected.file_name],
        ground_truth_answer=span["text"],
        expected_substrings=[span["text"]],
        expected_spans=[
            {
                "file_name": expected.file_name,
                "start": candidate.start + span["start"],
                "end": candidate.start + span["end"],
                "text": span["text"],
            }
        ],
        question_type=candidate.kind,
        lexical_overlap=round(lexical_overlap(generated["question"], candidate.passage), 3),
        review_status="generated",
        context={
            "article": expected.article_number,
            "legi_id": expected.legi_id,
            "etat": expected.etat,
            "date_debut": expected.date_debut,
            "date_fin": expected.date_fin,
            **(
                {"as_of": candidate.as_of.isoformat(), "as_of_phrase": candidate.as_of_phrase}
                if candidate.as_of
                else {}
            ),
        },
        trap=trap,
    )


class LegiVersionQuestionGenerator:
    """Write the versions set with a chat backend (see LegiQuestionGenerator)."""

    def __init__(
        self,
        settings: Settings | None = None,
        ollama: OllamaService | None = None,
        *,
        model: str | None = None,
        backend: str = "ollama",
        client: OpenAICompatibleChat | None = None,
    ) -> None:
        if backend not in ("ollama", "llamacpp"):
            raise ValueError(f"Backend inconnu: {backend}")
        self.settings = settings or get_settings()
        self.backend = backend
        if backend == "llamacpp":
            self.chat_client: Any = client or OpenAICompatibleChat(self.settings)
            self.model = model or self.settings.question_model
        else:
            self.chat_client = ollama or OllamaService(self.settings)
            self.model = model or self.settings.generation_model

    def prompt(self, candidate: TrapCandidate) -> str:
        expected = candidate.expected
        plan = " > ".join([expected.code_title, *expected.path])
        instruction = _INSTRUCTIONS[candidate.kind].format(phrase=candidate.as_of_phrase or "")
        parts = [f"PLAN : {plan}", f"CONSIGNE : {instruction}"]
        if candidate.kind == "reused_number":
            code_name = expected.code_title[:1].lower() + expected.code_title[1:]
            parts.append(f"RÉFÉRENCE : article {article_label(expected.article_number)} du {code_name}")
        if candidate.as_of_phrase:
            parts.append(f"DATE : {candidate.as_of_phrase}")
        parts.append(f"EXTRAIT :\n{candidate.passage}")
        if candidate.trap_passage and candidate.kind in ("rewritten", "as_of"):
            parts.append(f"ANCIENNE RÉDACTION :\n{candidate.trap_passage}")
        return "\n".join(parts) + "\n\nRéponds uniquement en JSON."

    def _ask(self, candidate: TrapCandidate) -> dict[str, str] | None:
        try:
            extra = {"json_mode": True} if self.backend == "llamacpp" else {}
            result = self.chat_client.chat(
                messages=[{"role": "user", "content": self.prompt(candidate)}],
                model=self.model,
                system=_SYSTEM_PROMPT,
                options={"temperature": 0.0, "num_predict": 260, "seed": 42},
                **extra,
            )
        except Exception as exc:  # network or model errors drop the candidate
            log_event(LOGGER, logging.WARNING, "legi.versions.chat_failed", error=str(exc))
            return None
        parsed = _parse(result.get("answer", ""))
        if parsed is None:
            return None
        raw = _raw_json(result.get("answer", ""))
        if raw.get("outdated_answer"):
            parsed["outdated_answer"] = str(raw["outdated_answer"]).strip()
        return parsed

    def generate(
        self,
        *,
        corpus_dir: Path | None = None,
        output_dir: Path,
        count: int = 100,
        seed: int = 42,
        code: str = "consommation",
        today: date | None = None,
    ) -> dict[str, Any]:
        corpus_dir = (corpus_dir or self.settings.legifrance_dir / code / "corpus").resolve()
        output_dir = output_dir.resolve()
        rng = random.Random(seed)
        mined = mine_candidates(corpus_dir, today=today)
        for kind in TRAP_KINDS:
            mined[kind].sort(key=lambda candidate: candidate.expected.file_name)
            rng.shuffle(mined[kind])
        quotas = kind_quotas(count)
        manifest_path = corpus_dir.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

        cases: list[GroundTruthCase] = []
        rejected: dict[str, int] = {}
        kept = dict.fromkeys(TRAP_KINDS, 0)
        used_articles: set[str] = set()
        for kind in TRAP_KINDS:
            for candidate in mined[kind]:
                if kept[kind] >= quotas[kind]:
                    break
                # One question per article and version, all kinds together.
                key = candidate.expected.file_name
                if key in used_articles:
                    continue
                generated = self._ask(candidate)
                reason = rejection_reason(generated, candidate)
                if reason is not None:
                    rejected[reason] = rejected.get(reason, 0) + 1
                    continue
                assert generated is not None
                used_articles.add(key)
                kept[kind] += 1
                cases.append(build_case(f"legi-versions-{len(cases) + 1:04d}", candidate, generated))
        assign_splits(cases, seed=seed)

        ground_truth_path = output_dir / "ground_truth.jsonl"
        write_ground_truth(ground_truth_path, cases)
        by_split = {split: sum(1 for case in cases if case.split == split) for split in ("dev", "heldout")}
        write_metadata(
            output_dir / "metadata.json",
            {
                "loader": f"legi_{code}_versions",
                "language": "fr",
                "licence": "Licence Ouverte 2.0 (données LEGI de la DILA, via tricoteuses)",
                "source_commit": manifest.get("commit"),
                "generator_model": self.model,
                "generator_backend": self.backend,
                "seed": seed,
                "case_count": len(cases),
                "by_type": kept,
                "by_split": by_split,
                "quotas": quotas,
                "candidates": {kind: len(rows) for kind, rows in mined.items()},
                "rejected": rejected,
                "corpus_dir": str(corpus_dir),
            },
        )
        log_event(LOGGER, logging.INFO, "legi.versions.completed", cases=len(cases), by_type=kept, rejected=rejected)
        return {
            "ground_truth_path": str(ground_truth_path),
            "case_count": len(cases),
            "by_type": kept,
            "by_split": by_split,
            "candidates": {kind: len(rows) for kind, rows in mined.items()},
            "rejected": rejected,
        }


def _raw_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def generate_version_questions(
    settings: Settings,
    *,
    backend: str,
    corpus_dir: Path,
    output_dir: Path,
    count: int,
    seed: int,
    model: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """CLI entry point. With llama.cpp, Ollama is unloaded and llama-server
    started for the run (and stopped after, if raglab started it)."""
    from raglab.llm.local_server import LocalLLMServer

    generator = LegiVersionQuestionGenerator(settings, model=model, backend=backend)
    if backend != "llamacpp":
        return generator.generate(corpus_dir=corpus_dir, output_dir=output_dir, count=count, seed=seed)
    with LocalLLMServer(settings, profile=profile or settings.question_model_profile):
        return generator.generate(corpus_dir=corpus_dir, output_dir=output_dir, count=count, seed=seed)


__all__ = [
    "TRAP_KINDS",
    "LegiVersionQuestionGenerator",
    "TrapCandidate",
    "Version",
    "build_case",
    "generate_version_questions",
    "kind_quotas",
    "load_versions",
    "mine_candidates",
    "rejection_reason",
]
