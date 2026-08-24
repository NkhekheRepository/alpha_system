#!/usr/bin/env python3
"""Audit trail for manual and automated state interventions."""

import json, sys
from pathlib import Path
from datetime import datetime

LOG = Path('/home/nkhekhe/alpha_system/dry_data/audit_log.jsonl')

def log_event(actor, event, details=None):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "actor": actor,
        "event": event,
        "details": details or {},
    }
    with open(LOG, 'a') as f:
        f.write(json.dumps(rec) + "\n")
    return rec

def show(last=20):
    if not LOG.exists():
        print("No audit log yet")
        return
    lines = LOG.read_text().strip().splitlines()
    for line in lines[-last:]:
        r = json.loads(line)
        print(f"{r['ts']}  {r['actor']:<12} {r['event']:<28} {json.dumps(r['details'])}")

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'show':
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        show(n)
    elif len(sys.argv) > 2:
        # audit.py <actor> <event> [json_details]
        actor, event = sys.argv[1], sys.argv[2]
        details = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(json.dumps(log_event(actor, event, details), indent=2))
    else:
        print("Usage: audit.py show [N]  |  audit.py <actor> <event> '{\"k\":\"v\"}'")
