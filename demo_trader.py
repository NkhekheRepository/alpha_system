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
    # Delegate to the centralized, server-time-synced signer (binance_config.sign_query)
    from binance_config import sign_query
    return sign_query(params)

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

def place_limit_order(symbol, side, quantity, price, reduce_only=False):
    """Place LIMIT order at exact price to match paper entry. Returns (order_json, error)."""
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
            'type': 'LIMIT',
            'quantity': qty,
            'price': round(float(price), 2),
            'timeInForce': 'GTC',
            'timestamp': ts,
        }
        if reduce_only:
            params['reduceOnly'] = 'true'
        signed = _sign(params)
        r = requests.post(f"{BASE}/fapi/v1/order", params=signed, headers=_headers(), timeout=10)
        j = r.json()
        if r.status_code == 200:
            return j, None
        print(f"[demo_trader] ORDER FAIL {r.status_code}: {j} (symbol={symbol} side={side})")
        return None, f"{r.status_code}: {j.get('msg','')} {j}"
    except Exception as e:
        return None, str(e)

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
        print(f"[demo_trader] ORDER FAIL {r.status_code}: {j} (symbol={symbol} side={side})")
        return None, f"{r.status_code}: {j.get('msg','')} {j}"
    except Exception as e:
        return None, str(e)

def place_bracket_orders(symbol, entry_side, quantity, tp_price, sl_price):
    """Place TP/SL bracket via AlgoOrder (CONDITIONAL) — survives runner death."""
    if not BINANCE_DEMO_API_KEY or not BINANCE_DEMO_API_SECRET:
        return
    try:
        close_side = 'SELL' if entry_side == 'BUY' else 'BUY'
        qty = round_qty(symbol, quantity)
        # Take profit
        from binance_config import sign_query
        tp_params = {
            'symbol': symbol,
            'side': close_side,
            'type': 'TAKE_PROFIT_MARKET',
            'quantity': qty,
            'triggerPrice': round(tp_price, 2),
            'algotype': 'CONDITIONAL',
        }
        signed_tp = sign_query(tp_params)
        h = {'X-MBX-APIKEY': BINANCE_DEMO_API_KEY}
        requests.post(f"{BASE}/fapi/v1/algoOrder", params=signed_tp, headers=h, timeout=10)
        time.sleep(0.15)
        sl_params = {
            'symbol': symbol,
            'side': close_side,
            'type': 'STOP_MARKET',
            'quantity': qty,
            'triggerPrice': round(sl_price, 2),
            'algotype': 'CONDITIONAL',
        }
        signed_sl = sign_query(sl_params)
        requests.post(f"{BASE}/fapi/v1/algoOrder", params=signed_sl, headers=h, timeout=10)
    except Exception:
        pass

def cancel_algo_orders(symbol):
    """Cancel all open algo orders for symbol."""
    if not BINANCE_DEMO_API_KEY or not BINANCE_DEMO_API_SECRET:
        return
    try:
        from binance_config import sign_query
        params = sign_query({'timestamp': 0})  # timestamp auto-filled by sign_query
        h = {'X-MBX-APIKEY': BINANCE_DEMO_API_KEY}
        r = requests.get(f"{BASE}/fapi/v1/openAlgoOrders", params=params, headers=h, timeout=10)
        if r.status_code != 200:
            return
        for o in r.json():
            if o.get('symbol') == symbol:
                algo_id = o.get('algoId')
                del_params = sign_query({'algoId': algo_id})
                requests.delete(f"{BASE}/fapi/v1/algoOrder", params=del_params, headers=h, timeout=10)
                time.sleep(0.1)
    except Exception:
        pass


def set_leverage(symbol, leverage=50):
    """Set leverage for a symbol on demo futures."""
    if not BINANCE_DEMO_API_KEY or not BINANCE_DEMO_API_SECRET:
        return None, "Demo keys not configured"
    try:
        ts = int(time.time() * 1000)
        params = {
            'symbol': symbol,
            'leverage': int(leverage),
            'timestamp': ts,
        }
        signed = _sign(params)
        r = requests.post(f"{BASE}/fapi/v1/leverage", params=signed, headers=_headers(), timeout=10)
        j = r.json()
        if r.status_code == 200:
            return j, None
        print(f"[demo_trader] ORDER FAIL {r.status_code}: {j} (symbol={symbol} side={side})")
        return None, f"{r.status_code}: {j.get('msg','')} {j}"
    except Exception as e:
        return None, str(e)


def set_leverage_all(symbols, leverage=50):
    """Set leverage for all symbols."""
    results = {}
    for sym in symbols:
        res, err = set_leverage(sym, leverage)
        results[sym] = (res, err)
        if err:
            print(f"  Leverage set {sym}: ERROR {err}")
        else:
            print(f"  Leverage set {sym}: {res.get('leverage', 'OK')}")
    return results
