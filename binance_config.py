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
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv('/home/nkhekhe/alpha_system/.env')
except Exception:
    pass

USE_TESTNET = os.environ.get('BINANCE_USE_TESTNET', '').lower() in ('1', 'true', 'yes', 'on')

# Demo Futures keys from https://demo.binance.com — use demo-fapi as testnet when present
USE_DEMO = USE_TESTNET and bool(os.environ.get('BINANCE_DEMO_API_KEY', ''))

if USE_DEMO:
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
ALPHA3_ASSETS = ['HANAUSDT', 'STRKUSDT', 'TACUSDT', 'ONGUSDT', 'BMTUSDT', 'STXUSDT']

# Demo Futures (https://demo.binance.com) — XRPUSDT futures
BINANCE_DEMO_FAPI_BASE = 'https://demo-fapi.binance.com'
BINANCE_DEMO_DAPI_BASE = 'https://demo-dapi.binance.com'

if USE_DEMO:
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
