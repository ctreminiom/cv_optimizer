"""
pdf_renderer.py — Convert the rendered Markdown report into a PDF.

We already produce a structured Markdown string inside `write_job_report`
(in tools.py). For end users, the new request is to deliver the report as
PDF instead of MD. This module owns that conversion.

Design:
- Use markdown_it_py to tokenize the MD (already installed via crewai).
- Walk the tokens and emit reportlab Flowables (Paragraph, ListFlowable,
  Table, Spacer, HRFlowable).
- Map inline markup (**bold**, *italic*, ~~strike~~, `code`, [link](url))
  to reportlab's inline HTML-like tags (<b>, <i>, <strike>, <font face=...>,
  <link>).
- Best-effort: features we don't render (HTML <details>) are inlined as
  plain text rather than dropped, so no information is lost.
"""

from __future__ import annotations

import re
from pathlib import Path

from markdown_it import MarkdownIt
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ─── Styles ───────────────────────────────────────────────────────────────

_STYLES = getSampleStyleSheet()


def _make_style(name: str, parent_name: str, **kw) -> ParagraphStyle:
    parent = _STYLES[parent_name]
    return ParagraphStyle(name=name, parent=parent, **kw)


_BODY = _make_style("Body", "BodyText", fontSize=10, leading=14, spaceAfter=4, spaceBefore=0)
_BODY_SMALL = _make_style("BodySmall", "BodyText", fontSize=9, leading=12, spaceAfter=2)
_H1 = _make_style(
    "H1",
    "Heading1",
    fontSize=18,
    leading=22,
    spaceAfter=8,
    spaceBefore=8,
    textColor=colors.HexColor("#1f2937"),
)
_H2 = _make_style(
    "H2",
    "Heading2",
    fontSize=14,
    leading=18,
    spaceAfter=6,
    spaceBefore=12,
    textColor=colors.HexColor("#1f2937"),
)
_H3 = _make_style(
    "H3",
    "Heading3",
    fontSize=12,
    leading=16,
    spaceAfter=4,
    spaceBefore=8,
    textColor=colors.HexColor("#374151"),
)
_H4 = _make_style(
    "H4",
    "Heading4",
    fontSize=11,
    leading=14,
    spaceAfter=3,
    spaceBefore=6,
    textColor=colors.HexColor("#4b5563"),
)
_QUOTE = _make_style(
    "Quote",
    "BodyText",
    fontSize=10,
    leading=14,
    leftIndent=12,
    rightIndent=8,
    spaceAfter=4,
    textColor=colors.HexColor("#374151"),
    borderColor=colors.HexColor("#9ca3af"),
    borderPadding=4,
    borderWidth=0,
)
_TLDR = _make_style(
    "TLDR",
    "BodyText",
    fontSize=10,
    leading=14,
    leftIndent=12,
    rightIndent=8,
    spaceAfter=2,
    spaceBefore=2,
    textColor=colors.HexColor("#1e3a8a"),
)
_LIST_ITEM = _make_style(
    "ListItem", "BodyText", fontSize=10, leading=14, spaceAfter=2, spaceBefore=0
)


# ─── Inline rendering ──────────────────────────────────────────────────────


def _escape(text: str) -> str:
    """Escape characters that reportlab's Paragraph parser interprets."""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_inline_children(children) -> str:
    """Walk the inline-token children list and emit reportlab-style HTML."""
    out: list[str] = []
    bold_depth = 0
    italic_depth = 0
    strike_depth = 0
    link_stack: list[str] = []
    for tok in children or []:
        ttype = tok.type
        if ttype == "text":
            out.append(_escape(tok.content))
        elif ttype == "softbreak":
            out.append(" ")
        elif ttype == "hardbreak":
            out.append("<br/>")
        elif ttype == "code_inline":
            out.append(f'<font face="Courier" size="9">{_escape(tok.content)}</font>')
        elif ttype == "strong_open":
            out.append("<b>")
            bold_depth += 1
        elif ttype == "strong_close":
            if bold_depth > 0:
                out.append("</b>")
                bold_depth -= 1
        elif ttype == "em_open":
            out.append("<i>")
            italic_depth += 1
        elif ttype == "em_close":
            if italic_depth > 0:
                out.append("</i>")
                italic_depth -= 1
        elif ttype == "s_open":
            out.append("<strike>")
            strike_depth += 1
        elif ttype == "s_close":
            if strike_depth > 0:
                out.append("</strike>")
                strike_depth -= 1
        elif ttype == "link_open":
            href = ""
            for k, v in tok.attrs.items() if hasattr(tok, "attrs") and tok.attrs else []:
                if k == "href":
                    href = v
                    break
            link_stack.append(href)
            out.append(f'<link href="{_escape(href)}" color="#1d4ed8">')
        elif ttype == "link_close":
            if link_stack:
                link_stack.pop()
            out.append("</link>")
        elif ttype == "image":
            # We don't embed images; emit the alt text.
            alt = tok.content or "image"
            out.append(_escape(alt))
        elif ttype == "html_inline":
            # Best-effort pass-through for safe inline html (<br/>, <b>, etc).
            text = tok.content or ""
            if re.fullmatch(r"\s*<\s*br\s*/?>\s*", text):
                out.append("<br/>")
            else:
                out.append(_escape(text))
        else:
            # Unknown inline token — fall back to its content.
            if tok.content:
                out.append(_escape(tok.content))
    # Close any unclosed tags defensively.
    while bold_depth > 0:
        out.append("</b>")
        bold_depth -= 1
    while italic_depth > 0:
        out.append("</i>")
        italic_depth -= 1
    while strike_depth > 0:
        out.append("</strike>")
        strike_depth -= 1
    while link_stack:
        out.append("</link>")
        link_stack.pop()
    return "".join(out)


def _inline_to_html(token) -> str:
    if hasattr(token, "children") and token.children:
        return _render_inline_children(token.children)
    return _escape(token.content or "")


# ─── Block walker ──────────────────────────────────────────────────────────


def _build_table(tokens: list, start: int) -> tuple:
    """Build a reportlab Table from a table_open .. table_close range.
    Returns (Table flowable, index_after_table_close)."""
    rows: list[list[str]] = []
    header_row_count = 0
    i = start
    while i < len(tokens) and tokens[i].type != "table_close":
        tok = tokens[i]
        if tok.type in ("tr_open",):
            row: list[str] = []
            i += 1
            while i < len(tokens) and tokens[i].type != "tr_close":
                cell_tok = tokens[i]
                if cell_tok.type in ("th_open", "td_open"):
                    # Next token is inline.
                    j = i + 1
                    cell_html = ""
                    while j < len(tokens) and tokens[j].type not in ("th_close", "td_close"):
                        if tokens[j].type == "inline":
                            cell_html += _inline_to_html(tokens[j])
                        j += 1
                    row.append(cell_html)
                    i = j  # at *_close
                i += 1
            rows.append(row)
            # Mark header rows (thead).
        elif tok.type == "thead_close":
            header_row_count = len(rows)
        i += 1

    if not rows:
        return None, i + 1

    col_count = max(len(r) for r in rows)
    norm_rows = []
    for r in rows:
        while len(r) < col_count:
            r.append("")
        norm_rows.append([Paragraph(c or "&nbsp;", _BODY_SMALL) for c in r])

    table = Table(norm_rows, repeatRows=header_row_count or 0)
    style = TableStyle(
        [
            (
                "BACKGROUND",
                (0, 0),
                (-1, header_row_count - 1 if header_row_count else 0),
                colors.HexColor("#eef2ff"),
            ),
            (
                "TEXTCOLOR",
                (0, 0),
                (-1, header_row_count - 1 if header_row_count else 0),
                colors.HexColor("#1e3a8a"),
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, header_row_count - 1 if header_row_count else 0),
                "Helvetica-Bold",
            ),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
    )
    table.setStyle(style)
    return table, i + 1  # past table_close


def _consume_list_items(tokens: list, start: int, bullet: bool = True) -> tuple:
    """Convert a bullet_list_open / ordered_list_open block into a
    reportlab ListFlowable. Returns (flowable, index_after_list_close)."""
    items: list[ListItem] = []
    i = start
    end_token = "bullet_list_close" if bullet else "ordered_list_close"
    while i < len(tokens) and tokens[i].type != end_token:
        if tokens[i].type == "list_item_open":
            i += 1
            item_flowables: list = []
            # Walk until matching list_item_close (depth-aware).
            depth = 1
            while i < len(tokens) and depth > 0:
                tt = tokens[i].type
                if tt == "list_item_open":
                    depth += 1
                elif tt == "list_item_close":
                    depth -= 1
                    if depth == 0:
                        break
                # Recursively render block children of this item.
                if tt == "paragraph_open":
                    inline = tokens[i + 1]
                    item_flowables.append(Paragraph(_inline_to_html(inline), _LIST_ITEM))
                    i += 3  # paragraph_open, inline, paragraph_close
                    continue
                elif tt == "bullet_list_open":
                    nested, ni = _consume_list_items(tokens, i + 1, bullet=True)
                    if nested is not None:
                        item_flowables.append(nested)
                    i = ni
                    continue
                elif tt == "ordered_list_open":
                    nested, ni = _consume_list_items(tokens, i + 1, bullet=False)
                    if nested is not None:
                        item_flowables.append(nested)
                    i = ni
                    continue
                elif tt == "fence" or tt == "code_block":
                    item_flowables.append(
                        Paragraph(
                            f'<font face="Courier" size="9">{_escape(tokens[i].content)}</font>',
                            _BODY_SMALL,
                        )
                    )
                elif tt == "inline":
                    item_flowables.append(Paragraph(_inline_to_html(tokens[i]), _LIST_ITEM))
                i += 1
            if item_flowables:
                items.append(
                    ListItem(item_flowables, leftIndent=12, bulletColor=colors.HexColor("#475569"))
                )
        i += 1

    if not items:
        return None, i + 1
    flow = ListFlowable(
        items,
        bulletType="bullet" if bullet else "1",
        start="•" if bullet else None,
        leftIndent=14,
        bulletFontSize=10,
        bulletColor=colors.HexColor("#475569"),
    )
    return flow, i + 1


def _flowables_from_markdown(markdown_text: str) -> list:
    """Tokenize the markdown and produce a flat list of reportlab flowables.

    This deliberately swallows raw `<details>`/`</details>` HTML tags
    (they're a markdown-only progressive-disclosure trick that has no PDF
    equivalent — we just inline the content instead of hiding it)."""
    md = MarkdownIt("commonmark", {"html": True}).enable("table").enable("strikethrough")
    tokens = md.parse(markdown_text)
    out: list = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        tt = tok.type
        if tt == "heading_open":
            level = int(tok.tag[1:])
            style = {1: _H1, 2: _H2, 3: _H3}.get(level, _H4)
            inline = tokens[i + 1]
            html = _inline_to_html(inline)
            out.append(Paragraph(html, style))
            i += 3  # heading_open, inline, heading_close
            continue
        if tt == "paragraph_open":
            inline = tokens[i + 1]
            html = _inline_to_html(inline)
            # Detect a one-line "horizontal rule paragraph" that markdown-it
            # may emit when the source has --- between blocks.
            out.append(Paragraph(html, _BODY))
            i += 3
            continue
        if tt == "blockquote_open":
            # Collect children paragraphs as a single quote block.
            j = i + 1
            lines: list[str] = []
            depth = 1
            while j < len(tokens) and depth > 0:
                jtt = tokens[j].type
                if jtt == "blockquote_open":
                    depth += 1
                elif jtt == "blockquote_close":
                    depth -= 1
                    if depth == 0:
                        break
                elif jtt == "inline":
                    lines.append(_inline_to_html(tokens[j]))
                j += 1
            # Render every line as its own indented "tldr"-style paragraph
            # so blockquotes (especially the TL;DR card) keep their visual
            # block break.
            for ln in lines:
                ln_stripped = ln.strip()
                if not ln_stripped:
                    out.append(Spacer(1, 4))
                else:
                    out.append(Paragraph(ln_stripped, _TLDR))
            out.append(Spacer(1, 4))
            i = j + 1
            continue
        if tt == "bullet_list_open":
            flow, ni = _consume_list_items(tokens, i + 1, bullet=True)
            if flow is not None:
                out.append(flow)
                out.append(Spacer(1, 4))
            i = ni
            continue
        if tt == "ordered_list_open":
            flow, ni = _consume_list_items(tokens, i + 1, bullet=False)
            if flow is not None:
                out.append(flow)
                out.append(Spacer(1, 4))
            i = ni
            continue
        if tt == "table_open":
            table, ni = _build_table(tokens, i + 1)
            if table is not None:
                out.append(table)
                out.append(Spacer(1, 6))
            i = ni
            continue
        if tt == "hr":
            out.append(
                HRFlowable(
                    width="100%",
                    thickness=0.5,
                    color=colors.HexColor("#cbd5e1"),
                    spaceBefore=6,
                    spaceAfter=6,
                )
            )
            i += 1
            continue
        if tt in ("fence", "code_block"):
            content = tok.content or ""
            out.append(
                Paragraph(
                    f'<font face="Courier" size="9">{_escape(content)}</font>',
                    _BODY_SMALL,
                )
            )
            out.append(Spacer(1, 4))
            i += 1
            continue
        if tt == "html_block":
            # Strip <details>/<summary> wrappers — render their text content.
            text = tok.content or ""
            # Replace summary tags with a small heading line.
            summary_match = re.search(r"<summary[^>]*>(.*?)</summary>", text, re.S | re.I)
            if summary_match:
                stext = re.sub(r"<[^>]+>", "", summary_match.group(1)).strip()
                if stext:
                    out.append(Paragraph(_escape(stext), _H4))
            # Drop everything else (closing </details> tags are silent).
            i += 1
            continue
        # Anything else — skip the open and let the matching close land safely.
        i += 1
    return out


# ─── Public API ────────────────────────────────────────────────────────────


def write_pdf_from_markdown(markdown_text: str, output_path: Path) -> Path:
    """Render `markdown_text` as a PDF saved at `output_path`. Returns the
    path on success; raises on failure."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    flowables = _flowables_from_markdown(markdown_text)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title="Resume Recommendation Report",
        author="CV Optimizer",
    )

    def _on_page(canvas_, _doc) -> None:
        canvas_.saveState()
        canvas_.setFont("Helvetica", 8)
        canvas_.setFillColor(colors.HexColor("#9ca3af"))
        page_num = canvas_.getPageNumber()
        canvas_.drawString(0.7 * inch, 0.4 * inch, "CV Optimizer — Resume Recommendation Report")
        canvas_.drawRightString(letter[0] - 0.7 * inch, 0.4 * inch, f"Page {page_num}")
        canvas_.restoreState()

    doc.build(flowables, onFirstPage=_on_page, onLaterPages=_on_page)
    return output_path
