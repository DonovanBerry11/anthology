#!/usr/bin/env python3
"""
update_orientation.py — Reads recent reading_events from Supabase and appends a
calibration note to the user's orientation file.

Usage:
    python update_orientation.py \
        --user-id 94baf514-f988-464f-8de1-56c29d4597ee \
        --orientation-file /path/to/orientation.md \
        --registry /path/to/users/registry.json \
        [--days 30] \
        [--supabase-url https://...] \
        [--supabase-key sb_publishable_...]

If --supabase-url / --supabase-key are omitted the script reads them from
the environment variables SUPABASE_URL and SUPABASE_ANON_KEY.

If --orientation-file is omitted the script looks up the path from the
registry using --user-id.

The script rewrites (or creates) a ## Reading Calibration section at the
bottom of the orientation file with a dated summary of engagement signals.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ── Supabase REST helpers ──────────────────────────────────────────────────

def supabase_select(base_url, anon_key, table, params):
    """
    GET from a Supabase REST endpoint.
    params: dict of query-string key→value (PostgREST filter syntax).
    Returns parsed JSON list.
    """
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{base_url}/rest/v1/{table}?{qs}"
    req = urllib.request.Request(url, headers={
        "apikey":        anon_key,
        "Authorization": f"Bearer {anon_key}",
        "Accept":        "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Supabase error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


# Need urllib.parse for quoting
import urllib.parse


# ── Orientation file helpers ───────────────────────────────────────────────

CALIBRATION_HEADER = "## Reading Calibration"


def load_orientation(path):
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def save_orientation(path, text):
    Path(path).write_text(text, encoding="utf-8")


def strip_calibration_section(text):
    """Remove any existing ## Reading Calibration section."""
    idx = text.find(f"\n{CALIBRATION_HEADER}")
    if idx == -1:
        idx = text.find(CALIBRATION_HEADER)
        if idx == 0:
            # File starts with it
            return ""
        return text
    return text[:idx]


def build_calibration_block(user_id, events, days, generated_at):
    """
    Analyse a list of reading_event dicts and produce a markdown section.
    Each event has: piece_slug, piece_type, read_depth_percent, time_on_page_seconds, created_at
    """
    if not events:
        return (
            f"\n\n{CALIBRATION_HEADER}\n\n"
            f"_Generated {generated_at} — no reading events in the past {days} days._\n"
        )

    # Aggregate per slug: max depth, total time, last read
    by_slug = defaultdict(lambda: {
        "depth": 0, "time": 0, "type": "unknown", "last": ""
    })
    for ev in events:
        slug = ev.get("piece_slug", "")
        d    = ev.get("read_depth_percent") or 0
        t    = ev.get("time_on_page_seconds") or 0
        tp   = ev.get("piece_type", "unknown")
        ca   = ev.get("created_at", "")
        entry = by_slug[slug]
        entry["depth"] = max(entry["depth"], d)
        entry["time"]  = max(entry["time"], t)
        entry["type"]  = tp
        if ca > entry["last"]:
            entry["last"] = ca

    total_pieces  = len(by_slug)
    fully_read    = [s for s, v in by_slug.items() if v["depth"] >= 80]
    partially_read = [s for s, v in by_slug.items() if 20 <= v["depth"] < 80]
    bounced        = [s for s, v in by_slug.items() if v["depth"] < 20]

    avg_depth = sum(v["depth"] for v in by_slug.values()) / total_pieces
    avg_time  = sum(v["time"]  for v in by_slug.values()) / total_pieces

    # Type breakdown
    by_type = defaultdict(int)
    for v in by_slug.values():
        by_type[v["type"]] += 1
    type_summary = ", ".join(f"{k}: {n}" for k, n in sorted(by_type.items()))

    lines = [
        f"\n\n{CALIBRATION_HEADER}",
        f"\n_Generated {generated_at} from reading events (last {days} days)._\n",
        f"**Pieces engaged:** {total_pieces}  ({type_summary})",
        f"**Average scroll depth:** {avg_depth:.0f}%   "
        f"**Average time on page:** {avg_time:.0f}s",
        "",
    ]

    if fully_read:
        lines.append(f"**Read in full (≥80% depth):** {', '.join(fully_read)}")
    if partially_read:
        lines.append(f"**Partially read (20–79%):** {', '.join(partially_read)}")
    if bounced:
        lines.append(f"**Bounced (<20%):** {', '.join(bounced)}")

    lines.append("")
    lines.append(
        "_Agent note: weight fully-read slugs as confirmed interests; "
        "treat bounced slugs as low-signal or mismatched framing._"
    )

    return "\n".join(lines) + "\n"


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Update orientation file with reading calibration from Supabase"
    )
    parser.add_argument("--user-id",          required=True)
    parser.add_argument("--orientation-file", default=None,
                        help="Path to orientation.md; auto-resolved from registry if omitted")
    parser.add_argument("--registry",         default=None,
                        help="Path to users/registry.json")
    parser.add_argument("--days",             type=int, default=30,
                        help="Look-back window in days (default 30)")
    parser.add_argument("--supabase-url",     default=None)
    parser.add_argument("--supabase-key",     default=None)
    args = parser.parse_args()

    # Resolve credentials
    sb_url = args.supabase_url or os.environ.get("SUPABASE_URL", "")
    sb_key = args.supabase_key or os.environ.get("SUPABASE_ANON_KEY", "")
    if not sb_url or not sb_key:
        print(
            "Error: Supabase URL and key required via --supabase-url/--supabase-key "
            "or SUPABASE_URL/SUPABASE_ANON_KEY env vars.",
            file=sys.stderr
        )
        sys.exit(1)

    # Resolve orientation file path
    orientation_path = args.orientation_file
    if not orientation_path:
        if not args.registry:
            print("Error: --registry required when --orientation-file is omitted.", file=sys.stderr)
            sys.exit(1)
        reg = json.loads(Path(args.registry).read_text(encoding="utf-8"))
        user_entry = next(
            (u for u in reg.get("users", []) if u["user_id"] == args.user_id),
            None
        )
        if not user_entry:
            print(f"Error: user_id {args.user_id} not found in registry.", file=sys.stderr)
            sys.exit(1)
        orientation_path = user_entry["orientation_path"]

    # Compute cutoff date
    est = timezone(timedelta(hours=-5))
    now_est = datetime.now(est)
    cutoff  = (now_est - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%S")
    generated_at = now_est.strftime("%-d %B %Y, %-I:%M %p EST")

    # Fetch events
    print(f"Fetching reading_events for {args.user_id} since {cutoff}...")
    events = supabase_select(sb_url, sb_key, "reading_events", {
        "select":     "piece_slug,piece_type,read_depth_percent,time_on_page_seconds,created_at",
        "user_id":    f"eq.{args.user_id}",
        "created_at": f"gte.{cutoff}",
        "order":      "created_at.desc",
    })
    print(f"  {len(events)} events retrieved.")

    # Build and write calibration block
    text         = load_orientation(orientation_path)
    base_text    = strip_calibration_section(text).rstrip()
    calib_block  = build_calibration_block(args.user_id, events, args.days, generated_at)
    updated_text = base_text + calib_block

    save_orientation(orientation_path, updated_text)
    print(f"✓ Orientation updated: {orientation_path}")


if __name__ == "__main__":
    main()
