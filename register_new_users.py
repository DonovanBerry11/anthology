#!/usr/bin/env python3
"""
register_new_users.py — Syncs confirmed Supabase auth users to the local
user registry and orientation file system.

Run this before each pipeline cycle to onboard any users who have signed up
and confirmed their email since the last run.

Usage:
    python3 ~/Desktop/anthology/register_new_users.py \
        --registry ~/Desktop/analytical-system/users/registry.json \
        --users-dir ~/Desktop/analytical-system/users \
        [--env ~/Desktop/analytical-system/.env] \
        [--dry-run]

What it does:
  1. Reads all confirmed users from the Supabase admin API
  2. Compares against registry.json
  3. For each confirmed user not already in the registry:
     a. Derives a username slug from their email
     b. Creates analytical-system/users/{slug}/ directory
     c. Writes a starter orientation.md populated from reading_interests
     d. Appends the entry to registry.json
  4. Reports what was created

Credentials: reads SUPABASE_KEY (service role key) from the --env file.
Falls back to a .supabase-config file in the same directory as this script.
"""

import argparse
import json
import os
import re
import ssl
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path


SUPABASE_URL = "https://uzjkepauhgbuunvcokru.supabase.co"


# ── SSL context ────────────────────────────────────────────────────────────

def _ssl_context():
    """Build an SSL context compatible with macOS python.org installs."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    mac_ca = "/etc/ssl/cert.pem"
    if os.path.exists(mac_ca):
        return ssl.create_default_context(cafile=mac_ca)
    return ssl.create_default_context()


_SSL = _ssl_context()


# ── Credential loading ─────────────────────────────────────────────────────

def load_env(env_path):
    """Parse a simple KEY=VALUE .env file. Returns a dict."""
    env = {}
    try:
        for line in Path(env_path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


def resolve_secret_key(env_path):
    """Load service role key from .env file, then .supabase-config fallback."""
    env = load_env(env_path)
    key = env.get("SUPABASE_KEY", "").strip()
    if key:
        return key
    # Fallback: .supabase-config in same directory as this script
    config_path = Path(__file__).parent / ".supabase-config"
    if config_path.exists():
        key = config_path.read_text(encoding="utf-8").strip()
        if key:
            return key
    return None


# ── Supabase admin API ─────────────────────────────────────────────────────

def fetch_admin(path, secret_key):
    url = f"{SUPABASE_URL}{path}"
    req = urllib.request.Request(url, headers={
        "apikey":        secret_key,
        "Authorization": f"Bearer {secret_key}",
        "Content-Type":  "application/json",
    })
    try:
        with urllib.request.urlopen(req, context=_SSL, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        sys.exit(f"Supabase API error {e.code}: {body}")


def fetch_all_users(secret_key):
    data = fetch_admin("/auth/v1/admin/users?per_page=1000", secret_key)
    return data.get("users", data) if isinstance(data, dict) else data


# ── Slug + name helpers ────────────────────────────────────────────────────

def email_to_slug(email, existing_slugs):
    """Derive a filesystem-safe slug from an email address, deduplicating."""
    local = email.split("@")[0].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", local).strip("-")
    if slug not in existing_slugs:
        return slug
    i = 2
    while f"{slug}-{i}" in existing_slugs:
        i += 1
    return f"{slug}-{i}"


def display_name_from_email(email):
    """Best-effort display name from the local part of an email address."""
    local = email.split("@")[0]
    return re.sub(r"[._\-]+", " ", local).title()


# ── Date helpers ───────────────────────────────────────────────────────────

def today_iso():
    est = timezone(timedelta(hours=-5))
    return datetime.now(est).strftime("%Y-%m-%d")


# ── Orientation file builder ───────────────────────────────────────────────

def build_orientation(user_id, email, display_name, reading_interests,
                      created_date, today):
    """
    Generate a starter orientation.md for a new user.
    Populated from reading_interests where available; otherwise leaves
    the analytical sections as stubs to be filled by the pipeline.
    """
    interests = reading_interests.strip() if reading_interests else ""

    if interests:
        # Naive domain extraction: split on commas/newlines, clean up tokens
        raw_tokens = re.split(r"[,\n]+", interests)
        tokens = [t.strip().strip(".,;")
                  for t in raw_tokens
                  if t.strip() and len(t.strip()) > 2]
        domains_line = " · ".join(tokens[:12]) if tokens else "(to be inferred)"
        stated_prefs_section = f"""\
## Stated Preferences

*Seeded directly from the reading_interests field submitted at signup. \
Treated as a prior — informative but not fixed. Revealed preference via \
engagement will calibrate over time.*

> {interests}

**Domains named:** {domains_line}

*Domain calibration and format routing will be inferred from these stated \
preferences and will deepen as content is produced and engagement data \
accumulates.*"""
    else:
        stated_prefs_section = """\
## Stated Preferences

*No interests stated at account creation. User has not yet completed the \
interests form. Orientation will be populated once interests are submitted \
and engagement data accumulates.*"""

    return f"""\
# User Orientation — {display_name}

*Personal orientation file for content production and delivery. Upstream of \
all format orientations, queues, and dispatch routing. Updated as engagement \
data accumulates and preferences clarify.*

**User ID:** {user_id}
**Email:** {email}
**Account created:** {created_date}
**Orientation initialised:** {today}
**Last updated:** {today}

---

{stated_prefs_section}

---

## Analytical Profile

*Not yet established. Will be inferred from engagement data as content is \
produced and read. This section populates once a reading history accumulates \
and signals a consistent analytical disposition.*

---

## Domain Calibration

*Not yet established. Routing guidance for content production will be inferred \
from stated preferences and confirmed by engagement signals. Will be filled in \
after the first content generation cycle.*

---

## Format and Depth Preferences

*Not yet established. To be determined from engagement signals — which formats \
are read in full, which are bounced, and how time on page varies across types.*

---

## Engagement History

*No engagement tracking recorded yet. This section populates as reading_events \
accumulate via the tracking beacon embedded in generated content pages.*

| Date | Piece | Format | Signal |
|---|---|---|---|
| — | — | — | — |

---

## Calibration Notes

### Entry 1 — Initialisation
**Date:** {today}
**Method:** Cold initialisation from Supabase auth user record. Reading \
interests pulled from user_metadata.reading_interests at time of registration.

**Reading interests at signup:** {interests if interests else "(none stated)"}

**Confidence:** Low — no published archive yet. Analytical profile, domain \
calibration, and format preferences will deepen once content is generated and \
reading events accumulate.

**What to watch for in first engagement data:** Which formats are read in full \
vs bounced; whether stated interests align with actual reading behaviour; any \
domains that consistently draw deep engagement.
"""


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Register new Supabase users into the Anthology analytical-system "
            "by creating orientation files and adding registry entries."
        )
    )
    parser.add_argument(
        "--registry", required=True,
        help="Path to analytical-system/users/registry.json"
    )
    parser.add_argument(
        "--users-dir", required=True,
        help="Path to analytical-system/users/ directory"
    )
    parser.add_argument(
        "--env",
        default=os.path.expanduser("~/Desktop/analytical-system/.env"),
        help="Path to .env file containing SUPABASE_KEY (service role key). "
             "Default: ~/Desktop/analytical-system/.env"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would happen without writing any files"
    )
    args = parser.parse_args()

    # ── Credentials ────────────────────────────────────────────────────────
    secret_key = resolve_secret_key(args.env)
    if not secret_key:
        sys.exit(
            "Error: No Supabase service role key found.\n"
            "  Set SUPABASE_KEY in the .env file at --env, "
            "or create a .supabase-config file next to this script."
        )

    # ── Load registry ──────────────────────────────────────────────────────
    registry_path = Path(args.registry)
    if not registry_path.exists():
        sys.exit(f"Error: registry.json not found at {registry_path}")

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    existing_ids   = {u["user_id"] for u in registry.get("users", [])}
    existing_slugs = {
        Path(u["orientation_path"]).parent.name
        for u in registry.get("users", [])
        if u.get("orientation_path")
    }
    users_dir = Path(args.users_dir)

    # ── Fetch Supabase users ────────────────────────────────────────────────
    print("Fetching users from Supabase…")
    all_users = fetch_all_users(secret_key)

    # Only process users who have confirmed their email
    confirmed = [
        u for u in all_users
        if u.get("email_confirmed_at") or u.get("confirmed_at")
    ]
    print(f"  {len(all_users)} total, {len(confirmed)} confirmed")

    today = today_iso()
    new_count = 0

    for user in confirmed:
        uid = user.get("id", "")
        if uid in existing_ids:
            continue  # Already registered

        email          = user.get("email", "")
        created_raw    = user.get("created_at", today)
        created_date   = created_raw[:10] if created_raw else today
        metadata       = user.get("user_metadata") or {}
        interests      = metadata.get("reading_interests", "")
        display_name   = display_name_from_email(email)

        slug             = email_to_slug(email, existing_slugs)
        existing_slugs.add(slug)
        orientation_path = users_dir / slug / "orientation.md"

        print(f"\n  New user: {email}")
        print(f"    user_id:     {uid}")
        print(f"    slug:        {slug}")
        print(f"    orientation: {orientation_path}")
        if interests:
            preview = interests[:80] + ("…" if len(interests) > 80 else "")
            print(f"    interests:   {preview}")
        else:
            print(f"    interests:   (none stated)")

        if args.dry_run:
            print("    [dry-run] Would create directory + orientation.md and update registry.json")
            new_count += 1
            continue

        # Write orientation file
        orientation_path.parent.mkdir(parents=True, exist_ok=True)
        content = build_orientation(
            user_id=uid,
            email=email,
            display_name=display_name,
            reading_interests=interests,
            created_date=created_date,
            today=today,
        )
        orientation_path.write_text(content, encoding="utf-8")
        print(f"    ✓ orientation.md written")

        # Append to registry
        registry.setdefault("users", []).append({
            "user_id":          uid,
            "display_name":     display_name,
            "email":            email,
            "orientation_path": str(orientation_path),
            "active":           True,
            "onboarded":        today,
        })
        existing_ids.add(uid)
        new_count += 1

    # ── Write updated registry ─────────────────────────────────────────────
    if not args.dry_run:
        if new_count > 0:
            registry_path.write_text(
                json.dumps(registry, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            print(f"\n✓ registry.json updated — {new_count} new user(s) added")
        else:
            print("\nNo new users to register.")
    else:
        if new_count > 0:
            print(f"\n[dry-run] {new_count} user(s) would be registered.")
        else:
            print("\nNo new users to register.")


if __name__ == "__main__":
    main()
