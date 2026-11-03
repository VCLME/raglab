"""Build a typed question set over a French code (`raglab legifrance fetch`).

Same protocol as LexML (`raglab.benchmarks.lexml_questions`): passages are
drawn at random inside the articles, a local model writes one question per
passage with a short answer quoted from it, the quote is located in the
document to give a gold span, and questions that fail the checks are
dropped. Four types:

* ``scenario`` (the main type, about half of the set) — a concrete
  situation as a consumer, a company or a lawyer describes it (« Mon client
  a acheté un canapé en ligne il y a dix jours, peut-il encore se
  rétracter ? »): no article number, no code name, no 6 consecutive words of
  the article, no date (the answer is the version in force). A question that
  names the article is solved by a Ctrl+F; real users describe their case;
* ``paraphrase`` — the question avoids the article's wording and cites no
  article number;
* ``reference`` — the question cites the article the way a lawyer does
  ("article L. 221-18 du code de la consommation"); the check uses the
  parser of the citation resolver, so every kept question is one it can read;
* ``entity`` — the question hinges on an acronym or a proper noun of the
  passage (DGCCRF, Banque de France, CNIL...).

What differs from LexML:

* the corpus holds one document per article *version*; passages are drawn
  only in versions in force, one article at a time, and each case records
  how many versions its article has and whether the answer also appears in
  an older version (`context`), so the version trap can be measured apart;
* every case gets a seeded `split`: `dev` (a quarter of each type, may be
  looked at while tuning a method) or `heldout` (never looked at), the rule
  applied by hand to LexML's citation questions (docs/citations.md).
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from raglab.benchmarks.base import GroundTruthCase, write_ground_truth, write_metadata
from raglab.benchmarks.lexml_questions import MAX_ANSWER_WORDS, _letter_ratio, _parse, lexical_overlap
from raglab.benchmarks.squad_style import locate_span
from raglab.config import Settings, get_settings
from raglab.legifrance.codes import find_code_mentions, get_code
from raglab.legifrance.collector import IN_FORCE_STATES
from raglab.legifrance.references import article_label
from raglab.llm.openai_compat import OpenAICompatibleChat
from raglab.logging_utils import log_event
from raglab.ollama.service import OllamaService
from raglab.retrieval.citations import parse_citation, parse_code_citation

LOGGER = logging.getLogger(__name__)

QUESTION_TYPES = ("scenario", "paraphrase", "reference", "entity")
# Target share of each type: situations first, as users ask; citations of
# articles (the identifiers failure mode) stay, as a minority.
TYPE_SHARES = {"scenario": 0.55, "paraphrase": 0.15, "reference": 0.15, "entity": 0.15}
# A question that copies this many consecutive words of the passage is a
# Ctrl+F, not a user's question.
MAX_COPIED_WORDS = 6
_WORD_RE = re.compile(r"\w+", re.UNICODE)
# A year in a scenario dates the situation: the answer would then be the
# version of that date, not the one in force.
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
DEV_SHARE = 0.25
MIN_PASSAGE_CHARS = 200
# Phrasings that only make sense next to the passage ("cet article", "le
# présent code", "mentionné ci-dessus"): among thousands of articles they
# have no single answer.
_VAGUE_RE = re.compile(
    r"\b(?:cet|cette|ces|ce)\s+(?:article|extrait|texte|passage|alin[ée]a|paragraphe|section|chapitre|"
    r"disposition|code|document)s?\b"
    r"|\b(?:le|la|les)\s+pr[ée]sente?s?\s+(?:article|texte|code|chapitre|section|disposition)s?\b"
    r"|\bselon\s+(?:le|l')\s*(?:texte|extrait)\b"
    r"|\b(?:mentionn[ée]e?s?|pr[ée]cit[ée]e?s?|susmentionn[ée]e?s?|susvis[ée]e?s?)\b"
    r"|\bci-(?:dessus|dessous|apr[èe]s)\b",
    re.IGNORECASE,
)
# Answers without content of their own: "(Abrogé)", the entry-into-force
# clause, or just "par décret en Conseil d'État".
_BOILERPLATE_RE = re.compile(
    r"^\(?(?:abrog[ée]e?|supprim[ée]e?)\)?\.?$"
    r"|entrent?\s+en\s+vigueur"
    r"|^(?:un\s+|par\s+)?(?:d[ée]cret|arr[êe]t[ée])(?:\s+en\s+Conseil\s+d'[ÉE]tat|\s+simple)?\.?$",
    re.IGNORECASE,
)
# A non-reference question must not name an article or a text number.
_LEAK_RE = re.compile(r"\b(?:articles?|art\.)\s+(?:[LRDA]\b|LO\b|\d)|\b(?:loi|d[ée]cret|ordonnance)\s+n", re.IGNORECASE)
# Acronyms (not roman numerals) and capitalised names ("Banque de France").
_ENTITY_RE = re.compile(
    r"\b(?![IVXLCDM]+\b)[A-Z]{2,}[A-Za-z]*\b"
    r"|\b[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+(?:de\s+la\s+|de\s+l'|d'|du\s+|des\s+|de\s+)?[A-ZÀ-Ý][a-zà-ÿ]+)+\b"
)
_PREFIXED_NUMBER_RE = re.compile(r"^(?:LO|L|R|D|A)\d")

_SYSTEM_PROMPT = """Tu crées des questions pour évaluer un moteur de \
recherche sur un code juridique français : des milliers d'articles, dont \
d'anciennes versions. Tu reçois la place de l'article dans le code (PLAN), \
un EXTRAIT de l'article et un TYPE de question. Écris UNE question en \
français dont la réponse se trouve dans cet extrait, et la RÉPONSE courte \
copiée mot pour mot de l'extrait.

Types :
* scenario — la question d'un vrai utilisateur (consommateur, entreprise ou \
avocat) face à une situation concrète, en français naturel (ex. : « Mon client \
a acheté un canapé en ligne il y a dix jours, peut-il encore se rétracter ? », \
« Un vendeur peut-il me facturer des frais de recouvrement ? ») : ne cite aucun \
numéro d'article, ne nomme aucun code, ne recopie pas l'extrait, ne donne \
aucune année.
* paraphrase — reformule avec d'autres mots : n'emprunte pas les expressions \
de l'extrait (utilise des synonymes), ne cite aucun numéro d'article ni de texte.
* reference — la question cite l'article indiqué en RÉFÉRENCE, comme le ferait \
un juriste (ex. : « Que prévoit l'article L. 221-18 du code de la consommation \
sur le délai de rétractation ? »).
* entity — la question s'appuie sur un sigle ou un nom propre présent dans \
l'extrait (organisme, autorité, fichier, fonds...), sans citer de numéro d'article.

Règles :
* La question doit avoir un sens seule, pour qui n'a pas lu l'extrait : \
précise le sujet (ex. : « pour un contrat conclu à distance », « en matière de \
crédit immobilier ») pour qu'une seule réponse existe dans tout le code. \
N'écris jamais « cet article », « cet extrait », « le présent code », \
« mentionné », « selon le texte ».
* La réponse doit être une copie exacte d'un morceau de l'extrait (3 à 25 mots).

Réponds uniquement en JSON : {"question": "...", "answer": "..."}"""


@dataclass(slots=True)
class ArticlePassage:
    file_name: str
    legi_id: str
    code: str
    code_title: str
    article_number: str
    path: list[str]
    start: int
    end: int
    text: str
    version_count: int
    #: Text files of the other versions of the same article number.
    other_versions: list[str]


def _body_start(text: str) -> int:
    """Offset of the article text, after the "Code ... — Article X" heading."""
    index = text.find("\n\n")
    return index + 2 if index >= 0 else 0


def sample_passages(
    corpus_dir: Path,
    *,
    count: int,
    seed: int,
    target_chars: int = 700,
    min_chars: int = MIN_PASSAGE_CHARS,
) -> list[ArticlePassage]:
    """Draw `count` passages of about `target_chars` in the versions in
    force, one per article first, then round-robin.

    Only numbered articles (L, R, D...) are used: annexes are forms and
    tables. A passage spans whole lines; an article shorter than
    `target_chars` gives its whole text, if it reaches `min_chars`.
    """
    rng = random.Random(seed)
    sidecars: list[tuple[Path, dict[str, Any]]] = []
    files_by_number: dict[tuple[str, str], list[str]] = {}
    for sidecar_path in sorted(corpus_dir.glob("*.json")):
        metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
        if "article_number" not in metadata:
            continue
        text_name = sidecar_path.with_suffix(".txt").name
        files_by_number.setdefault((metadata["code"], metadata["article_number"]), []).append(text_name)
        if metadata.get("etat") in IN_FORCE_STATES and _PREFIXED_NUMBER_RE.match(metadata["article_number"]):
            sidecars.append((sidecar_path, metadata))
    rng.shuffle(sidecars)

    documents: list[tuple[Path, dict[str, Any], str, list[tuple[int, int]]]] = []
    for sidecar_path, metadata in sidecars:
        text = sidecar_path.with_suffix(".txt").read_text(encoding="utf-8")
        lines: list[tuple[int, int]] = []
        offset = _body_start(text)
        for line in text[offset:].split("\n"):
            lines.append((offset, offset + len(line)))
            offset += len(line) + 1
        documents.append((sidecar_path, metadata, text, lines))

    passages: list[ArticlePassage] = []
    used: set[tuple[str, int]] = set()
    rounds = 0
    while len(passages) < count and rounds < 20:
        rounds += 1
        for sidecar_path, metadata, text, lines in documents:
            if len(passages) >= count:
                break
            body = [index for index in range(len(lines)) if (sidecar_path.name, index) not in used]
            if not body:
                continue
            body_chars = lines[-1][1] - lines[0][0]
            # A short article is asked about as a whole.
            first = body[0] if body_chars <= target_chars else rng.choice(body)
            last = first
            while last + 1 < len(lines) and lines[last][1] - lines[first][0] < target_chars:
                last += 1
            start, end = lines[first][0], lines[last][1]
            if end - start < min_chars or _letter_ratio(text[start:end]) < 0.6:
                continue
            used.update((sidecar_path.name, index) for index in range(first, last + 1))
            text_name = sidecar_path.with_suffix(".txt").name
            siblings = files_by_number[(metadata["code"], metadata["article_number"])]
            passages.append(
                ArticlePassage(
                    file_name=text_name,
                    legi_id=str(metadata.get("legi_id", "")),
                    code=str(metadata["code"]),
                    code_title=str(metadata.get("code_title", "")),
                    article_number=metadata["article_number"],
                    path=[str(title) for title in metadata.get("path") or []],
                    start=start,
                    end=end,
                    text=text[start:end],
                    version_count=len(siblings),
                    other_versions=[name for name in siblings if name != text_name],
                )
            )
    return passages


def eligible_types(passage: ArticlePassage) -> list[str]:
    types = ["scenario", "paraphrase", "reference"]
    if _ENTITY_RE.search(passage.text):
        types.append("entity")
    return types


def pick_question_type(passage: ArticlePassage, wanted: str) -> str:
    return wanted if wanted in eligible_types(passage) else "paraphrase"


def copied_wording(question: str, text: str, size: int = MAX_COPIED_WORDS) -> bool:
    """The question repeats `size` consecutive words of `text`."""

    def grams(value: str) -> set[tuple[str, ...]]:
        words = [word.lower() for word in _WORD_RE.findall(value)]
        return {tuple(words[index : index + size]) for index in range(len(words) - size + 1)}

    return bool(grams(question) & grams(text))


def text_rejection_reason(question: str, answer: str) -> str | None:
    """Checks that only need the question and its answer; also applied to
    an existing set by `review_question_set`."""
    words = len(answer.split())
    if words > MAX_ANSWER_WORDS:
        return "answer_too_long"
    if not words or _letter_ratio(answer) < 0.5 or _BOILERPLATE_RE.search(answer.strip()):
        return "boilerplate_answer"
    if _VAGUE_RE.search(question):
        return "vague"
    return None


def cites_reference(question: str, passage: ArticlePassage) -> bool:
    """A reference question cites the passage's article in a form the
    citation resolver reads, and no other code."""
    citation = parse_code_citation(question)
    return citation is not None and citation.article == passage.article_number and citation.code in (None, passage.code)


def _rejection_reason(generated: dict[str, str] | None, passage: ArticlePassage, question_type: str) -> str | None:
    if generated is None:
        return "invalid_json"
    span = locate_span(passage.text, generated["answer"])
    if span is None:
        return "quote_not_found"
    reason = text_rejection_reason(generated["question"], span["text"])
    if reason is not None:
        return reason
    question = generated["question"]
    if question_type != "reference" and (_LEAK_RE.search(question) or parse_citation(question) is not None):
        return "leaks_reference"
    if question_type == "reference" and not cites_reference(question, passage):
        return "reference_missing"
    if question_type == "scenario":
        if find_code_mentions(question):
            return "names_code"
        if copied_wording(question, passage.text):
            return "copies_wording"
        if _YEAR_RE.search(question):
            return "dated"
    return None


def assign_splits(cases: list[GroundTruthCase], *, seed: int, dev_share: float = DEV_SHARE) -> None:
    """Mark `dev_share` of each question type `dev`, the rest `heldout`."""
    rng = random.Random(seed)
    for question_type in sorted({case.question_type or "" for case in cases}):
        group = sorted((case for case in cases if (case.question_type or "") == question_type), key=lambda c: c.id)
        rng.shuffle(group)
        dev_count = round(len(group) * dev_share)
        for position, case in enumerate(group):
            case.split = "dev" if position < dev_count else "heldout"


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

    generator = LegiQuestionGenerator(settings, model=model, backend=backend)
    if backend != "llamacpp":
        return generator.generate(corpus_dir=corpus_dir, output_dir=output_dir, count=count, seed=seed)
    with LocalLLMServer(settings, profile=profile or settings.question_model_profile):
        return generator.generate(corpus_dir=corpus_dir, output_dir=output_dir, count=count, seed=seed)


class LegiQuestionGenerator:
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

    def _ask(self, passage: ArticlePassage, question_type: str) -> dict[str, str] | None:
        reference = ""
        if question_type == "reference":
            code_name = passage.code_title[:1].lower() + passage.code_title[1:]
            reference = f"RÉFÉRENCE : article {article_label(passage.article_number)} du {code_name}\n"
        plan = " > ".join([passage.code_title, *passage.path])
        user = (
            f"PLAN : {plan}\nTYPE : {question_type}\n{reference}EXTRAIT :\n{passage.text}\n\n"
            "Réponds uniquement en JSON."
        )
        try:
            extra = {"json_mode": True} if self.backend == "llamacpp" else {}
            result = self.chat_client.chat(
                messages=[{"role": "user", "content": user}],
                model=self.model,
                system=_SYSTEM_PROMPT,
                options={"temperature": 0.0, "num_predict": 200, "seed": 42},
                **extra,
            )
        except Exception as exc:  # network or model errors drop the passage
            log_event(LOGGER, logging.WARNING, "legi.questions.chat_failed", error=str(exc))
            return None
        return _parse(result.get("answer", ""))

    def generate(
        self,
        *,
        corpus_dir: Path | None = None,
        output_dir: Path,
        count: int = 300,
        seed: int = 42,
        code: str = "consommation",
    ) -> dict[str, Any]:
        corpus_dir = (corpus_dir or self.settings.legifrance_dir / code / "corpus").resolve()
        output_dir = output_dir.resolve()
        spec = get_code(code)
        # Over-sample: some questions are rejected by the checks.
        passages = sample_passages(corpus_dir, count=int(count * 2.5) + 10, seed=seed)
        manifest_path = corpus_dir.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

        cases: list[GroundTruthCase] = []
        rejected = dict.fromkeys(
            (
                "invalid_json",
                "quote_not_found",
                "answer_too_long",
                "leaks_reference",
                "reference_missing",
                "vague",
                "boilerplate_answer",
                "names_code",
                "copies_wording",
                "dated",
            ),
            0,
        )
        kept_by_type = dict.fromkeys(QUESTION_TYPES, 0)
        failed_by_type = dict.fromkeys(QUESTION_TYPES, 0)
        for passage in passages:
            if len(cases) >= count:
                break
            # The least represented type first; a type the model keeps
            # failing on is no longer asked for (as for LexML).
            available = [kind for kind in QUESTION_TYPES if failed_by_type[kind] < 3 * kept_by_type[kind] + 10] or [
                "paraphrase"
            ]
            # The type furthest below its share (TYPE_SHARES) first.
            wanted = min(available, key=lambda kind: kept_by_type[kind] / TYPE_SHARES[kind])
            question_type = pick_question_type(passage, wanted)
            generated = self._ask(passage, question_type)
            reason = _rejection_reason(generated, passage, question_type)
            if reason is not None:
                rejected[reason] += 1
                failed_by_type[question_type] += 1
                continue
            assert generated is not None
            span = locate_span(passage.text, generated["answer"])
            assert span is not None
            kept_by_type[question_type] += 1
            answer_in_other_version = any(
                span["text"] in (corpus_dir / name).read_text(encoding="utf-8") for name in passage.other_versions
            )
            cases.append(
                GroundTruthCase(
                    id=f"legi-{code}-{len(cases) + 1:04d}",
                    question=generated["question"],
                    expected_file_names=[passage.file_name],
                    ground_truth_answer=span["text"],
                    expected_substrings=[span["text"]],
                    expected_spans=[
                        {
                            "file_name": passage.file_name,
                            "start": passage.start + span["start"],
                            "end": passage.start + span["end"],
                            "text": span["text"],
                        }
                    ],
                    question_type=question_type,
                    lexical_overlap=round(lexical_overlap(generated["question"], passage.text), 3),
                    review_status="generated",
                    context={
                        "article": passage.article_number,
                        "legi_id": passage.legi_id,
                        "version_count": passage.version_count,
                        "answer_in_other_version": answer_in_other_version,
                    },
                )
            )
        assign_splits(cases, seed=seed)

        ground_truth_path = output_dir / "ground_truth.jsonl"
        write_ground_truth(ground_truth_path, cases)
        by_type = {kind: sum(1 for case in cases if case.question_type == kind) for kind in QUESTION_TYPES}
        by_split = {split: sum(1 for case in cases if case.split == split) for split in ("dev", "heldout")}
        with_history = sum(1 for case in cases if (case.context or {}).get("version_count", 1) > 1)
        write_metadata(
            output_dir / "metadata.json",
            {
                "loader": f"legi_{code}",
                "language": "fr",
                "licence": "Licence Ouverte 2.0 (données LEGI de la DILA, via tricoteuses)",
                "code": spec.title,
                "source_commit": manifest.get("commit"),
                "generator_model": self.model,
                "generator_backend": self.backend,
                "seed": seed,
                "case_count": len(cases),
                "by_type": by_type,
                "by_split": by_split,
                "cases_on_articles_with_history": with_history,
                "rejected": rejected,
                "corpus_dir": str(corpus_dir),
            },
        )
        log_event(
            LOGGER, logging.INFO, "legi.questions.completed", cases=len(cases), by_type=by_type, rejected=rejected
        )
        return {
            "ground_truth_path": str(ground_truth_path),
            "case_count": len(cases),
            "by_type": by_type,
            "by_split": by_split,
            "rejected": rejected,
        }
