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
from datetime import datetime, timezone, timedelta
from pathlib import Path


def current_est_datetime():
    est = timezone(timedelta(hours=-5))
    now = datetime.now(est)
    return now.strftime("%-d %B %Y, %-I:%M %p")


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
    parser.add_argument("--date-iso",     default=None, help="ISO date YYYY-MM-DD for catalog sorting")
    parser.add_argument("--sector",       default="political-economy", help="Sector tag for catalog")
    parser.add_argument("--standfirst",   required=True)
    parser.add_argument("--analysis-md",  required=True)
    parser.add_argument("--token-file",   required=True)
    parser.add_argument("--repo",         default="DonovanBerry11/anthology")
    parser.add_argument("--scripts-dir",  required=True)
    parser.add_argument("--user-id",      default=None,
                        help="Supabase user UUID; routes output to users/{user_id}/ paths")
    args = parser.parse_args()

    pub_datetime = current_est_datetime()
    user_id = args.user_id
    token = Path(args.token_file).read_text().strip()
    clone_dir = Path("/tmp/anthology-note-publish")

    # 1. Fresh clone into /tmp
    print("Cloning repo...")
    if clone_dir.exists():
        shutil.rmtree(clone_dir)
    run(f'git clone "https://DonovanBerry11:{token}@github.com/{args.repo}.git" {clone_dir}')
    run(f'git config user.email "donovanberry11@gmail.com"', cwd=clone_dir)
    run(f'git config user.name "Donovan Berry"', cwd=clone_dir)

    gen_script = Path(args.scripts_dir) / "generate_note_html.py"
    git_add_paths = []

    # 2a. Generate shared note HTML
    print("Generating shared note HTML...")
    shared_html = clone_dir / "notes" / f"{args.slug}.html"
    run(
        f'python3 {gen_script} '
        f'--input "{args.analysis_md}" '
        f'--output "{shared_html}" '
        f'--slug "{args.slug}" '
        f'--title "{args.title}" '
        f'--date "{args.date}" '
        f'--pub-datetime "{pub_datetime}"'
    )
    git_add_paths.append(f'notes/{args.slug}.html')

    # 2b. Per-user HTML if user_id provided
    if user_id:
        print(f"Generating per-user note HTML for {user_id}...")
        user_html = clone_dir / "users" / user_id / "notes" / f"{args.slug}.html"
        run(
            f'python3 {gen_script} '
            f'--input "{args.analysis_md}" '
            f'--output "{user_html}" '
            f'--slug "{args.slug}" '
            f'--title "{args.title}" '
            f'--date "{args.date}" '
            f'--pub-datetime "{pub_datetime}"'
        )
        git_add_paths.append(f'users/{user_id}/notes/{args.slug}.html')

    # 3. Update catalogs
    print("Updating content catalog...")
    sys.path.insert(0, args.scripts_dir)
    from catalog_utils import update_catalog
    entry = {
        "slug": args.slug,
        "type": "note",
        "section": "notes",
        "domain": "global",
        "sector": args.sector,
        "title": args.title,
        "standfirst": args.standfirst,
        "date": args.date_iso if args.date_iso else args.date,
        "date_display": args.date,
        "url": f"/notes/{args.slug}.html",
        "keywords": [],
    }
    update_catalog(clone_dir, entry, user_id=user_id)
    git_add_paths.append("shared-catalog.json")
    if user_id:
        git_add_paths.append(f"users/{user_id}/content-catalog.json")

    # 4. Commit and push
    print("Committing and pushing...")
    run(f'git add {" ".join(git_add_paths)}', cwd=clone_dir)
    run(f'git commit -m "Add note: {args.title}"', cwd=clone_dir)
    run('git push', cwd=clone_dir)

    print(f"\n✅ Published: https://anthology-weld.vercel.app/notes/{args.slug}.html")
    print("   (Vercel deployment typically takes under 60 seconds)")


if __name__ == "__main__":
    main()
