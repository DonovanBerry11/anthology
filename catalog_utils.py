"""
catalog_utils.py — Shared utility for updating content-catalog.json.

Called by all publish scripts immediately after generating HTML.
Reads the existing catalog from the cloned repo, upserts the new entry,
sorts by date descending, and writes back.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


CATALOG_FILENAME = "content-catalog.json"


def update_catalog(repo_dir, entry):
    """
    Upsert `entry` into content-catalog.json inside `repo_dir`.

    `entry` must contain at minimum:
        slug, type, section, domain, sector, title, standfirst,
        date (ISO: YYYY-MM-DD), date_display, url, keywords (list)

    Optional fields: dispatch_type, format, sport
    """
    catalog_path = Path(repo_dir) / CATALOG_FILENAME

    if catalog_path.exists():
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
    else:
        catalog = {"pieces": []}

    # Remove existing entry with same slug + section (idempotent upsert)
    catalog["pieces"] = [
        p for p in catalog["pieces"]
        if not (p.get("slug") == entry["slug"] and p.get("section") == entry["section"])
    ]

    catalog["pieces"].append(entry)

    # Sort newest first
    catalog["pieces"].sort(key=lambda p: p.get("date", ""), reverse=True)

    catalog["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    print(f"  Catalog updated: {entry['slug']} → {CATALOG_FILENAME}")
