#!/usr/bin/env python3
"""Reconciliation: paper vs demo (alert-only, 2-cycle hysteresis)."""

import json, time, sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import send_message
from audit import log_event

PAPER_STATE = Path('/home/nkhekhe/alpha_system/dry_data/alpha3_state.json')
drift_counts = defaultdict(int)

def get_paper():
    try:
        s = json.loads(PAPER_STATE.read_text())
        return s.get('open_positions', {})
    except Exception:
        return {}

def get_demo():
    try:
        import hmac, hashlib, requests, os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent / '.env')
        from binance_config import BINANCE_DEMO_FAPI_BASE, BINANCE_DEMO_API_KEY, BINANCE_DEMO_API_SECRET
        if not BINANCE_DEMO_API_KEY:
            return {}, "no keys"
        base = BINANCE_DEMO_FAPI_BASE
        signed = sign_query({'timestamp': 0})  # server-synced timestamp
        h = {'X-MBX-APIKEY': BINANCE_DEMO_API_KEY}
        r = requests.get(f'{base}/fapi/v2/positionRisk', params=signed, headers=h, timeout=10)
        if r.status_code != 200:
            print(f"[reconcile] DEMO GET FAIL {r.status_code}: {r.text[:200]}")
            return {}, f"api {r.status_code}"
        demo = {}
        for p in r.json():
            amt = float(p['positionAmt'])
            if amt != 0:
                demo[p['symbol']] = {'amt': amt, 'entry': float(p['entryPrice'])}
        return demo, None
    except Exception as e:
        return {}, str(e)

def check():
    paper = get_paper()
    demo, err = get_demo()
    if err and "no keys" not in err:
        # Don't alert on transient API errors, just log
        return
    symbols = set(paper.keys()) | set(demo.keys())
    drifts = []
    for sym in symbols:
        p = paper.get(sym)
        d = demo.get(sym)
        if p and not d:
            drifts.append(f"{sym}: paper {p['direction']} {p['quantity']:.4f} but demo flat")
        elif d and not p:
            drifts.append(f"{sym}: demo {d['amt']} but paper flat")
        elif p and d:
            p_amt = p['quantity'] * (1 if p['direction']=='long' else -1)
            d_amt = d['amt']
            # allow 1 lot step tolerance (0.001 BTC, 0.1 XRP)
            if abs(p_amt - d_amt) > 0.002:
                drifts.append(f"{sym}: qty paper {p_amt:.4f} vs demo {d_amt:.4f}")
            if (p_amt > 0) != (d_amt > 0):
                drifts.append(f"{sym}: side paper {p['direction']} vs demo {'long' if d_amt>0 else 'short'}")
    if drifts:
        for drift in drifts:
            drift_counts[drift] += 1
            if drift_counts[drift] == 2:  # 2 consecutive cycles
                msg = f"⚠️ <b>Reconciliation Drift</b> — Alpha3 paper vs demo\n" + "\n".join(drifts[:5])
                send_message(msg, bot='alpha2')
                log_event("reconcile", "drift_alert", {"drifts": drifts})
                print(msg)
        # reset counters for drifts that disappeared
        for k in list(drift_counts.keys()):
            if k not in drifts:
                del drift_counts[k]
    else:
        drift_counts.clear()

if __name__ == '__main__':
    print("Reconcile daemon started: 2m poll, 2-cycle hysteresis, alert-only")
    while True:
        try:
            check()
        except Exception as e:
            print(f"reconcile error: {e}")
        time.sleep(120)
