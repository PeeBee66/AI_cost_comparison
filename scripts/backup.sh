#!/usr/bin/env bash
# Snapshot the SQLite DB into data/backups/ with a timestamp.
# Run on the host (outside the container) or via `docker compose exec`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/data/cost_dashboard.db"
DEST_DIR="$ROOT/data/backups"
mkdir -p "$DEST_DIR"

if [ ! -f "$DB" ]; then
  echo "✗ DB not found at $DB"
  exit 1
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$DEST_DIR/cost_dashboard-$TS.db"
cp "$DB" "$DEST"
echo "✓ $DEST"

# Retain last 30 backups
ls -1t "$DEST_DIR"/cost_dashboard-*.db 2>/dev/null | tail -n +31 | xargs -r rm --
