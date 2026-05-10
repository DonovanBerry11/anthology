#!/usr/bin/env python3
"""
fetch_user_data.py — Anthology Supabase user data utility

Fetches user records from Supabase using the secret key (service role access).
Used by agentic workflows to read user_metadata (reading_interests, etc.)
and to enumerate users for orientation file population and updates.

Usage:
  # Fetch all users (summary)
  python3 fetch_user_data.py --all

  # Fetch a specific user by email
  python3 fetch_user_data.py --email user@example.com

  # Fetch a specific user by Supabase user ID
  python3 fetch_user_data.py --id <uuid>

  # Output just the reading_interests field for a user
  python3 fetch_user_data.py --email user@example.com --field reading_interests

  # Specify a custom config file (default: .supabase-config in same dir as this script)
  python3 fetch_user_data.py --email user@example.com --config /path/to/.supabase-config
"""

import argparse
import json
import os
import ssl
import sys
import urllib.request
import urllib.error

SUPABASE_URL = "https://uzjkepauhgbuunvcokru.supabase.co"


def _ssl_context():
    """
    Build an SSL context that works on macOS python.org installs,
    which don't wire up the system CA bundle by default.
    Tries certifi first (best), then system certs, then falls back
    to the default context (which may work on some setups).
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    # macOS system CA bundle fallback
    mac_ca = "/etc/ssl/cert.pem"
    if os.path.exists(mac_ca):
        return ssl.create_default_context(cafile=mac_ca)
    return ssl.create_default_context()


_SSL_CONTEXT = _ssl_context()


def load_secret_key(config_path):
    with open(config_path, "r") as f:
        key = f.read().strip()
    if not key:
        sys.exit("Error: .supabase-config is empty.")
    return key


def supabase_request(path, secret_key):
    url = f"{SUPABASE_URL}{path}"
    req = urllib.request.Request(url, headers={
        "apikey": secret_key,
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, context=_SSL_CONTEXT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        sys.exit(f"Supabase API error {e.code}: {body}")


def fetch_all_users(secret_key):
    data = supabase_request("/auth/v1/admin/users?per_page=1000", secret_key)
    return data.get("users", data) if isinstance(data, dict) else data


def fetch_user_by_email(secret_key, email):
    users = fetch_all_users(secret_key)
    for u in users:
        if u.get("email", "").lower() == email.lower():
            return u
    return None


def fetch_user_by_id(secret_key, user_id):
    return supabase_request(f"/auth/v1/admin/users/{user_id}", secret_key)


def format_user_summary(user):
    uid = user.get("id", "—")
    email = user.get("email", "—")
    created = user.get("created_at", "—")
    confirmed = user.get("email_confirmed_at") or user.get("confirmed_at") or "unconfirmed"
    metadata = user.get("user_metadata", {})
    interests = metadata.get("reading_interests", "").strip()
    lines = [
        f"id:               {uid}",
        f"email:            {email}",
        f"created_at:       {created}",
        f"email_confirmed:  {confirmed}",
        f"reading_interests:",
    ]
    if interests:
        for line in interests.splitlines():
            lines.append(f"  {line}")
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Fetch Anthology user data from Supabase.")
    parser.add_argument("--all", action="store_true", help="List all users (summary)")
    parser.add_argument("--email", help="Fetch user by email address")
    parser.add_argument("--id", help="Fetch user by Supabase UUID")
    parser.add_argument("--field", help="Output a single user_metadata field value")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), ".supabase-config"),
        help="Path to .supabase-config (default: same dir as script)",
    )
    args = parser.parse_args()

    secret_key = load_secret_key(args.config)

    if args.all:
        users = fetch_all_users(secret_key)
        if args.json:
            print(json.dumps(users, indent=2))
        else:
            print(f"{len(users)} user(s) found:\n")
            for u in users:
                print(format_user_summary(u))
                print()
        return

    if args.email:
        user = fetch_user_by_email(secret_key, args.email)
        if not user:
            sys.exit(f"No user found with email: {args.email}")
    elif args.id:
        user = fetch_user_by_id(secret_key, args.id)
    else:
        parser.print_help()
        sys.exit(1)

    if args.field:
        value = user.get("user_metadata", {}).get(args.field, "")
        print(value)
        return

    if args.json:
        print(json.dumps(user, indent=2))
    else:
        print(format_user_summary(user))


if __name__ == "__main__":
    main()
