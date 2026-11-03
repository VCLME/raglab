"""Build a typed question set over the EU compliance corpus (`raglab eurlex fetch`).

Same protocol as LexML and the French code: passages are drawn at random in
the units in force, a local model (Qwen3.6 through llama.cpp, started by
`LocalLLMServer`) writes one question per passage with a short answer
quoted from it, the quote is located in the document to give a gold span,
and questions that fail the checks are dropped. Five types:

* ``paraphrase`` — other words than the passage, no unit number (the act
  may be named: a compliance question says "under the GDPR");
* ``reference`` — cites the unit the way a lawyer does ("article 32 du
  RGPD", "Article 6(1)(a) GDPR", "artigo 5.º do RGPD"); the check uses the
  citation resolver's parser, so every kept question is one it can read;
* ``entity`` — hinges on an acronym or a proper noun of the passage (ENISA,
  CSIRT, AI Office, ESAs…), without a unit number;
* ``cross_reference`` — the failure mode the citation graph is for: unit A
  cites unit B (same language, rules of `raglab.eurlex.references`), the
  question cites A and its act, the answer is quoted from B. B's number must
  not appear in the question and the answer must not be in A; relevance is
  B's span only, A's citing sentence is kept in `citing_spans`;
* ``cross_language`` — the question is written in another corpus language
  than the passage (French question, English passage); the answer is still
  quoted from the passage.

Passages are drawn one unit (CELEX + kind + number) at a time, in a language
drawn with the seed, so the three language copies of an article do not all
end up in the set. Each case records in `context` the unit, its language,
the files of the same unit in the other languages, how many versions it has
and whether the answer also appears in an older version
(`answer_in_other_version`, the AI Act articles rewritten by the Digital
Omnibus). Every case gets a seeded `split` (`dev` / `heldout`).
"""

from __future__ import annotations

import json
import logging
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from raglab.benchmarks.base import write_metadata
from raglab.benchmarks.legi_questions import DEV_SHARE
from raglab.benchmarks.lexml_questions import MAX_ANSWER_WORDS, _letter_ratio, _parse, lexical_overlap
from raglab.benchmarks.squad_style import locate_span
from raglab.config import Settings, get_settings
from raglab.eurlex.acts import BY_CELEX, LANGUAGES, UNIT_NAMES
from raglab.eurlex.collector import LICENCE
from raglab.llm.openai_compat import OpenAICompatibleChat
from raglab.logging_utils import log_event
from raglab.ollama.service import OllamaService
from raglab.retrieval.citations import guess_language, parse_eu_citation

LOGGER = logging.getLogger(__name__)

QUESTION_TYPES = ("paraphrase", "reference", "entity", "cross_reference", "cross_language")
MIN_PASSAGE_CHARS = 200
LANGUAGE_NAMES = {"fr": "French", "en": "English", "pt": "Portuguese"}
# Phrasings that only make sense next to the passage: "this Article", "cet
# article", "o presente artigo", "the above".
_VAGUE_RE = re.compile(
    r"\b(?:this|that|the\s+present|the\s+above|the\s+said)\s+(?:article|recital|annex|paragraph|provision|passage|"
    r"excerpt|text|extract)s?\b"
    r"|\b(?:cet|cette|ces|ce|le\s+présent|la\s+présente|ledit|ladite)\s+(?:article|considérant|annexe|paragraphe|"
    r"extrait|texte|passage|disposition)s?\b"
    r"|\b(?:este|esta|estes|estas|o\s+presente|a\s+presente|esse|essa|referid[oa])\s+(?:artigo|considerando|anexo|"
    r"número|parágrafo|excerto|texto|trecho|disposição)s?\b"
    r"|\b(?:above|below|ci-dessus|ci-dessous|supra|infra|acima|abaixo)\b"
    r"|\b(?:mentioned|mentionn[ée]e?s?|précité|referido)\b",
    re.IGNORECASE,
)
# Answers without content of their own.
_BOILERPLATE_RE = re.compile(
    r"^\(?(?:deleted|supprimé|suprimido|repealed|abrogé|revogado)\)?\.?$"
    r"|shall\s+enter\s+into\s+force|entre\s+en\s+vigueur|entra\s+em\s+vigor"
    r"|binding\s+in\s+its\s+entirety|obligatoire\s+dans\s+tous\s+ses\s+éléments|obrigatório\s+em\s+todos\s+os\s+seus",
    re.IGNORECASE,
)
# Acronyms (not roman numerals) and capitalised multi-word names.
_ENTITY_RE = re.compile(
    r"\b(?![IVXLC]+\b)[A-Z]{2,}[A-Za-z0-9]*\b"
    r"|\b[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+(?:of\s+the\s+|de\s+la\s+|de\s+l'|du\s+|des\s+|de\s+|da\s+|do\s+|dos\s+)?"
    r"[A-ZÀ-Ý][a-zà-ÿ]+)+\b"
)

_SYSTEM_PROMPT = """You write questions to evaluate a search engine over \
EU regulatory-compliance law (GDPR, AI Act, DORA, NIS 2 and the delegated \
and implementing acts that complete them), in French, English and \
Portuguese. You receive the act and the unit (article, recital or annex) a \
PASSAGE comes from, the PASSAGE, a question TYPE and the LANGUAGE the \
question must be written in. Write ONE question whose answer is in the \
passage, and the short ANSWER copied word for word from the passage (in the \
passage's own language, even when the question is in another language).

Types:
* paraphrase — use other words than the passage (synonyms), cite no article, \
recital or annex number; you may name the act ("under the GDPR").
* reference — cite the unit given as REFERENCE the way a lawyer would \
("Under Article 33 of the GDPR, …", « Selon l'article 33 du RGPD, … », \
"Nos termos do artigo 33.º do RGPD, …").
* entity — hinge on an acronym or a proper noun of the passage (authority, \
body, register…), cite no unit number.
* cross_reference — the passage comes from the unit CITED by the unit given \
as REFERENCE. Cite the REFERENCE unit and its act, ask what it leads to, \
and take the answer from the passage. Never write the number of the \
passage's own unit.
* cross_language — like paraphrase, written in LANGUAGE although the \
passage is in another language.

Rules:
* The question must make sense on its own, for someone who has not read the \
passage: name the subject precisely so that a single answer exists among \
thousands of articles. Never write "this article", "cet article", "este \
artigo", "the above", "mentioned".
* The answer is an exact copy of a piece of the passage (3 to 25 words).

Answer only with JSON: {"question": "...", "answer": "..."}"""


@dataclass(slots=True)
class Passage:
    file_name: str
    celex: str
    act_short: str
    unit: str
    number: str
    unit_label: str
    language: str
    start: int
    end: int
    text: str
    version_count: int
    other_versions: list[str] = field(default_factory=list)
    same_unit_files: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CitingUnit:
    """Unit A citing the passage's unit B (cross_reference)."""

    file_name: str
    unit: str
    number: str
    celex: str
    act_short: str
    unit_label: str
    citing_start: int
    citing_end: int
    citing_text: str


def _body_start(text: str) -> int:
    index = text.find("\n\n")
    return index + 2 if index >= 0 else 0


def load_sidecars(corpus_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        path.with_suffix(".txt").name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(corpus_dir.glob("*.json"))
    }


def _passage_from(
    rng: random.Random,
    name: str,
    metadata: dict[str, Any],
    text: str,
    *,
    target_chars: int,
    min_chars: int,
    used: set[tuple[str, int]],
) -> tuple[int, int] | None:
    lines: list[tuple[int, int]] = []
    offset = _body_start(text)
    for line in text[offset:].split("\n"):
        lines.append((offset, offset + len(line)))
        offset += len(line) + 1
    free = [index for index in range(len(lines)) if (name, index) not in used]
    if not free:
        return None
    body_chars = lines[-1][1] - lines[0][0]
    first = free[0] if body_chars <= target_chars else rng.choice(free)
    last = first
    while last + 1 < len(lines) and lines[last][1] - lines[first][0] < target_chars:
        last += 1
    start, end = lines[first][0], lines[last][1]
    if end - start < min_chars or _letter_ratio(text[start:end]) < 0.6:
        return None
    used.update((name, index) for index in range(first, last + 1))
    return start, end


def sample_passages(
    corpus_dir: Path,
    *,
    count: int,
    seed: int,
    target_chars: int = 700,
    min_chars: int = MIN_PASSAGE_CHARS,
    sidecars: dict[str, dict[str, Any]] | None = None,
) -> list[Passage]:
    """`count` passages of about `target_chars` in units in force, one unit
    (all languages together) at a time, then round-robin."""
    rng = random.Random(seed)
    sidecars = sidecars if sidecars is not None else load_sidecars(corpus_dir)
    by_unit: dict[str, dict[str, str]] = defaultdict(dict)
    versions: dict[tuple[str, str], list[str]] = defaultdict(list)
    for name, metadata in sidecars.items():
        versions[(metadata["unit_key"], metadata["language"])].append(name)
        if metadata.get("in_force"):
            by_unit[metadata["unit_key"]][metadata["language"]] = name
    unit_keys = sorted(by_unit)
    rng.shuffle(unit_keys)
    texts: dict[str, str] = {}
    passages: list[Passage] = []
    used: set[tuple[str, int]] = set()
    rounds = 0
    while len(passages) < count and rounds < 10:
        rounds += 1
        for unit_key in unit_keys:
            if len(passages) >= count:
                break
            languages = sorted(by_unit[unit_key])
            language = rng.choice(languages)
            name = by_unit[unit_key][language]
            metadata = sidecars[name]
            text = texts.setdefault(name, (corpus_dir / name).read_text(encoding="utf-8"))
            bounds = _passage_from(rng, name, metadata, text, target_chars=target_chars, min_chars=min_chars, used=used)
            if bounds is None:
                continue
            start, end = bounds
            passages.append(
                Passage(
                    file_name=name,
                    celex=metadata["celex"],
                    act_short=metadata["act_short"],
                    unit=metadata["unit"],
                    number=str(metadata["unit_number"]),
                    unit_label=metadata["unit_label"],
                    language=language,
                    start=start,
                    end=end,
                    text=text[start:end],
                    version_count=int(metadata.get("version_count") or 1),
                    other_versions=[other for other in versions[(unit_key, language)] if other != name],
                    same_unit_files=[by_unit[unit_key][other] for other in languages if other != language],
                )
            )
    return passages


def citing_units(sidecars: dict[str, dict[str, Any]]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """For every file in force, the in-force units of the same language that
    cite it (by unit key): {target file: [(citing file, reference)]}."""
    current = {
        (metadata["unit_key"], metadata["language"]): name
        for name, metadata in sidecars.items()
        if metadata.get("in_force")
    }
    cited_by: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for name, metadata in sidecars.items():
        if not metadata.get("in_force") or metadata["unit"] == "annex":
            continue
        for reference in metadata.get("references") or []:
            if reference.get("celex") is None or reference.get("number") is None:
                continue
            key = f"{reference['celex']}:{reference['unit']}:{reference['number']}"
            target = current.get((key, metadata["language"]))
            if target is None or target == name or reference["unit"] == "recital":
                continue
            cited_by[target].append((name, reference))
    return cited_by


def eligible_types(passage: Passage, *, has_citing: bool) -> list[str]:
    types = ["paraphrase", "reference", "cross_language"]
    if _ENTITY_RE.search(passage.text):
        types.append("entity")
    if has_citing:
        types.append("cross_reference")
    return types


def text_rejection_reason(question: str, answer: str) -> str | None:
    words = len(answer.split())
    if words > MAX_ANSWER_WORDS:
        return "answer_too_long"
    if words < 2 or _letter_ratio(answer) < 0.5 or _BOILERPLATE_RE.search(answer.strip()):
        return "boilerplate_answer"
    if _VAGUE_RE.search(question):
        return "vague"
    return None


def cites_unit(question: str, celex: str, unit: str, number: str) -> bool:
    citation = parse_eu_citation(question)
    return citation is not None and (citation.celex, citation.unit, citation.article) == (celex, unit, number)


def rejection_reason(
    generated: dict[str, str] | None,
    passage: Passage,
    question_type: str,
    *,
    language: str,
    citing: CitingUnit | None = None,
    citing_text: str = "",
) -> str | None:
    if generated is None:
        return "invalid_json"
    span = locate_span(passage.text, generated["answer"])
    if span is None:
        return "quote_not_found"
    question = generated["question"]
    reason = text_rejection_reason(question, span["text"])
    if reason is not None:
        return reason
    if guess_language(question) != language:
        return "wrong_language"
    citation = parse_eu_citation(question)
    if question_type in ("paraphrase", "entity", "cross_language") and citation is not None and citation.unit:
        return "leaks_reference"
    if question_type == "reference" and not cites_unit(question, passage.celex, passage.unit, passage.number):
        return "reference_missing"
    if question_type == "cross_reference":
        assert citing is not None
        if not cites_unit(question, citing.celex, citing.unit, citing.number):
            return "reference_missing"
        if re.search(rf"\b{re.escape(passage.number)}\b", question):
            return "leaks_target"
        if span["text"] in citing_text:
            return "answer_in_citing_unit"
    return None


def assign_splits(cases: list[dict[str, Any]], *, seed: int, dev_share: float = DEV_SHARE) -> None:
    rng = random.Random(seed)
    for question_type in sorted({case["question_type"] for case in cases}):
        group = sorted((case for case in cases if case["question_type"] == question_type), key=lambda c: c["id"])
        rng.shuffle(group)
        dev_count = round(len(group) * dev_share)
        for position, case in enumerate(group):
            case["split"] = "dev" if position < dev_count else "heldout"


def review_question_set(ground_truth_path: Path) -> dict[str, int]:
    """Mark as `rejected` the cases that fail the current text rules; they
    stay in the file (with `rejection_reason`) and the benchmark skips them."""
    counts: dict[str, int] = {}
    output: list[str] = []
    for line in ground_truth_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        if case.get("review_status") != "rejected":
            reason = text_rejection_reason(case["question"], case.get("ground_truth_answer") or "")
            if reason is not None:
                case["review_status"] = "rejected"
                case["rejection_reason"] = reason
                counts[reason] = counts.get(reason, 0) + 1
        output.append(json.dumps(case, ensure_ascii=False))
    ground_truth_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return counts


def generate_questions(
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

    generator = EurlexQuestionGenerator(settings, model=model, backend=backend)
    if backend != "llamacpp":
        return generator.generate(corpus_dir=corpus_dir, output_dir=output_dir, count=count, seed=seed)
    with LocalLLMServer(settings, profile=profile or settings.question_model_profile):
        return generator.generate(corpus_dir=corpus_dir, output_dir=output_dir, count=count, seed=seed)


def reference_label(unit: str, number: str, act_short: str, language: str) -> str:
    """ "Article 33 — RGPD" in the question's language."""
    return f"{UNIT_NAMES[language][unit]} {number} — {act_short}"


class EurlexQuestionGenerator:
    """Write the question set with a chat backend (see LexMLQuestionGenerator
    for the two backends)."""

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

    def _ask(
        self, passage: Passage, question_type: str, language: str, citing: CitingUnit | None
    ) -> dict[str, str] | None:
        reference = ""
        if question_type == "reference":
            act = BY_CELEX.get(passage.celex)
            short = act.short_name(language) if act else passage.act_short
            reference = f"REFERENCE: {reference_label(passage.unit, passage.number, short, language)}\n"
        elif question_type == "cross_reference" and citing is not None:
            act = BY_CELEX.get(citing.celex)
            short = act.short_name(language) if act else citing.act_short
            reference = (
                f"REFERENCE: {reference_label(citing.unit, citing.number, short, language)}\n"
                f"REFERENCE TEXT (cites the passage's unit): {citing.citing_text}\n"
            )
        user = (
            f"ACT: {passage.act_short} — {passage.unit_label}\nTYPE: {question_type}\n"
            f"LANGUAGE: {LANGUAGE_NAMES[language]}\n{reference}PASSAGE ({LANGUAGE_NAMES[passage.language]}):\n"
            f"{passage.text}\n\nAnswer only with JSON."
        )
        try:
            extra = {"json_mode": True} if self.backend == "llamacpp" else {}
            result = self.chat_client.chat(
                messages=[{"role": "user", "content": user}],
                model=self.model,
                system=_SYSTEM_PROMPT,
                options={"temperature": 0.0, "num_predict": 220, "seed": 42},
                **extra,
            )
        except Exception as exc:  # network or model errors drop the passage
            log_event(LOGGER, logging.WARNING, "eurlex.questions.chat_failed", error=str(exc))
            return None
        return _parse(result.get("answer", ""))

    def generate(
        self,
        *,
        corpus_dir: Path | None = None,
        output_dir: Path,
        count: int = 300,
        seed: int = 42,
    ) -> dict[str, Any]:
        corpus_dir = (corpus_dir or self.settings.eurlex_dir / "compliance" / "corpus").resolve()
        output_dir = output_dir.resolve()
        sidecars = load_sidecars(corpus_dir)
        # Over-sample: some questions are rejected by the checks.
        passages = sample_passages(corpus_dir, count=int(count * 2.5) + 10, seed=seed, sidecars=sidecars)
        cited_by = citing_units(sidecars)
        manifest_path = corpus_dir.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        rng = random.Random(f"{seed}:types")

        cases: list[dict[str, Any]] = []
        rejected: dict[str, int] = defaultdict(int)
        kept = dict.fromkeys(QUESTION_TYPES, 0)
        failed = dict.fromkeys(QUESTION_TYPES, 0)
        texts: dict[str, str] = {}
        for passage in passages:
            if len(cases) >= count:
                break
            citing_rows = cited_by.get(passage.file_name, [])
            eligible = eligible_types(passage, has_citing=bool(citing_rows))
            # The least represented type first; a type the model keeps
            # failing on is no longer asked for (as for LexML).
            available = [kind for kind in eligible if failed[kind] < 3 * kept[kind] + 10] or ["paraphrase"]
            question_type = min(available, key=lambda kind: kept[kind])
            language = passage.language
            if question_type == "cross_language":
                language = rng.choice([other for other in LANGUAGES if other != passage.language])
            citing: CitingUnit | None = None
            citing_full = ""
            if question_type == "cross_reference":
                name, reference = rng.choice(citing_rows)
                metadata = sidecars[name]
                citing_full = texts.setdefault(name, (corpus_dir / name).read_text(encoding="utf-8"))
                start = citing_full.find(reference.get("text") or "")
                line_start = citing_full.rfind("\n", 0, max(start, 0)) + 1
                line_end = citing_full.find("\n", max(start, 0))
                line_end = len(citing_full) if line_end == -1 else line_end
                citing = CitingUnit(
                    file_name=name,
                    unit=metadata["unit"],
                    number=str(metadata["unit_number"]),
                    celex=metadata["celex"],
                    act_short=metadata["act_short"],
                    unit_label=metadata["unit_label"],
                    citing_start=line_start,
                    citing_end=line_end,
                    citing_text=citing_full[line_start:line_end],
                )
            generated = self._ask(passage, question_type, language, citing)
            reason = rejection_reason(
                generated, passage, question_type, language=language, citing=citing, citing_text=citing_full
            )
            if reason is not None:
                rejected[reason] += 1
                failed[question_type] += 1
                continue
            assert generated is not None
            span = locate_span(passage.text, generated["answer"])
            assert span is not None
            kept[question_type] += 1
            answer_in_other_version = any(
                span["text"] in texts.setdefault(name, (corpus_dir / name).read_text(encoding="utf-8"))
                for name in passage.other_versions
            )
            case: dict[str, Any] = {
                "id": f"eurlex-{len(cases) + 1:04d}",
                "question": generated["question"],
                "expected_file_names": [passage.file_name],
                "ground_truth_answer": span["text"],
                "expected_substrings": [span["text"]],
                "expected_spans": [
                    {
                        "file_name": passage.file_name,
                        "start": passage.start + span["start"],
                        "end": passage.start + span["end"],
                        "text": span["text"],
                    }
                ],
                "question_type": question_type,
                "lexical_overlap": round(lexical_overlap(generated["question"], passage.text), 3),
                "review_status": "generated",
                "context": {
                    "unit_key": f"{passage.celex}:{passage.unit}:{passage.number}",
                    "unit": passage.unit,
                    "passage_language": passage.language,
                    "question_language": language,
                    "same_unit_files": passage.same_unit_files,
                    "version_count": passage.version_count,
                    "answer_in_other_version": answer_in_other_version,
                },
            }
            if citing is not None:
                case["citing_spans"] = [
                    {
                        "file_name": citing.file_name,
                        "start": citing.citing_start,
                        "end": citing.citing_end,
                        "text": citing.citing_text,
                    }
                ]
                case["context"]["citing_unit"] = f"{citing.celex}:{citing.unit}:{citing.number}"
                case["context"]["reference_scope"] = "within_act" if citing.celex == passage.celex else "across_acts"
            cases.append(case)
        assign_splits(cases, seed=seed)

        output_dir.mkdir(parents=True, exist_ok=True)
        ground_truth_path = output_dir / "ground_truth.jsonl"
        ground_truth_path.write_text(
            "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8"
        )
        by_type = {kind: sum(1 for case in cases if case["question_type"] == kind) for kind in QUESTION_TYPES}
        by_split = {split: sum(1 for case in cases if case["split"] == split) for split in ("dev", "heldout")}
        by_language = {
            language: sum(1 for case in cases if case["context"]["question_language"] == language)
            for language in LANGUAGES
        }
        write_metadata(
            output_dir / "metadata.json",
            {
                "loader": "eurlex_compliance",
                "language": "multi",
                "licence": LICENCE,
                "rules_version": manifest.get("rules_version"),
                "generator_model": self.model,
                "generator_backend": self.backend,
                "seed": seed,
                "case_count": len(cases),
                "by_type": by_type,
                "by_split": by_split,
                "by_question_language": by_language,
                "rejected": dict(rejected),
                "corpus_dir": str(corpus_dir),
            },
        )
        log_event(
            LOGGER,
            logging.INFO,
            "eurlex.questions.completed",
            cases=len(cases),
            by_type=by_type,
            rejected=dict(rejected),
        )
        return {
            "ground_truth_path": str(ground_truth_path),
            "case_count": len(cases),
            "by_type": by_type,
            "by_split": by_split,
            "by_question_language": by_language,
            "rejected": dict(rejected),
        }
