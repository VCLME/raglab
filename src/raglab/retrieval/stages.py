"""Pipeline stage events for the Chat's educational mode (SSE `stage`).

The stage list is derived from what the request actually ran: the stage keys
of `RetrievalOutcome.timings_ms` (`embed`, `retrieval`, and `dense`,
`lexical`, `fusion`, `rerank` when hybrid retrieval or re-ranking ran,
`versions` when a passage carries version information), the
router decision when one is attached, then `prompt` and `generation` when an
answer is generated. A stage the pipeline did not run is simply absent.

Embed and search run before the HTTP response starts (so their failures keep
a real status code), hence their events are replayed from the finished
outcome with `live: false`; prompt and generation events are emitted live.
"""

from __future__ import annotations

import math
from typing import Any

# Order of the retrieval-side stages, as drawn in the UI diagram.
RETRIEVAL_STAGES = ("routing", "embed", "retrieval", "lexical", "graph", "fusion", "rerank", "versions")
GENERATION_STAGES = ("prompt", "generation")

VECTOR_PREVIEW = 8
TOP_CHUNKS = 5
GRAPH_LINKS = 8
EXCERPT_CHARS = 160
PROMPT_PREVIEW_CHARS = 600


def stage_start(stage: str, t_ms: float, *, live: bool = True) -> dict[str, Any]:
    return {"stage": stage, "status": "start", "t_ms": round(t_ms, 3), "live": live}


def stage_end(
    stage: str,
    t_ms: float,
    duration_ms: float | None,
    *,
    counts: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    live: bool = True,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": "end",
        "t_ms": round(t_ms, 3),
        "duration_ms": None if duration_ms is None else round(duration_ms, 3),
        "counts": counts or {},
        "data": data or {},
        "live": live,
    }


def _retrieval_durations(timings_ms: dict[str, float]) -> dict[str, float]:
    """Duration of each retrieval-side stage the request ran, keyed by UI stage.

    With hybrid retrieval `retrieval` is the whole search and `dense` its
    vector part; the vector-search stage then reports `dense`. A lexical-only
    search has no vector stage at all.
    """
    durations: dict[str, float] = {}
    for key in ("routing", "embed"):
        if key in timings_ms:
            durations[key] = timings_ms[key]
    if "dense" in timings_ms:
        durations["retrieval"] = timings_ms["dense"]
    elif "retrieval" in timings_ms and "lexical" not in timings_ms:
        durations["retrieval"] = timings_ms["retrieval"]
    for key in ("lexical", "graph", "fusion", "rerank", "versions"):
        if key in timings_ms:
            durations[key] = timings_ms[key]
    return durations


def _chunk_preview(chunk: Any) -> dict[str, Any]:
    payload = chunk.model_dump(mode="json")
    preview = {
        "rank": payload.get("rank"),
        "file_name": payload.get("file_name"),
        "excerpt": (payload.get("chunk_text") or "")[:EXCERPT_CHARS],
    }
    # `score` plus whatever intermediate scores and ranks the pipeline filled
    # in (dense_*, lexical_*, fused_*, rerank_*): the learning mode draws the
    # RRF formula and the re-ranking reorder from them.
    for key, value in payload.items():
        if (key.endswith("score") or key.endswith("_rank")) and value is not None:
            preview[key] = value
    # Passages placed by a rule rather than by their score: the cited article
    # (citation resolver), a cited passage kept next to the one citing it.
    for key in ("citation_match", "graph_pinned"):
        if payload.get(key):
            preview[key] = True
    version = payload.get("version")
    if version:
        # Version state of the passage (versions option): the learning mode
        # shows which version it is and whether it applies.
        preview["version"] = {
            key: version[key]
            for key in ("source", "etat", "in_force", "date_debut", "date_fin", "article", "revoked_only", "demoted")
            if version.get(key) is not None
        }
    return preview


def _top_chunks(retrieved: list[Any]) -> list[dict[str, Any]]:
    return [_chunk_preview(chunk) for chunk in retrieved[:TOP_CHUNKS]]


def _vector_preview(vector: list[float] | None) -> dict[str, Any]:
    if not vector:
        return {}
    return {
        "dimension": len(vector),
        "head": [round(float(value), 4) for value in vector[:VECTOR_PREVIEW]],
        "norm": round(math.sqrt(sum(float(value) ** 2 for value in vector)), 4),
    }


def _routing_payload(routing: Any) -> dict[str, Any]:
    if routing is None:
        return {}
    if hasattr(routing, "model_dump"):
        return routing.model_dump(mode="json")
    return {"decision": str(routing)}


def _stage_details(stage: str, outcome: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    retrieved = outcome.retrieved
    if stage == "embed":
        vector = _vector_preview(getattr(outcome, "query_embedding", None))
        return ({"dimension": vector["dimension"]} if vector else {}), vector
    if stage == "routing":
        return {}, _routing_payload(getattr(outcome, "routing", None))
    if stage == "graph":
        # What the third branch found: seeds, cited articles followed, the
        # passages it fetched and those new to the fusion; or why it was
        # skipped (Neo4j off, no graph for the index run).
        data: dict[str, Any] = {
            "links": list(getattr(outcome, "graph_links", []))[:GRAPH_LINKS],
            "top_chunks": _top_chunks(getattr(outcome, "graph_chunks", [])),
        }
        notice = getattr(outcome, "graph_notice", None)
        if notice:
            data["notice"] = notice
        return dict(getattr(outcome, "graph_stats", {}) or {}), data
    if stage == "versions":
        # The rule applied (mode, reference date and where it came from) and
        # what it did: versions filtered before ranking, repealed-only
        # passages moved last, outdated passages still in the list.
        info = dict(getattr(outcome, "versions", None) or {})
        version_counts: dict[str, Any] = {key: info[key] for key in ("demoted", "outdated") if key in info}
        version_counts["chunks_out"] = len(retrieved)
        return version_counts, {"policy": info, "top_chunks": _top_chunks(retrieved)}
    counts: dict[str, Any] = {"chunks_out": len(retrieved)}
    if stage == "retrieval":
        counts["top_k"] = outcome.top_k
    candidates = getattr(outcome, "rerank_candidates", None)
    if stage == "rerank" and candidates:
        counts["candidates_in"] = candidates
    return counts, {"top_chunks": _top_chunks(retrieved)}


def planned_stages(outcome: Any, *, generate: bool) -> list[str]:
    """Stages this request runs, in pipeline order."""
    durations = _retrieval_durations(outcome.timings_ms)
    stages = [stage for stage in RETRIEVAL_STAGES if stage in durations]
    if getattr(outcome, "routing", None) is not None and "routing" not in stages:
        stages.insert(0, "routing")
    if generate:
        stages.extend(GENERATION_STAGES)
    return stages


def retrieval_stage_events(outcome: Any) -> list[dict[str, Any]]:
    """Replay the stages that ran before the response started, in order."""
    durations = _retrieval_durations(outcome.timings_ms)
    events: list[dict[str, Any]] = []
    t_ms = 0.0
    for stage in planned_stages(outcome, generate=False):
        duration = durations.get(stage)
        counts, data = _stage_details(stage, outcome)
        events.append(stage_start(stage, t_ms, live=False))
        t_ms += duration or 0.0
        events.append(stage_end(stage, t_ms, duration, counts=counts, data=data, live=False))
    return events


def prompt_details(bundle: Any, chunks_in: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Counts and a truncated preview of the prompt sent to the LLM."""
    system, user = bundle.system_prompt, bundle.user_prompt
    counts = {"chunks_in": chunks_in, "prompt_chars": len(system) + len(user)}
    data = {
        "system_prompt": system[:PROMPT_PREVIEW_CHARS],
        "user_prompt": user[:PROMPT_PREVIEW_CHARS],
        "truncated": len(system) > PROMPT_PREVIEW_CHARS or len(user) > PROMPT_PREVIEW_CHARS,
    }
    return counts, data
