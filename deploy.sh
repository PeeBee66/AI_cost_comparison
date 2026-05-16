#!/usr/bin/env bash
# Deploy AI_cost_comparison to a remote Docker host over SSH.
#
# Usage:
#   SSH_HOST=user@your.server ./deploy.sh
#   SSH_KEY=~/.ssh/your_key SSH_HOST=user@host REMOTE_DIR=/srv/cost-dashboard ./deploy.sh
#
# Assumes:
#   - You can SSH to $SSH_HOST with $SSH_KEY (or via ssh-agent / ~/.ssh/config alias)
#   - The remote .env is already in place on the server (we won't overwrite it)
#   - docker + docker compose are installed on the remote host

set -euo pipefail

SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
SSH_HOST="${SSH_HOST:?Set SSH_HOST=user@host (or pre-configure as a host alias in ~/.ssh/config)}"
REMOTE_DIR="${REMOTE_DIR:-/srv/cost-dashboard}"
APP_PORT="${APP_PORT:-8556}"

if [ ! -f "$SSH_KEY" ]; then
  echo "✗ SSH key not found at $SSH_KEY"
  echo "  Set SSH_KEY=/path/to/key or rotate the leaked key first."
  exit 1
fi

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
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
  ./ "$SSH_HOST:$REMOTE_DIR/"

echo "→ remote: ensuring .env exists"
ssh -i "$SSH_KEY" "$SSH_HOST" "cd '$REMOTE_DIR' && [ -f .env ] || { cp .env.example .env && echo '!! Edit $REMOTE_DIR/.env to set ANTHROPIC_API_KEY then re-run deploy.'; exit 2; }"

echo "→ remote: docker compose build && up -d"
ssh -i "$SSH_KEY" "$SSH_HOST" "cd '$REMOTE_DIR' && docker compose build && docker compose up -d"

echo "→ remote: waiting for healthz"
ssh -i "$SSH_KEY" "$SSH_HOST" "for i in {1..20}; do curl -fsS http://localhost:$APP_PORT/healthz >/dev/null && { echo OK; exit 0; }; sleep 1; done; echo 'healthz did not respond'; docker compose -f $REMOTE_DIR/docker-compose.yml logs --tail=50; exit 1"

echo
echo "✓ deployed. Dashboard: http://${SSH_HOST#*@}:$APP_PORT/"
