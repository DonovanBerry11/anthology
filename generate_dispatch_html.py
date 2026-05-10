#!/usr/bin/env python3
"""
generate_dispatch_html.py — Converts a dispatch analysis.md into a styled HTML page
for the Anthology website (Dispatches section).

Handles both daily dispatches (no subheadings, 300–500w) and weekly dispatches
(## subheadings render as section headers, 600–1000w).

Usage:
    python generate_dispatch_html.py \
        --input analysis.md \
        --output dispatches/my-dispatch.html \
        --slug my-dispatch \
        --title "My Dispatch Title" \
        --date "May 2026" \
        --dispatch-type daily
"""

import argparse
import re
from pathlib import Path


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{meta_description}">
  <title>{title} — Anthology</title>
  <link rel="stylesheet" href="../style.css">
</head>
<body class="page--dispatch">

<div class="container">

  <header class="essay-page-header">
    <a class="essay-page-header__back" href="{back_url}">← Anthology</a>
    <div class="essay-page-header__pub">{dispatch_label}</div>
    <h1>{title}</h1>
    <div class="essay-page-header__meta">{date}</div>
  </header>

  <article class="dispatch-body">
{body}
  </article>

  <footer class="site-footer">
    <p>Anthology &copy; 2026</p>
  </footer>

</div>

</body>
</html>
"""


def md_to_html_body(md_text, dispatch_type):
    """
    Markdown-to-HTML converter for dispatch body.
    Daily: paragraphs, *em*, **strong** only (no subheadings).
    Weekly: also handles ## subheadings → <h2 class="dispatch-section-header">.
    Both: handles bullet lists (- item) and markdown tables (| col | col |).
    """
    lines = md_text.strip().splitlines()
    paragraphs = []
    current = []
    list_items = []
    table_rows = []
    in_list = False
    in_table = False

    def flush_current():
        if current:
            paragraphs.append(('para', '\n'.join(current)))
        current.clear()

    def flush_list():
        if list_items:
            paragraphs.append(('list', list(list_items)))
        list_items.clear()

    def flush_table():
        if table_rows:
            paragraphs.append(('table', list(table_rows)))
        table_rows.clear()

    def is_table_separator(s):
        return bool(re.match(r'^\|[-| :]+\|$', s))

    def parse_table_row(s):
        # Split on | and strip whitespace; drop empty first/last from surrounding pipes
        cells = [c.strip() for c in s.split('|')]
        return [c for c in cells if c != '']

    for line in lines:
        stripped = line.strip()

        # Skip title line
        if stripped.startswith('# ') and not stripped.startswith('## '):
            flush_current()
            flush_list()
            flush_table()
            in_list = False
            in_table = False
            continue

        # Section header (## )
        if stripped.startswith('## '):
            flush_current()
            flush_list()
            flush_table()
            in_list = False
            in_table = False
            heading_text = stripped[3:].strip()
            paragraphs.append(('heading', heading_text))
            continue

        # Horizontal rule
        if stripped == '---':
            flush_current()
            flush_list()
            flush_table()
            in_list = False
            in_table = False
            continue

        # Table separator row — skip, marks header/body boundary
        if stripped.startswith('|') and is_table_separator(stripped):
            continue

        # Table row
        if stripped.startswith('|') and stripped.endswith('|'):
            if current:
                flush_current()
                in_list = False
            if in_list:
                flush_list()
                in_list = False
            in_table = True
            table_rows.append(parse_table_row(stripped))
            continue

        # Bullet list item
        if stripped.startswith('- ') or stripped.startswith('* '):
            if current:
                flush_current()
            if in_table:
                flush_table()
                in_table = False
            in_list = True
            list_items.append(stripped[2:])
            continue

        # Empty line
        if stripped == '':
            if in_list:
                flush_list()
                in_list = False
            elif in_table:
                flush_table()
                in_table = False
            else:
                flush_current()
            continue

        # Regular text
        if in_list:
            flush_list()
            in_list = False
        if in_table:
            flush_table()
            in_table = False
        current.append(line)

    flush_current()
    flush_list()
    flush_table()

    html_parts = []
    for item_type, content in paragraphs:
        if item_type == 'heading':
            if dispatch_type == 'weekly':
                html_parts.append(f'<h2 class="dispatch-section-header">{content}</h2>')
        elif item_type == 'list':
            items_html = '\n'.join(f'      <li>{inline(i)}</li>' for i in content)
            html_parts.append(f'<ul class="dispatch-list-items">\n{items_html}\n    </ul>')
        elif item_type == 'table':
            rows = content
            if not rows:
                continue
            # First row is header
            header_html = ''.join(f'<th>{inline(c)}</th>' for c in rows[0])
            body_rows_html = ''
            for row in rows[1:]:
                body_rows_html += '<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in row) + '</tr>\n'
            html_parts.append(
                f'<table class="dispatch-table">\n'
                f'  <thead><tr>{header_html}</tr></thead>\n'
                f'  <tbody>\n{body_rows_html}  </tbody>\n'
                f'</table>'
            )
        elif item_type == 'para':
            text = content.strip()
            if re.match(r'^\*[^*]+\*$', text):
                continue
            html_parts.append(f'<p>{inline(text)}</p>')

    return '\n'.join(html_parts)


def inline(text):
    """Apply inline markdown: [links](url), **strong**, *em*."""
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    return text


def extract_meta_description(md_text, max_len=200):
    """Pull the first substantive sentence for the meta tag."""
    for line in md_text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('---') \
                and not line.startswith('-') and not line.startswith('*'):
            sentence_end = re.search(r'(?<=[.!?])\s', line)
            if sentence_end:
                snippet = line[:sentence_end.start()].strip()
            else:
                snippet = line[:max_len].strip()
            snippet = re.sub(r'\*+(.+?)\*+', r'\1', snippet)
            return snippet[:max_len]
    return ""


def main():
    parser = argparse.ArgumentParser(description="Convert dispatch analysis.md to Anthology HTML")
    parser.add_argument("--input",         required=True, help="Path to analysis.md")
    parser.add_argument("--output",        required=True, help="Path to write dispatch HTML")
    parser.add_argument("--slug",          required=True, help="URL slug")
    parser.add_argument("--title",         required=True, help="Dispatch title")
    parser.add_argument("--date",          required=True, help="Display date, e.g. 'May 2026'")
    parser.add_argument("--dispatch-type", required=True, choices=["daily", "weekly"],
                        help="Dispatch type: daily or weekly")
    parser.add_argument("--label",         default=None,
                        help="Override the dispatch label (e.g. 'UK Politics', 'NBA')")
    parser.add_argument("--back-url",      default=None,
                        help="Override the back-link URL (default: ../index.html#dispatches)")
    args = parser.parse_args()

    if args.label:
        dispatch_label = args.label
    else:
        dispatch_label = "Daily Dispatch" if args.dispatch_type == "daily" else "Weekly Dispatch"

    back_url = args.back_url if args.back_url else "../index.html#dispatches"

    md_text = Path(args.input).read_text(encoding="utf-8")
    body    = md_to_html_body(md_text, args.dispatch_type)
    meta    = extract_meta_description(md_text)

    html = HTML_TEMPLATE.format(
        title=args.title,
        date=args.date,
        slug=args.slug,
        dispatch_label=dispatch_label,
        meta_description=meta,
        back_url=back_url,
        body=body,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"✓ Written: {out}")


if __name__ == "__main__":
    main()
