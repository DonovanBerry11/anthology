#!/bin/bash
# deploy_bootstrap.command
# Double-click in Finder to deploy the Anthology Bootstrap API to the droplet.
# Requires SSH access to root@159.65.80.203 (uses your existing SSH key).

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DROPLET="root@159.65.80.203"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Anthology Bootstrap Server — Deployment Script     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Install Flask dependencies ────────────────────────────────────────
echo "[1/5] Installing flask and flask-cors into venv..."
ssh "$DROPLET" "/root/anthology-env/bin/pip install flask flask-cors --quiet"
echo "      ✓ Flask installed"

# ── Step 2: Deploy bootstrap_server.py ────────────────────────────────────────
echo "[2/5] Deploying bootstrap_server.py..."
ssh "$DROPLET" "mkdir -p /root/pipeline"
scp "$SCRIPT_DIR/bootstrap_server.py" "$DROPLET:/root/pipeline/bootstrap_server.py"
echo "      ✓ bootstrap_server.py deployed"

# ── Step 3: Deploy systemd service ────────────────────────────────────────────
echo "[3/5] Deploying systemd service file..."
scp "$SCRIPT_DIR/anthology-bootstrap.service" "$DROPLET:/etc/systemd/system/anthology-bootstrap.service"
echo "      ✓ anthology-bootstrap.service deployed"

# ── Step 4: Ensure log directory exists ───────────────────────────────────────
echo "[4/5] Ensuring log directory exists..."
ssh "$DROPLET" "mkdir -p /root/anthology-system/logs"
echo "      ✓ Log directory ready"

# ── Step 5: Enable and start service ──────────────────────────────────────────
echo "[5/5] Enabling and starting anthology-bootstrap service..."
ssh "$DROPLET" "systemctl daemon-reload && systemctl enable anthology-bootstrap && systemctl restart anthology-bootstrap"
echo "      ✓ Service started"

echo ""
echo "── Verification ─────────────────────────────────────────"
echo "Service status:"
ssh "$DROPLET" "systemctl status anthology-bootstrap --no-pager -l"
echo ""
echo "Health check (port 5050):"
ssh "$DROPLET" "curl -s http://localhost:5050/health || echo 'Health check failed (server may still be starting)'"
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Deployment complete.                               ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
read -p "Press Enter to close..."
