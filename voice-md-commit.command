#!/bin/bash
# voice-md-commit.command — COMPLETED, safe to delete
# This script was used to commit voice.md infrastructure changes on 2026-05-16.
# All commits have been pushed. This file can be deleted.
exit 0

echo "=== voice.md infrastructure commit script ==="
echo ""

# ── anthology-system repo ──────────────────────────────────────────────────────
echo "--- anthology-system repo ---"
cd ~/Desktop/analytical-system

rm -f .git/index.lock 2>/dev/null && echo "  Removed stale index.lock" || true

git add users/voice-template.md
git add users/donovan/voice.md
git add scripts/register_new_users.py

echo "  Staged files:"
git diff --cached --name-only

git commit -m "feat: per-user voice.md infrastructure

- Add users/voice-template.md — canonical schema for voice calibration files
- Add users/donovan/voice.md — Donovan's starter voice file, cross-referenced
  from orientation.md and onboarding metadata at initial infrastructure setup
- Update scripts/register_new_users.py — generates starter voice.md for new
  users at registration; backfills voice.md for existing users missing it
- dispatch-agent.skill updated locally (gitignored binary): Pre-Draft voice.md
  read step added (step 3); Round 1 sense-check voice compliance section added
  (section 5); Drafting section voice compliance note added"

git push origin main
echo "  ✓ anthology-system pushed"
echo ""

# ── anthology repo ─────────────────────────────────────────────────────────────
echo "--- anthology repo ---"
cd ~/Desktop/anthology

rm -f .git/index.lock 2>/dev/null && echo "  Removed stale index.lock" || true

git add bootstrap_orientation.py
git add first_dispatch.py

echo "  Staged files:"
git diff --cached --name-only

git commit -m "feat: per-user voice.md infrastructure

- Update bootstrap_orientation.py — generates starter voice.md immediately
  after orientation.md at bootstrap; fields inferred from interests[] and
  additional_info; unknown fields marked unknown
- Update first_dispatch.py — reads users/{user_id}/voice.md before constructing
  system prompts; injects populated voice preferences into topics, dispatch
  draft, and note draft prompts as a voice instruction block"

git push origin main
echo "  ✓ anthology pushed"
echo ""
echo "=== All done. Both repos committed and pushed. ==="
echo "Press Enter to close."
read
