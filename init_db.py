#!/usr/bin/env python3
"""
init_db.py — Anthology database migration script
Initialises required Supabase tables via the REST API (no direct Postgres access needed).

Usage:
    python3 init_db.py
    python3 init_db.py --dry-run        # Print SQL only, don't execute
    python3 init_db.py --table agent_logs  # Run a single table only

Requirements:
    pip install requests python-dotenv

Environment variables (set in .env or shell):
    SUPABASE_URL   — e.g. https://uzjkepauhgbuunvcokru.supabase.co
    SUPABASE_KEY   — your service_role key (NOT the anon/publishable key)

IMPORTANT: This script requires the service_role key, not the anon key.
Find it in your Supabase dashboard → Project Settings → API → service_role.
The service_role key bypasses RLS and can execute DDL via the REST API.
Never commit it to Git.
"""

import argparse
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional — env vars can be set directly in shell


# ---------------------------------------------------------------------------
# Migration definitions
# Each entry: (table_name, sql)
# Order matters — no foreign keys here, so order is just for readability.
# ---------------------------------------------------------------------------

MIGRATIONS = [
    (
        "reading_events",
        """
CREATE TABLE IF NOT EXISTS reading_events (
  id                    uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id               uuid        NOT NULL,
  piece_slug            text        NOT NULL,
  piece_type            text        NOT NULL,
  read_depth_percent    integer,
  time_on_page_seconds  integer,
  created_at            timestamptz DEFAULT now()
);
        """.strip(),
    ),
    (
        "content_pieces",
        """
CREATE TABLE IF NOT EXISTS content_pieces (
  id            uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id       uuid        NOT NULL,
  slug          text        NOT NULL UNIQUE,
  type          text        NOT NULL CHECK (type IN ('essay', 'note', 'dispatch')),
  title         text        NOT NULL,
  body          text        NOT NULL,
  standfirst    text,
  status        text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
  sector        text,
  domain        text,
  generated_at  timestamptz DEFAULT now(),
  published_at  timestamptz,
  created_at    timestamptz DEFAULT now()
);
        """.strip(),
    ),
    (
        "agent_logs",
        """
CREATE TABLE IF NOT EXISTS agent_logs (
  id          uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id     uuid,
  task_id     text,
  action      text        NOT NULL,
  detail      text,
  status      text        NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'error', 'warn')),
  created_at  timestamptz DEFAULT now()
);
        """.strip(),
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_config():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")

    if not url:
        sys.exit(
            "ERROR: SUPABASE_URL not set.\n"
            "Export it in your shell or add it to a .env file:\n"
            "  export SUPABASE_URL=https://uzjkepauhgbuunvcokru.supabase.co"
        )
    if not key:
        sys.exit(
            "ERROR: SUPABASE_KEY not set.\n"
            "This must be your service_role key (not the anon key).\n"
            "Find it in Supabase → Project Settings → API → service_role.\n"
            "  export SUPABASE_KEY=your-service-role-key"
        )
    if "publishable" in key or key.startswith("sb_publishable"):
        sys.exit(
            "ERROR: You've provided the anon/publishable key.\n"
            "DDL requires the service_role key instead.\n"
            "Find it in Supabase → Project Settings → API → service_role."
        )

    return url, key


def run_sql(url, key, sql, table_name):
    """Execute a SQL statement via Supabase's /rest/v1/rpc or pg endpoint."""
    endpoint = f"{url}/rest/v1/rpc/exec_sql"

    # Supabase doesn't expose a generic SQL endpoint on the anon REST API.
    # The canonical approach for migrations is the Management API or pg directly.
    # Here we use the pg meta endpoint available on all Supabase projects.
    endpoint = f"{url}/pg/query"

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(endpoint, headers=headers, json={"query": sql}, timeout=30)

    if resp.status_code in (200, 201):
        return True, None

    # Some Supabase plans return 200 with an error in the body
    try:
        body = resp.json()
        if "error" in body:
            return False, body["error"]
        # "already exists" is fine — CREATE TABLE IF NOT EXISTS handles it,
        # but belt-and-braces in case the pg endpoint doesn't honour IF NOT EXISTS
        if "already exists" in str(body).lower():
            return True, "(already existed)"
    except Exception:
        pass

    return False, f"HTTP {resp.status_code}: {resp.text[:300]}"


def print_sql_block(table_name, sql):
    print(f"\n{'─' * 60}")
    print(f"  TABLE: {table_name}")
    print(f"{'─' * 60}")
    print(sql)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Initialise Anthology Supabase tables."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL statements without executing them.",
    )
    parser.add_argument(
        "--table",
        metavar="NAME",
        help="Run migration for a single table only.",
    )
    args = parser.parse_args()

    # Filter migrations if --table specified
    migrations = MIGRATIONS
    if args.table:
        migrations = [(n, s) for n, s in MIGRATIONS if n == args.table]
        if not migrations:
            known = ", ".join(n for n, _ in MIGRATIONS)
            sys.exit(f"Unknown table '{args.table}'. Known tables: {known}")

    if args.dry_run:
        print("DRY RUN — SQL that would be executed:\n")
        for table_name, sql in migrations:
            print_sql_block(table_name, sql)
        print(f"\n{'─' * 60}")
        print("No changes made.")
        return

    url, key = get_config()
    print(f"Connecting to: {url}")
    print(f"Running {len(migrations)} migration(s)...\n")

    success_count = 0
    fail_count = 0

    for table_name, sql in migrations:
        print(f"  → {table_name} ... ", end="", flush=True)
        ok, err = run_sql(url, key, sql, table_name)
        if ok:
            note = f" {err}" if err else ""
            print(f"OK{note}")
            success_count += 1
        else:
            print(f"FAILED\n    {err}")
            fail_count += 1

    print(f"\n{'─' * 60}")
    print(f"Done. {success_count} succeeded, {fail_count} failed.")

    if fail_count:
        print(
            "\nIf the /pg/query endpoint returned 404, your Supabase plan may not\n"
            "expose it. In that case, run the SQL manually in:\n"
            "  Supabase Dashboard → SQL Editor\n"
            "Use --dry-run to print the statements."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
