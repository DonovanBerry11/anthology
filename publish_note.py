#!/usr/bin/env python3
"""
publish_note.py — Publishes a note to the Anthology GitHub repo.

Clones the repo into /tmp, generates the note HTML, updates index.html,
commits, and pushes.

Usage:
    python publish_note.py \
        --slug the-subtraction-problem \
        --title "The Subtraction Problem" \
        --date "May 2026" \
        --standfirst "One to two sentence summary." \
        --analysis-md path/to/analysis.md \
        --token-file path/to/.publish-config \
        --repo DonovanBerry11/anthology \
        --scripts-dir path/to/anthology/
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

NOTE_ITEM_TEMPLATE = """\

      <li class="note-item">
        <div class="note-item__meta">{date}</div>
        <h2 class="note-item__title">
          <a href="notes/{slug}.html">{title}</a>
        </h2>
        <p class="note-item__standfirst">
          {standfirst}
        </p>
      </li>
"""

INDEX_MARKER = '      <ul class="note-list">\n'


def run(cmd, cwd=None, check=True):
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Command failed: {cmd}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="Publish a note to Anthology")
    parser.add_argument("--slug",         required=True)
    parser.add_argument("--title",        required=True)
    parser.add_argument("--date",         required=True)
    parser.add_argument("--standfirst",   required=True)
    parser.add_argument("--analysis-md",  required=True)
    parser.add_argument("--token-file",   required=True)
    parser.add_argument("--repo",         default="DonovanBerry11/anthology")
    parser.add_argument("--scripts-dir",  required=True)
    args = parser.parse_args()

    token = Path(args.token_file).read_text().strip()
    clone_dir = Path("/tmp/anthology-note-publish")

    # 1. Fresh clone into /tmp
    print("Cloning repo...")
    if clone_dir.exists():
        shutil.rmtree(clone_dir)
    run(f'git clone "https://DonovanBerry11:{token}@github.com/{args.repo}.git" {clone_dir}')
    run(f'git config user.email "donovanberry11@gmail.com"', cwd=clone_dir)
    run(f'git config user.name "Donovan Berry"', cwd=clone_dir)

    # 2. Generate note HTML
    print("Generating note HTML...")
    gen_script = Path(args.scripts_dir) / "generate_note_html.py"
    note_html  = clone_dir / "notes" / f"{args.slug}.html"
    run(
        f'python3 {gen_script} '
        f'--input "{args.analysis_md}" '
        f'--output "{note_html}" '
        f'--slug "{args.slug}" '
        f'--title "{args.title}" '
        f'--date "{args.date}"'
    )

    # 3. Update index.html (inject at top of note list, idempotent)
    print("Updating index...")
    index_path = clone_dir / "index.html"
    index = index_path.read_text()
    if f'href="notes/{args.slug}.html"' not in index:
        new_item = NOTE_ITEM_TEMPLATE.format(
            slug=args.slug, title=args.title,
            date=args.date, standfirst=args.standfirst
        )
        index = index.replace(INDEX_MARKER, INDEX_MARKER + new_item, 1)
        index_path.write_text(index)
    else:
        print("  (note already in index — skipping index update)")

    # 4. Commit and push
    print("Committing and pushing...")
    run(f'git add notes/{args.slug}.html index.html', cwd=clone_dir)
    run(f'git commit -m "Add note: {args.title}"', cwd=clone_dir)
    run('git push', cwd=clone_dir)

    print(f"\n✅ Published: https://anthology-weld.vercel.app/notes/{args.slug}.html")
    print("   (Vercel deployment typically takes under 60 seconds)")


if __name__ == "__main__":
    main()
