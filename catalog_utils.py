"""
catalog_utils.py — Shared utility for updating catalog files.

Called by all publish scripts immediately after generating HTML.
Reads the existing catalog from the cloned repo, upserts the new entry,
sorts by date descending, and writes back.

Supports two catalog targets:
  - Shared catalog: shared-catalog.json (always updated, serves unauthenticated users)
  - Per-user catalog: users/{user_id}/content-catalog.json (written when user_id provided,
    serves authenticated users their personalised feed)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


SHARED_CATALOG_FILENAME = "shared-catalog.json"
USER_CATALOG_FILENAME = "content-catalog.json"


def _upsert_catalog_file(catalog_path, entry):
    """Read, upsert, sort, and write a single catalog file."""
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

    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)


def update_catalog(repo_dir, entry, user_id=None):
    """
    Upsert `entry` into content-catalog.json inside `repo_dir`.

    `entry` must contain at minimum:
        slug, type, section, domain, sector, title, standfirst,
        date (ISO: YYYY-MM-DD), date_display, url, keywords (list)

    Optional fields: dispatch_type, format, sport

    If `user_id` is provided, also writes to users/{user_id}/content-catalog.json.
    The shared catalog is always updated (serves unauthenticated / archive view).
    """
    repo_dir = Path(repo_dir)

    # 1. Always update the shared catalog
    shared_path = repo_dir / SHARED_CATALOG_FILENAME
    _upsert_catalog_file(shared_path, entry)
    print(f"  Shared catalog updated: {entry['slug']} → {SHARED_CATALOG_FILENAME}")

    # 2. If user_id provided, also update per-user catalog
    if user_id:
        user_catalog_path = repo_dir / "users" / user_id / USER_CATALOG_FILENAME
        # For the per-user catalog, update the url to the per-user path
        user_entry = dict(entry)
        section = entry.get("section", "")
        slug = entry.get("slug", "")
        user_entry["url"] = f"/users/{user_id}/{section}/{slug}.html"
        _upsert_catalog_file(user_catalog_path, user_entry)
        print(f"  Per-user catalog updated: {entry['slug']} → users/{user_id}/{USER_CATALOG_FILENAME}")
