#!/usr/bin/env python3
"""Dead-man heartbeat: alerts if runners go silent, 3h digest."""

import json, time, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '/home/nkhekhe/alpha_system')
from notify import send_message
from audit import log_event

A1_STATE = Path('/home/nkhekhe/alpha_system/dry_data/dry_state.json')
A3_STATE = Path('/home/nkhekhe/alpha_system/dry_data/alpha3_state.json')

STALE_SEC = 3 * 60
DIGEST_SEC = 3 * 3600

last_alert = {}
last_digest = 0

def check(name, path):
    if not path.exists():
        return f"{name}: no state file"
    try:
        s = json.loads(path.read_text())
        lu = s.get('last_update')
        if not lu:
            return None
        dt = datetime.fromisoformat(lu)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        if age > STALE_SEC:
            # throttle re-alert every 15 min
            if time.time() - last_alert.get(name, 0) > 900:
                last_alert[name] = time.time()
                msg = f"🚨 <b>RUNNER STALE</b> — {name} silent {int(age)}s (>{STALE_SEC}s)\nLast: {lu}"
                send_message(msg, bot='alpha1')
                log_event("heartbeat", "stale_alert", {"runner": name, "age": int(age)})
                return msg
        return None
    except Exception as e:
        return f"{name}: check error {e}"

def digest():
    try:
        a1 = json.loads(A1_STATE.read_text()) if A1_STATE.exists() else {}
        a3 = json.loads(A3_STATE.read_text()) if A3_STATE.exists() else {}
        msg = (
            f"💓 <b>Heartbeat — 3h Digest</b>\n"
            f"A1: {a1.get('total_trades',0)} trades {a1.get('total_wins',0)}W/{a1.get('total_losses',0)}L "
            f"eq ${a1.get('equity',0):,.2f} open {len(a1.get('open_positions',{}))}\n"
            f"A3: {a3.get('total_trades',0)} trades {a3.get('total_wins',0)}W/{a3.get('total_losses',0)}L "
            f"eq ${a3.get('equity',0):,.2f} open {len(a3.get('open_positions',{}))}\n"
            f"Demo USDT: check /positions"
        )
        send_message(msg, bot='alpha2')
        log_event("heartbeat", "digest", {"a1_trades": a1.get('total_trades'), "a3_trades": a3.get('total_trades')})
    except Exception as e:
        print(f"digest error: {e}")

if __name__ == '__main__':
    print("Heartbeat started: 60s poll, 3m stale, 3h digest")
    while True:
        for name, path in [("Alpha1", A1_STATE), ("Alpha3", A3_STATE)]:
            msg = check(name, path)
            if msg:
                print(msg)
        if time.time() - last_digest > DIGEST_SEC:
            digest()
            last_digest = time.time()
        time.sleep(60)
