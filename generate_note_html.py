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
        --date "May 2026" \
        --pub-datetime "10 May 2026, 3:45 PM"
"""

import argparse
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path


def current_est_datetime():
    """Return current time as a formatted string in EST (UTC-5)."""
    est = timezone(timedelta(hours=-5))
    now = datetime.now(est)
    return now.strftime("%-d %B %Y, %-I:%M %p")


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
    <div class="essay-page-header__meta">{date_line}</div>
  </header>

  <article class="note-body">
{body}
  </article>

  <footer class="site-footer">
    <p>Anthology &copy; 2026</p>
  </footer>

</div>

<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script src="/auth/auth.js"></script>
<script>
// ── Reading engagement tracker ────────────────────────────────────────────
// Records scroll depth and time-on-page to Supabase reading_events table.
// Requires: reading_events(user_id uuid, piece_slug text, piece_type text,
//           read_depth_percent int, time_on_page_seconds int, created_at timestamptz)
(function() {{
  const PIECE_SLUG = "{slug}";
  const PIECE_TYPE = "note";
  const startTime  = Date.now();
  let maxDepth     = 0;
  let recorded50   = false;

  function getDepth() {{
    const el  = document.documentElement;
    const top = el.scrollTop || document.body.scrollTop;
    const h   = el.scrollHeight - el.clientHeight;
    return h > 0 ? Math.round((top / h) * 100) : 100;
  }}

  async function record(depth) {{
    try {{
      const {{ data: {{ session }} }} = await _supabase.auth.getSession();
      if (!session) return;
      const secs = Math.round((Date.now() - startTime) / 1000);
      await _supabase.from('reading_events').insert({{
        user_id: session.user.id,
        piece_slug: PIECE_SLUG,
        piece_type: PIECE_TYPE,
        read_depth_percent: depth,
        time_on_page_seconds: secs
      }});
    }} catch(e) {{ /* non-blocking */ }}
  }}

  window.addEventListener('scroll', function() {{
    const d = getDepth();
    if (d > maxDepth) maxDepth = d;
    if (!recorded50 && maxDepth >= 50) {{ recorded50 = true; record(50); }}
  }}, {{ passive: true }});

  window.addEventListener('pagehide', function() {{
    record(maxDepth);
  }});
}})();
</script>

</body>
</html>
"""


def md_to_html_body(md_text):
    """
    Minimal markdown-to-HTML converter for note body.
    Handles: paragraphs, [links](url), *em*, **strong**.
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
        # Inline: links first, then **strong**, then *em*
        content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', content)
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
    parser.add_argument("--pub-datetime", default=None,
                        help="Publication datetime, e.g. '10 May 2026, 3:45 PM'. "
                             "Auto-generated from current EST time if omitted.")
    args = parser.parse_args()

    pub_dt = args.pub_datetime if args.pub_datetime else current_est_datetime()
    date_line = f'{args.date} &middot; Published {pub_dt} EST'

    md_text = Path(args.input).read_text(encoding="utf-8")
    body    = md_to_html_body(md_text)
    meta    = extract_meta_description(md_text)

    html = HTML_TEMPLATE.format(
        title=args.title,
        date_line=date_line,
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
