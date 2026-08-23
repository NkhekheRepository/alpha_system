#!/usr/bin/env python3
"""
Demo Futures trader — places real orders on https://demo-fapi.binance.com
Uses BINANCE_DEMO_API_KEY / BINANCE_DEMO_API_SECRET from .env
Only active when BINANCE_USE_DEMO=true (or explicit flag).
"""

import hmac, hashlib, time, requests, os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv('/home/nkhekhe/alpha_system/.env')
except Exception:
    pass

from binance_config import BINANCE_DEMO_FAPI_BASE, BINANCE_DEMO_API_KEY, BINANCE_DEMO_API_SECRET

BASE = BINANCE_DEMO_FAPI_BASE
_lot_cache = {}

def _sign(params):
    qs = '&'.join([f"{k}={v}" for k, v in params.items()])
    sig = hmac.new(BINANCE_DEMO_API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return {**params, 'signature': sig}

def _headers():
    return {'X-MBX-APIKEY': BINANCE_DEMO_API_KEY}

def get_step_size(symbol):
    if symbol in _lot_cache:
        return _lot_cache[symbol]
    try:
        r = requests.get(f"{BASE}/fapi/v1/exchangeInfo", timeout=10)
        r.raise_for_status()
        for s in r.json()['symbols']:
            if s['symbol'] == symbol:
                for f in s['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        step = float(f['stepSize'])
                        _lot_cache[symbol] = step
                        return step
    except Exception:
        pass
    return 0.001

def round_qty(symbol, qty):
    step = get_step_size(symbol)
    # round down to step
    precision = max(0, str(step)[::-1].find('.'))
    if step == 0:
        return qty
    return round(int(qty / step) * step, 8)

def get_balance(asset='USDT'):
    try:
        ts = int(time.time() * 1000)
        params = _sign({'timestamp': ts})
        r = requests.get(f"{BASE}/fapi/v2/balance", params=params, headers=_headers(), timeout=10)
        r.raise_for_status()
        for b in r.json():
            if b['asset'] == asset:
                return float(b['availableBalance'])
    except Exception:
        pass
    return 0.0

def place_market_order(symbol, side, quantity, reduce_only=False):
    """Place MARKET order on demo futures. Returns (order_json, error)."""
    if not BINANCE_DEMO_API_KEY or not BINANCE_DEMO_API_SECRET:
        return None, "Demo keys not configured"
    try:
        qty = round_qty(symbol, quantity)
        if qty <= 0:
            step = get_step_size(symbol)
            qty = step
            if qty <= 0:
                return None, f"qty {quantity} -> 0 after rounding (step {step})"
        ts = int(time.time() * 1000)
        params = {
            'symbol': symbol,
            'side': side.upper(),
            'type': 'MARKET',
            'quantity': qty,
            'timestamp': ts,
        }
        if reduce_only:
            params['reduceOnly'] = 'true'
        signed = _sign(params)
        r = requests.post(f"{BASE}/fapi/v1/order", params=signed, headers=_headers(), timeout=10)
        j = r.json()
        if r.status_code == 200:
            return j, None
        return None, f"{r.status_code}: {j.get('msg','')} {j}"
    except Exception as e:
        return None, str(e)

def close_position_market(symbol, side_to_close):
    """Close by placing opposite MARKET reduceOnly. side_to_close is the position side (long/short)."""
    opposite = 'SELL' if side_to_close == 'long' else 'BUY'
    # Get current position size
    try:
        ts = int(time.time() * 1000)
        params = _sign({'timestamp': ts})
        r = requests.get(f"{BASE}/fapi/v2/positionRisk", params=params, headers=_headers(), timeout=10)
        r.raise_for_status()
        for p in r.json():
            if p['symbol'] == symbol:
                amt = abs(float(p['positionAmt']))
                if amt > 0:
                    return place_market_order(symbol, opposite, amt, reduce_only=True)
        return None, f"No position to close for {symbol}"
    except Exception as e:
        return None, str(e)

def get_open_position(symbol):
    try:
        ts = int(time.time() * 1000)
        params = _sign({'timestamp': ts})
        r = requests.get(f"{BASE}/fapi/v2/positionRisk", params=params, headers=_headers(), timeout=10)
        r.raise_for_status()
        for p in r.json():
            if p['symbol'] == symbol and float(p['positionAmt']) != 0:
                return p
    except Exception:
        pass
    return None
