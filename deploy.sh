#!/usr/bin/env bash
# deploy.sh — One-command setup for the Alpha 3 Dry Mode system on a fresh server.
# Usage:  ./deploy.sh
# After running, edit .env with your keys, then start the services (last step prints how).
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "=================================================="
echo "  ALPHA 3 DRY MODE — DEPLOY"
echo "=================================================="

# 1. Python version
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYMAJ=$(echo $PYVER | cut -d. -f1); PYMIN=$(echo $PYVER | cut -d. -f2)
if [ "$PYMAJ" -lt 3 ] || ([ "$PYMAJ" -eq 3 ] && [ "$PYMIN" -lt 11 ]); then
    echo "ERROR: Python 3.11+ required (found $PYVER)."
    exit 1
fi
echo "[1/6] Python $PYVER OK"

# 2. Install dependencies
echo "[2/6] Installing Python dependencies..."
pip install -q -r requirements.txt
echo "      dependencies installed"

# 3. Create data directory + .env if missing
mkdir -p dry_data
if [ ! -f .env ]; then
    cp .env.template .env
    echo "[3/6] .env created from template — FILL IN YOUR KEYS before starting services"
else
    echo "[3/6] .env already exists — keeping it"
fi

# 4. Systemd user units
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
for svc in alpha3-dry-runner.service alpha3-tg-bot.service; do
    cp "systemd/$svc" "$UNIT_DIR/$svc"
    # Rewrite WorkingDirectory / ExecStart paths to this repo location
    sed -i "s#/home/nkhekhe/alpha_system#$REPO_DIR#g" "$UNIT_DIR/$svc"
done
echo "[4/6] Systemd user units installed to $UNIT_DIR"

# 5. Verify frozen model present
if [ -f models/meta_labeler.joblib ]; then
    echo "[5/6] Meta-labeler model present (models/meta_labeler.joblib)"
else
    echo "[5/6] WARNING: models/meta_labeler.joblib MISSING — runner will run WITHOUT filter."
    echo "      To (re)train: python3 scripts/fetch_historical_klines.py && \\"
    echo "                    python3 scripts/generate_labels.py && \\"
    echo "                    python3 scripts/engineer_features.py && \\"
    echo "                    python3 scripts/train_meta_labeler.py"
fi

# 6. Reload systemd
systemctl --user daemon-reload
echo "[6/6] systemd daemon-reloaded"

echo ""
echo "=================================================="
echo "  DEPLOY COMPLETE"
echo "=================================================="
echo ""
echo "NEXT STEPS:"
echo "  1. Edit .env and fill in your keys:"
echo "       nano $REPO_DIR/.env"
echo ""
echo "  2. Start the services:"
echo "       systemctl --user enable --now alpha3-dry-runner.service"
echo "       systemctl --user enable --now alpha3-tg-bot.service"
echo ""
echo "  3. Watch logs:"
echo "       journalctl --user -u alpha3-dry-runner.service -f"
echo ""
echo "  4. Check status:"
echo "       python3 alpha3_dry_runner.py --status"
echo ""
echo "  (To run WITHOUT systemd: python3 alpha3_dry_runner.py --stake 0.075 --leverage 50)"
