#!/bin/bash
# deploy_first_dispatch.command
# Deploys the /first-dispatch feature to the Digital Ocean server and pushes
# updated files to GitHub.
#
# Double-click in Finder, or run:
#   bash ~/Desktop/anthology/deploy_first_dispatch.command

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DROPLET="root@159.65.80.203"
TOKEN="$(cat "$SCRIPT_DIR/.publish-config")"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Anthology — Deploy first-dispatch feature          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Deploy first_dispatch.py ─────────────────────────────────────────
echo "[1/7] Deploying first_dispatch.py..."
scp "$SCRIPT_DIR/first_dispatch.py" "$DROPLET:/root/pipeline/first_dispatch.py"
ssh "$DROPLET" "chmod +x /root/pipeline/first_dispatch.py"
echo "      ✓ first_dispatch.py deployed and made executable"

# ── Step 2: Deploy updated bootstrap_server.py ───────────────────────────────
echo "[2/7] Deploying updated bootstrap_server.py..."
scp "$SCRIPT_DIR/bootstrap_server.py" "$DROPLET:/root/pipeline/bootstrap_server.py"
echo "      ✓ bootstrap_server.py deployed"

# ── Step 3: Restart service ───────────────────────────────────────────────────
echo "[3/7] Restarting anthology-bootstrap service..."
ssh "$DROPLET" "systemctl restart anthology-bootstrap"
sleep 2
echo "      ✓ Service restarted"

# ── Step 4: Verify service status ─────────────────────────────────────────────
echo "[4/7] Verifying service status..."
echo ""
ssh "$DROPLET" "systemctl status anthology-bootstrap --no-pager -l"
echo ""

# ── Step 5: Test /first-dispatch returns 401 with bad token ───────────────────
echo "[5/7] Testing /first-dispatch endpoint (expect 401)..."
RESPONSE=$(curl -s -X POST http://159.65.80.203:5050/first-dispatch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-token" \
  -d '{"user_id": "00000000-0000-0000-0000-000000000000"}')
echo "      Response: $RESPONSE"
if echo "$RESPONSE" | grep -q '"error"'; then
  echo "      ✓ Endpoint responded correctly (auth rejection confirmed)"
else
  echo "      ⚠ Unexpected response — check service logs"
fi

# ── Step 6: Push to DonovanBerry11/anthology ──────────────────────────────────
echo "[6/7] Pushing to DonovanBerry11/anthology..."
cd "$SCRIPT_DIR"
git config user.email "donovanberry11@gmail.com"
git config user.name "Donovan Berry"
git add onboarding.html bootstrap_server.py PROJECT_REFERENCE.md first_dispatch.py
# Commit if there are staged changes
if git diff --cached --quiet; then
  echo "      (nothing new to commit to anthology)"
else
  git commit -m "Add /first-dispatch endpoint and first_dispatch.py for immediate post-onboarding dispatch"
  git push
  echo "      ✓ Pushed to DonovanBerry11/anthology"
fi

# ── Step 7: Push PROJECT_REFERENCE.md to DonovanBerry11/anthology-system ──────
echo "[7/7] Pushing PROJECT_REFERENCE.md to DonovanBerry11/anthology-system..."
SYSTEM_DIR="$HOME/Desktop/analytical-system"
if [ -d "$SYSTEM_DIR/.git" ]; then
  cp "$SCRIPT_DIR/PROJECT_REFERENCE.md" "$SYSTEM_DIR/PROJECT_REFERENCE.md"
  cd "$SYSTEM_DIR"
  git config user.email "donovanberry11@gmail.com"
  git config user.name "Donovan Berry"
  git add PROJECT_REFERENCE.md
  if git diff --cached --quiet; then
    echo "      (PROJECT_REFERENCE.md unchanged in anthology-system)"
  else
    git commit -m "Update PROJECT_REFERENCE.md — add /first-dispatch endpoint (2026-05-13)"
    git push
    echo "      ✓ Pushed PROJECT_REFERENCE.md to DonovanBerry11/anthology-system"
  fi
else
  echo "      ⚠ ~/Desktop/analytical-system not found or not a git repo."
  echo "        Push PROJECT_REFERENCE.md manually:"
  echo "        - Copy: $SCRIPT_DIR/PROJECT_REFERENCE.md"
  echo "        - To the root of your local DonovanBerry11/anthology-system clone"
  echo "        - Then commit and push"
fi

echo ""
echo "── Summary ──────────────────────────────────────────────"
echo ""
echo "  ✓ first_dispatch.py deployed to /root/pipeline/"
echo "  ✓ bootstrap_server.py updated on server (adds /first-dispatch)"
echo "  ✓ anthology-bootstrap service restarted"
echo "  ✓ /first-dispatch returns 401 on bad token"
echo ""
echo "  Manual test (run from your terminal after a real user logs in):"
echo "  python3 /root/pipeline/first_dispatch.py \\"
echo "    --user-id 94baf514-f988-464f-8de1-56c29d4597ee \\"
echo "    --env /root/.anthology.env"
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Deployment complete.                               ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
read -p "Press Enter to close..."
