#!/usr/bin/env python3
"""
generate_dispatch_html.py — Converts a dispatch analysis.md into a styled HTML page
for the Anthology website (Dispatches section).

NORMAL MODE — single dispatch:
    python generate_dispatch_html.py \
        --input analysis.md \
        --output dispatches/my-dispatch.html \
        --slug my-dispatch \
        --title "My Dispatch Title" \
        --date "May 2026" \
        --dispatch-type daily \
        --pub-datetime "10 May 2026, 3:45 PM"

COMBINED MODE — 5-section edition (one combined post, five dispatches):
    python generate_dispatch_html.py \
        --combined-dispatches /tmp/edition-dispatches.json \
        --output dispatches/daily-edition-2026-05-14.html \
        --slug daily-edition-2026-05-14 \
        --title "Thursday, 14 May 2026" \
        --date "May 2026"

    The JSON file must contain an array of exactly 5 objects:
    [
      {
        "label": "I.",
        "title": "Dispatch title",
        "body_md": "Full markdown body…",
        "note_url": "/users/{user_id}/notes/{slug}.html"
      },
      …
    ]
"""

import argparse
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path


def current_est_datetime():
    """Return current time as a formatted string in EST (UTC-5)."""
    est = timezone(timedelta(hours=-5))
    now = datetime.now(est)
    return now.strftime("%-d %B %Y, %-I:%M %p")


# ── Single-dispatch template (unchanged) ──────────────────────────────────────

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{meta_description}">
  <title>{title} — Anthology</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body class="page--dispatch">

<div class="container">

  <header class="essay-page-header">
    <a class="essay-page-header__back" href="{back_url}">← Anthology</a>
    <div class="essay-page-header__pub">{dispatch_label}</div>
    <h1>{title}</h1>
    <div class="essay-page-header__meta">{date_line}</div>
  </header>

  <article class="dispatch-body">
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
  const PIECE_TYPE = "dispatch";
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


# ── Combined-dispatch template (new) ──────────────────────────────────────────

COMBINED_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{meta_description}">
  <title>{edition_title} — Anthology</title>
  <link rel="stylesheet" href="/style.css">
  <style>
    /* ── Combined dispatch sections ─────────────────── */
    .dispatch-section {{
      padding: 36px 0 0;
    }}
    .dispatch-section__label {{
      font-family: var(--sans);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 2.5px;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 12px;
    }}
    .dispatch-section__title {{
      font-family: var(--serif);
      font-size: clamp(22px, 3.5vw, 30px);
      font-weight: 400;
      line-height: 1.18;
      letter-spacing: -0.3px;
      color: var(--text);
      margin-bottom: 22px;
    }}
    .dispatch-section__readmore {{
      margin-top: 18px;
      padding-bottom: 36px;
    }}
    .dispatch-section__readmore a {{
      font-family: var(--sans);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.8px;
      color: var(--text);
      text-decoration: none;
      text-transform: uppercase;
      border-bottom: 1.5px solid var(--text);
      padding-bottom: 1px;
      transition: opacity 0.15s;
    }}
    .dispatch-section__readmore a:hover {{ opacity: 0.5; }}
    .dispatch-rule {{
      border: none;
      border-top: 1px solid var(--rule);
      margin: 0;
    }}
  </style>
</head>
<body class="page--dispatch">

<div class="container">

  <header class="essay-page-header">
    <a class="essay-page-header__back" href="{back_url}">← Anthology</a>
    <div class="essay-page-header__pub">Daily Dispatch</div>
    <h1>{edition_title}</h1>
    <div class="essay-page-header__meta">{date_line}</div>
  </header>

  <article class="dispatch-body">
{sections_html}
  </article>

  <footer class="site-footer">
    <p>Anthology &copy; 2026</p>
  </footer>

</div>

<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script src="/auth/auth.js"></script>
<script>
// ── Reading engagement tracker ────────────────────────────────────────────
(function() {{
  const PIECE_SLUG = "{slug}";
  const PIECE_TYPE = "dispatch";
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


# ── Markdown utilities (unchanged) ────────────────────────────────────────────

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


# ── Combined-dispatch renderer ─────────────────────────────────────────────────

ROMAN_LABELS = ['I.', 'II.', 'III.', 'IV.', 'V.']


def render_combined_sections(dispatches_data):
    """
    Render 5 dispatch sections for the combined dispatch page.

    Each element of dispatches_data must be a dict with:
        label    – section label, e.g. "I." (defaults to roman numeral)
        title    – section heading
        body_md  – raw markdown body text
        note_url – absolute URL of the corresponding note page
    """
    parts = []
    for i, d in enumerate(dispatches_data):
        label    = d.get('label') or ROMAN_LABELS[i] if i < len(ROMAN_LABELS) else f'{i+1}.'
        title    = d.get('title', '').strip()
        body_md  = d.get('body_md', '').strip()
        note_url = d.get('note_url', '').strip()

        body_html = md_to_html_body(body_md, 'daily')

        # Indent body HTML lines for readability
        indented_body = '\n'.join(
            '    ' + line if line.strip() else line
            for line in body_html.splitlines()
        )

        section = (
            f'    <div class="dispatch-section">\n'
            f'      <p class="dispatch-section__label">{label}</p>\n'
            f'      <h2 class="dispatch-section__title">{title}</h2>\n'
            f'{indented_body}'
        )

        if note_url:
            section += (
                f'\n      <p class="dispatch-section__readmore">'
                f'<a href="{note_url}">Read more &rarr;</a></p>'
            )

        section += '\n    </div>'
        parts.append(section)

    # Sections separated by a full-width rule; no rule after the last section
    separator = '\n    <hr class="dispatch-rule">\n'
    return separator.join(parts)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert dispatch analysis.md (or combined JSON) to Anthology HTML"
    )
    # Normal mode args
    parser.add_argument("--input",         default=None,
                        help="Path to analysis.md (required in normal mode)")
    parser.add_argument("--dispatch-type", default="daily", choices=["daily", "weekly"],
                        help="Dispatch type: daily or weekly (normal mode only)")
    parser.add_argument("--label",         default=None,
                        help="Override the dispatch label (e.g. 'UK Politics', 'NBA')")

    # Combined mode arg
    parser.add_argument("--combined-dispatches", default=None,
                        help="Path to JSON file containing array of 5 dispatch objects "
                             "{label, title, body_md, note_url}. Activates combined mode.")

    # Shared args
    parser.add_argument("--output",        required=True, help="Path to write HTML output")
    parser.add_argument("--slug",          required=True, help="URL slug")
    parser.add_argument("--title",         required=True,
                        help="Dispatch title (normal) or edition title (combined)")
    parser.add_argument("--date",          required=True,
                        help="Display date, e.g. 'May 2026'")
    parser.add_argument("--back-url",      default=None,
                        help="Override the back-link URL (default: /)")
    parser.add_argument("--pub-datetime",  default=None,
                        help="Publication datetime, e.g. '10 May 2026, 3:45 PM'. "
                             "Auto-generated from current EST time if omitted.")
    args = parser.parse_args()

    back_url = args.back_url if args.back_url else "/"
    pub_dt   = args.pub_datetime if args.pub_datetime else current_est_datetime()
    date_line = f'{args.date} &middot; Published {pub_dt} EST'

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    # ── COMBINED MODE ──────────────────────────────────────────────────────────
    if args.combined_dispatches:
        dispatches_data = json.loads(
            Path(args.combined_dispatches).read_text(encoding='utf-8')
        )
        sections_html = render_combined_sections(dispatches_data)

        # Meta description from first dispatch title
        first_title = dispatches_data[0].get('title', '') if dispatches_data else ''
        meta = first_title[:200]

        html = COMBINED_HTML_TEMPLATE.format(
            edition_title=args.title,
            date_line=date_line,
            slug=args.slug,
            meta_description=meta,
            back_url=back_url,
            sections_html=sections_html,
        )
        out.write_text(html, encoding='utf-8')
        print(f"✓ Written (combined, {len(dispatches_data)} sections): {out}")
        return

    # ── NORMAL MODE ────────────────────────────────────────────────────────────
    if not args.input:
        parser.error("--input is required in normal (single-dispatch) mode")

    if args.label:
        dispatch_label = args.label
    else:
        dispatch_label = "Daily Dispatch" if args.dispatch_type == "daily" else "Weekly Dispatch"

    md_text = Path(args.input).read_text(encoding="utf-8")
    body    = md_to_html_body(md_text, args.dispatch_type)
    meta    = extract_meta_description(md_text)

    html = HTML_TEMPLATE.format(
        title=args.title,
        date_line=date_line,
        slug=args.slug,
        dispatch_label=dispatch_label,
        meta_description=meta,
        back_url=back_url,
        body=body,
    )

    out.write_text(html, encoding="utf-8")
    print(f"✓ Written: {out}")


if __name__ == "__main__":
    main()
