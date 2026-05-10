#!/usr/bin/env python3
"""
generate_edition.py — Builds a daily edition.json for a user from their
content catalog. The edition defines an editorial hierarchy:
  - lead:            the single most prominent story
  - secondary:       2–3 supporting stories from different sections
  - further_reading: remaining pieces up to a cap

Usage:
    python generate_edition.py \
        --user-id 94baf514-f988-464f-8de1-56c29d4597ee \
        --catalog /path/to/users/{user_id}/content-catalog.json \
        --output  /path/to/users/{user_id}/edition.json

Or, to work directly on a cloned repo directory:
    python generate_edition.py \
        --user-id 94baf514-... \
        --repo-dir /tmp/anthology-clone

When --repo-dir is provided, --catalog and --output are resolved automatically:
  catalog → {repo_dir}/users/{user_id}/content-catalog.json
           (fallback: {repo_dir}/content-catalog.json)
  output  → {repo_dir}/users/{user_id}/edition.json
"""

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


def current_est_datetime():
    est = timezone(timedelta(hours=-5))
    now = datetime.now(est)
    return now.strftime("%-d %B %Y, %-I:%M %p")


def today_iso():
    est = timezone(timedelta(hours=-5))
    return datetime.now(est).strftime("%Y-%m-%d")


def today_display():
    est = timezone(timedelta(hours=-5))
    return datetime.now(est).strftime("%A, %-d %B %Y")


def section_priority(piece):
    """
    Assign a base priority score by section so the lead is likely
    to be the freshest dispatch-type piece rather than an archival essay.
    Returns (section_priority, date_string) for sorting.
    """
    section = piece.get("section") or piece.get("type", "")
    priority_map = {
        "dispatches":  0,
        "uk-politics": 0,
        "us-sports":   0,
        "notes":       1,
        "essays":      2,
    }
    return (priority_map.get(section, 3), piece.get("date", ""))


def build_edition(pieces, user_id):
    """
    Given a flat list of catalog pieces, build the editorial hierarchy.
    """
    if not pieces:
        return None

    # Sort: by section priority (dispatches first), then date descending
    ranked = sorted(
        pieces,
        key=lambda p: (section_priority(p)[0], ""),
        # secondary key: date descending within each priority tier
    )
    # Re-sort properly: primary = section priority, secondary = date desc
    ranked = sorted(
        pieces,
        key=lambda p: (section_priority(p)[0], "".join(["z"] if not p.get("date") else []) + p.get("date", "")),
        reverse=False
    )
    # Within each tier, sort by date descending
    from itertools import groupby
    final = []
    for _, group in groupby(ranked, key=lambda p: section_priority(p)[0]):
        tier = sorted(group, key=lambda p: p.get("date", ""), reverse=True)
        final.extend(tier)

    lead = final[0]

    # Secondary: pick 2–3 pieces from different sections than the lead
    lead_section = lead.get("section") or lead.get("type", "")
    secondary = []
    for p in final[1:]:
        sec = p.get("section") or p.get("type", "")
        if len(secondary) >= 3:
            break
        # Prefer pieces from different sections to ensure variety
        if sec != lead_section or all((p2.get("section") or p2.get("type")) == lead_section for p2 in final[1:6]):
            secondary.append(p)

    secondary_slugs = {p["slug"] for p in secondary}
    secondary_slugs.add(lead["slug"])

    # Further reading: everything else, capped at 8
    further = [p for p in final if p["slug"] not in secondary_slugs][:8]

    return {
        "date":          today_iso(),
        "date_display":  today_display(),
        "generated_at":  current_est_datetime() + " EST",
        "user_id":       user_id,
        "lead":          lead,
        "secondary":     secondary,
        "further_reading": further,
    }


def main():
    parser = argparse.ArgumentParser(description="Build a daily edition.json from a user's content catalog")
    parser.add_argument("--user-id",   required=True)
    parser.add_argument("--catalog",   default=None, help="Path to content-catalog.json")
    parser.add_argument("--output",    default=None, help="Path to write edition.json")
    parser.add_argument("--repo-dir",  default=None, help="Cloned repo root; auto-resolves catalog and output")
    parser.add_argument("--max-further", type=int, default=8,
                        help="Max pieces in further_reading (default 8)")
    args = parser.parse_args()

    # Resolve paths
    if args.repo_dir:
        repo = Path(args.repo_dir)
        per_user_catalog = repo / "users" / args.user_id / "content-catalog.json"
        shared_catalog   = repo / "content-catalog.json"
        catalog_path     = per_user_catalog if per_user_catalog.exists() else shared_catalog
        output_path      = repo / "users" / args.user_id / "edition.json"
    else:
        if not args.catalog or not args.output:
            parser.error("--catalog and --output are required when --repo-dir is not provided")
        catalog_path = Path(args.catalog)
        output_path  = Path(args.output)

    if not catalog_path.exists():
        print(f"Catalog not found: {catalog_path}")
        return

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    pieces  = catalog.get("pieces", [])

    edition = build_edition(pieces, args.user_id)
    if not edition:
        print("No pieces found; edition not generated.")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(edition, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ Edition written: {output_path}")
    print(f"  Lead: {edition['lead']['title']}")
    print(f"  Secondary: {[p['title'] for p in edition['secondary']]}")
    print(f"  Further reading: {len(edition['further_reading'])} pieces")


if __name__ == "__main__":
    main()
