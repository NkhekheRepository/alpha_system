#!/usr/bin/env bash
# setup.sh — Clone-ready setup for the Alpha trading system
# Run AFTER git clone, BEFORE running any scripts.
set -e

echo "=== Alpha System Setup ==="

# 1. Python version check
PYVER=$(python3 -c 'import sys; print(sys.version_info)' 2>/dev/null | grep -o "[0-9]* [0-9]*")
PYMAJ=$(echo $PYVER | awk '{print $1}')
PYMIN=$(echo $PYVER | awk '{print $2}')
if [ "$PYMAJ" -lt 3 ] || ([ "$PYMAJ" -eq 3 ] && [ "$PYMIN" -lt 14 ]); then
    echo "ERROR: Python 3.14+ required. Found $PYMAJ.$PYMIN"
    exit 1
fi
echo "Python: $PYMAJ.$PYMIN"

# 2. Install dependencies
echo "Installing Python dependencies..."
pip install -q numpy pandas requests pyarrow scipy

# 3. Ensure nkkelhe_quant_core is available
if [ ! -d "/home/nkhekhe/nkhekhe_quant_core" ]; then
    echo "WARNING: nkkelhe_quant_core not found at /home/nkhekhe/nkhekhe_quant_core"
    echo "  Either:"
    echo "    a) Clone it: git clone <repo> /home/nkhekhe/nkhekhe_quant_core"
    echo "    b) Install via pip: pip install nkkelhe_quant_core"
    echo "    c) Set PYTHONPATH: export PYTHONPATH=/path/to/nkkelhe_quant_core:\$PYTHONPATH"
    exit 1
fi
echo "nkkelhe_quant_core: OK"

# 4. Download market data
echo "Downloading 5m klines (BTC/ETH, 2024-01-01 -> now)..."
python3 download_5m.py || echo "WARNING: 5m download failed; check Binance API access"

echo "Downloading 1m klines (BTC/ETH, 2026-01-01 -> now)..."
python3 download_1m.py || echo "WARNING: 1m download failed; check Binance API access"

# 5. Create symlink for user_data if it doesn't exist inside repo
if [ ! -d "user_data" ] && [ -d "/home/nkhekhe/user_data" ]; then
    echo "Linking /home/nkhekhe/user_data -> ./user_data"
    ln -s /home/nkhekhe/user_data user_data
fi

# 6. Telegram env vars
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "WARNING: TELEGRAM_BOT_TOKEN not set (needed for live trade alerts)"
    echo "  Set in .env or export in environment"
fi

# 7. Verify
echo ""
echo "=== Setup Complete ==="
echo "Run: python3 dry_runner.py --status"
echo "Run: python3 bidir_runner.py --status"
echo "Run: python3 backtest_alpha2.py"
