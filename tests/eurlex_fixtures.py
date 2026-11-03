"""Small XHTML documents in the two CELLAR flavours (Official Journal and
consolidated), trimmed from real acts, for the EUR-Lex tests."""

from __future__ import annotations

HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE html PUBLIC "-//W3C//DTD XHTML//EN" "xhtml-strict.dtd">'
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head><body>'
)
TAIL = "</body></html>"


def _row(label: str, text: str) -> str:
    return (
        '<table width="100%"><col width="4%"/><col width="96%"/><tbody><tr>'
        f'<td valign="top"><p class="oj-normal">{label}</p></td>'
        f'<td valign="top"><p class="oj-normal">{text}</p></td>'
        "</tr></tbody></table>"
    )


def oj_act(
    *,
    title: str,
    date: str,
    citations: list[str],
    recitals: list[str],
    articles: list[tuple[str, str, str, str]],
    annexes: list[tuple[str, str, str]] = (),
) -> str:
    """Official Journal XHTML: `articles` are (id number, heading, title, body markup)."""
    parts = [HEAD, f'<p class="oj-hd-date">{date}</p>', f'<p class="oj-doc-ti">{title}</p>']
    for index, citation in enumerate(citations, start=1):
        parts.append(f'<div class="eli-subdivision" id="cit_{index}"><p class="oj-normal">{citation}</p></div>')
    for index, recital in enumerate(recitals, start=1):
        parts.append(f'<div class="eli-subdivision" id="rct_{index}">{_row(f"({index})", recital)}</div>')
    parts.append('<div class="eli-subdivision" id="enc_1">')
    for number, heading, article_title, body in articles:
        parts.append(
            f'<div class="eli-subdivision" id="art_{number}"><p class="oj-ti-art">{heading}</p>'
            f'<div class="eli-title" id="art_{number}.tit_1"><p class="oj-sti-art">{article_title}</p></div>'
            f"{body}</div>"
        )
    parts.append("</div>")
    for number, heading, body in annexes:
        parts.append(f'<div class="eli-container" id="anx_{number}"><p class="oj-doc-ti">{heading}</p>{body}</div>')
    parts.append(TAIL)
    return "".join(parts)


def consolidated_act(articles: list[tuple[str, str, str, str, str | None]]) -> str:
    """Consolidated XHTML: (id number, heading, title, body markup, marker title or None)."""
    parts = [HEAD, '<p class="reference">consolidated</p>', '<p class="title-doc-first">REGULATION</p>']
    for number, heading, article_title, body, marker in articles:
        if marker:
            parts.append(
                f'<p class="modref"><a href="http://publications.europa.eu/resource/celex/x" title="{marker}">▼M1</a></p>'
            )
        parts.append(
            f'<div class="eli-subdivision" id="art_{number}"><p class="title-article-norm">{heading}</p>'
            f'<div class="eli-title" id="art_{number}.tit_1"><p class="stitle-article-norm">{article_title}</p></div>'
            f"{body}</div>"
        )
    parts.append(TAIL)
    return "".join(parts)


def consolidated_paragraph(number: str, text: str) -> str:
    return (
        f'<div class="norm"><span class="no-parag">{number}.  </span>'
        f'<div class="norm inline-element">{text}</div></div>'
    )


def consolidated_point(label: str, text: str) -> str:
    return (
        '<div class="grid-container grid-list"><div class="list grid-list-column-1">'
        f'<span>{label} </span></div><div class="grid-list-column-2"><p class="norm">{text}</p></div></div>'
    )


def oj_paragraph(number: str, text: str, points: list[tuple[str, str]] = ()) -> str:
    return (
        f'<div id="{int(number):03d}.001"><p class="oj-normal">{number}.   {text}</p>'
        + "".join(_row(label, point) for label, point in points)
        + "</div>"
    )
