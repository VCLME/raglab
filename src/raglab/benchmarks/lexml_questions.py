"""Build a typed question set over the LexML full-text corpus.

The legacy LexML ground truth used each document's title + ementa as the
question, i.e. a copy of the document: retrieval was trivially perfect and
said nothing about real queries. Here questions are written by the local
LLM from passages drawn at random inside the laws, in three types that
stress different retrieval behaviours:

* ``paraphrase`` — the question avoids the passage's wording (semantic
  matching; dense retrieval should be at home);
* ``reference`` — the question cites the law number and/or the article
  ("art. 49 da Lei 8.078"): exact tokens that dense embeddings blur;
* ``entity`` — the question hinges on an acronym or a proper noun found in
  the passage (FGTS, INSS, Ministério da Saúde...).

Each question comes with a short answer *quoted* from the passage. The quote
is located in the document to produce a gold span, so relevance is judged at
passage level like PIAF. Questions whose quote cannot be found are dropped:
that check is what keeps hallucinated questions out of the benchmark. Every
case also records its lexical overlap with the passage, so the report can
show how much a result owes to shared words.
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
from raglab.benchmarks.squad_style import locate_span
from raglab.config import Settings, get_settings
from raglab.llm.openai_compat import OpenAICompatibleChat
from raglab.logging_utils import log_event
from raglab.ollama.service import OllamaService

LOGGER = logging.getLogger(__name__)

QUESTION_TYPES = ("paraphrase", "reference", "entity")
MAX_ANSWER_WORDS = 40
# Phrasings that only make sense next to the passage ("this law", "this
# excerpt"): in a corpus of hundreds of laws they have no single answer.
_VAGUE_RE = re.compile(
    r"\b(?:nest[ea]s?|dest[ea]s?|est[ea]s?)\s+(?:trecho|texto|lei|artigo|par[aá]grafo|anexo|dispositivo)\b"
    r"|\b(?:segundo|conforme)\s+o\s+texto\b"
    r"|\bem\s+(?:an[aá]lise|quest[aã]o)\b"
    r"|\b(?:mencionad|referid|citad|introduzid)[oa]s?\b"
    r"|\bconforme\s+(?:o|a)\s+(?:inciso|al[ií]nea|item|subt[ií]tulo|par[aá]grafo|dispositivo)\b",
    re.IGNORECASE,
)
# Answers that carry no content of their own: the enacting formula, the
# "in force on publication" clause, vetoed or exempt markers, amendment notes
# and the Planalto page footer.
_BOILERPLATE_RE = re.compile(
    r"PRESIDENT[EA]\s+DA\s+REP[UÚ]BLICA|Congresso Nacional decreta"
    r"|entra\s+em\s+vigor|^\(?VETADO\)?$|^ISENTO$|Reda[cç][aã]o dada pela"
    r"|n[aã]o substitui o publicado",
    re.IGNORECASE,
)
MIN_ANSWER_WORDS = 1
_BUDGET_EMENTA_RE = re.compile(r"^\s*(?:abre|reabre)\b", re.IGNORECASE)

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_ARTICLE_RE = re.compile(r"^Art\.\s*(\d+[A-Z\-]*)", re.IGNORECASE)
_ENTITY_RE = re.compile(r"\b(?:[A-Z]{2,}[A-Za-z]*|[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][a-zà-ÿ]+)+)\b")

_SYSTEM_PROMPT = """Você cria perguntas para avaliar um sistema de busca em \
textos legais brasileiros. A busca é feita em centenas de leis federais. \
Você recebe o ASSUNTO DA LEI (sua ementa), um TRECHO dessa lei e um TIPO de \
pergunta. Escreva UMA pergunta em português que só pode ser respondida com \
esse trecho, e a RESPOSTA curta copiada literalmente do trecho.

Tipos:
* paraphrase — reformule com outras palavras: não reutilize as expressões do \
trecho (use sinônimos), não cite número de lei nem de artigo.
* reference — a pergunta cita o número do artigo e o número da lei \
indicados em REFERÊNCIA (ex.: "O que dispõe o art. 49 da Lei nº 8.078?").
* entity — a pergunta se apoia em uma sigla ou nome próprio presente no \
trecho (órgão, programa, fundo, tributo...), sem citar número de lei.

Regras:
* A pergunta deve fazer sentido sozinha para quem não leu o trecho: \
mencione o tema da lei (ex.: "na lei que trata da erva-mate", "no regime do \
FGTS") para que só exista uma resposta entre todas as leis. Nunca escreva \
"neste trecho", "segundo o texto", "o programa" sem dizer qual.
* A resposta deve ser uma cópia exata de um pedaço do trecho (3 a 25 palavras).

Responda apenas com JSON: {"question": "...", "answer": "..."}"""


@dataclass(slots=True)
class Passage:
    file_name: str
    urn: str
    law_title: str
    ementa: str
    start: int
    end: int
    text: str
    article: str | None


def lexical_overlap(question: str, passage: str) -> float:
    """Share of the question's content words (len > 3) found in the passage."""
    question_words = {word.lower() for word in _WORD_RE.findall(question) if len(word) > 3}
    if not question_words:
        return 0.0
    passage_words = {word.lower() for word in _WORD_RE.findall(passage)}
    return len(question_words & passage_words) / len(question_words)


def sample_passages(
    corpus_dir: Path,
    *,
    count: int,
    seed: int,
    target_chars: int = 700,
) -> list[Passage]:
    """Draw `count` passages of about `target_chars`, at most one per law
    first, then round-robin, so long laws do not dominate the question set.

    A passage starts at a line (paragraph) boundary and extends over whole
    lines; the nearest preceding ``Art. N`` line gives its article number.
    """
    rng = random.Random(seed)
    documents: list[tuple[Path, dict[str, Any], str, list[tuple[int, int]]]] = []
    for text_path in sorted(corpus_dir.glob("*.txt")):
        sidecar = json.loads(text_path.with_suffix(".json").read_text(encoding="utf-8"))
        text = text_path.read_text(encoding="utf-8")
        lines: list[tuple[int, int]] = []
        offset = 0
        for line in text.split("\n"):
            lines.append((offset, offset + len(line)))
            offset += len(line) + 1
        if _BUDGET_EMENTA_RE.match(str(sidecar.get("ementa", ""))):
            # Credit-opening laws are tables of budget lines: they stay in the
            # corpus as distractors but yield no meaningful question.
            continue
        documents.append((text_path, sidecar, text, lines))
    rng.shuffle(documents)

    passages: list[Passage] = []
    used: set[tuple[str, int]] = set()
    rounds = 0
    while len(passages) < count and rounds < 20:
        rounds += 1
        for text_path, sidecar, text, lines in documents:
            if len(passages) >= count:
                break
            # The body starts at the first article: heading, ementa and the
            # enacting formula ("O PRESIDENTE DA REPÚBLICA...") are the same in
            # every law and make useless questions.
            first_article = next(
                (index for index, (a, b) in enumerate(lines) if _ARTICLE_RE.match(text[a:b])),
                3,
            )
            body = [index for index in range(first_article, len(lines)) if (text_path.name, index) not in used]
            if not body:
                continue
            first = rng.choice(body)
            last = first
            while last + 1 < len(lines) and lines[last][1] - lines[first][0] < target_chars:
                last += 1
            start, end = lines[first][0], lines[last][1]
            if end - start < target_chars // 2 or _letter_ratio(text[start:end]) < 0.6:
                # Too short, or a budget table: nothing to ask in words.
                continue
            used.update((text_path.name, index) for index in range(first, last + 1))
            article = None
            for index in range(first, -1, -1):
                line_text = text[lines[index][0] : lines[index][1]]
                match = _ARTICLE_RE.match(line_text)
                if match:
                    article = match.group(1)
                    break
            passages.append(
                Passage(
                    file_name=text_path.name,
                    urn=str(sidecar.get("urn", "")),
                    law_title=str(sidecar.get("title", "")),
                    ementa=str(sidecar.get("ementa", "")),
                    start=start,
                    end=end,
                    text=text[start:end],
                    article=article,
                )
            )
    return passages


def _letter_ratio(text: str) -> float:
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return 0.0
    return sum(char.isalpha() for char in visible) / len(visible)


def eligible_types(passage: Passage) -> list[str]:
    types = ["paraphrase"]
    if passage.article:
        types.append("reference")
    if _ENTITY_RE.search(passage.text):
        types.append("entity")
    return types


def pick_question_type(passage: Passage, wanted: str) -> str:
    """Use `wanted` when the passage supports it, otherwise fall back to
    paraphrase (always possible). Callers rotate `wanted` through
    QUESTION_TYPES so the set ends up roughly balanced."""
    return wanted if wanted in eligible_types(passage) else "paraphrase"


def _parse(answer: str) -> dict[str, str] | None:
    match = _JSON_BLOCK_RE.search(answer or "")
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    question = payload.get("question") if isinstance(payload, dict) else None
    quote = payload.get("answer") if isinstance(payload, dict) else None
    if not isinstance(question, str) or not isinstance(quote, str):
        return None
    if not question.strip() or not quote.strip():
        return None
    return {"question": question.strip(), "answer": quote.strip().strip('"“”')}


def _cites_reference(question: str, passage: Passage) -> bool:
    """A reference question must cite both the article and the law number."""
    digits = re.sub(r"\D", "", question)
    law_number = passage.file_name.split("_")[1] if passage.file_name.count("_") >= 2 else ""
    article_number = re.sub(r"\D", "", passage.article or "")
    has_article = bool(re.search(rf"\bart(?:\.|igo)\s*{article_number}\b", question, re.IGNORECASE))
    return has_article and bool(law_number) and law_number in digits


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
    """Entry point shared by the CLI and the API.

    With the llama.cpp backend, Ollama models are unloaded and llama-server
    is started for the duration of the run (and stopped afterwards if raglab
    started it).
    """
    from raglab.llm.local_server import LocalLLMServer

    generator = LexMLQuestionGenerator(settings, model=model, backend=backend)
    if backend != "llamacpp":
        return generator.generate(corpus_dir=corpus_dir, output_dir=output_dir, count=count, seed=seed)
    with LocalLLMServer(settings, profile=profile or settings.question_model_profile):
        return generator.generate(corpus_dir=corpus_dir, output_dir=output_dir, count=count, seed=seed)


def text_rejection_reason(question: str, answer: str) -> str | None:
    """Checks that only need the question and its answer.

    Also applied to an existing question set by `review_question_set`, so a
    rule added after generation can be enforced without regenerating.
    """
    words = len(answer.split())
    if words > MAX_ANSWER_WORDS:
        return "answer_too_long"
    if words < MIN_ANSWER_WORDS or _letter_ratio(answer) < 0.5 or _BOILERPLATE_RE.search(answer.strip()):
        return "boilerplate_answer"
    if _VAGUE_RE.search(question):
        return "vague"
    return None


def review_question_set(ground_truth_path: Path) -> dict[str, int]:
    """Mark as `rejected` the cases that fail the current text rules.

    Rejected cases stay in the file (with `rejection_reason`) so the set can
    be audited, but the recall benchmark skips them.
    """
    lines = ground_truth_path.read_text(encoding="utf-8").splitlines()
    counts: dict[str, int] = {}
    output: list[str] = []
    for line in lines:
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


def _rejection_reason(generated: dict[str, str] | None, passage: Passage, question_type: str) -> str | None:
    if generated is None:
        return "invalid_json"
    span = locate_span(passage.text, generated["answer"])
    if span is None:
        return "quote_not_found"
    reason = text_rejection_reason(generated["question"], span["text"])
    if reason is not None:
        return reason
    question = generated["question"]
    if question_type != "reference" and re.search(r"\b(?:art\.|artigo|lei n)", question, re.I):
        return "leaks_reference"
    if question_type == "reference" and not _cites_reference(question, passage):
        return "reference_missing"
    return None


class LexMLQuestionGenerator:
    """Write the question set with a chat backend.

    `backend="ollama"` uses the generation model served by Ollama;
    `backend="llamacpp"` uses an OpenAI-compatible llama-server (JSON output
    enforced by grammar). Starting/stopping that server is the caller's job
    (see `raglab.llm.local_server.LocalLLMServer`).
    """

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

    def _ask(self, passage: Passage, question_type: str) -> dict[str, str] | None:
        reference = ""
        if question_type == "reference":
            reference = f"REFERÊNCIA: art. {passage.article} da {passage.law_title}\n"
        user = (
            f"ASSUNTO DA LEI: {passage.ementa or passage.law_title}\n"
            f"TIPO: {question_type}\n{reference}TRECHO:\n{passage.text}\n\nResponda apenas com JSON."
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
            log_event(LOGGER, logging.WARNING, "lexml.questions.chat_failed", error=str(exc))
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
        corpus_dir = (corpus_dir or self.settings.lexml_fulltext_dir / "corpus").resolve()
        output_dir = output_dir.resolve()
        # Over-sample: some questions are rejected by the quote check.
        passages = sample_passages(corpus_dir, count=int(count * 2.5) + 10, seed=seed)

        cases: list[GroundTruthCase] = []
        rejected = {
            "invalid_json": 0,
            "quote_not_found": 0,
            "answer_too_long": 0,
            "leaks_reference": 0,
            "reference_missing": 0,
            "vague": 0,
            "boilerplate_answer": 0,
        }
        kept_by_type = dict.fromkeys(QUESTION_TYPES, 0)
        failed_by_type = dict.fromkeys(QUESTION_TYPES, 0)
        for passage in passages:
            if len(cases) >= count:
                break
            # Ask for the type we have the fewest of, so the set stays balanced
            # even when one type gets rejected more often.
            # A type the model keeps failing on is no longer asked for: better
            # a slightly unbalanced set than one that never reaches `count`.
            available = [
                kind for kind in QUESTION_TYPES if failed_by_type[kind] < 3 * kept_by_type[kind] + 10
            ] or ["paraphrase"]
            wanted = min(available, key=lambda kind: kept_by_type[kind])
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
            case_id = f"lexml-{len(cases) + 1:04d}"
            cases.append(
                GroundTruthCase(
                    id=case_id,
                    question=generated["question"],
                    expected_file_names=[passage.file_name],
                    ground_truth_answer=span["text"],
                    expected_substrings=[span["text"]],
                    expected_urns=[passage.urn] if passage.urn else [],
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
                )
            )

        ground_truth_path = output_dir / "ground_truth.jsonl"
        write_ground_truth(ground_truth_path, cases)
        by_type = {kind: sum(1 for case in cases if case.question_type == kind) for kind in QUESTION_TYPES}
        write_metadata(
            output_dir / "metadata.json",
            {
                "loader": "lexml_fulltext",
                "language": "pt",
                "licence": "Public domain (Lei 9.610/1998, art. 8º, IV)",
                "generator_model": self.model,
                "generator_backend": self.backend,
                "seed": seed,
                "case_count": len(cases),
                "by_type": by_type,
                "rejected": rejected,
                "corpus_dir": str(corpus_dir),
            },
        )
        log_event(
            LOGGER,
            logging.INFO,
            "lexml.questions.completed",
            cases=len(cases),
            by_type=by_type,
            rejected=rejected,
        )
        return {
            "ground_truth_path": str(ground_truth_path),
            "case_count": len(cases),
            "by_type": by_type,
            "rejected": rejected,
        }
