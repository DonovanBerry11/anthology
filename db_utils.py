"""
db_utils.py — Anthology shared database helper
Drop this in ~/Desktop/anthology/ alongside catalog_utils.py.

Provides two thin wrappers over Supabase REST:
  - log_action(...)      → writes a row to agent_logs
  - upsert_piece(...)    → writes/updates a row in content_pieces

Both are silent-fail by default (pass raise_errors=True to surface exceptions),
so a logging failure never crashes the pipeline that called it.

Usage in any publish script:
    from db_utils import get_db_client, log_action, upsert_piece

    db = get_db_client()   # reads SUPABASE_URL + SUPABASE_KEY from env

    log_action(db, task_id="dispatch-autonomous-workflow",
               action="Cloned repo", detail="/tmp/anthology-abc123-publish")

    upsert_piece(db, user_id="94baf514-...", slug="my-slug",
                 piece_type="dispatch", title="My Title", body=html,
                 status="published")

Environment variables required:
    SUPABASE_URL   — https://uzjkepauhgbuunvcokru.supabase.co
    SUPABASE_KEY   — service_role key (NOT the anon/publishable key)

These can live in a .env file; the helper will load it automatically
if python-dotenv is installed.
"""

import os
import sys
import json
import logging
import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    sys.exit("db_utils requires 'requests': pip install requests")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # optional


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class SupabaseClient:
    """Minimal Supabase REST client — just enough for inserts and upserts."""

    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",  # don't return rows — faster
        }

    def insert(self, table: str, row: dict) -> requests.Response:
        url = f"{self.url}/rest/v1/{table}"
        return requests.post(url, headers=self.headers, json=row, timeout=10)

    def upsert(self, table: str, row: dict, on_conflict: str) -> requests.Response:
        headers = {**self.headers, "Prefer": f"resolution=merge-duplicates,return=minimal"}
        url = f"{self.url}/rest/v1/{table}?on_conflict={on_conflict}"
        return requests.post(url, headers=headers, json=row, timeout=10)


def get_db_client() -> SupabaseClient:
    """
    Build a SupabaseClient from environment variables.
    Exits with a clear message if either variable is missing or wrong key type.
    """
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")

    if not url:
        sys.exit(
            "db_utils: SUPABASE_URL not set.\n"
            "  export SUPABASE_URL=https://uzjkepauhgbuunvcokru.supabase.co"
        )
    if not key:
        sys.exit(
            "db_utils: SUPABASE_KEY not set.\n"
            "  This must be your service_role key, not the anon key.\n"
            "  Find it in Supabase → Project Settings → API → service_role."
        )
    if "publishable" in key or key.startswith("sb_publishable"):
        sys.exit(
            "db_utils: You've supplied the anon/publishable key.\n"
            "  Writes require the service_role key instead."
        )

    return SupabaseClient(url, key)


# ---------------------------------------------------------------------------
# agent_logs
# ---------------------------------------------------------------------------

def log_action(
    db: SupabaseClient,
    action: str,
    *,
    task_id: Optional[str] = None,
    user_id: Optional[str] = None,
    detail: Optional[str] = None,
    status: str = "ok",
    raise_errors: bool = False,
) -> bool:
    """
    Write one row to agent_logs.

    Args:
        db         — SupabaseClient from get_db_client()
        action     — Short description of what happened, e.g. "Cloned repo"
        task_id    — Cowork task ID, e.g. "dispatch-autonomous-workflow"
        user_id    — Supabase UUID string, or None for non-user-scoped actions
        detail     — Any extra context: paths, slugs, error messages, etc.
        status     — "ok" | "error" | "warn"  (default "ok")
        raise_errors — If True, re-raises on failure instead of returning False

    Returns:
        True on success, False on failure (unless raise_errors=True).
    """
    if status not in ("ok", "error", "warn"):
        status = "warn"

    row = {
        "action": action,
        "status": status,
        "created_at": _now_iso(),
    }
    if task_id:
        row["task_id"] = task_id
    if user_id:
        row["user_id"] = user_id
    if detail:
        row["detail"] = str(detail)[:2000]  # guard against huge tracebacks

    try:
        resp = db.insert("agent_logs", row)
        if resp.status_code in (200, 201):
            logger.debug("agent_logs: logged '%s' [%s]", action, status)
            return True
        else:
            msg = f"agent_logs insert failed: HTTP {resp.status_code} — {resp.text[:200]}"
            logger.warning(msg)
            if raise_errors:
                raise RuntimeError(msg)
            return False
    except Exception as exc:
        logger.warning("agent_logs: exception during insert: %s", exc)
        if raise_errors:
            raise
        return False


def log_error(
    db: SupabaseClient,
    action: str,
    exc: Exception,
    *,
    task_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> bool:
    """Convenience wrapper: log an exception as status='error'."""
    return log_action(
        db,
        action,
        task_id=task_id,
        user_id=user_id,
        detail=f"{type(exc).__name__}: {exc}",
        status="error",
    )


# ---------------------------------------------------------------------------
# content_pieces
# ---------------------------------------------------------------------------

def upsert_piece(
    db: SupabaseClient,
    *,
    slug: str,
    piece_type: str,
    title: str,
    body: str,
    user_id: Optional[str] = None,
    standfirst: Optional[str] = None,
    status: str = "draft",
    sector: Optional[str] = None,
    domain: Optional[str] = None,
    published_at: Optional[str] = None,
    raise_errors: bool = False,
) -> bool:
    """
    Insert or update a row in content_pieces (upserts on slug).

    Args:
        db          — SupabaseClient from get_db_client()
        slug        — Unique piece identifier, e.g. "fed-rate-decision-may-2026"
        piece_type  — "essay" | "note" | "dispatch"
        title       — Piece title
        body        — Full HTML or Markdown body
        user_id     — Supabase UUID string, or None for shared pieces
        standfirst  — Optional standfirst / subtitle
        status      — "draft" | "published"  (default "draft")
        sector      — e.g. "political-economy", "technology"
        domain      — e.g. "global", "uk", "us-sports"
        published_at — ISO timestamp string; set automatically if status="published"
                       and not provided
        raise_errors — If True, re-raises on failure

    Returns:
        True on success, False on failure (unless raise_errors=True).
    """
    valid_types = ("essay", "note", "dispatch")
    if piece_type not in valid_types:
        msg = f"upsert_piece: invalid type '{piece_type}'. Must be one of {valid_types}"
        logger.warning(msg)
        if raise_errors:
            raise ValueError(msg)
        return False

    if status not in ("draft", "published"):
        status = "draft"

    now = _now_iso()

    row = {
        "slug": slug,
        "type": piece_type,
        "title": title,
        "body": body,
        "status": status,
        "generated_at": now,
        "created_at": now,
    }

    if user_id:
        row["user_id"] = user_id
    if standfirst:
        row["standfirst"] = standfirst
    if sector:
        row["sector"] = sector
    if domain:
        row["domain"] = domain

    if status == "published":
        row["published_at"] = published_at or now

    try:
        resp = db.upsert("content_pieces", row, on_conflict="slug")
        if resp.status_code in (200, 201):
            logger.debug("content_pieces: upserted '%s' [%s]", slug, status)
            return True
        else:
            msg = f"content_pieces upsert failed: HTTP {resp.status_code} — {resp.text[:200]}"
            logger.warning(msg)
            if raise_errors:
                raise RuntimeError(msg)
            return False
    except Exception as exc:
        logger.warning("content_pieces: exception during upsert: %s", exc)
        if raise_errors:
            raise
        return False


def mark_published(
    db: SupabaseClient,
    slug: str,
    *,
    raise_errors: bool = False,
) -> bool:
    """
    Flip an existing content_pieces row from draft → published.
    Convenience wrapper so publish scripts don't need to re-supply the full body.
    """
    now = _now_iso()
    headers = {**db.headers, "Prefer": "return=minimal"}
    url = f"{db.url}/rest/v1/content_pieces?slug=eq.{slug}"

    payload = {"status": "published", "published_at": now}

    try:
        resp = requests.patch(url, headers=headers, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            logger.debug("content_pieces: marked '%s' as published", slug)
            return True
        else:
            msg = f"mark_published failed for '{slug}': HTTP {resp.status_code} — {resp.text[:200]}"
            logger.warning(msg)
            if raise_errors:
                raise RuntimeError(msg)
            return False
    except Exception as exc:
        logger.warning("mark_published: exception: %s", exc)
        if raise_errors:
            raise
        return False


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Smoke test — run directly to verify credentials and connectivity
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

    print("db_utils smoke test")
    print("=" * 50)

    db = get_db_client()
    print(f"Connected to: {db.url}\n")

    # 1. agent_logs — basic ok entry
    print("1. Writing test row to agent_logs (status=ok)...")
    ok = log_action(
        db,
        action="db_utils smoke test",
        task_id="manual",
        detail="Connectivity check from db_utils.__main__",
        status="ok",
    )
    print(f"   {'✓ OK' if ok else '✗ FAILED'}\n")

    # 2. agent_logs — warn entry
    print("2. Writing test row to agent_logs (status=warn)...")
    ok = log_action(
        db,
        action="db_utils smoke test — warn",
        task_id="manual",
        detail="This is a test warning entry",
        status="warn",
    )
    print(f"   {'✓ OK' if ok else '✗ FAILED'}\n")

    # 3. content_pieces — draft upsert
    # user_id is NOT NULL in the schema, so we pass Donovan's UUID here.
    # If running as a different user, swap in the correct UUID.
    print("3. Upserting test row to content_pieces (status=draft)...")
    ok = upsert_piece(
        db,
        slug="_db-utils-smoke-test",
        piece_type="note",
        title="db_utils smoke test",
        body="<p>This is a smoke test entry — safe to delete.</p>",
        standfirst="Connectivity check.",
        status="draft",
        domain="global",
        sector="test",
        user_id="94baf514-f988-464f-8de1-56c29d4597ee",
    )
    print(f"   {'✓ OK' if ok else '✗ FAILED'}\n")

    # 4. mark_published
    print("4. Marking test piece as published...")
    ok = mark_published(db, slug="_db-utils-smoke-test")
    print(f"   {'✓ OK' if ok else '✗ FAILED'}\n")

    print("=" * 50)
    print("Done. Check your Supabase tables to confirm the rows are visible.")
    print("Delete the '_db-utils-smoke-test' row from content_pieces when done.")
