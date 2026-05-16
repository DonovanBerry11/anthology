#!/bin/bash
# update-server.sh — Run this once from your Mac terminal.
# Pulls the updated anthology-system onto the Digital Ocean server.
#
# Usage:
#   bash ~/Desktop/anthology/update-server.sh

set -e

echo "→ Connecting to Digital Ocean server..."

ssh root@159.65.80.203 << 'ENDSSH'
set -e

echo "→ Pulling anthology-system..."
cd /root/anthology-system
git pull origin main

echo "→ Re-applying registry path fix..."
sed -i 's|/Users/donovanberry/Desktop/analytical-system/|/root/anthology-system/|g' \
  /root/anthology-system/users/registry.json

echo ""
echo "✓ Done. register_new_users.py updated on server."
echo "  New users who complete the onboarding questionnaire will now get"
echo "  fully structured orientation files from the 4:38 AM cron run."
ENDSSH
