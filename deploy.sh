#!/usr/bin/env bash
# Deploy AI_cost_comparison to a remote Docker host over SSH.
#
# Usage:
#   SSH_HOST=user@your.server ./deploy.sh
#   SSH_HOST=my-server ./deploy.sh          # if you have a host alias in ~/.ssh/config
#
# Assumes:
#   - ssh-agent is running (or key is in ~/.ssh/config), so plain `ssh $SSH_HOST` works
#   - The remote .env is already in place on the server (we won't overwrite it)
#   - docker + docker compose are installed on the remote host

set -euo pipefail

SSH_HOST="${SSH_HOST:?Set SSH_HOST=user@host (or a host alias from ~/.ssh/config)}"
REMOTE_DIR="${REMOTE_DIR:-/srv/cost-dashboard}"
APP_PORT="${APP_PORT:-8556}"

echo "→ syncing project to $SSH_HOST:$REMOTE_DIR"
rsync -avz --delete \
  --exclude '.env' \
  --exclude '.env.local' \
  --exclude 'data/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.git/' \
  --exclude '.idea/' \
  --exclude '.vscode/' \
  -e "ssh -o StrictHostKeyChecking=accept-new" \
  ./ "$SSH_HOST:$REMOTE_DIR/"

echo "→ remote: ensuring .env exists"
ssh "$SSH_HOST" "cd '$REMOTE_DIR' && [ -f .env ] || { cp .env.example .env && echo '!! Edit $REMOTE_DIR/.env to set FIRECRAWL_URL then re-run deploy.'; exit 2; }"

echo "→ remote: docker compose build && up -d"
ssh "$SSH_HOST" "cd '$REMOTE_DIR' && docker compose build && docker compose up -d"

echo "→ remote: waiting for healthz"
ssh "$SSH_HOST" "for i in {1..20}; do curl -fsS http://localhost:$APP_PORT/healthz >/dev/null && { echo OK; exit 0; }; sleep 1; done; echo 'healthz did not respond'; docker compose -f $REMOTE_DIR/docker-compose.yml logs --tail=50; exit 1"

echo
echo "✓ deployed. Dashboard: http://${SSH_HOST#*@}:$APP_PORT/"
