#!/usr/bin/env python3
"""
publish_uk_politics.py — Publishes a UK politics briefing to the Anthology GitHub repo.

Clones the repo into /tmp, generates the briefing HTML under uk-politics/,
updates catalogs, commits, and pushes.

Usage:
    python publish_uk_politics.py \
        --slug starmer-survival-kings-speech \
        --title "Starmer's Survival: King's Speech" \
        --date "May 2026" \
        --sector politics \
        --standfirst "One to two sentence summary." \
        --analysis-md path/to/analysis.md \
        --token-file path/to/.publish-config \
        --repo DonovanBerry11/anthology \
        --scripts-dir path/to/anthology/ \
        --user-id 94baf514-f988-464f-8de1-56c29d4597ee
"""

import argparse
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
    parser = argparse.ArgumentParser(description="Publish a UK politics briefing to Anthology")
    parser.add_argument("--slug",          required=True)
    parser.add_argument("--title",         required=True)
    parser.add_argument("--date",          required=True)
    parser.add_argument("--date-iso",      default=None, help="ISO date YYYY-MM-DD for catalog sorting")
    parser.add_argument("--sector",        default="politics", help="Sector tag for catalog")
    parser.add_argument("--standfirst",    required=True)
    parser.add_argument("--analysis-md",   required=True)
    parser.add_argument("--token-file",    required=True)
    parser.add_argument("--repo",          default="DonovanBerry11/anthology")
    parser.add_argument("--scripts-dir",   required=True)
    parser.add_argument("--user-id",       default=None,
                        help="Supabase user UUID; routes output to users/{user_id}/ paths")
    args = parser.parse_args()

    pub_datetime = current_est_datetime()
    user_id = args.user_id
    token = Path(args.token_file).read_text().strip()
    clone_dir = Path("/tmp/anthology-ukpol-publish")

    # 1. Fresh clone into /tmp
    print("Cloning repo...")
    if clone_dir.exists():
        shutil.rmtree(clone_dir)
    run(f'git clone "https://DonovanBerry11:{token}@github.com/{args.repo}.git" {clone_dir}')
    run(f'git config user.email "donovanberry11@gmail.com"', cwd=clone_dir)
    run(f'git config user.name "Donovan Berry"', cwd=clone_dir)

    gen_script = Path(args.scripts_dir) / "generate_dispatch_html.py"
    git_add_paths = []

    _gen_base = (
        f'python3 {gen_script} '
        f'--input "{args.analysis_md}" '
        f'--slug "{args.slug}" '
        f'--title "{args.title}" '
        f'--date "{args.date}" '
        f'--dispatch-type "weekly" '
        f'--label "UK Politics" '
        f'--pub-datetime "{pub_datetime}"'
    )

    # 2a. Generate shared UK politics HTML
    print("Generating shared UK politics HTML...")
    shared_html = clone_dir / "uk-politics" / f"{args.slug}.html"
    run(_gen_base + f' --output "{shared_html}"')
    git_add_paths.append(f'uk-politics/{args.slug}.html')

    # 2b. Per-user HTML if user_id provided
    if user_id:
        print(f"Generating per-user UK politics HTML for {user_id}...")
        user_html = clone_dir / "users" / user_id / "uk-politics" / f"{args.slug}.html"
        run(_gen_base + f' --back-url "/" --output "{user_html}"')
        git_add_paths.append(f'users/{user_id}/uk-politics/{args.slug}.html')

    # 3. Update catalogs
    print("Updating content catalog...")
    sys.path.insert(0, args.scripts_dir)
    from catalog_utils import update_catalog
    entry = {
        "slug": args.slug,
        "type": "briefing",
        "section": "uk-politics",
        "domain": "uk-politics",
        "sector": args.sector,
        "title": args.title,
        "standfirst": args.standfirst,
        "date": args.date_iso if args.date_iso else args.date,
        "date_display": args.date,
        "url": f"/uk-politics/{args.slug}.html",
        "keywords": [],
    }
    update_catalog(clone_dir, entry, user_id=user_id)
    git_add_paths.append("shared-catalog.json")
    if user_id:
        git_add_paths.append(f"users/{user_id}/content-catalog.json")

    # 4. Commit and push
    print("Committing and pushing...")
    run(f'git add {" ".join(git_add_paths)}', cwd=clone_dir)
    run(f'git commit -m "Add UK politics briefing: {args.title}"', cwd=clone_dir)
    run('git push', cwd=clone_dir)

    print(f"\n✅ Published: https://anthology-weld.vercel.app/uk-politics/{args.slug}.html")
    if user_id:
        print(f"   Per-user: https://anthology-weld.vercel.app/users/{user_id}/uk-politics/{args.slug}.html")
    print("   (Vercel deployment typically takes under 60 seconds)")


if __name__ == "__main__":
    main()
