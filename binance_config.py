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

BINANCE_API_BASE = 'https://testnet.binance.vision' if USE_TESTNET else 'https://api.binance.com'

BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET', '')
BINANCE_TESTNET_API_KEY = os.environ.get('BINANCE_TESTNET_API_KEY', '')
BINANCE_TESTNET_API_SECRET = os.environ.get('BINANCE_TESTNET_API_SECRET', '')

ACTIVE_API_KEY = BINANCE_TESTNET_API_KEY if USE_TESTNET else BINANCE_API_KEY
ACTIVE_API_SECRET = BINANCE_TESTNET_API_SECRET if USE_TESTNET else BINANCE_API_SECRET

def get_api_base():
    return BINANCE_API_BASE

def is_testnet():
    return USE_TESTNET

def get_active_keys():
    return ACTIVE_API_KEY, ACTIVE_API_SECRET
