"""Frozen question set for the "cross-references" failure mode (phase 9.9b).

Each question starts from a real reference of the LexML corpus: article A
cites article B ("as penalidades do art. 12", "nos termos do art. 5º da Lei
nº X"), and the answer is quoted from B. A retriever that finds A, the
article that looks like the question, still misses the answer; following the
reference is what this set measures.

Pairs come from the structured graph's rules (`raglab.graph.legal`), read
directly from the frozen corpus files, so the set does not depend on an index
run, its chunking or Neo4j. The local LLM (Qwen3.6 via llama.cpp, as for the
LexML set) writes one question and quotes the answer from B; the same checks
as the LexML set drop the rest (quote found in B, length, boilerplate,
vagueness), plus three of their own: the question must not cite B's number
(the citation resolver would then find B directly), the answer must not also
be in A, and a `via_article` question must cite A and its law.

Two question types:

* ``via_article`` — the question cites article A and its law ("Quais
  penalidades se aplicam a quem descumpre o art. 5º da Lei nº 8.078?"), the
  canonical case;
* ``via_topic`` — the question names A's subject without any number.

Relevance is judged on B only (`expected_spans`): a run that returns A alone
must not pass. A's citing sentence is kept in `citing_spans` for analysis. A
seeded share of the questions is marked `split: "dev"` (may be looked at
while tuning); the others are `heldout`.
"""

from __future__ import annotations

import json
import logging
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from raglab.benchmarks.base import write_metadata
from raglab.benchmarks.lexml_questions import (
    _letter_ratio,
    _parse,
    lexical_overlap,
    text_rejection_reason,
)
from raglab.benchmarks.squad_style import locate_span
from raglab.config import Settings, get_settings
from raglab.graph.legal import article_label, format_law_number
from raglab.graph.structure import DocumentRow, build_payload
from raglab.llm.openai_compat import OpenAICompatibleChat
from raglab.logging_utils import log_event
from raglab.ollama.service import OllamaService

LOGGER = logging.getLogger(__name__)

QUESTION_TYPES = ("via_article", "via_topic")
DEV_SHARE = 0.3
MAX_ARTICLE_CHARS = 1800
MIN_TARGET_CHARS = 120

_SYSTEM_PROMPT = """Você cria perguntas para avaliar um sistema de busca em \
leis federais brasileiras. A busca é feita em centenas de leis. Você recebe \
o ASSUNTO DA LEI, um ARTIGO DE ORIGEM que remete a outro artigo, e o ARTIGO \
CITADO. Escreva UMA pergunta em português sobre o assunto do artigo de \
origem cuja resposta só está no artigo citado, e a RESPOSTA curta copiada \
literalmente do ARTIGO CITADO.

Tipos:
* via_article — a pergunta cita o número do artigo de origem e o número da \
lei indicados em REFERÊNCIA (ex.: "Que prazo se aplica aos contratos do \
art. 10-B da Lei nº 11.445?").
* via_topic — a pergunta descreve o assunto do artigo de origem com outras \
palavras, sem citar nenhum número de artigo nem de lei.

Regras:
* Nunca cite o número do ARTIGO CITADO: quem pergunta não sabe para onde o \
artigo de origem remete.
* A pergunta deve fazer sentido sozinha para quem não leu os artigos: \
mencione o tema da lei para que só exista uma resposta entre todas as leis. \
Nunca escreva "neste artigo", "segundo o texto", "o referido".
* A resposta deve ser uma cópia exata de um pedaço do ARTIGO CITADO (3 a 25 \
palavras) que não aparece no artigo de origem.

Responda apenas com JSON: {"question": "...", "answer": "..."}"""

_VETOED_OR_REVOKED_RE = re.compile(r"\((?:VETADO|Vetado|Revogad[oa])", re.IGNORECASE)
_AMENDING_RE = re.compile(r"passa(?:m)?\s+a\s+vigorar|fica(?:m)?\s+acrescid", re.IGNORECASE)
_FORMAL_CLAUSE_RE = re.compile(
    r"entra(?:m)?\s+em\s+vigor|revoga(?:m)?-se|fica(?:m)?\s+revogad|produzindo\s+efeitos", re.IGNORECASE
)


@dataclass(slots=True)
class ReferencePair:
    """Article A (source) cites article B (target)."""

    source_file: str
    source_law: str
    source_ementa: str
    source_article: str
    source_start: int
    source_end: int
    citing_start: int
    target_file: str
    target_law: str
    target_article: str
    target_start: int
    target_end: int
    scope: str


def load_corpus(corpus_dir: Path) -> tuple[list[DocumentRow], dict[str, str]]:
    """Frozen corpus files as rows (id = file name) and their texts."""
    documents: list[DocumentRow] = []
    texts: dict[str, str] = {}
    for text_path in sorted(corpus_dir.glob("*.txt")):
        sidecar_path = text_path.with_suffix(".json")
        metadata = json.loads(sidecar_path.read_text(encoding="utf-8")) if sidecar_path.exists() else {}
        text = text_path.read_text(encoding="utf-8")
        documents.append(DocumentRow(id=text_path.name, file_name=text_path.name, content=text, metadata=metadata))
        texts[text_path.name] = text
    return documents, texts


def reference_pairs(documents: list[DocumentRow]) -> list[ReferencePair]:
    """Every in-corpus article-to-article reference, from the graph's rules."""
    payload = build_payload(index_run_id="refs", corpus="refs", documents=documents, chunks=[], profile="laws")
    articles = {row["uid"]: row for row in payload.nodes.get("Article", [])}
    laws = {row["document_id"]: row for row in payload.nodes.get("Document", [])}
    pairs: list[ReferencePair] = []
    for row in payload.relationships.get(("CITES", "Article", "Article"), []):
        source, target = articles[row["source"]], articles[row["target"]]
        source_law, target_law = laws[source["document_id"]], laws[target["document_id"]]
        offset = int(row["props"].get("offset") or source["char_start"])
        pairs.append(
            ReferencePair(
                source_file=source["document_id"],
                source_law=_law_title(source_law),
                source_ementa=str(source_law.get("ementa") or ""),
                source_article=source["number"],
                source_start=source["char_start"],
                source_end=source["char_end"],
                citing_start=offset,
                target_file=target["document_id"],
                target_law=_law_title(target_law),
                target_article=target["number"],
                target_start=target["char_start"],
                target_end=target["char_end"],
                scope=row["props"].get("scope", ""),
            )
        )
    return sorted(pairs, key=lambda pair: (pair.source_file, pair.source_start, pair.target_file, pair.target_start))


def _law_title(row: dict[str, Any]) -> str:
    number = row.get("number")
    return f"Lei nº {format_law_number(str(number))}" if number else str(row.get("title") or "")


def eligible(pair: ReferencePair, texts: dict[str, str]) -> bool:
    """A pair worth a question: the cited article is substantive (not
    revoked, vetoed, or an amendment of another law whose text is quoted),
    and the citing one is not a commencement or revocation clause."""
    target = texts[pair.target_file][pair.target_start : pair.target_end]
    source = texts[pair.source_file][pair.source_start : pair.source_end]
    if len(target.strip()) < MIN_TARGET_CHARS or _letter_ratio(target) < 0.6:
        return False
    if _VETOED_OR_REVOKED_RE.search(target[:120]) or _AMENDING_RE.search(target[:300]):
        return False
    return not _FORMAL_CLAUSE_RE.search(source[:200])


def sample_pairs(pairs: list[ReferencePair], texts: dict[str, str], *, count: int, seed: int) -> list[ReferencePair]:
    """Seeded draw, one pair per citing law first, then round-robin, so
    laws with many references do not dominate the set."""
    rng = random.Random(seed)
    by_law: dict[str, list[ReferencePair]] = defaultdict(list)
    for pair in pairs:
        if eligible(pair, texts):
            by_law[pair.source_file].append(pair)
    laws = sorted(by_law)
    rng.shuffle(laws)
    for law in laws:
        rng.shuffle(by_law[law])
    drawn: list[ReferencePair] = []
    seen_targets: set[tuple[str, str]] = set()
    while len(drawn) < count and any(by_law.values()):
        for law in laws:
            while by_law[law]:
                pair = by_law[law].pop()
                if (pair.target_file, pair.target_article) not in seen_targets:
                    seen_targets.add((pair.target_file, pair.target_article))
                    drawn.append(pair)
                    break
            if len(drawn) >= count:
                break
    return drawn


def rejection_reason(
    generated: dict[str, str] | None, pair: ReferencePair, question_type: str, texts: dict[str, str]
) -> str | None:
    if generated is None:
        return "invalid_json"
    target = texts[pair.target_file][pair.target_start : pair.target_end]
    source = texts[pair.source_file][pair.source_start : pair.source_end]
    span = locate_span(target, generated["answer"])
    if span is None:
        return "quote_not_found"
    reason = text_rejection_reason(generated["question"], span["text"])
    if reason is not None:
        return reason
    if span["text"].strip() and span["text"].strip() in source:
        return "answer_in_source"
    question = generated["question"]
    if _cites_article(question, pair.target_article):
        return "leaks_target"
    if question_type == "via_topic" and re.search(r"\b(?:art\.|artigo|lei\s+n)", question, re.IGNORECASE):
        return "leaks_reference"
    if question_type == "via_article":
        law_digits = re.sub(r"\D", "", pair.source_law)
        if not _cites_article(question, pair.source_article) or law_digits not in re.sub(r"\D", "", question):
            return "reference_missing"
    return None


def _cites_article(question: str, article: str) -> bool:
    number, _, letter = article.partition("-")
    suffix = rf"\s*[º°o]?\s*-?\s*{letter}\b" if letter else r"(?![\d-])"
    return bool(re.search(rf"\bart(?:\.|igo)\s*{number}{suffix}", question, re.IGNORECASE))


class LexMLReferenceQuestionGenerator:
    """Write the references set with a chat backend (see LexMLQuestionGenerator)."""

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

    def _ask(self, pair: ReferencePair, question_type: str, texts: dict[str, str]) -> dict[str, str] | None:
        source = texts[pair.source_file][pair.source_start : pair.source_end][:MAX_ARTICLE_CHARS]
        target = texts[pair.target_file][pair.target_start : pair.target_end][:MAX_ARTICLE_CHARS]
        reference = (
            f"REFERÊNCIA: {article_label(pair.source_article).lower()} da {pair.source_law}\n"
            if question_type == "via_article"
            else ""
        )
        user = (
            f"ASSUNTO DA LEI: {pair.source_ementa or pair.source_law}\n"
            f"TIPO: {question_type}\n{reference}"
            f"ARTIGO DE ORIGEM ({pair.source_law}):\n{source}\n\n"
            f"ARTIGO CITADO ({pair.target_law}):\n{target}\n\nResponda apenas com JSON."
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
        except Exception as exc:  # network or model errors drop the pair
            log_event(LOGGER, logging.WARNING, "lexml.references.chat_failed", error=str(exc))
            return None
        return _parse(result.get("answer", ""))

    def generate(
        self,
        *,
        corpus_dir: Path | None = None,
        output_dir: Path,
        count: int = 100,
        seed: int = 42,
    ) -> dict[str, Any]:
        corpus_dir = (corpus_dir or self.settings.lexml_fulltext_dir / "corpus").resolve()
        output_dir = output_dir.resolve()
        documents, texts = load_corpus(corpus_dir)
        urns = {document.id: str(document.metadata.get("urn") or "") for document in documents}
        pairs = reference_pairs(documents)
        # Over-sample: some questions are rejected by the checks.
        drawn = sample_pairs(pairs, texts, count=int(count * 2.5) + 10, seed=seed)

        cases: list[dict[str, Any]] = []
        rejected: dict[str, int] = defaultdict(int)
        kept = dict.fromkeys(QUESTION_TYPES, 0)
        for pair in drawn:
            if len(cases) >= count:
                break
            question_type = min(QUESTION_TYPES, key=lambda kind: kept[kind])
            generated = self._ask(pair, question_type, texts)
            reason = rejection_reason(generated, pair, question_type, texts)
            if reason is not None:
                rejected[reason] += 1
                continue
            assert generated is not None
            target_text = texts[pair.target_file][pair.target_start : pair.target_end]
            span = locate_span(target_text, generated["answer"])
            assert span is not None
            kept[question_type] += 1
            source_text = texts[pair.source_file]
            citing_line_start = source_text.rfind("\n", pair.source_start, pair.citing_start) + 1
            citing_line_end = source_text.find("\n", pair.citing_start)
            citing_line_end = pair.source_end if citing_line_end == -1 else min(citing_line_end, pair.source_end)
            cases.append(
                {
                    "id": f"lexml-ref-{len(cases) + 1:04d}",
                    "question": generated["question"],
                    "expected_file_names": [pair.target_file],
                    "ground_truth_answer": span["text"],
                    "expected_substrings": [span["text"]],
                    "expected_urns": [urns[pair.target_file]] if urns.get(pair.target_file) else [],
                    "expected_spans": [
                        {
                            "file_name": pair.target_file,
                            "start": pair.target_start + span["start"],
                            "end": pair.target_start + span["end"],
                            "text": span["text"],
                        }
                    ],
                    "citing_spans": [
                        {
                            "file_name": pair.source_file,
                            "start": max(citing_line_start, pair.source_start),
                            "end": citing_line_end,
                            "text": source_text[max(citing_line_start, pair.source_start) : citing_line_end],
                        }
                    ],
                    "source_article": f"{article_label(pair.source_article)} — {pair.source_law}",
                    "target_article": f"{article_label(pair.target_article)} — {pair.target_law}",
                    "reference_scope": pair.scope,
                    "question_type": question_type,
                    "lexical_overlap": round(lexical_overlap(generated["question"], target_text), 3),
                    "review_status": "generated",
                }
            )
        assign_splits(cases, seed=seed)

        output_dir.mkdir(parents=True, exist_ok=True)
        ground_truth_path = output_dir / "ground_truth.jsonl"
        ground_truth_path.write_text(
            "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8"
        )
        by_type = {kind: sum(1 for case in cases if case["question_type"] == kind) for kind in QUESTION_TYPES}
        by_split = {split: sum(1 for case in cases if case["split"] == split) for split in ("dev", "heldout")}
        write_metadata(
            output_dir / "metadata.json",
            {
                "loader": "lexml_references",
                "language": "pt",
                "licence": "Public domain (Lei 9.610/1998, art. 8º, IV)",
                "generator_model": self.model,
                "generator_backend": self.backend,
                "seed": seed,
                "case_count": len(cases),
                "by_type": by_type,
                "by_split": by_split,
                "reference_pairs": len(pairs),
                "rejected": dict(rejected),
                "corpus_dir": str(corpus_dir),
            },
        )
        log_event(LOGGER, logging.INFO, "lexml.references.completed", cases=len(cases), by_type=by_type)
        return {
            "ground_truth_path": str(ground_truth_path),
            "case_count": len(cases),
            "by_type": by_type,
            "by_split": by_split,
            "reference_pairs": len(pairs),
            "rejected": dict(rejected),
        }


def assign_splits(cases: list[dict[str, Any]], *, seed: int, dev_share: float = DEV_SHARE) -> None:
    """Seeded `dev` / `heldout` split: only `dev` questions may be looked at
    while tuning the graph branch."""
    order = list(range(len(cases)))
    random.Random(f"{seed}:split").shuffle(order)
    dev = set(order[: round(len(cases) * dev_share)])
    for index, case in enumerate(cases):
        case["split"] = "dev" if index in dev else "heldout"


def generate_reference_questions(
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
    """Entry point of the CLI. With llama.cpp, Ollama is unloaded and
    llama-server started for the run, stopped afterwards if raglab started it."""
    from raglab.llm.local_server import LocalLLMServer

    generator = LexMLReferenceQuestionGenerator(settings, model=model, backend=backend)
    if backend != "llamacpp":
        return generator.generate(corpus_dir=corpus_dir, output_dir=output_dir, count=count, seed=seed)
    with LocalLLMServer(settings, profile=profile or settings.question_model_profile):
        return generator.generate(corpus_dir=corpus_dir, output_dir=output_dir, count=count, seed=seed)
