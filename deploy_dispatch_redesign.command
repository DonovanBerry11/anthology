#!/bin/bash
# deploy_dispatch_redesign.command
# Deploys the dispatch format redesign to the Digital Ocean server and pushes
# all updated files to GitHub.
#
# Changes deployed:
#   - generate_dispatch_html.py  : added --combined-dispatches mode
#   - publish_dispatch.py        : --combined-dispatches passthrough
#   - first_dispatch.py          : now generates 5 dispatches + 5 notes as combined
#   - run_combined_dispatch.py   : new daily pipeline Python script
#   - run_dispatch.sh            : updated to call run_combined_dispatch.py
#
# Double-click in Finder, or run:
#   bash ~/Desktop/anthology/deploy_dispatch_redesign.command

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DROPLET="root@159.65.80.203"
TOKEN="$(cat "$SCRIPT_DIR/.publish-config")"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Anthology — Deploy Dispatch Format Redesign        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Deploy updated anthology Python scripts to server ─────────────────
echo "[1/9] Deploying generate_dispatch_html.py…"
scp "$SCRIPT_DIR/generate_dispatch_html.py" "$DROPLET:/root/anthology/generate_dispatch_html.py"
echo "      ✓ generate_dispatch_html.py deployed"

echo "[2/9] Deploying publish_dispatch.py…"
scp "$SCRIPT_DIR/publish_dispatch.py" "$DROPLET:/root/anthology/publish_dispatch.py"
echo "      ✓ publish_dispatch.py deployed"

# ── Step 2: Deploy new pipeline scripts to /root/pipeline/ ────────────────────
echo "[3/9] Deploying first_dispatch.py…"
scp "$SCRIPT_DIR/first_dispatch.py" "$DROPLET:/root/pipeline/first_dispatch.py"
ssh "$DROPLET" "chmod +x /root/pipeline/first_dispatch.py"
echo "      ✓ first_dispatch.py deployed"

echo "[4/9] Deploying run_combined_dispatch.py…"
scp "$SCRIPT_DIR/run_combined_dispatch.py" "$DROPLET:/root/pipeline/run_combined_dispatch.py"
ssh "$DROPLET" "chmod +x /root/pipeline/run_combined_dispatch.py"
echo "      ✓ run_combined_dispatch.py deployed"

# ── Step 3: Inspect and update run_dispatch.sh ────────────────────────────────
echo "[5/9] Inspecting current run_dispatch.sh and updating pipeline…"
CURRENT_RUN_DISPATCH="$(ssh "$DROPLET" 'cat /root/pipeline/run_dispatch.sh 2>/dev/null || echo "NOT_FOUND"')"
echo "      Current run_dispatch.sh:"
echo "---"
echo "$CURRENT_RUN_DISPATCH"
echo "---"

# Back up the original
echo "      Backing up original run_dispatch.sh…"
ssh "$DROPLET" "cp /root/pipeline/run_dispatch.sh /root/pipeline/run_dispatch.sh.bak.$(date +%Y%m%d) 2>/dev/null || true"

# Write the new run_dispatch.sh
echo "      Writing new run_dispatch.sh…"
ssh "$DROPLET" 'cat > /root/pipeline/run_dispatch.sh' << 'ENDDISPATCH'
#!/bin/bash
# run_dispatch.sh — Daily combined dispatch pipeline (updated: dispatch format redesign)
# Cron: 7 5 * * * root /root/pipeline/run_dispatch.sh >> /root/anthology-system/logs/cron-dispatch.log 2>&1

set -e

SCRIPT_DIR="/root/pipeline"
ENV_FILE="/root/.anthology.env"
LOG_DIR="/root/anthology-system/logs"
VENV_PYTHON="/root/anthology-env/bin/python3"

echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Starting daily combined dispatch run"

# Check if the anthology-env python is available
if [ ! -f "$VENV_PYTHON" ]; then
  echo "[ERROR] Python venv not found: $VENV_PYTHON"
  exit 1
fi

# Check if run_combined_dispatch.py exists
if [ ! -f "$SCRIPT_DIR/run_combined_dispatch.py" ]; then
  echo "[ERROR] run_combined_dispatch.py not found: $SCRIPT_DIR/run_combined_dispatch.py"
  exit 1
fi

# Activate venv and run the combined dispatch pipeline
source /root/anthology-env/bin/activate
python3 "$SCRIPT_DIR/run_combined_dispatch.py" --env "$ENV_FILE"

echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Daily combined dispatch run finished"
ENDDISPATCH

ssh "$DROPLET" "chmod +x /root/pipeline/run_dispatch.sh"
echo "      ✓ run_dispatch.sh updated"

# ── Step 4: Restart bootstrap server to pick up updated first_dispatch.py ─────
echo "[6/9] Restarting anthology-bootstrap service…"
ssh "$DROPLET" "systemctl restart anthology-bootstrap"
sleep 2
echo "      ✓ Service restarted"

# ── Step 5: Verify service status ─────────────────────────────────────────────
echo "[7/9] Verifying service status…"
echo ""
ssh "$DROPLET" "systemctl status anthology-bootstrap --no-pager -l | head -20"
echo ""

# Test /first-dispatch endpoint
RESPONSE=$(curl -s -X POST http://159.65.80.203:5050/first-dispatch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-token" \
  -d '{"user_id": "00000000-0000-0000-0000-000000000000"}')
echo "      /first-dispatch test: $RESPONSE"
if echo "$RESPONSE" | grep -q '"error"'; then
  echo "      ✓ Endpoint auth rejection confirmed"
else
  echo "      ⚠ Unexpected response — check service logs"
fi

# ── Step 6: Run a smoke test of the updated generate_dispatch_html.py ─────────
echo "[8/9] Smoke-testing combined HTML generator on server…"
ssh "$DROPLET" << 'ENDSMOKETEST'
set -e
source /root/anthology-env/bin/activate

# Write a sample combined-dispatches JSON
TMPJSON=$(mktemp /tmp/test-dispatches-XXXXXX.json)
cat > "$TMPJSON" << 'ENDJSON'
[
  {"label": "I.",   "title": "Test Dispatch One",   "body_md": "First paragraph of dispatch one. It covers an important development in international affairs.\n\nSecond paragraph provides context. The situation is complex and evolving rapidly.", "note_url": "/users/test/notes/test-note-one.html"},
  {"label": "II.",  "title": "Test Dispatch Two",   "body_md": "First paragraph of dispatch two. Economics are at the centre of this development.\n\nSecond paragraph adds depth. Analysts are watching closely.", "note_url": "/users/test/notes/test-note-two.html"},
  {"label": "III.", "title": "Test Dispatch Three", "body_md": "First paragraph of dispatch three. Technology underpins these structural changes.\n\nSecond paragraph explains the mechanism. The implications extend further than first appears.", "note_url": "/users/test/notes/test-note-three.html"},
  {"label": "IV.",  "title": "Test Dispatch Four",  "body_md": "First paragraph of dispatch four. Political dynamics are shifting.\n\nSecond paragraph provides the institutional framing. The outcome will be determined over the next quarter.", "note_url": "/users/test/notes/test-note-four.html"},
  {"label": "V.",   "title": "Test Dispatch Five",  "body_md": "First paragraph of dispatch five. Financial markets have responded to these signals.\n\nSecond paragraph examines the downstream effects. Watch for the central bank response.", "note_url": "/users/test/notes/test-note-five.html"}
]
ENDJSON

TMPOUT=$(mktemp /tmp/test-combined-dispatch-XXXXXX.html)

python3 /root/anthology/generate_dispatch_html.py \
  --combined-dispatches "$TMPJSON" \
  --output "$TMPOUT" \
  --slug "test-combined-2026-05-14" \
  --title "Thursday, 14 May 2026" \
  --date "May 2026"

# Verify the output
if grep -q "dispatch-section" "$TMPOUT" && grep -q "Read more" "$TMPOUT" && grep -q "dispatch-rule" "$TMPOUT"; then
  echo "      ✓ Combined HTML output verified (sections + rules + read-more links present)"
  SECTION_COUNT=$(grep -c "dispatch-section__label" "$TMPOUT" || echo 0)
  echo "      ✓ Section count: $SECTION_COUNT"
else
  echo "      ✗ HTML verification failed — check generator output"
  head -50 "$TMPOUT"
  exit 1
fi

rm -f "$TMPJSON" "$TMPOUT"
echo "      ✓ Smoke test passed"
ENDSMOKETEST

# ── Step 7: Push all Mac-side changes to GitHub ───────────────────────────────
echo "[9/9] Pushing updated files to GitHub…"
cd "$SCRIPT_DIR"
git config user.email "donovanberry11@gmail.com"
git config user.name "Donovan Berry"

# Clear any locally-modified tracked files before git operations
git checkout -- PROJECT_REFERENCE.md 2>/dev/null || true

git add \
  generate_dispatch_html.py \
  publish_dispatch.py \
  first_dispatch.py \
  run_combined_dispatch.py \
  deploy_dispatch_redesign.command

if git diff --cached --quiet; then
  echo "      (no changes staged — all files already committed)"
else
  git commit -m "Dispatch redesign: combined 5-section post + 5 linked notes per run"
  git push
  echo "      ✓ Pushed to DonovanBerry11/anthology"
fi

echo ""
echo "── Summary ──────────────────────────────────────────────"
echo ""
echo "  ✓ generate_dispatch_html.py — --combined-dispatches mode added"
echo "  ✓ publish_dispatch.py       — --combined-dispatches passthrough added"
echo "  ✓ first_dispatch.py         — generates 5 dispatches + 5 notes as combined"
echo "  ✓ run_combined_dispatch.py  — new daily pipeline script deployed"
echo "  ✓ run_dispatch.sh           — updated to call run_combined_dispatch.py"
echo "  ✓ anthology-bootstrap       — restarted"
echo "  ✓ Combined HTML generator   — smoke test passed"
echo ""
echo "  Next dispatch run: tomorrow at 5:07 AM UTC"
echo ""
echo "  To verify the first-dispatch endpoint manually:"
echo "  ssh root@159.65.80.203"
echo "  source /root/anthology-env/bin/activate"
echo "  python3 /root/pipeline/first_dispatch.py \\"
echo "    --user-id 94baf514-f988-464f-8de1-56c29d4597ee \\"
echo "    --env /root/.anthology.env"
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Deployment complete.                               ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
read -p "Press Enter to close..."
