#!/usr/bin/env bash
# setup.sh — Legacy alias. Use deploy.sh for the full automated setup.
# Kept for compatibility; delegates to deploy.sh.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/deploy.sh" "$@"
