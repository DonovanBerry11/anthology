#!/usr/bin/env python3
"""
generate_note_html.py — Converts an analysis.md note into a styled HTML page
for the Anthology website (Notes section).

Usage:
    python generate_note_html.py \
        --input analysis.md \
        --output notes/the-subtraction-problem.html \
        --slug the-subtraction-problem \
        --title "The Subtraction Problem" \
        --date "May 2026"
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
<body class="page--note">

<div class="container">

  <header class="essay-page-header">
    <a class="essay-page-header__back" href="../index.html#notes">← Anthology</a>
    <div class="essay-page-header__pub">Note</div>
    <h1>{title}</h1>
    <div class="essay-page-header__meta">{date}</div>
  </header>

  <article class="note-body">
{body}
  </article>

  <footer class="site-footer">
    <p>Anthology &copy; 2026</p>
  </footer>

</div>

</body>
</html>
"""


def md_to_html_body(md_text):
    """
    Minimal markdown-to-HTML converter for note body.
    Handles: paragraphs, *em*, **strong**.
    Notes do not use section breaks (---).
    """
    lines = md_text.strip().splitlines()
    paragraphs = []
    current = []

    for line in lines:
        stripped = line.strip()
        if stripped == '':
            if current:
                paragraphs.append('\n'.join(current))
                current = []
        elif stripped == '---':
            if current:
                paragraphs.append('\n'.join(current))
                current = []
            # Notes don't use section breaks; treat as paragraph boundary only
        else:
            current.append(line)
    if current:
        paragraphs.append('\n'.join(current))

    html_parts = []
    for para in paragraphs:
        # Skip the title line (starts with #)
        if para.startswith('# '):
            continue
        content = para.strip()
        # Skip standalone italic meta lines (e.g. *Draft 1 — May 2026*)
        if re.match(r'^\*[^*]+\*$', content):
            continue
        # Inline: **strong** then *em*
        content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
        content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
        html_parts.append(f'<p>{content}</p>')

    return '\n'.join(html_parts)


def extract_meta_description(md_text, max_len=200):
    """Pull the first substantive sentence from the note for the meta tag."""
    for line in md_text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('---'):
            sentence_end = re.search(r'(?<=[.!?])\s', line)
            if sentence_end:
                snippet = line[:sentence_end.start()].strip()
            else:
                snippet = line[:max_len].strip()
            snippet = re.sub(r'\*+(.+?)\*+', r'\1', snippet)
            return snippet[:max_len]
    return ""


def main():
    parser = argparse.ArgumentParser(description="Convert analysis.md to Anthology note HTML")
    parser.add_argument("--input",  required=True, help="Path to analysis.md")
    parser.add_argument("--output", required=True, help="Path to write note HTML")
    parser.add_argument("--slug",   required=True, help="URL slug, e.g. the-subtraction-problem")
    parser.add_argument("--title",  required=True, help="Note title")
    parser.add_argument("--date",   required=True, help="Display date, e.g. 'May 2026'")
    args = parser.parse_args()

    md_text = Path(args.input).read_text(encoding="utf-8")
    body    = md_to_html_body(md_text)
    meta    = extract_meta_description(md_text)

    html = HTML_TEMPLATE.format(
        title=args.title,
        date=args.date,
        slug=args.slug,
        meta_description=meta,
        body=body,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"✓ Written: {out}")


if __name__ == "__main__":
    main()
