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
_filter_cache = {}  # symbol -> {step, maxQty, minQty, tick}
_balance_cache = {'ts': 0, 'val': None}

def get_demo_usdt_balance():
    """Fetch demo USDT available balance, cached 30s."""
    import time
    now = time.time()
    if now - _balance_cache['ts'] < 30 and _balance_cache['val'] is not None:
        return _balance_cache['val']
    try:
        from binance_config import sign_query
        p = sign_query({})
        r = requests.get(f"{BASE}/fapi/v2/balance", params=p, headers=_headers(), timeout=5)
        if r.status_code == 200:
            for b in r.json():
                if b.get('asset') == 'USDT':
                    v = float(b.get('availableBalance', 0) or b.get('balance', 0))
                    _balance_cache['ts'] = now
                    _balance_cache['val'] = v
                    return v
    except Exception:
        pass
    return _balance_cache['val'] if _balance_cache['val'] is not None else 4888.0

def _sign(params):
    # Delegate to the centralized, server-time-synced signer (binance_config.sign_query)
    from binance_config import sign_query
    return sign_query(params)

def _headers():
    return {'X-MBX-APIKEY': BINANCE_DEMO_API_KEY}

def get_symbol_filters(symbol):
    if symbol in _filter_cache:
        return _filter_cache[symbol]
    try:
        r = requests.get(f"{BASE}/fapi/v1/exchangeInfo", timeout=10)
        r.raise_for_status()
        for s in r.json()['symbols']:
            if s['symbol'] == symbol:
                lot = next((f for f in s['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                mlot = next((f for f in s['filters'] if f['filterType'] == 'MARKET_LOT_SIZE'), None)
                pricef = next((f for f in s['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
                min_not = next((f for f in s['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
                if lot:
                    filt = {
                        'stepSize': lot['stepSize'],
                        'maxQty': lot['maxQty'],
                        'minQty': lot['minQty'],
                        'tickSize': pricef['tickSize'] if pricef else '0.01',
                        'minNotional': min_not['notional'] if min_not else '5',
                        'marketMaxQty': mlot['maxQty'] if mlot else lot['maxQty'],
                        'marketMinQty': mlot['minQty'] if mlot else lot['minQty'],
                        'marketStep': mlot['stepSize'] if mlot else lot['stepSize'],
                    }
                    _filter_cache[symbol] = filt
                    _lot_cache[symbol] = float(lot['stepSize'])
                    return filt
    except Exception:
        pass
    filt = {'stepSize': '1', 'maxQty': '1000000', 'minQty': '1', 'tickSize': '0.01', 'minNotional': '5', 'marketMaxQty': '30000', 'marketMinQty': '1', 'marketStep': '1'}
    _filter_cache[symbol] = filt
    return filt

def get_step_size(symbol):
    if symbol in _lot_cache:
        return float(_lot_cache[symbol])
    return float(get_symbol_filters(symbol)['stepSize'])

def get_demo_position(symbol):
    """Return signed demo position amt for symbol (0 if flat)."""
    try:
        from binance_config import sign_query
        p = sign_query({})
        r = requests.get(f"{BASE}/fapi/v2/positionRisk", params=p, headers=_headers(), timeout=5)
        if r.status_code == 200:
            for pos in r.json():
                if pos.get('symbol') == symbol:
                    return float(pos.get('positionAmt', 0) or 0)
    except Exception:
        pass
    return 0.0

def _cap_qty_by_balance(symbol, qty, price=None, is_market=True, for_close=False):
    """Cap qty so notional does not exceed demo balance * leverage * stake. Also respects maxQty.
    When for_close=True the balance-based cap is skipped — closes must use the
    full live position size to avoid residual holdings and -4118/-2019 errors."""
    if for_close:
        # still enforce marketMaxQty for market closes (live position is already within it)
        if is_market:
            try:
                filt = get_symbol_filters(symbol)
                mmax = float(filt.get('marketMaxQty', filt.get('maxQty', '1000000')))
                if qty > mmax:
                    qty = mmax
            except Exception:
                pass
        return qty
    try:
        from decimal import Decimal
        filt = get_symbol_filters(symbol)
        if price is None:
            try:
                r = requests.get(f"{BASE}/fapi/v1/ticker/price", params={'symbol': symbol}, timeout=3)
                if r.status_code == 200:
                    price = float(r.json().get('price', 0))
            except:
                price = None
        if price and price > 0:
            bal = get_demo_usdt_balance()
            # use actual STAKE_PCT (0.20) for live compounding; cap at 50% of wallet*leverage to allow compounding beyond 8000 as equity grows
            try:
                from alpha3_dry_runner import STAKE_PCT as _SP, LEVERAGE as _LEV
            except Exception:
                _SP, _LEV = 0.20, 20.0
            max_notional = bal * _SP * _LEV
            # allow compounding: cap scales with balance, but keep a hard max of 20000 to avoid exchange max-position errors
            max_notional = min(max_notional, max(8000, bal * 0.5 * _LEV))
            max_qty_by_notional = max_notional / price
            if qty > max_qty_by_notional:
                qty = max_qty_by_notional
            try:
                min_not = float(filt.get('minNotional', '5'))
                min_qty_by_notional = min_not / price * 1.01
                if qty < min_qty_by_notional:
                    qty = min_qty_by_notional
            except:
                pass
        # also enforce marketMaxQty for market orders
        if is_market:
            try:
                mmax = float(filt.get('marketMaxQty', filt.get('maxQty', '1000000')))
                if qty > mmax:
                    qty = mmax
            except:
                pass
    except Exception:
        pass
    return qty

def _format_qty(symbol, qty, price=None, is_market=True, for_close=False):
    """Format qty as decimal string with correct precision, no scientific notation, floor to step, enforce minNotional.
    When for_close=True the balance cap and min-notional bump are skipped."""
    from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation
    qty = _cap_qty_by_balance(symbol, qty, price, is_market=is_market, for_close=for_close)
    filt = get_symbol_filters(symbol)
    step_s = filt['marketStep'] if is_market else filt['stepSize']
    max_s = filt['marketMaxQty'] if is_market else filt['maxQty']
    min_notional_s = filt.get('minNotional', '5')
    try:
        d_qty = Decimal(str(qty))
        d_step = Decimal(step_s)
        d_max = Decimal(max_s)
        if d_qty > d_max:
            d_qty = d_max
        if d_step != 0:
            steps = (d_qty // d_step)
            d_qty = steps * d_step
        dec = len(step_s.split('.')[1].rstrip('0')) if '.' in step_s else 0
        if dec > 0:
            exp = Decimal('1e-%d' % dec)
            d_qty = d_qty.quantize(exp, rounding=ROUND_DOWN)
            s = format(d_qty, 'f')
        else:
            d_qty = d_qty.quantize(Decimal('1'), rounding=ROUND_DOWN)
            s = format(d_qty, 'f').split('.')[0]
        if '.' in s:
            if dec == 0:
                s = s.split('.')[0]
            else:
                intp, decp = s.split('.')
                decp = (decp + '0'*dec)[:dec]
                s = intp + '.' + decp
        if 'E' in s or 'e' in s:
            s = format(d_qty, 'f')
        try:
            if Decimal(s) > d_max:
                s = format(d_max, 'f')
        except:
            pass
        if Decimal(s) == 0:
            s = filt['marketMinQty'] if is_market else filt['minQty']
            d_qty = Decimal(s)
        if not for_close:
            try:
                if price and price > 0:
                    min_not = Decimal(min_notional_s)
                    d_price = Decimal(str(price))
                    notional = Decimal(s) * d_price
                    if notional < min_not:
                        needed = (min_not / d_price)
                        if d_step != 0:
                            steps_needed = (needed / d_step).to_integral_value(rounding=ROUND_UP)
                            d_qty_needed = steps_needed * d_step
                            if d_qty_needed > d_max:
                                d_qty_needed = d_max
                            if dec > 0:
                                exp = Decimal('1e-%d' % dec)
                                d_qty_needed = d_qty_needed.quantize(exp, rounding=ROUND_UP)
                                s = format(d_qty_needed, 'f')
                            else:
                                d_qty_needed = d_qty_needed.quantize(Decimal('1'), rounding=ROUND_UP)
                                s = format(d_qty_needed, 'f').split('.')[0]
            except:
                pass
        return s
    except (InvalidOperation, ValueError, Exception):
        try:
            s = ('%.8f' % float(qty)).rstrip('0').rstrip('.')
            if s == '-0' or s == '':
                s = '0'
            return s
        except:
            return str(qty)

def round_qty(symbol, qty):
    # Backward compat: uses _lot_cache if set (tests), else live filters
    step = get_step_size(symbol)
    if step == 0:
        return float(qty)
    # mimic original simple floor behavior (used by tests)
    q = float(qty)
    # also respect maxQty if we have filters (but don't break test expectations)
    try:
        filt = get_symbol_filters(symbol) if symbol not in _lot_cache else None
        if filt is not None:
            max_q = float(filt['maxQty'])
            if q > max_q:
                q = max_q
    except Exception:
        pass
    return round(int(q / step) * step, 8)

def place_limit_order(symbol, side, quantity, price, reduce_only=False):
    """Place LIMIT order at exact price to match paper entry. Returns (order_json, error)."""
    if not BINANCE_DEMO_API_KEY or not BINANCE_DEMO_API_SECRET:
        return None, "Demo keys not configured"
    try:
        qty_str = _format_qty(symbol, quantity, price, is_market=False)
        try:
            if float(qty_str) <= 0:
                filt = get_symbol_filters(symbol)
                qty_str = filt['stepSize']
                if float(qty_str) <= 0:
                    return None, f"qty {quantity} -> 0 after rounding"
        except:
            pass
        ts = int(time.time() * 1000)
        params = {
            'symbol': symbol,
            'side': side.upper(),
            'type': 'LIMIT',
            'quantity': qty_str,
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
        # suppress -1111 spam after fix: log but don't spam if it's precision (should not happen now)
        print(f"[demo_trader] ORDER FAIL {r.status_code}: {j} (symbol={symbol} side={side} qty={qty_str})")
        return None, f"{r.status_code}: {j.get('msg','')} {j}"
    except Exception as e:
        return None, str(e)

def place_market_order(symbol, side, quantity, reduce_only=False):
    """Place MARKET order on demo futures. Returns (order_json, error)."""
    if not BINANCE_DEMO_API_KEY or not BINANCE_DEMO_API_SECRET:
        return None, "Demo keys not configured"
    try:
        # Use price hint for notional capping if available via ticker
        price_hint = None
        try:
            r0 = requests.get(f"{BASE}/fapi/v1/ticker/price", params={'symbol': symbol}, timeout=3)
            if r0.status_code == 200:
                price_hint = float(r0.json().get('price', 0))
        except:
            pass
        qty_str = _format_qty(symbol, quantity, price_hint, is_market=True, for_close=reduce_only)
        try:
            if float(qty_str) <= 0:
                filt = get_symbol_filters(symbol)
                qty_str = filt['stepSize']
                if float(qty_str) <= 0:
                    return None, f"qty {quantity} -> 0 after rounding"
        except:
            pass
        ts = int(time.time() * 1000)
        params = {
            'symbol': symbol,
            'side': side.upper(),
            'type': 'MARKET',
            'quantity': qty_str,
            'timestamp': ts,
        }
        if reduce_only:
            params['reduceOnly'] = 'true'
        signed = _sign(params)
        r = requests.post(f"{BASE}/fapi/v1/order", params=signed, headers=_headers(), timeout=10)
        j = r.json()
        if r.status_code == 200:
            return j, None
        print(f"[demo_trader] ORDER FAIL {r.status_code}: {j} (symbol={symbol} side={side} qty={qty_str})")
        return None, f"{r.status_code}: {j.get('msg','')} {j}"
    except Exception as e:
        return None, str(e)

def place_bracket_orders(symbol, entry_side, quantity, tp_price, sl_price):
    """Place TP/SL bracket via AlgoOrder (CONDITIONAL) — survives runner death."""
    if not BINANCE_DEMO_API_KEY or not BINANCE_DEMO_API_SECRET:
        return
    try:
        close_side = 'SELL' if entry_side == 'BUY' else 'BUY'
        qty_str = _format_qty(symbol, quantity)
        # Take profit
        from binance_config import sign_query
        tp_params = {
            'symbol': symbol,
            'side': close_side,
            'type': 'TAKE_PROFIT_MARKET',
            'quantity': qty_str,
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
            'quantity': qty_str,
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
        print(f"[demo_trader] LEVERAGE FAIL {r.status_code}: {j} (symbol={symbol})")
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

# ---------------------------------------------------------------------------
# Testnet Futures trader (https://testnet.binancefuture.com) — mirrors demo
# Uses BINANCE_TESTNET_API_KEY/SECRET, same 7 assets. Provides parallel
# execution path so paper trades can be hedged on both demo and testnet.
# ---------------------------------------------------------------------------
TESTNET_FAPI_BASE = 'https://testnet.binancefuture.com'
try:
    from binance_config import BINANCE_TESTNET_API_KEY as _TN_KEY, BINANCE_TESTNET_API_SECRET as _TN_SEC
except Exception:
    _TN_KEY = _TN_SEC = ''

_testnet_filter_cache = {}
_testnet_balance_cache = {'ts': 0, 'val': None}

def _sign_testnet(params):
    from binance_config import sign_query
    return sign_query(params, secret=_TN_SEC)

def _headers_testnet():
    return {'X-MBX-APIKEY': _TN_KEY}

def get_demo_position(symbol):
    """(duplicate alias for runner use; see top-level definition)."""
    try:
        from binance_config import sign_query
        p = sign_query({})
        r = requests.get(f"{BASE}/fapi/v2/positionRisk", params=p, headers=_headers(), timeout=5)
        if r.status_code == 200:
            for pos in r.json():
                if pos.get('symbol') == symbol:
                    return float(pos.get('positionAmt', 0) or 0)
    except Exception:
        pass
    return 0.0

def get_testnet_position(symbol):
    """Return signed testnet position amt for symbol (0 if flat)."""
    try:
        from binance_config import sign_query
        p = sign_query({}, secret=_TN_SEC)
        r = requests.get(f"{TESTNET_FAPI_BASE}/fapi/v2/positionRisk", params=p, headers=_headers_testnet(), timeout=5)
        if r.status_code == 200:
            for pos in r.json():
                if pos.get('symbol') == symbol:
                    return float(pos.get('positionAmt', 0) or 0)
    except Exception:
        pass
    return 0.0

def get_testnet_usdt_balance():
    import time
    now = time.time()
    if now - _testnet_balance_cache['ts'] < 30 and _testnet_balance_cache['val'] is not None:
        return _testnet_balance_cache['val']
    try:
        from binance_config import sign_query
        p = sign_query({}, secret=_TN_SEC)
        r = requests.get(f"{TESTNET_FAPI_BASE}/fapi/v2/balance", params=p, headers=_headers_testnet(), timeout=5)
        if r.status_code == 200:
            for b in r.json():
                if b.get('asset') == 'USDT':
                    v = float(b.get('availableBalance', 0) or b.get('balance', 0))
                    _testnet_balance_cache['ts'] = now
                    _testnet_balance_cache['val'] = v
                    return v
    except Exception:
        pass
    return _testnet_balance_cache['val'] if _testnet_balance_cache['val'] is not None else 4884.0

def get_testnet_symbol_filters(symbol):
    if symbol in _testnet_filter_cache:
        return _testnet_filter_cache[symbol]
    try:
        r = requests.get(f"{TESTNET_FAPI_BASE}/fapi/v1/exchangeInfo", timeout=10)
        r.raise_for_status()
        for s in r.json()['symbols']:
            if s['symbol'] == symbol:
                lot = next((f for f in s['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                mlot = next((f for f in s['filters'] if f['filterType'] == 'MARKET_LOT_SIZE'), None)
                pricef = next((f for f in s['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
                min_not = next((f for f in s['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
                if lot:
                    filt = {
                        'stepSize': lot['stepSize'],
                        'maxQty': lot['maxQty'],
                        'minQty': lot['minQty'],
                        'tickSize': pricef['tickSize'] if pricef else '0.01',
                        'minNotional': min_not['notional'] if min_not else '5',
                        'marketMaxQty': mlot['maxQty'] if mlot else lot['maxQty'],
                        'marketMinQty': mlot['minQty'] if mlot else lot['minQty'],
                        'marketStep': mlot['stepSize'] if mlot else lot['stepSize'],
                    }
                    _testnet_filter_cache[symbol] = filt
                    return filt
    except Exception:
        pass
    filt = {'stepSize': '1', 'maxQty': '1000000', 'minQty': '1', 'tickSize': '0.01', 'minNotional': '5', 'marketMaxQty': '30000', 'marketMinQty': '1', 'marketStep': '1'}
    _testnet_filter_cache[symbol] = filt
    return filt

def _format_testnet_qty(symbol, qty, price=None, is_market=True, for_close=False):
    from decimal import Decimal, ROUND_DOWN, ROUND_UP
    if for_close:
        # closes must use the full live position — only clamp to marketMaxQty/step, no balance cap
        try:
            if is_market:
                filt = get_testnet_symbol_filters(symbol)
                mmax = float(filt.get('marketMaxQty', filt.get('maxQty', '1000000')))
                if qty > mmax:
                    qty = mmax
        except:
            pass
    else:
        try:
            if price is None:
                try:
                    r = requests.get(f"{TESTNET_FAPI_BASE}/fapi/v1/ticker/price", params={'symbol': symbol}, timeout=3)
                    if r.status_code == 200:
                        price = float(r.json().get('price', 0))
                except:
                    price = None
            if price and price > 0:
                bal = get_testnet_usdt_balance()
                try:
                    from alpha3_dry_runner import STAKE_PCT as _SP, LEVERAGE as _LEV
                except Exception:
                    _SP, _LEV = 0.20, 20.0
                max_notional = bal * _SP * _LEV
                max_notional = min(max_notional, max(8000, bal * 0.5 * _LEV))
                max_qty = max_notional / price
                if qty > max_qty:
                    qty = max_qty
                try:
                    filt = get_testnet_symbol_filters(symbol)
                    min_not = float(filt.get('minNotional', '5'))
                    min_qty = min_not / price * 1.01
                    if qty < min_qty:
                        qty = min_qty
                except:
                    pass
            if is_market:
                try:
                    filt = get_testnet_symbol_filters(symbol)
                    mmax = float(filt.get('marketMaxQty', filt.get('maxQty', '1000000')))
                    if qty > mmax:
                        qty = mmax
                except:
                    pass
        except:
            pass
    filt = get_testnet_symbol_filters(symbol)
    step_s = filt['marketStep'] if is_market else filt['stepSize']
    max_s = filt['marketMaxQty'] if is_market else filt['maxQty']
    try:
        d_qty = Decimal(str(qty))
        d_step = Decimal(step_s)
        d_max = Decimal(max_s)
        if d_qty > d_max:
            d_qty = d_max
        if d_step != 0:
            d_qty = (d_qty // d_step) * d_step
        dec = len(step_s.split('.')[1].rstrip('0')) if '.' in step_s else 0
        if dec > 0:
            exp = Decimal('1e-%d' % dec)
            d_qty = d_qty.quantize(exp, rounding=ROUND_DOWN)
            s = format(d_qty, 'f')
        else:
            d_qty = d_qty.quantize(Decimal('1'), rounding=ROUND_DOWN)
            s = format(d_qty, 'f').split('.')[0]
        if Decimal(s) == 0:
            s = filt['marketMinQty'] if is_market else filt['minQty']
        if not for_close:
            try:
                if price and price > 0:
                    min_not = Decimal(filt.get('minNotional', '5'))
                    if Decimal(s) * Decimal(str(price)) < min_not:
                        needed = (min_not / Decimal(str(price)))
                        steps_needed = (needed / d_step).to_integral_value(rounding=ROUND_UP)
                        d_needed = steps_needed * d_step
                        if d_needed > d_max:
                            d_needed = d_max
                        if dec > 0:
                            exp = Decimal('1e-%d' % dec)
                            d_needed = d_needed.quantize(exp, rounding=ROUND_UP)
                            s = format(d_needed, 'f')
                        else:
                            s = format(d_needed.quantize(Decimal('1'), rounding=ROUND_UP), 'f').split('.')[0]
            except:
                pass
        return s
    except Exception:
        return ('%.8f' % float(qty)).rstrip('0').rstrip('.') or '0'

def place_testnet_market_order(symbol, side, quantity, reduce_only=False):
    if not _TN_KEY or not _TN_SEC:
        return None, "Testnet keys not configured"
    try:
        price_hint = None
        try:
            r0 = requests.get(f"{TESTNET_FAPI_BASE}/fapi/v1/ticker/price", params={'symbol': symbol}, timeout=3)
            if r0.status_code == 200:
                price_hint = float(r0.json().get('price', 0))
        except:
            pass
        qty_str = _format_testnet_qty(symbol, quantity, price_hint, is_market=True, for_close=reduce_only)
        try:
            if float(qty_str) <= 0:
                qty_str = get_testnet_symbol_filters(symbol)['stepSize']
        except:
            pass
        ts = int(time.time() * 1000)
        params = {'symbol': symbol, 'side': side.upper(), 'type': 'MARKET', 'quantity': qty_str, 'timestamp': ts}
        if reduce_only:
            params['reduceOnly'] = 'true'
        signed = _sign_testnet(params)
        r = requests.post(f"{TESTNET_FAPI_BASE}/fapi/v1/order", params=signed, headers=_headers_testnet(), timeout=10)
        j = r.json()
        if r.status_code == 200:
            return j, None
        print(f"[testnet] ORDER FAIL {r.status_code}: {j} (symbol={symbol} side={side} qty={qty_str})")
        return None, f"{r.status_code}: {j.get('msg','')} {j}"
    except Exception as e:
        return None, str(e)

def set_testnet_leverage_all(symbols, leverage=20):
    if not _TN_KEY or not _TN_SEC:
        print("  Testnet leverage: keys not configured")
        return {}
    results = {}
    for sym in symbols:
        try:
            ts = int(time.time() * 1000)
            params = {'symbol': sym, 'leverage': int(leverage), 'timestamp': ts}
            signed = _sign_testnet(params)
            r = requests.post(f"{TESTNET_FAPI_BASE}/fapi/v1/leverage", params=signed, headers=_headers_testnet(), timeout=10)
            j = r.json()
            if r.status_code == 200:
                print(f"  Testnet leverage set {sym}: {j.get('leverage','OK')}")
                results[sym] = (j, None)
            else:
                print(f"  Testnet leverage set {sym}: ERROR {j}")
                results[sym] = (None, str(j))
        except Exception as e:
            print(f"  Testnet leverage set {sym}: ERROR {e}")
            results[sym] = (None, str(e))
    return results
