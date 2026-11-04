"""Whether a legal citation in the question points to a text of an index run.

The router never declines a question citing a text the index holds (an
article of a Brazilian law, of a French code or of an EU act): it names a
document, so it is documentary by construction. A citation of a text the
index does not hold ("Lei nº 99.871, de 2031") gets the normal rule, so a
fabricated reference can still be declined.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from raglab.retrieval.citations import Citation, find_code_article, find_law_document, has_eu_act


def cited_text_in_run(session: Session, index_run: Any, citation: Citation) -> bool:
    if citation.law_number is not None:
        return find_law_document(session, index_run, citation) is not None
    if citation.celex is not None:
        return has_eu_act(session, index_run, citation.celex)
    return find_code_article(session, index_run, citation) is not None
