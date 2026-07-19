"""Documentation API routes — serve project markdown files."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

from src.exceptions import NotFoundError

router = APIRouter()

DOCS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "docs"

# ── Document groups ──────────────────────────────────────────
# Grouped for structured sidebar rendering in the Docs page.
# ALLOWED_DOCS is auto-derived from the groups below.

DOC_GROUPS: list[dict] = [
    {
        "key": "productDocs",
        "labelKey": "docs.groups.productDocs",
        "items": [
            "prd.md",
            "architecture.md",
            "protocol.md",
            "data-model.md",
            "security-model.md",
            "onboarding.md",
            "CHANGELOG.md",
        ],
    },
    {
        "key": "engineeringRef",
        "labelKey": "docs.groups.engineeringRef",
        "items": [
            "methodology.md",
            "phase-criteria.md",
            "mvp-boundary.md",
        ],
    },
]

ALLOWED_DOCS: set[str] = {
    item for group in DOC_GROUPS for item in group["items"]
}


@router.get("/docs/{filename}")
async def get_doc(
    filename: str,
    format: str | None = Query(None, pattern=r"^(raw|html)$"),
):
    """Serve a documentation file.

    Returns the raw markdown content by default.
    Set ``format=html`` to receive server-rendered HTML.
    """
    if filename not in ALLOWED_DOCS:
        raise NotFoundError("document", filename)

    filepath = DOCS_DIR / filename
    if not filepath.exists() or not filepath.is_file():
        raise NotFoundError("document", filename)

    content = filepath.read_text(encoding="utf-8")

    if format == "html":
        # Basic markdown-to-HTML conversion (no external deps)
        html = _md_to_html(content)
        return {"filename": filename, "content": html, "content_type": "html"}

    return {"filename": filename, "content": content, "content_type": "markdown"}


@router.get("/docs")
async def list_docs():
    """List available documentation files grouped by category."""
    groups = []
    for group in DOC_GROUPS:
        items = [
            {"filename": f, "exists": (DOCS_DIR / f).exists()}
            for f in group["items"]
        ]
        groups.append({
            "key": group["key"],
            "labelKey": group["labelKey"],
            "items": items,
        })
    return {"groups": groups}


# ── Minimal markdown → HTML converter ──────────────────────────

import re


def _md_to_html(md: str) -> str:
    """Convert basic markdown to HTML.

    Handles headings, code blocks, inline code, bold, italic,
    links, images, unordered lists, paragraphs, and horizontal rules.
    """
    lines = md.split("\n")
    out: list[str] = []
    in_code_block = False
    code_buf: list[str] = []
    in_list = False

    i = 0
    while i < len(lines):
        line = lines[i]

        # Fenced code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                out.append(
                    f"<pre><code>{_escape_html('\n'.join(code_buf))}</code></pre>"
                )
                code_buf = []
                in_code_block = False
            else:
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            code_buf.append(line)
            i += 1
            continue

        # Empty line — close list if open
        if line.strip() == "":
            if in_list:
                out.append("</ul>")
                in_list = False
            i += 1
            continue

        # Headings
        h_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if h_match:
            if in_list:
                out.append("</ul>")
                in_list = False
            level = len(h_match.group(1))
            out.append(f"<h{level}>{_inline_md(h_match.group(2))}</h{level}>")
            i += 1
            continue

        # Horizontal rule
        if line.strip() in ("---", "***", "___"):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<hr>")
            i += 1
            continue

        # Unordered list items
        li_match = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
        if li_match:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline_md(li_match.group(2))}</li>")
            i += 1
            continue

        # Ordered list items
        ol_match = re.match(r"^(\s*)\d+[.)]\s+(.+)$", line)
        if ol_match:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<ol><li>{_inline_md(ol_match.group(2))}</li></ol>")
            i += 1
            continue

        # Blockquote
        bq_match = re.match(r"^>\s?(.*)$", line)
        if bq_match:
            if in_list:
                out.append("</ul>")
                in_list = False
            bq_lines = []
            while i < len(lines) and re.match(r"^>\s?(.*)$", lines[i]):
                bq_lines.append(re.match(r"^>\s?(.*)$", lines[i]).group(1))
                i += 1
            out.append(f"<blockquote><p>{_inline_md(' '.join(bq_lines))}</p></blockquote>")
            continue

        # Regular paragraph
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{_inline_md(line)}</p>")
        i += 1

    if in_list:
        out.append("</ul>")
    if in_code_block:
        out.append(f"<pre><code>{_escape_html('\n'.join(code_buf))}</code></pre>")

    return "\n".join(out)


def _inline_md(text: str) -> str:
    """Convert inline markdown to HTML."""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Links
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # Images
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', text)
    return text


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
