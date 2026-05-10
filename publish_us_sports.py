#!/usr/bin/env python3
"""
publish_us_sports.py — Publishes a US sports briefing to the Anthology GitHub repo.

Clones the repo into /tmp, generates the briefing HTML (using generate_dispatch_html.py
with --dispatch-type weekly for subheading support), updates content-catalog.json,
commits, and pushes.

Usage:
    python publish_us_sports.py \
        --slug nba-may9 \
        --title "NBA: 9 May 2026" \
        --sport "NBA" \
        --date "May 2026" \
        --standfirst "One to two sentence summary." \
        --analysis-md path/to/analysis.md \
        --token-file path/to/.publish-config \
        --repo DonovanBerry11/anthology \
        --scripts-dir path/to/anthology/

Note: --sport sets the label shown in the briefing header and homepage meta line.
Common values: NBA, NFL, MLB, NHL, CFB, CBB
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
    parser = argparse.ArgumentParser(description="Publish a US sports briefing to Anthology")
    parser.add_argument("--slug",        required=True)
    parser.add_argument("--title",       required=True)
    parser.add_argument("--sport",       required=True,
                        help="Sport label for display, e.g. NBA, NFL, MLB, NHL")
    parser.add_argument("--date",        required=True)
    parser.add_argument("--date-iso",    default=None, help="ISO date YYYY-MM-DD for catalog sorting")
    parser.add_argument("--sector",      default="sports", help="Sector tag for catalog")
    parser.add_argument("--standfirst",  required=True)
    parser.add_argument("--analysis-md", required=True)
    parser.add_argument("--token-file",  required=True)
    parser.add_argument("--repo",        default="DonovanBerry11/anthology")
    parser.add_argument("--scripts-dir", required=True)
    args = parser.parse_args()

    pub_datetime = current_est_datetime()
    token = Path(args.token_file).read_text().strip()
    clone_dir = Path("/tmp/anthology-ussports-publish")

    # 1. Fresh clone into /tmp
    print("Cloning repo...")
    if clone_dir.exists():
        shutil.rmtree(clone_dir)
    run(f'git clone "https://DonovanBerry11:{token}@github.com/{args.repo}.git" {clone_dir}')
    run(f'git config user.email "donovanberry11@gmail.com"', cwd=clone_dir)
    run(f'git config user.name "Donovan Berry"', cwd=clone_dir)

    # 2. Generate briefing HTML (weekly type for subheading support; label set to sport name)
    print("Generating briefing HTML...")
    gen_script    = Path(args.scripts_dir) / "generate_dispatch_html.py"
    briefing_html = clone_dir / "us-sports" / f"{args.slug}.html"
    run(
        f'python3 {gen_script} '
        f'--input "{args.analysis_md}" '
        f'--output "{briefing_html}" '
        f'--slug "{args.slug}" '
        f'--title "{args.title}" '
        f'--date "{args.date}" '
        f'--dispatch-type "weekly" '
        f'--label "{args.sport}" '
        f'--back-url "../index.html#us-sports" '
        f'--pub-datetime "{pub_datetime}"'
    )

    # 3. Update content catalog
    print("Updating content catalog...")
    sys.path.insert(0, args.scripts_dir)
    from catalog_utils import update_catalog
    update_catalog(clone_dir, {
        "slug": args.slug,
        "type": "briefing",
        "section": "us-sports",
        "domain": "us-sports",
        "sector": args.sector,
        "sport": args.sport,
        "title": args.title,
        "standfirst": args.standfirst,
        "date": args.date_iso if args.date_iso else args.date,
        "date_display": args.date,
        "url": f"/us-sports/{args.slug}.html",
        "keywords": [],
    })

    # 4. Commit and push
    print("Committing and pushing...")
    run(f'git add us-sports/{args.slug}.html content-catalog.json', cwd=clone_dir)
    run(f'git commit -m "Add US sports briefing: {args.title}"', cwd=clone_dir)
    run('git push', cwd=clone_dir)

    print(f"\n✅ Published: https://anthology-weld.vercel.app/us-sports/{args.slug}.html")
    print("   (Vercel deployment typically takes under 60 seconds)")


if __name__ == "__main__":
    main()
