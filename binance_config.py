#!/usr/bin/env python3
"""
Binance API configuration — supports mainnet and testnet.

Set in .env:
  BINANCE_USE_TESTNET=true  # to use testnet
  BINANCE_API_KEY=...       # mainnet key (optional for price feed)
  BINANCE_API_SECRET=...
  BINANCE_TESTNET_API_KEY=...    # testnet key from https://testnet.binance.vision/
  BINANCE_TESTNET_API_SECRET=...

Price feed (ticker/price, klines) works without keys on both networks.
Authenticated endpoints (order placement) require keys.

Toggle testnet: set BINANCE_USE_TESTNET=true and restart services.
"""

import os
import hmac
import hashlib
import time
import requests
from urllib.parse import urlencode
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')
except Exception:
    pass

USE_TESTNET = os.environ.get('BINANCE_USE_TESTNET', '').lower() in ('1', 'true', 'yes', 'on')
USE_LIVE = os.environ.get('BINANCE_USE_LIVE', '').lower() in ('1', 'true', 'yes', 'on')

# Demo Futures keys from https://demo.binance.com — use demo-fapi as testnet when present
USE_DEMO = USE_TESTNET and bool(os.environ.get('BINANCE_DEMO_API_KEY', ''))

# Priority: LIVE (real money) > DEMO (testnet futures) > TESTNET (spot) > mainnet spot (price feed only)
if USE_LIVE:
    BINANCE_API_BASE = 'https://fapi.binance.com/fapi/v1'
elif USE_DEMO:
    BINANCE_API_BASE = 'https://demo-fapi.binance.com/fapi/v1'
elif USE_TESTNET:
    BINANCE_API_BASE = 'https://testnet.binance.vision/api/v3'
else:
    BINANCE_API_BASE = 'https://api.binance.com/api/v3'

BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET', '')
BINANCE_TESTNET_API_KEY = os.environ.get('BINANCE_TESTNET_API_KEY', '')
BINANCE_TESTNET_API_SECRET = os.environ.get('BINANCE_TESTNET_API_SECRET', '')
BINANCE_DEMO_API_KEY = os.environ.get('BINANCE_DEMO_API_KEY', '')
BINANCE_DEMO_API_SECRET = os.environ.get('BINANCE_DEMO_API_SECRET', '')

# Alpha 3 tradable universe — single source of truth
ALPHA3_ASSETS = ['TRIAUSDT', 'QUSDT', 'MAGMAUSDT', 'TRADOORUSDT', 'APRUSDT', 'BTRUSDT']
ALPHA3_GROUP = 'pump'  # user-named universe group, surfaced in /status + dashboards

# Live USDT-M Futures (real money)
BINANCE_LIVE_FAPI_BASE = 'https://fapi.binance.com'
# Demo Futures (https://demo.binance.com) — XRPUSDT futures
BINANCE_DEMO_FAPI_BASE = 'https://demo-fapi.binance.com'
BINANCE_DEMO_DAPI_BASE = 'https://demo-dapi.binance.com'

if USE_LIVE:
    ACTIVE_API_KEY = BINANCE_API_KEY
    ACTIVE_API_SECRET = BINANCE_API_SECRET
elif USE_DEMO:
    ACTIVE_API_KEY = BINANCE_DEMO_API_KEY
    ACTIVE_API_SECRET = BINANCE_DEMO_API_SECRET
elif USE_TESTNET:
    ACTIVE_API_KEY = BINANCE_TESTNET_API_KEY
    ACTIVE_API_SECRET = BINANCE_TESTNET_API_SECRET
else:
    ACTIVE_API_KEY = BINANCE_API_KEY
    ACTIVE_API_SECRET = BINANCE_API_SECRET

def get_api_base():
    return BINANCE_API_BASE

def is_testnet():
    return USE_TESTNET

def get_active_keys():
    return ACTIVE_API_KEY, ACTIVE_API_SECRET

def get_demo_keys():
    return BINANCE_DEMO_API_KEY, BINANCE_DEMO_API_SECRET

def get_demo_fapi_base():
    return BINANCE_DEMO_FAPI_BASE


# ---------------------------------------------------------------------------
# Signature hardening (fixes intermittent -1022 "Signature not valid" on
# demo-fapi). Root cause: signing with the local machine clock + a tight
# recvWindow means any clock drift or API latency pushes the request outside
# Binance's allowed time window. Fix: sync timestamp to Binance *server* time
# and centralize signing so the signed string always equals the sent query.
# ---------------------------------------------------------------------------
_SERVER_TIME_OFFSET_MS = None


def sync_binance_time():
    """Fetch Binance server time once and cache the offset vs local clock."""
    global _SERVER_TIME_OFFSET_MS
    try:
        r = requests.get(f"{BINANCE_DEMO_FAPI_BASE}/fapi/v1/time", timeout=5)
        if r.status_code == 200:
            _SERVER_TIME_OFFSET_MS = int(r.json()["serverTime"]) - int(time.time() * 1000)
            return True
    except Exception:
        pass
    _SERVER_TIME_OFFSET_MS = None
    return False


def server_timestamp():
    """Timestamp synced to Binance server clock (eliminates clock-skew -1022)."""
    if _SERVER_TIME_OFFSET_MS is None:
        sync_binance_time()
    return int(time.time() * 1000) + (_SERVER_TIME_OFFSET_MS or 0)


def sign_query(params, secret=None):
    """Build an HMAC-SHA256 signature over params (incl. synced timestamp).

    Returns a dict ready for requests ``params=``. The signature is excluded
    from the signed payload (Binance ignores it on verification). The secret is
    stripped defensively against trailing whitespace/newlines from .env.
    """
    p = dict(params)
    if not p.get("timestamp"):
        p["timestamp"] = server_timestamp()
    if "recvWindow" not in p:
        p["recvWindow"] = 10000
    # Sign the URL-ENCODED query string — exactly what requests sends on the
    # wire. Manual '&'.join mismatches whenever a value contains characters that
    # requests encodes (e.g. '+' in scientific-notation floats like 5.6e+20),
    # which produced -1022 "Signature not valid".
    qs = urlencode(p)
    sec = (secret if secret is not None else BINANCE_DEMO_API_SECRET or "").strip()
    sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return {**p, "signature": sig}
