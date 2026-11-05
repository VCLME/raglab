"""What an index run holds of a legal citation in the question.

The router never declines a question whose cited unit the index holds (an
article of a Brazilian law, of a French code, a unit of an EU act), nor one
naming an indexed act without a unit: it names a document, so it is
documentary by construction. The act alone does not vouch for the unit: a
question on "l'article 412 du RGPD" or "art. 999 da Lei nº 13.445" (act
indexed, unit absent) is declined with an explicit answer. A citation of a
text the index does not hold ("Lei nº 99.871, de 2031") gets the normal
rule, so a fabricated reference can still be declined.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from raglab.retrieval.citations import (
    Citation,
    CitationResolution,
    article_chunks,
    code_version,
    find_code_article,
    find_eu_unit,
    find_law_document,
    has_code,
    has_eu_act,
    law_article_version,
)


def cited_text_in_run(session: Session, index_run: Any, citation: Citation) -> bool:
    """Whether the run holds the cited act (corpus choice)."""
    if citation.law_number is not None:
        return find_law_document(session, index_run, citation) is not None
    if citation.celex is not None:
        return has_eu_act(session, index_run, citation.celex)
    return find_code_article(session, index_run, citation) is not None


def resolve_cited_text(session: Session, index_run: Any, citation: Citation) -> CitationResolution:
    """Act, unit and version of the citation in this run (the same checks as
    the citation resolver, for when it did not run)."""
    if citation.law_number is not None:
        document_id = find_law_document(session, index_run, citation)
        chunks = (
            article_chunks(session, index_run, document_id, citation.article)
            if document_id is not None and citation.article
            else []
        )
        return CitationResolution(
            act_found=document_id is not None,
            unit_requested=bool(citation.article),
            unit_found=bool(chunks),
            version=law_article_version(chunks, citation.article) if citation.article else None,
        )
    if citation.celex is not None:
        unit = find_eu_unit(session, index_run, citation)
        return CitationResolution(
            act_found=unit is not None or has_eu_act(session, index_run, citation.celex),
            unit_requested=citation.unit is not None and citation.article is not None,
            unit_found=unit is not None,
            version=("in_force" if unit.in_force else "historical") if unit is not None else None,
        )
    article = find_code_article(session, index_run, citation)
    return CitationResolution(
        act_found=article is not None or has_code(session, index_run, citation.code),
        unit_requested=True,
        unit_found=article is not None,
        version=code_version(article.etat) if article is not None else None,
    )
