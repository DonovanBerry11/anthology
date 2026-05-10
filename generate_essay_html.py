#!/usr/bin/env python3
"""
generate_essay_html.py — Converts an analysis.md essay into a styled HTML page
for the Anthology website.

Usage:
    python generate_essay_html.py \
        --input analysis.md \
        --output essays/the-ownership-problem.html \
        --slug the-ownership-problem \
        --title "The Ownership Problem" \
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
<body>

<div class="container">

  <header class="essay-page-header">
    <a class="essay-page-header__back" href="../index.html">← Anthology</a>
    <div class="essay-page-header__pub">Anthology</div>
    <h1>{title}</h1>
    <div class="essay-page-header__meta">{date}</div>
  </header>

  <article class="essay-body">
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
    Minimal markdown-to-HTML converter for essay body.
    Handles: paragraphs, section breaks (---), [links](url), *em*, **strong**.
    Does not use external dependencies.
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
            paragraphs.append('HR')
        else:
            current.append(line)
    if current:
        paragraphs.append('\n'.join(current))

    html_parts = []
    for para in paragraphs:
        if para == 'HR':
            html_parts.append('<hr />')
        else:
            # Skip the title line (starts with #)
            if para.startswith('# '):
                continue
            content = para.strip()
            # Skip standalone italic meta lines (e.g. *Draft 1 — May 2026*)
            if re.match(r'^\*[^*]+\*$', content):
                continue
            # Inline: links first, then **strong**, then *em*
            content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', content)
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
            content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
            # Smart quotes already in source; just wrap
            html_parts.append(f'<p>{content}</p>')

    return '\n'.join(html_parts)


def extract_meta_description(md_text, max_len=200):
    """Pull the first substantive sentence from the essay for the meta tag."""
    for line in md_text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('---'):
            # Trim to first sentence
            sentence_end = re.search(r'(?<=[.!?])\s', line)
            if sentence_end:
                snippet = line[:sentence_end.start()].strip()
            else:
                snippet = line[:max_len].strip()
            # Strip inline markdown
            snippet = re.sub(r'\*+(.+?)\*+', r'\1', snippet)
            return snippet[:max_len]
    return ""


def main():
    parser = argparse.ArgumentParser(description="Convert analysis.md to Anthology essay HTML")
    parser.add_argument("--input", required=True, help="Path to analysis.md")
    parser.add_argument("--output", required=True, help="Path to write essay HTML")
    parser.add_argument("--slug", required=True, help="URL slug, e.g. the-ownership-problem")
    parser.add_argument("--title", required=True, help="Essay title")
    parser.add_argument("--date", required=True, help="Display date, e.g. 'May 2026'")
    args = parser.parse_args()

    md_text = Path(args.input).read_text(encoding="utf-8")
    body = md_to_html_body(md_text)
    meta = extract_meta_description(md_text)

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
