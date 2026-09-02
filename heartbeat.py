#!/usr/bin/env python3
"""Dead-man heartbeat: alerts if runners go silent, 3h digest."""

import json, time, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import send_message
from audit import log_event
try:
    import analytics as vis
    HAS_ANALYTICS = True
except Exception:
    HAS_ANALYTICS = False

A1_STATE = Path('/home/nkhekhe/alpha_system/dry_data/dry_state.json')
A3_STATE = Path('/home/nkhekhe/alpha_system/dry_data/alpha3_state.json')

STALE_SEC = 3 * 60
DIGEST_SEC = 3 * 3600

last_alert = {}
last_health_alert = {}
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
            if time.time() - last_alert.get(name, 0) > 900:
                last_alert[name] = time.time()
                msg = f"🚨 <b>RUNNER STALE</b> — {name} silent {int(age)}s (>{STALE_SEC}s)\nLast: {lu}"
                bot = 'alpha1' if name == 'Alpha1' else 'alpha2'
                send_message(msg, bot=bot)
                log_event("heartbeat", "stale_alert", {"runner": name, "age": int(age)})
                return msg
        return None
    except Exception as e:
        return f"{name}: check error {e}"

def check_health(name, path):
    if not HAS_ANALYTICS or not path.exists():
        return None
    try:
        h = vis.health_checks(path)
        if h['level'] == 'CRITICAL':
            # de-dupe 1h for health critical
            if time.time() - last_health_alert.get(name, 0) > 3600:
                last_health_alert[name] = time.time()
                bot = 'alpha1' if name == 'Alpha1' else 'alpha2'
                msg = f"🚨 <b>HEALTH CRITICAL — {name}</b>\n" + "\n".join(h['alerts'][:4])
                send_message(msg, bot=bot)
                log_event("heartbeat", "health_critical", {"runner": name, "alerts": h['alerts']})
                return msg
        elif h['level'] == 'WARN':
            # WARN only in 3h digest, not immediate
            pass
        return None
    except Exception as e:
        return f"{name}: health error {e}"

def digest():
    try:
        a1 = json.loads(A1_STATE.read_text()) if A1_STATE.exists() else {}
        a3 = json.loads(A3_STATE.read_text()) if A3_STATE.exists() else {}
        # Enhanced digest with risk metrics if analytics available
        def risk_line(path, label):
            if not HAS_ANALYTICS or not path.exists():
                return ""
            try:
                r = vis.get_risk_report(path)
                h = r['health']
                health_icon = "🟢" if h['level']=="OK" else "🟡" if h['level']=="WARN" else "🔴"
                return f"\nSharpe {r['sharpe']:.2f} PF {r['pf']:.2f} DD {r['dd_stats']['current_dd']*100:.2f}% {health_icon} {h['level']}"
            except:
                return ""
        # Separate digests per bot — no cross-contamination
        msg1 = (
            f"💓 <b>Heartbeat — Alpha 1 (3h)</b>\n"
            f"Trades: {a1.get('total_trades',0)} ({a1.get('total_wins',0)}W/{a1.get('total_losses',0)}L) "
            f"WR {100*a1.get('total_wins',0)/max(1,a1.get('total_trades',0)):.1f}%\n"
            f"Equity: ${a1.get('equity',0):,.2f} | Open: {len(a1.get('open_positions',{}))}"
            f"{risk_line(A1_STATE, 'Alpha1')}"
        )
        # append WARN details if any
        if HAS_ANALYTICS and A1_STATE.exists():
            try:
                h1 = vis.health_checks(A1_STATE)
                if h1['alerts']:
                    msg1 += "\n" + "\n".join(h1['alerts'][:3])
            except:
                pass
        msg3 = (
            f"💓 <b>Heartbeat — Alpha 3 (3h)</b>\n"
            f"Trades: {a3.get('total_trades',0)} ({a3.get('total_wins',0)}W/{a3.get('total_losses',0)}L) "
            f"WR {100*a3.get('total_wins',0)/max(1,a3.get('total_trades',0)):.1f}%\n"
            f"Equity: ${a3.get('equity',0):,.2f} | Open: {len(a3.get('open_positions',{}))} | Demo USDT: check /positions"
            f"{risk_line(A3_STATE, 'Alpha3')}"
        )
        if HAS_ANALYTICS and A3_STATE.exists():
            try:
                h3 = vis.health_checks(A3_STATE)
                if h3['alerts']:
                    msg3 += "\n" + "\n".join(h3['alerts'][:3])
            except:
                pass
        send_message(msg1, bot='alpha1')
        send_message(msg3, bot='alpha2')
        log_event("heartbeat", "digest", {"a1_trades": a1.get('total_trades'), "a3_trades": a3.get('total_trades')})
    except Exception as e:
        print(f"digest error: {e}")

if __name__ == '__main__':
    print("Heartbeat started: 60s poll, 3m stale, 3h digest (+ health)")
    while True:
        for name, path in [("Alpha1", A1_STATE), ("Alpha3", A3_STATE)]:
            msg = check(name, path)
            if msg:
                print(msg)
            hmsg = check_health(name, path)
            if hmsg:
                print(hmsg)
        if time.time() - last_digest > DIGEST_SEC:
            digest()
            last_digest = time.time()
        time.sleep(60)
