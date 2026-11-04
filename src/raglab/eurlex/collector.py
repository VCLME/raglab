"""Collect EU compliance acts as one document per unit, language and version.

For each act of `raglab.eurlex.acts` and each language (French, English,
Portuguese):

1. download the Official Journal XHTML and the pinned consolidated versions
   from CELLAR (`raglab.eurlex.cellar`, cached under `raw/`);
2. split them into units (`raglab.eurlex.xhtml`): recitals, articles,
   annexes, and the preamble citations that give a delegated or implementing
   act its legal basis;
3. build the versions of each article and annex: the Official Journal text,
   then every consolidated version whose text differs (consolidations have
   no recitals: a recital keeps its Official Journal text). The amendment
   markers of the consolidated text say which act changed the unit (the
   Digital Omnibus "inserted" AI Act Article 4a) or which corrigendum
   corrected it;
4. read the references of each unit (`raglab.eurlex.references`);
5. write one `.txt` + `.json` sidecar per unit version under `corpus/`, then
   `manifest.json` (SHA-256 of every text and of every downloaded file) and
   `stats.json` (units per act / kind / language, references, versions).

One unit per document, as for the French code: a citation ("Article 32 of
the GDPR", "considérant 39 du RGPD") resolves to exactly one document
through its metadata, the same unit in another language shares its
`unit_key` (CELEX + kind + number), and every chunk carries the version
state of its unit (`in_force`, `valid_from`, `valid_to`) without parsing
text. Chunkers are untouched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from raglab.config import Settings, get_settings
from raglab.eurlex.acts import ACTS, BY_CELEX, LANGUAGES, UNIT_NAMES, ActSpec, celex_label, get_act
from raglab.eurlex.cellar import CellarClient
from raglab.eurlex.references import (
    RULES_VERSION,
    UnitReference,
    amended_act,
    citation_act,
    extract_references,
    find_acts,
    roman_to_int,
)
from raglab.eurlex.xhtml import ParsedAct, Unit, parse_act
from raglab.ingestion.readers import normalize_text
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

EURLEX_URL = "https://eur-lex.europa.eu/legal-content/{lang}/TXT/?uri=CELEX:{celex}"
ELI_KINDS = {"regulation": "reg", "directive": "dir", "decision": "dec"}
UNIT_KINDS = ("recital", "article", "annex")
_FILE_KINDS = {"recital": "rct", "article": "art", "annex": "anx"}


@dataclass(slots=True)
class UnitVersion:
    unit: Unit
    source_celex: str
    valid_from: str | None
    #: "original", "corrigendum", "amendment" or "consolidated" (text
    #: changed with no marker naming why)
    version_kind: str
    amended_by: list[dict[str, Any]] = field(default_factory=list)
    valid_to: str | None = None


def comparable(text: str) -> str:
    """Text reduced to letters and digits: two renderings of the same
    provision (Official Journal, consolidated) compare equal."""
    return re.sub(r"\W+", "", text.lower())


def consolidation_date(celex: str) -> str:
    """ "02024R1689-20260727" -> "2026-07-27"."""
    raw = celex.rsplit("-", 1)[1]
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def file_number(kind: str, number: str) -> str:
    """Sortable number in file names: "006", "004a", "III" -> "03-III"."""
    if kind == "annex":
        if re.fullmatch(r"[IVXLC]+", number):
            return f"{roman_to_int(number):02d}-{number}"
        return number.zfill(2)
    match = re.match(r"(\d+)(.*)", number)
    return f"{int(match.group(1)):03d}{match.group(2)}" if match else number


def file_stem(act: ActSpec, language: str, kind: str, number: str, source_celex: str) -> str:
    tag = "oj" if source_celex == act.celex else "c" + source_celex.rsplit("-", 1)[1]
    return f"{act.key}_{language}_{_FILE_KINDS[kind]}{file_number(kind, number)}_{tag}"


def unit_label(kind: str, unit: Unit, language: str) -> str:
    """ "Article 6", "Artigo 9.º", "Considérant 39", "Annex III"."""
    if kind in ("article", "annex") and unit.heading:
        if kind == "article":
            return unit.heading
        # Annex headings are in capitals in the Official Journal ("ANNEX III").
        word, _, rest = unit.heading.partition(" ")
        return f"{word.capitalize()} {rest}".strip()
    word = UNIT_NAMES[language][kind]
    return f"{word} {unit.number}" if unit.number else word


def build_versions(
    act: ActSpec, original: ParsedAct, consolidated: list[tuple[str, ParsedAct]]
) -> dict[tuple[str, str], list[UnitVersion]]:
    """Versions of every unit of one act in one language, oldest first."""
    oj_date = original.oj_date
    versions: dict[tuple[str, str], list[UnitVersion]] = {}
    for unit in original.units:
        if unit.kind in UNIT_KINDS:
            versions[(unit.kind, unit.number)] = [UnitVersion(unit, act.celex, oj_date, "original")]
    for celex, parsed in consolidated:
        date = consolidation_date(celex)
        present: set[tuple[str, str]] = set()
        for unit in parsed.units:
            if unit.kind not in ("article", "annex"):
                continue
            key = (unit.kind, unit.number)
            present.add(key)
            history = versions.setdefault(key, [])
            latest = history[-1] if history else None
            if latest is not None and comparable(latest.unit.title + latest.unit.body) == comparable(
                unit.title + unit.body
            ):
                continue
            markers = {source: actions for source, actions in unit.markers.items() if source != act.celex}
            if markers and all("R(" in source for source in markers):
                kind = "corrigendum"
            elif markers:
                kind = "amendment"
            elif latest is None:
                # Only in a consolidated version (AI Act Article 75b, inserted
                # by the Digital Omnibus under a marker placed before it).
                kind = "inserted"
            else:
                kind = "consolidated"
            if latest is not None:
                latest.valid_to = date
            history.append(
                UnitVersion(
                    unit,
                    celex,
                    date,
                    kind,
                    amended_by=[{"celex": source, "actions": actions} for source, actions in sorted(markers.items())],
                )
            )
        # A unit dropped by a later consolidation is no longer in force.
        for key, history in versions.items():
            if key[0] in ("article", "annex") and key not in present and history[-1].valid_to is None:
                history[-1].valid_to = date
    return versions


def legal_basis(act: ActSpec, parsed: ParsedAct, language: str) -> list[dict[str, Any]]:
    """Acts and articles named by the preamble citations: "Having regard to
    Regulation (EU) 2022/2554…, and in particular Article 15 thereof"."""
    basis: dict[str, dict[str, Any]] = {}
    for unit in parsed.of_kind("citation"):
        context = citation_act(unit.body)
        if context is None or context == act.celex:
            continue
        row = basis.setdefault(context, {"celex": context, "articles": [], "citation": unit.body})
        for reference in extract_references(unit.body, language, own_celex=act.celex, context_celex=context):
            if reference.unit == "article" and reference.celex == context and reference.number not in row["articles"]:
                row["articles"].append(reference.number)
    return list(basis.values())


def infer_base(reference: UnitReference, act: ActSpec, known_units: set[str] | frozenset[str]) -> UnitReference:
    """An unqualified reference to a unit the act does not have, in an act
    that supplements another one which has it, points to the base act:
    "Articles 91 to 93" in the AI Act scientific-panel regulation, written
    after "Article 90(1) of Regulation (EU) 2024/1689"."""
    if (
        reference.scope != "same_act"
        or act.base is None
        or reference.number is None
        or not known_units
        or f"{act.celex}:{reference.unit}:{reference.number}" in known_units
        or f"{act.base}:{reference.unit}:{reference.number}" not in known_units
    ):
        return reference
    return replace(reference, celex=act.base, scope="inferred")


def _act_references(text: str, own: str) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for mention in find_acts(text):
        if mention.celex is None or mention.celex == own or mention.celex in rows:
            continue
        rows[mention.celex] = {"celex": mention.celex, "text": mention.text, "in_corpus": mention.celex in BY_CELEX}
    return list(rows.values())


def _eli(act: ActSpec) -> str:
    return f"http://data.europa.eu/eli/{ELI_KINDS[act.kind]}/{act.year}/{act.number}/oj"


def unit_metadata(
    act: ActSpec,
    language: str,
    kind: str,
    history: list[UnitVersion],
    position: int,
    *,
    act_title: str,
    basis: list[dict[str, Any]],
    file_names: list[str],
    known_units: set[str] | frozenset[str] = frozenset(),
) -> tuple[str, dict[str, Any]]:
    """(document text, sidecar metadata) of one unit version."""
    version = history[position]
    unit = version.unit
    label = unit_label(kind, unit, language)
    header = f"{act.label(language)} — {label}"
    text = normalize_text("\n".join(part for part in (header, unit.title) if part) + "\n\n" + unit.body)
    # An amending article speaks about the act it amends ("Regulation (EU)
    # 2024/1689 is amended as follows"; DORA amends five other regulations
    # that way), and so do the recitals and annexes of an amending act.
    context = amended_act(unit.body) if kind == "article" else None
    if act.role == "amending" and kind != "article":
        context = act.base
    references = [
        infer_base(reference, act, known_units)
        for reference in extract_references(unit.body, language, own_celex=act.celex, context_celex=context)
    ]
    short = act.short_name(language)
    metadata: dict[str, Any] = {
        "title": f"{short} — {label}" + (f" — {unit.title}" if unit.title else ""),
        "act": act.key,
        "act_short": short,
        "act_label": act.label(language),
        "act_title": act_title,
        "act_type": act.kind,
        "act_role": act.role,
        "celex": act.celex,
        "base_celex": act.base,
        "eli": _eli(act),
        "unit": kind,
        "unit_number": unit.number,
        "unit_label": label,
        "unit_title": unit.title or None,
        "unit_key": f"{act.celex}:{kind}:{unit.number}",
        "paragraphs": unit.paragraphs,
        "language": language,
        "source_celex": version.source_celex,
        "version_kind": version.version_kind,
        "consolidation_date": None if version.source_celex == act.celex else consolidation_date(version.source_celex),
        "valid_from": version.valid_from,
        "valid_to": version.valid_to,
        "in_force": version.valid_to is None,
        "version": position + 1,
        "version_count": len(history),
        "versions": [
            {
                "file_name": file_names[index],
                "source_celex": sibling.source_celex,
                "version_kind": sibling.version_kind,
                "valid_from": sibling.valid_from,
                "valid_to": sibling.valid_to,
            }
            for index, sibling in enumerate(history)
        ],
        "amended_by": version.amended_by,
        "references": [reference.as_metadata() for reference in references],
        "act_references": _act_references(unit.body, act.celex),
        "amends_celex": context,
        "legal_basis": basis,
        "source": "eurlex",
        "source_mirror": "cellar",
        "source_url": EURLEX_URL.format(lang=language.upper(), celex=version.source_celex),
        "tags": ["eurlex", f"act_{act.key}", kind],
    }
    return text, metadata


def _distribution(counts: list[int]) -> dict[str, Any]:
    if not counts:
        return {}
    return {"mean": round(statistics.mean(counts), 2), "median": statistics.median(counts), "max": max(counts)}


def corpus_stats(documents: list[dict[str, Any]], downloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Units per act / kind / language, references, versions: what each
    failure mode has to work with."""
    units = {(row["unit_key"], row["language"]) for row in documents}
    current = [row for row in documents if row["in_force"]]
    keys = {row["unit_key"] for row in documents}
    annex_counts = Counter(row["celex"] for row in documents if row["unit"] == "annex" and row["language"] == "en")

    def exists(reference: dict[str, Any]) -> str:
        celex = reference.get("celex")
        if celex is None:
            return "treaty"
        if celex not in BY_CELEX:
            return "outside_corpus"
        number = reference.get("number")
        if reference["unit"] == "annex" and number is None:
            return "in_corpus" if annex_counts.get(celex) == 1 else "unknown_unit"
        return "in_corpus" if f"{celex}:{reference['unit']}:{number}" in keys else "unknown_unit"

    scope_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    pairs: Counter[str] = Counter()
    recital_links: set[tuple[str, str]] = set()
    outside: Counter[str] = Counter()
    for row in current:
        for reference in row["references"]:
            if (
                reference["unit"] == "article"
                and reference.get("number") == row["unit_number"]
                and (reference.get("celex") == row["celex"] and row["unit"] == "article")
            ):
                continue  # an article citing itself
            target = exists(reference)
            scope_counts[reference["scope"]] += 1
            target_counts[target] += 1
            celex = reference.get("celex")
            if target == "in_corpus":
                kind = "within_act" if celex == row["celex"] else "across_acts"
                pairs[f"{row['unit']}->{reference['unit']}:{kind}"] += 1
                if row["unit"] == "recital" and reference["unit"] == "article" and celex == row["celex"]:
                    recital_links.add((row["unit_key"], f"{celex}:article:{reference['number']}"))
            elif target == "outside_corpus" and celex:
                outside[celex_label(celex)] += 1
        for act_reference in row["act_references"]:
            if not act_reference["in_corpus"]:
                outside[celex_label(act_reference["celex"])] += 0
    by_act: dict[str, dict[str, Any]] = {}
    for act in ACTS:
        rows = [row for row in documents if row["act"] == act.key]
        if not rows:
            continue
        by_act[act.key] = {
            "celex": act.celex,
            "documents": len(rows),
            "units": {kind: len({row["unit_key"] for row in rows if row["unit"] == kind}) for kind in UNIT_KINDS},
            "by_language": dict(sorted(Counter(row["language"] for row in rows).items())),
            "consolidations": list(act.consolidations),
            "units_with_later_versions": len({row["unit_key"] for row in rows if row["version_count"] > 1}),
            "legal_basis": rows[0]["legal_basis"],
        }
    version_kinds = Counter(row["version_kind"] for row in documents)
    return {
        "documents": len(documents),
        "units": len(keys),
        "unit_language_pairs": len(units),
        "documents_by_kind": dict(sorted(Counter(row["unit"] for row in documents).items())),
        "documents_by_language": dict(sorted(Counter(row["language"] for row in documents).items())),
        "documents_in_force": len(current),
        "version_kinds": dict(sorted(version_kinds.items())),
        "versions_per_unit": _distribution(
            list(Counter((row["unit_key"], row["language"]) for row in documents).values())
        ),
        "amended_units": sorted(
            {row["unit_key"] for row in documents if row["version_kind"] in ("amendment", "corrigendum")}
        ),
        "by_act": by_act,
        "chars_total": sum(row["chars"] for row in documents),
        "chars_median": statistics.median([row["chars"] for row in documents]) if documents else 0,
        "references_in_force": {
            "mentions": sum(target_counts.values()),
            "by_scope": dict(sorted(scope_counts.items())),
            "by_target": dict(sorted(target_counts.items())),
            "in_corpus_pairs": dict(sorted(pairs.items())),
            "recital_to_article_links": len(recital_links),
            "acts_outside_corpus": dict(outside.most_common(15)),
        },
        "downloads": {
            "files": len(downloads),
            "bytes": sum(row["bytes"] for row in downloads),
            "missing": [f"{row['celex']}.{row['language']}" for row in downloads if row.get("missing")],
        },
    }


class EurlexCollector:
    def __init__(self, settings: Settings | None = None, *, client: CellarClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client

    def collect(
        self,
        *,
        acts: list[str] | None = None,
        languages: list[str] | None = None,
        output_dir: Path | None = None,
        delay: float = 1.0,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """`progress(done, total)` is called after each CELLAR document
        (downloaded or read from the cache)."""
        specs = [get_act(key) for key in (acts or [act.key for act in ACTS])]
        languages = languages or list(LANGUAGES)
        unknown = [language for language in languages if language not in LANGUAGES]
        if unknown:
            raise ValueError(f"Langues inconnues: {unknown} (connues: {', '.join(LANGUAGES)})")
        base_dir = (output_dir or self.settings.eurlex_dir / "compliance").resolve()
        corpus_dir = base_dir / "corpus"
        corpus_dir.mkdir(parents=True, exist_ok=True)
        for stale in [*corpus_dir.glob("*.txt"), *corpus_dir.glob("*.json")]:
            stale.unlink()
        client = self._client or CellarClient(
            base_dir / "raw", delay=delay, timeout=self.settings.eurlex_request_timeout_seconds
        )
        total = sum(len(languages) * (1 + len(act.consolidations)) for act in specs)
        fetched = 0

        def advance() -> None:
            nonlocal fetched
            fetched += 1
            if progress is not None:
                progress(fetched, total)

        documents: list[dict[str, Any]] = []
        manifest_rows: list[dict[str, Any]] = []
        downloads: list[dict[str, Any]] = []
        parsed: list[tuple[ActSpec, str, ParsedAct, dict[tuple[str, str], list[UnitVersion]]]] = []
        for act in specs:
            for language in languages:
                original_download = client.fetch(act.celex, language)
                assert original_download is not None
                advance()
                downloads.append(_download_row(original_download))
                original = parse_act(original_download.path.read_bytes())
                consolidated: list[tuple[str, ParsedAct]] = []
                for celex in act.consolidations:
                    download = client.fetch(celex, language, missing_ok=True)
                    advance()
                    if download is None:
                        downloads.append({"celex": celex, "language": language, "missing": True, "bytes": 0})
                        continue
                    downloads.append(_download_row(download))
                    consolidated.append((celex, parse_act(download.path.read_bytes())))
                parsed.append((act, language, original, build_versions(act, original, consolidated)))
        # Every unit of every act, to tell a reference to a missing unit.
        known_units = {f"{act.celex}:{kind}:{number}" for act, _, _, versions in parsed for kind, number in versions}

        for act, language, original, versions in parsed:
            basis = legal_basis(act, original, language)
            for (kind, number), history in sorted(versions.items(), key=lambda item: _sort_key(*item[0])):
                names = [f"{file_stem(act, language, kind, number, v.source_celex)}.txt" for v in history]
                for position in range(len(history)):
                    if not history[position].unit.body.strip():
                        continue
                    text, metadata = unit_metadata(
                        act,
                        language,
                        kind,
                        history,
                        position,
                        act_title=original.title,
                        basis=basis,
                        file_names=names,
                        known_units=known_units,
                    )
                    text_path = corpus_dir / names[position]
                    text_path.write_text(text, encoding="utf-8")
                    text_path.with_suffix(".json").write_text(
                        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    manifest_rows.append({"file_name": text_path.name, "chars": len(text), "sha256": digest})
                    documents.append({**metadata, "chars": len(text)})

        stats = corpus_stats(documents, downloads)
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "source": "cellar",
            "rules_version": RULES_VERSION,
            "acts": [{"key": act.key, "celex": act.celex, "consolidations": list(act.consolidations)} for act in specs],
            "languages": languages,
            "downloads": sorted(downloads, key=lambda row: (row["celex"], row["language"])),
            "documents": sorted(manifest_rows, key=lambda row: row["file_name"]),
        }
        (base_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (base_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        (base_dir / "metadata.json").write_text(
            json.dumps(
                {"loader": "eurlex_compliance", "language": "multi", "languages": languages, "licence": LICENCE},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log_event(
            LOGGER,
            logging.INFO,
            "eurlex.collect.completed",
            acts=len(specs),
            languages=languages,
            documents=len(documents),
        )
        return {
            "output_dir": str(base_dir),
            "corpus_dir": str(corpus_dir),
            "documents": len(documents),
            "stats": stats,
        }


LICENCE = "© Union européenne, EUR-Lex / CELLAR ; réutilisation autorisée (décision 2011/833/UE de la Commission)"


def _download_row(download: Any) -> dict[str, Any]:
    return {
        "celex": download.celex,
        "language": download.language,
        "file": download.path.name,
        "bytes": download.path.stat().st_size,
        "sha256": download.sha256,
    }


def _sort_key(kind: str, number: str) -> tuple[int, str]:
    return (UNIT_KINDS.index(kind), file_number(kind, number))
