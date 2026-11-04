"""Collect a French code with its full version history (Légifrance data).

The official source of consolidated French law is the DILA LEGI open data
(`echanges.dila.gouv.fr/OPENDATA/LEGI/`, Licence Ouverte 2.0). It comes as a
1.1 GB global archive plus daily increments, for a few megabytes per code.
The tricoteuses project publishes the same data as one git repository per
code (`git.tricoteuses.fr/codes/<code>`): one Markdown file per article with
its LEGI metadata (LEGIARTI id, state, validity dates), and one commit per
amending text, dated at its entry into force and named after it. The whole
history of the Code de la consommation (1993 to today) is a 4.5 MB clone, so
that is what is collected here, pinned to a commit:

1. clone the repository bare (article paths exceed Windows' 260-character
   limit once checked out; nothing is checked out, blobs are read with
   `git cat-file`);
2. walk the history up to the pinned commit: every distinct LEGIARTI id is
   one version of an article, introduced by the commit that added it and
   ended by the one that replaced or removed it;
3. write one `.txt` + `.json` sidecar per version under `corpus/`: the text
   is what the article says (no version banner: the state lives in the
   metadata, which is what a version-aware retriever has to use), the
   sidecar carries the code, article number, hierarchy, state, dates,
   amending and ending texts, and the article references found in the text;
4. write `manifest.json` (SHA-256 of every text, source commit) and
   `stats.json` (articles in force / repealed, versions per article,
   cross-references), so a run can tell whether it measures the same corpus.

Every version is a document: one article per document keeps the unit a
lawyer cites, lets a citation resolve to exactly one document through its
metadata, and gives every chunk the state of its version without parsing
text. Chunkers are untouched: they cut each article like any other text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from raglab.config import Settings, get_settings
from raglab.ingestion.readers import normalize_text
from raglab.legifrance.codes import CodeSpec, get_code
from raglab.legifrance.references import extract_references, normalize_article_number
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

LEGIFRANCE_ARTICLE_URL = "https://www.legifrance.gouv.fr/codes/article_lc/{legi_id}"
# LEGI writes "no end date" as 2999-01-01.
_OPEN_END = "2999-01-01"
# States of a version that applies on the date the corpus is frozen:
# ABROGE_DIFF is repealed with a deferred date, still in force until then.
IN_FORCE_STATES = ("VIGUEUR", "ABROGE_DIFF")
_ARTICLE_FILE_RE = re.compile(r"(?:^|/)article_[^/]+\.md$")
_BLOCK_TAGS = {"p", "br", "div", "tr", "table", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}
_CELL_TAGS = {"td", "th"}
_SKIPPED_TAGS = {"script", "style"}


@dataclass(slots=True)
class AmendingText:
    """The text a commit stands for: "LOI n° 2014-344 du 17 mars 2014..."."""

    sha: str
    date: str
    title: str | None
    jorf_id: str | None = None
    nature: str | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {"title": self.title, "jorf_id": self.jorf_id, "nature": self.nature, "date": self.date}


@dataclass(slots=True)
class _Change:
    status: str
    blob: str
    path: str


@dataclass(slots=True)
class _Commit:
    text: AmendingText
    changes: list[_Change] = field(default_factory=list)


@dataclass(slots=True)
class ParsedArticle:
    fields: dict[str, str]
    title: str
    body: str
    nota: str


@dataclass(slots=True)
class ArticleVersion:
    legi_id: str
    label: str
    number: str
    path: str
    etat: str
    date_debut: str | None
    date_fin: str | None
    body: str
    nota: str
    introduced_by: str
    ended_by: str | None = None


class _HtmlText(HTMLParser):
    """Visible text of the article HTML, one block per line, table cells
    separated by " | "."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in _CELL_TAGS:
            self.parts.append(" | ")
        if tag in _SKIPPED_TAGS:
            self._skipping += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag in _SKIPPED_TAGS and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(markup: str) -> str:
    """Plain text of an article body: one paragraph per line, so the
    chunkers' sentence splitter sees paragraph boundaries."""
    lines: list[str] = []
    # Markdown paragraphs (blank-line separated) are paragraphs too, even
    # without a <br /> or <p> around them.
    for paragraph in re.split(r"\n\s*\n", markup):
        parser = _HtmlText()
        parser.feed(paragraph)
        parser.close()
        raw = unescape("".join(parser.parts)).replace("\xa0", " ")
        for line in raw.split("\n"):
            cleaned = re.sub(r"\s+", " ", line).strip().removeprefix("| ").strip()
            if cleaned and cleaned != "|":
                lines.append(cleaned)
    return normalize_text("\n".join(lines))


def parse_article_markdown(content: str) -> ParsedArticle:
    """Split a tricoteuses article file: YAML-like front matter, "# Article
    X" heading, body, optional "### Nota", "## [Autres formats]" footer."""
    fields: dict[str, str] = {}
    lines = content.replace("\r\n", "\n").split("\n")
    index = 0
    if lines and lines[0].strip() == "---":
        index = 1
        while index < len(lines) and lines[index].strip() != "---":
            key, separator, value = lines[index].partition(":")
            if separator:
                fields[key.strip()] = value.strip()
            index += 1
        index += 1
    title = ""
    sections: dict[str, list[str]] = {"body": [], "nota": []}
    current: str | None = None
    for line in lines[index:]:
        heading = re.match(r"^(#+)\s+(.*)$", line)
        if heading:
            level, text = len(heading.group(1)), heading.group(2).strip()
            if level == 1 and not title:
                title, current = text, "body"
            elif text.lower() == "nota":
                current = "nota"
            else:
                current = None  # "Autres formats" footer and anything after
            continue
        if current is not None:
            sections[current].append(line)
    return ParsedArticle(
        fields=fields,
        title=title,
        body=html_to_text("\n".join(sections["body"])),
        nota=html_to_text("\n".join(sections["nota"])),
    )


def _readme_title(content: str | None) -> tuple[str | None, str | None]:
    """(title, LEGISCTA id) of a section README."""
    if not content:
        return None, None
    identifier = re.search(r"^Identifiant:\s*(\S+)", content, re.MULTILINE)
    heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return (heading.group(1).strip() if heading else None), (identifier.group(1) if identifier else None)


def parse_commit_message(sha: str, date: str, message: str) -> AmendingText:
    lines = [line.strip() for line in message.strip().split("\n")]
    title = lines[0] if lines and lines[0] else None
    if title is None or title.startswith("!!!") or title == "Création du dépôt git":
        title = None
    trailer = dict(line.split(": ", 1) for line in lines if re.match(r"^(Identifiant|Nature|NOR): ", line))
    return AmendingText(
        sha=sha, date=date, title=title, jorf_id=trailer.get("Identifiant"), nature=trailer.get("Nature")
    )


class GitObjects:
    """Read blobs through one `git cat-file --batch` process."""

    def __init__(self, repository: Path) -> None:
        self._process = subprocess.Popen(
            ["git", "-C", str(repository), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    def read(self, spec: str) -> str | None:
        assert self._process.stdin is not None and self._process.stdout is not None
        self._process.stdin.write(spec.encode("utf-8") + b"\n")
        self._process.stdin.flush()
        header = self._process.stdout.readline().decode("utf-8").rstrip("\n")
        if header.endswith(" missing") or header.endswith(" ambiguous"):
            return None
        size = int(header.rsplit(" ", 1)[1])
        data = self._process.stdout.read(size)
        self._process.stdout.read(1)  # trailing newline
        return data.decode("utf-8")

    def close(self) -> None:
        if self._process.stdin:
            self._process.stdin.close()
        self._process.wait(timeout=30)

    def __enter__(self) -> GitObjects:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", "-C", str(repository), *args],
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout


def iter_commits(repository: Path, commit: str) -> Iterator[_Commit]:
    """Commits up to `commit`, oldest first, with their article changes."""
    log = _git(
        repository,
        "log",
        "--reverse",
        "--no-renames",
        "--raw",
        "--no-abbrev",
        "--date=short",
        "--format=%x1e%H%x1f%ad%x1f%B%x1f",
        commit,
    )
    for record in log.split("\x1e"):
        if not record.strip():
            continue
        sha, date, message, raw = record.split("\x1f", 3)
        entry = _Commit(text=parse_commit_message(sha.strip(), date.strip(), message))
        for line in raw.splitlines():
            if not line.startswith(":"):
                continue
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if _ARTICLE_FILE_RE.search(path):
                entry.changes.append(_Change(status=parts[4][0], blob=parts[3], path=path))
        yield entry


def walk_history(repository: Path, commit: str, objects: GitObjects) -> tuple[dict[str, ArticleVersion], list[_Commit]]:
    """Every article version (by LEGIARTI id) with the commits that
    introduced and ended it."""
    versions: dict[str, ArticleVersion] = {}
    current: dict[str, str] = {}  # path -> LEGIARTI id present there
    commits: list[_Commit] = []
    for entry in iter_commits(repository, commit):
        commits.append(entry)
        added: set[str] = set()
        gone: list[str] = []
        for change in entry.changes:
            if change.status == "D":
                if change.path in current:
                    gone.append(current.pop(change.path))
                continue
            content = objects.read(change.blob)
            if content is None:
                continue
            parsed = parse_article_markdown(content)
            legi_id = parsed.fields.get("Identifiant")
            if not legi_id:
                continue
            previous = current.get(change.path)
            if previous and previous != legi_id:
                gone.append(previous)
            current[change.path] = legi_id
            added.add(legi_id)
            label = parsed.fields.get("Numéro") or parsed.title.removeprefix("Article ").strip()
            end = parsed.fields.get("Date de fin")
            version = ArticleVersion(
                legi_id=legi_id,
                label=label,
                number=normalize_article_number(label),
                path=change.path,
                etat=parsed.fields.get("État", ""),
                date_debut=parsed.fields.get("Date de début"),
                date_fin=None if end in (None, "", _OPEN_END) else end,
                body=parsed.body,
                nota=parsed.nota,
                introduced_by=entry.text.sha,
            )
            known = versions.get(legi_id)
            if known is not None:
                # Same version, moved or corrected: keep where it came from.
                version.introduced_by = known.introduced_by
            versions[legi_id] = version
        for legi_id in gone:
            # A version re-added elsewhere in the same commit only moved.
            if legi_id not in added and legi_id in versions:
                versions[legi_id].ended_by = entry.text.sha
    return versions, commits


def _hierarchy(objects: GitObjects, commit: str, path: str, cache: dict[str, tuple[str | None, str | None]]):
    """Titles of the sections above an article, from their README files."""
    titles: list[str] = []
    section_id: str | None = None
    parts = path.split("/")[:-1]
    for depth in range(1, len(parts) + 1):
        spec = f"{commit}:{'/'.join(parts[:depth])}/README.md"
        if spec not in cache:
            cache[spec] = _readme_title(objects.read(spec))
        title, identifier = cache[spec]
        if title:
            titles.append(title)
        section_id = identifier or section_id
    return titles, section_id


def file_stem(code: CodeSpec, version: ArticleVersion) -> str:
    return f"{code.slug}_{re.sub(r'[^A-Za-z0-9-]+', '_', version.number).strip('_')}_{version.legi_id}"


def _dedupe(values: Iterable[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _distribution(counts: list[int]) -> dict[str, Any]:
    if not counts:
        return {}
    buckets = Counter(
        "1" if n == 1 else "2" if n == 2 else "3-5" if n <= 5 else "6-10" if n <= 10 else ">10" for n in counts
    )
    return {
        "mean": round(statistics.mean(counts), 2),
        "median": statistics.median(counts),
        "max": max(counts),
        "histogram": {key: buckets.get(key, 0) for key in ("1", "2", "3-5", "6-10", ">10")},
    }


def corpus_stats(code: CodeSpec, documents: list[dict[str, Any]], amending_texts: int) -> dict[str, Any]:
    """What each failure mode has to work with: identifiers, cross
    references, versions."""
    by_number: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metadata in documents:
        by_number[metadata["article_number"]].append(metadata)
    in_force_numbers = {
        number for number, rows in by_number.items() if any(row["etat"] in IN_FORCE_STATES for row in rows)
    }
    current = [row for row in documents if row["etat"] in IN_FORCE_STATES]

    internal = [ref for row in current for ref in row["references"]]
    external = [ref for row in current for ref in row["external_references"]]
    targets = Counter(
        "in_force" if ref in in_force_numbers else "no_longer_in_force" if ref in by_number else "unknown"
        for ref in internal
    )
    # Numbers used by two different articles over time: the 2016
    # recodification reused L. 121-1 etc. for other rules.
    reused = sum(1 for rows in by_number.values() if len({row["partie"] for row in rows}) > 1)
    # Versions whose text is identical to the previous version of the same
    # article (only the nota or the place in the code changed).
    identical = 0
    for rows in by_number.values():
        ordered = sorted(rows, key=lambda row: row["date_debut"] or "")
        identical += sum(1 for a, b in zip(ordered, ordered[1:], strict=False) if a["_body_sha"] == b["_body_sha"])
    return {
        "code": code.slug,
        "documents": len(documents),
        "articles": len(by_number),
        "articles_in_force": len(in_force_numbers),
        "articles_no_longer_in_force": len(by_number) - len(in_force_numbers),
        "versions_by_state": dict(Counter(row["etat"] for row in documents).most_common()),
        "versions_by_part": dict(Counter(row["partie"] for row in documents).most_common()),
        "versions_per_article": _distribution([len(rows) for rows in by_number.values()]),
        "articles_rewritten": sum(1 for rows in by_number.values() if len(rows) > 1),
        "article_numbers_reused_across_parts": reused,
        "versions_identical_to_previous": identical,
        "amending_texts": amending_texts,
        "chars_total": sum(row["chars"] for row in documents),
        "chars_median": statistics.median([row["chars"] for row in documents]) if documents else 0,
        "references_in_force": {
            "articles_citing": sum(1 for row in current if row["references"]),
            "internal_mentions": len(internal),
            "internal_targets": dict(targets),
            "other_code_mentions": len(external),
            "other_codes": dict(Counter(ref["code"] for ref in external).most_common(10)),
        },
    }


class CodeCollector:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def ensure_repository(self, code: CodeSpec, repository: Path, commit: str) -> None:
        if not (repository / "HEAD").exists():
            repository.parent.mkdir(parents=True, exist_ok=True)
            log_event(LOGGER, logging.INFO, "legifrance.clone", url=code.repository_url, target=repository)
            subprocess.run(
                ["git", "clone", "--bare", "--quiet", code.repository_url, str(repository)],
                check=True,
                capture_output=True,
            )
        probe = subprocess.run(
            ["git", "-C", str(repository), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True
        )
        if probe.returncode != 0:
            subprocess.run(
                ["git", "-C", str(repository), "fetch", "--quiet", "origin", "+refs/heads/*:refs/heads/*"],
                check=True,
                capture_output=True,
            )

    def collect(
        self,
        *,
        code: str = "consommation",
        output_dir: Path | None = None,
        commit: str | None = None,
        versions: str = "all",
    ) -> dict[str, Any]:
        """Write the corpus of `code` as of `commit` (default: the pinned one).

        `versions="current"` keeps only the versions in force, for an
        ablation without history; the benchmark uses "all".
        """
        if versions not in ("all", "current"):
            raise ValueError(f"versions doit valoir all ou current, pas {versions}")
        spec = get_code(code)
        if spec.legitext is None:
            raise ValueError(f"Le {spec.title} n'est pas encore collectable (pas de depot epingle).")
        base_dir = (output_dir or self.settings.legifrance_dir / spec.slug).resolve()
        repository = base_dir / "source.git"
        commit = commit or spec.pinned_commit or "HEAD"
        self.ensure_repository(spec, repository, commit)
        commit = _git(repository, "rev-parse", f"{commit}^{{commit}}").strip()
        corpus_dir = base_dir / "corpus"
        corpus_dir.mkdir(parents=True, exist_ok=True)
        for stale in [*corpus_dir.glob("*.txt"), *corpus_dir.glob("*.json")]:
            stale.unlink()

        with GitObjects(repository) as objects:
            all_versions, commits = walk_history(repository, commit, objects)
            texts = {entry.text.sha: entry.text for entry in commits}
            by_number: dict[str, list[ArticleVersion]] = defaultdict(list)
            for version in all_versions.values():
                by_number[version.number].append(version)
            for rows in by_number.values():
                rows.sort(key=lambda row: (row.date_debut or "", row.legi_id))

            readme_cache: dict[str, tuple[str | None, str | None]] = {}
            documents: list[dict[str, Any]] = []
            manifest_rows: list[dict[str, Any]] = []
            skipped = {"empty": 0, "not_in_force": 0}
            for number in sorted(by_number):
                siblings = by_number[number]
                for position, version in enumerate(siblings, start=1):
                    if not version.body:
                        skipped["empty"] += 1
                        continue
                    if versions == "current" and version.etat not in IN_FORCE_STATES:
                        skipped["not_in_force"] += 1
                        continue
                    titles, section_id = _hierarchy(objects, version.introduced_by, version.path, readme_cache)
                    references = extract_references(version.body)
                    text = normalize_text(f"{spec.title} — Article {version.label}\n\n{version.body}")
                    ended = texts.get(version.ended_by) if version.ended_by else None
                    metadata: dict[str, Any] = {
                        "title": f"{spec.title}, article {version.label}",
                        "code": spec.slug,
                        "code_title": spec.title,
                        "code_id": spec.legitext,
                        "article_number": version.number,
                        "article_label": version.label,
                        "legi_id": version.legi_id,
                        "etat": version.etat,
                        "date_debut": version.date_debut,
                        "date_fin": version.date_fin,
                        "version": position,
                        "version_count": len(siblings),
                        "versions": [
                            {
                                "legi_id": sibling.legi_id,
                                "etat": sibling.etat,
                                "date_debut": sibling.date_debut,
                                "date_fin": sibling.date_fin,
                            }
                            for sibling in siblings
                        ],
                        "amended_by": texts[version.introduced_by].as_metadata(),
                        "ended_by": ended.as_metadata() if ended else None,
                        "partie": version.path.split("/", 1)[0],
                        "path": titles,
                        "section_id": section_id,
                        "references": _dedupe(ref.article for ref in references if ref.code in (None, spec.slug)),
                        "external_references": [
                            {"article": article, "code": other}
                            for article, other in _dedupe(
                                (ref.article, ref.code) for ref in references if ref.code not in (None, spec.slug)
                            )
                        ],
                        "nota": version.nota or None,
                        "source": "legifrance",
                        "source_mirror": code_repository_label(spec),
                        "source_commit": commit,
                        "source_url": LEGIFRANCE_ARTICLE_URL.format(legi_id=version.legi_id),
                        "language": "fr",
                        "tags": ["legifrance", f"code_{spec.slug}"],
                    }
                    stem = file_stem(spec, version)
                    text_path = corpus_dir / f"{stem}.txt"
                    text_path.write_text(text, encoding="utf-8")
                    text_path.with_suffix(".json").write_text(
                        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    manifest_rows.append({"file_name": text_path.name, "chars": len(text), "sha256": digest})
                    documents.append(
                        {
                            **metadata,
                            "chars": len(text),
                            "_body_sha": hashlib.sha256(version.body.encode("utf-8")).hexdigest(),
                        }
                    )

        stats = corpus_stats(spec, documents, amending_texts=sum(1 for entry in commits if entry.text.title))
        stats["skipped"] = skipped
        commit_date = texts[commit].date
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "code": spec.slug,
            "code_id": spec.legitext,
            "source": code_repository_label(spec),
            "repository": spec.repository_url,
            "commit": commit,
            "commit_date": commit_date,
            "versions": versions,
            "documents": sorted(manifest_rows, key=lambda row: row["file_name"]),
            "skipped": skipped,
        }
        (base_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (base_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        log_event(
            LOGGER,
            logging.INFO,
            "legifrance.collect.completed",
            code=spec.slug,
            commit=commit,
            documents=len(documents),
            articles=stats["articles"],
        )
        return {
            "output_dir": str(base_dir),
            "corpus_dir": str(corpus_dir),
            "commit": commit,
            "commit_date": commit_date,
            "documents": len(documents),
            "stats": stats,
        }


def code_repository_label(spec: CodeSpec) -> str:
    return f"tricoteuses:{spec.repository_url.rsplit('/', 1)[-1].removesuffix('.git')}"
