#!/usr/bin/env python3
"""
bootstrap_orientation.py — Generates an orientation.md for a new Anthology
user immediately after they complete the onboarding questionnaire.

Called at the end of the onboarding flow (not on a cron schedule).
Designed to complete in under 5 seconds.

Usage:
    python3 ~/Desktop/anthology/bootstrap_orientation.py \\
        --user-id <supabase-uuid> \\
        [--env ~/Desktop/anthology/.env] \\
        [--system-dir ~/Desktop/analytical-system] \\
        [--dry-run]

What it does:
  1. Reads SUPABASE_URL + SUPABASE_SERVICE_KEY from the env file (or environment)
  2. Fetches the single user by UUID via the Supabase admin API
  3. Parses structured user_metadata set by the onboarding questionnaire
  4. Writes orientation.md to {system_dir}/users/{user_id}/orientation.md
  5. Adds the user to registry.json if not already present
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


# ── SSL context ────────────────────────────────────────────────────────────────

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


# ── Credential loading ─────────────────────────────────────────────────────────

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


def resolve_credentials(env_path):
    """
    Load SUPABASE_URL and SUPABASE_SERVICE_KEY.

    Priority:
      1. Values from the --env file
      2. OS environment variables
    Returns (supabase_url, service_key) or exits with an error.
    """
    file_env = load_env(env_path)

    supabase_url = (
        file_env.get("SUPABASE_URL")
        or os.environ.get("SUPABASE_URL", "")
    ).strip()

    service_key = (
        file_env.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY", "")
    ).strip()

    errors = []
    if not supabase_url:
        errors.append("SUPABASE_URL")
    if not service_key:
        errors.append("SUPABASE_SERVICE_KEY")

    if errors:
        sys.exit(
            f"Error: Missing credentials: {', '.join(errors)}\n"
            f"  Set them in the --env file ({env_path}) or as environment variables."
        )

    return supabase_url, service_key


# ── Supabase admin API ─────────────────────────────────────────────────────────

def fetch_user_by_id(supabase_url, service_key, user_id):
    """
    Fetch a single user from the Supabase admin API by UUID.
    Returns the user dict or exits with an error.
    """
    url = f"{supabase_url}/auth/v1/admin/users/{user_id}"
    req = urllib.request.Request(
        url,
        headers={
            "apikey":        service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type":  "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=_SSL, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        sys.exit(f"Supabase API error {e.code} fetching user {user_id}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error fetching user {user_id}: {e.reason}")


# ── Helpers ────────────────────────────────────────────────────────────────────

def display_name_from_email(email):
    """Best-effort display name from the local part of an email address."""
    local = email.split("@")[0]
    return re.sub(r"[._\-]+", " ", local).title()


def today_iso():
    est = timezone(timedelta(hours=-5))
    return datetime.now(est).strftime("%Y-%m-%d")


# ── Orientation file builder ───────────────────────────────────────────────────

def build_orientation(user_id, email, display_name, reading_interests,
                      created_date, today,
                      country_of_residence="", city="",
                      country_of_origin="", interests=None,
                      additional_info=""):
    """
    Generate a starter orientation.md for a new user.

    Prefers the structured onboarding fields (country_of_residence, city,
    country_of_origin, interests[], additional_info) written by the onboarding
    questionnaire. Falls back to the legacy reading_interests free-text field
    for users who registered before the questionnaire was introduced.
    """
    interests = interests or []
    ri = reading_interests.strip() if reading_interests else ""

    has_structured = bool(
        country_of_residence or city or country_of_origin or interests
    )

    # ── Stated Preferences section ─────────────────────────────────────────────
    if has_structured:
        location_parts = []
        if city and country_of_residence:
            location_parts.append(f"{city}, {country_of_residence}")
        elif country_of_residence:
            location_parts.append(country_of_residence)

        location_line  = location_parts[0] if location_parts else "(not stated)"
        origin_line    = country_of_origin if country_of_origin else "(not stated)"
        interests_line = ", ".join(interests) if interests else "(not stated)"
        composite_line = ri if ri else "(not generated)"

        additional_block = ""
        if additional_info:
            additional_block = f"\n**Additional context:** {additional_info}\n"

        stated_prefs_section = f"""\
## Stated Preferences

*Seeded from the onboarding questionnaire completed at account creation. \
Treated as a prior — informative but not fixed. Revealed preference via \
engagement will calibrate over time.*

**Location:** {location_line}
**Origin:** {origin_line}
**Declared interests:** {interests_line}{additional_block}
**Composite reading signal:** {composite_line}

*Domain calibration and format routing will be inferred from these stated \
preferences and will deepen as content is produced and engagement data \
accumulates.*"""

        method_note = (
            "Structured onboarding questionnaire completed at signup. "
            "Location, origin, declared interests, and additional context "
            "populated from user_metadata."
        )
        interests_note = f"Declared interests: {interests_line}"

    elif ri:
        # Legacy path: only reading_interests free-text available
        raw_tokens = re.split(r"[,\n]+", ri)
        tokens = [
            t.strip().strip(".,;")
            for t in raw_tokens
            if t.strip() and len(t.strip()) > 2
        ]
        domains_line = " · ".join(tokens[:12]) if tokens else "(to be inferred)"

        stated_prefs_section = f"""\
## Stated Preferences

*Seeded from the reading_interests field submitted at signup. \
Treated as a prior — informative but not fixed. Revealed preference via \
engagement will calibrate over time.*

> {ri}

**Domains named:** {domains_line}

*Domain calibration and format routing will be inferred from these stated \
preferences and will deepen as content is produced and engagement data \
accumulates.*"""

        method_note = (
            "Cold initialisation from Supabase auth user record. "
            "Reading interests pulled from user_metadata.reading_interests."
        )
        interests_note = f"Reading interests at signup: {ri}"

    else:
        stated_prefs_section = """\
## Stated Preferences

*No interests stated at account creation. Orientation will be populated once \
interests are submitted and engagement data accumulates.*"""

        method_note = (
            "Cold initialisation from Supabase auth user record. "
            "No reading interests or onboarding data found in user_metadata."
        )
        interests_note = "Reading interests at signup: (none stated)"

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
**Method:** {method_note}

**{interests_note}**

**Confidence:** Low — no published archive yet. Analytical profile, domain \
calibration, and format preferences will deepen once content is generated and \
reading events accumulate.

**What to watch for in first engagement data:** Which formats are read in full \
vs bounced; whether stated interests align with actual reading behaviour; any \
domains that consistently draw deep engagement.
"""


# ── Voice file builder ────────────────────────────────────────────────────────

def build_voice_md(user_id, today, interests=None, additional_info="",
                   country_of_residence="", city=""):
    """
    Generate a starter voice.md for a new user following the voice-template.md schema.

    Fields that cannot be inferred from the available onboarding data are marked
    `unknown`. The interests[] array and additional_info field provide the most
    signal — used to infer register and structural preferences conservatively.
    """
    interests = interests or []
    has_interests = bool(interests)
    has_additional = bool(additional_info.strip())

    # Infer register from interests: sports-heavy → add domain exception note
    sports = [i for i in interests if i.lower() in ('sports',)]
    analytical = [i for i in interests if i.lower() in (
        'politics', 'foreign affairs', 'economics', 'finance', 'tech'
    )]

    if analytical:
        register_formality = "formal-analytical"
        register_distance = "neutral-to-distant"
    elif has_interests:
        register_formality = "default"
        register_distance = "default"
    else:
        register_formality = "unknown"
        register_distance = "unknown"

    sports_exception = (
        "Sports content: fan-register warmth, not analytical distance."
        if sports else "unknown"
    )

    # Structural preferences: conservative inferences from interests
    if analytical:
        vocabulary_register = "elevated-technical"
        lead_type = "analytical-observation-first"
    elif has_interests:
        vocabulary_register = "default"
        lead_type = "default"
    else:
        vocabulary_register = "unknown"
        lead_type = "unknown"

    # Additional info may contain voice signals — preserve as a note
    additional_note = ""
    if has_additional:
        additional_note = (
            f"\n*Note from onboarding additional_info field (may contain voice signals):*\n"
            f"> {additional_info.strip()}\n"
        )

    return f"""\
# Voice Calibration — User {user_id[:8]}

*Per-user voice calibration file. Read by the dispatch agent in Pre-Draft and Round 1 sense-check.
Populated fields take precedence over pipeline orientation defaults on register, rhythm, and anti-patterns.
Pipeline orientation takes precedence on structure, attribution, and sourcing.*

---

## Header

```
user_id:        {user_id}
generated_at:   {today}
last_updated:   {today}
data_sources:   [onboarding_metadata]
```

*Generated at bootstrap from onboarding metadata. Fields inferred conservatively from interests[]
and additional_info. Update as reading engagement data accumulates.*
{additional_note}
---

## 1. Register

**State:** `{"populated" if analytical else "unknown"}`

**Formality axis** *(formal-analytical / conversational / direct)*:
> {register_formality}

**Distance-warmth axis** *(distant / neutral / warm)*:
> {register_distance}

**Domain exceptions** *(register that diverges from the default for specific content types)*:
> {sports_exception}

---

## 2. Sentence Rhythm

**State:** `unknown`

**Preferred sentence length** *(short-punchy / varied / long-complex)*:
> unknown

**Tolerance for long constructions** *(low / medium / high)*:
> unknown

**Format-dependent variation** *(does rhythm preference vary by content type?)*:
> unknown

---

## 3. Vocabulary

**State:** `{"populated" if analytical else "unknown"}`

**Preferred diction register** *(plain / elevated / technical)*:
> {vocabulary_register}

**Domain-specific terminology** *(tolerate / require / avoid)*:
> {"require in analytical domains — technical terms expected without hedging" if analytical else "unknown"}

**Explicit aversions** *(known vocabulary to avoid)*:
> unknown

---

## 4. Lead Framing

**State:** `{"populated" if analytical else "unknown"}`

**Preferred lead type** *(news-first / analytical-observation-first / context-first)*:
> {lead_type}

**Explicit opening avoidances**:
> unknown

---

## 5. Structural Preferences

**State:** `unknown`

**Subheadings** *(none / contextual / required)*:
> unknown

**Bullet points and lists** *(none / contextual / preferred)*:
> unknown

**Section breaks** *(sparse / standard / frequent)*:
> unknown

**Format-dependent structural norms**:
> unknown

---

## 6. Endings

**State:** `unknown`

**Preferred closing style** *(abrupt-closed / contextual-close / forward-looking)*:
> unknown

**Explicit closing avoidances**:
> unknown

**What-to-watch convention** *(absent / named-events-only / analytical-forecast)*:
> unknown

---

## 7. Anti-Patterns

**State:** `unknown`

- unknown

---

## 8. Calibration Log

*Append-only. Most recent entry first.*

---

### {today} — Initial generation from onboarding metadata at bootstrap

**Source:** onboarding_metadata
**Fields updated:** register (partial), vocabulary (partial), lead framing (partial) — inferred from interests[]; all other fields marked unknown
**Notes:** Generated by bootstrap_orientation.py immediately after orientation.md was written.
Interests available: {", ".join(interests) if interests else "(none stated)"}. Additional info: {"present" if has_additional else "not provided"}.
Fields marked unknown should be updated as reading engagement accumulates.

---
"""


# ── Registry helpers ───────────────────────────────────────────────────────────

def load_registry(registry_path):
    """Load registry.json, returning a dict. Creates a skeleton if absent."""
    if registry_path.exists():
        return json.loads(registry_path.read_text(encoding="utf-8"))
    return {
        "_comment": (
            "User registry for the Anthology personalised generation pipeline. "
            "Each entry maps a Supabase user_id to the user's orientation file "
            "path and display name."
        ),
        "users": [],
    }


def user_in_registry(registry, user_id):
    return any(u["user_id"] == user_id for u in registry.get("users", []))


def add_to_registry(registry, user_id, display_name, email,
                    orientation_path, today):
    registry.setdefault("users", []).append({
        "user_id":          user_id,
        "display_name":     display_name,
        "email":            email,
        "orientation_path": str(orientation_path),
        "active":           True,
        "onboarded":        today,
    })


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap an orientation.md for a new Anthology user immediately "
            "after they complete the onboarding questionnaire."
        )
    )
    parser.add_argument(
        "--user-id", required=True,
        help="Supabase UUID of the user"
    )
    parser.add_argument(
        "--env",
        default=os.path.expanduser("~/Desktop/anthology/.env"),
        help="Path to credentials file containing SUPABASE_URL and "
             "SUPABASE_SERVICE_KEY. Default: ~/Desktop/anthology/.env"
    )
    parser.add_argument(
        "--system-dir",
        default=os.path.expanduser("~/Desktop/analytical-system"),
        help="Path to the analytical-system directory. "
             "Default: ~/Desktop/analytical-system"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be written without writing any files"
    )
    args = parser.parse_args()

    user_id    = args.user_id.strip()
    system_dir = Path(args.system_dir).expanduser()
    users_dir  = system_dir / "users"
    registry_path = users_dir / "registry.json"

    # ── Credentials ────────────────────────────────────────────────────────────
    supabase_url, service_key = resolve_credentials(
        os.path.expanduser(args.env)
    )

    # ── Fetch user ─────────────────────────────────────────────────────────────
    print(f"Fetching user {user_id} from Supabase…")
    user = fetch_user_by_id(supabase_url, service_key, user_id)

    email        = user.get("email", "")
    created_raw  = user.get("created_at", "")
    created_date = created_raw[:10] if created_raw else today_iso()
    metadata     = user.get("user_metadata") or {}
    display_name = display_name_from_email(email) if email else f"User {user_id[:8]}"

    # Structured fields from onboarding questionnaire
    country_of_residence = metadata.get("country_of_residence", "")
    city                 = metadata.get("city", "")
    country_of_origin    = metadata.get("country_of_origin", "")
    user_interests       = metadata.get("interests") or []
    additional_info      = metadata.get("additional_info", "")
    # Composite string — used by the pipeline keyword-scorer and feed ranking
    reading_interests    = metadata.get("reading_interests", "")

    today = today_iso()

    # ── Report what we found ───────────────────────────────────────────────────
    print(f"  email:       {email or '(none)'}")
    print(f"  display:     {display_name}")
    if user_interests:
        print(f"  interests:   {', '.join(user_interests)}")
    elif reading_interests:
        preview = reading_interests[:80] + ("…" if len(reading_interests) > 80 else "")
        print(f"  interests:   {preview}")
    else:
        print(f"  interests:   (none stated)")
    if country_of_residence:
        loc = f"{city}, {country_of_residence}" if city else country_of_residence
        print(f"  location:    {loc}")
    if country_of_origin:
        print(f"  origin:      {country_of_origin}")

    # ── Paths ──────────────────────────────────────────────────────────────────
    user_dir         = users_dir / user_id
    orientation_path = user_dir / "orientation.md"

    print(f"\n  orientation: {orientation_path}")

    # ── Build orientation content ──────────────────────────────────────────────
    content = build_orientation(
        user_id=user_id,
        email=email,
        display_name=display_name,
        reading_interests=reading_interests,
        created_date=created_date,
        today=today,
        country_of_residence=country_of_residence,
        city=city,
        country_of_origin=country_of_origin,
        interests=user_interests,
        additional_info=additional_info,
    )

    # ── Registry check ─────────────────────────────────────────────────────────
    registry = load_registry(registry_path)
    already_registered = user_in_registry(registry, user_id)

    if already_registered:
        print("  [registry] User already present in registry.json — skipping registry update.")
    else:
        print("  [registry] User not in registry.json — will add entry.")

    # ── Dry-run output ─────────────────────────────────────────────────────────
    if args.dry_run:
        print("\n[dry-run] orientation.md content that would be written:\n")
        print("─" * 60)
        print(content)
        print("─" * 60)
        voice_content = build_voice_md(
            user_id=user_id,
            today=today,
            interests=user_interests,
            additional_info=additional_info,
            country_of_residence=country_of_residence,
            city=city,
        )
        print("\n[dry-run] voice.md content that would be written:\n")
        print("─" * 60)
        print(voice_content[:500] + "…")
        print("─" * 60)
        if not already_registered:
            print("\n[dry-run] registry.json entry that would be added:")
            print(json.dumps({
                "user_id":          user_id,
                "display_name":     display_name,
                "email":            email,
                "orientation_path": str(orientation_path),
                "active":           True,
                "onboarded":        today,
            }, indent=2))
        return

    # ── Write orientation file ─────────────────────────────────────────────────
    user_dir.mkdir(parents=True, exist_ok=True)
    orientation_path.write_text(content, encoding="utf-8")
    print(f"\n✓ orientation.md written → {orientation_path}")

    # ── Write starter voice.md ─────────────────────────────────────────────────
    voice_path = user_dir / "voice.md"
    voice_content = build_voice_md(
        user_id=user_id,
        today=today,
        interests=user_interests,
        additional_info=additional_info,
        country_of_residence=country_of_residence,
        city=city,
    )
    voice_path.write_text(voice_content, encoding="utf-8")
    print(f"✓ voice.md written → {voice_path}")

    # ── Update registry ────────────────────────────────────────────────────────
    if not already_registered:
        add_to_registry(
            registry=registry,
            user_id=user_id,
            display_name=display_name,
            email=email,
            orientation_path=orientation_path,
            today=today,
        )
        registry_path.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"✓ registry.json updated — {display_name} ({user_id}) added")
    else:
        print("✓ registry.json unchanged (user already registered)")


if __name__ == "__main__":
    main()
