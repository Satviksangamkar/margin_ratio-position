#!/usr/bin/env python3
"""
depth_categories.py

Fetch historical data & continuously tail Redis for real-time updates,
displaying Non-Cumulative and Cumulative depth-band metrics clearly.
"""

import json, time
import redis

# Redis connection details
REDIS = dict(
    host="redis-11972.c9.us-east-1-2.ec2.redns.redis-cloud.com",
    port=11972, db=0,
    username="default",
    password="sgP7uvhkNQvn9bV57hRQiHQSkU2MU46A",
    decode_responses=True
)

RANGES = [(0, 1), (1, 2.5), (2.5, 5), (5, 10), (10, 25)]
BANDS = [f"{lo}-{hi}" for lo, hi in RANGES]

def compute_view(rec, cum: bool):
    rb = ra = 0.0
    out = {"datetime": rec["datetime"]}
    for rk in BANDS:
        b = rec.get(f"{rk}_bid", 0); a = rec.get(f"{rk}_ask", 0)
        if cum:
            rb += b; ra += a; b, a = rb, ra
        r = float('inf') if b==0 else round(a/b, 4)
        imb = 0.0 if b+a==0 else round((b-a)/(b+a)*100, 2)
        pred= "ask" if a>b else "bid" if b>a else "neutral"
        out.update({f"{rk}_bid": b, f"{rk}_ask": a,
                    f"{rk}_ratio": r, f"{rk}_imb%": imb, f"{rk}_pred": pred})
    return out

def print_view(side, mode, v):
    print(f"{mode} [{side}] {v['datetime']}")
    for rk in BANDS:
        print(f"  Band {rk}% – bid={v[f'{rk}_bid']}, ask={v[f'{rk}_ask']}, "
              f"ratio={v[f'{rk}_ratio']}, imb%={v[f'{rk}_imb%']}%, pred={v[f'{rk}_pred']}")
    print("-" * 50)

def main():
    symbol = input("Symbol [BTCUSDT]: ") or "BTCUSDT"
    mode   = input("Mode [noncum/cum/both]: ") or "both"
    side   = input("Side [spot/futures/both]: ") or "both"

    sides = ["spot", "futures"] if side == "both" else [side]

    r = redis.Redis(**REDIS)
    try:
        r.ping()
    except Exception as e:
        print(f"Redis connection failed: {e}")
        return

    keys = [f"{s}:{symbol}:bands" for s in sides]

    seen = {}
    # Fetch and process historical data
    for side, key in zip(sides, keys):
        raws = r.lrange(key, 0, -1)
        for raw in raws:
            rec = json.loads(raw)
            for m, flag in [("Non-Cum", False), ("Cumulative", True)]:
                if mode in ("both", m.lower()):
                    v = compute_view(rec, flag)
                    print_view(side, m, v)
        seen[side] = len(raws)

    # Continuously tail live data
    print("\n...live tail started (Ctrl-C to stop)...\n")
    try:
        while True:
            for side, key in zip(sides, keys):
                total = r.llen(key)
                if total > seen[side]:
                    new_raws = r.lrange(key, seen[side], total - 1)
                    for raw in new_raws:
                        rec = json.loads(raw)
                        for m, flag in [("Non-Cum", False), ("Cumulative", True)]:
                            if mode in ("both", m.lower()):
                                v = compute_view(rec, flag)
                                print_view(side, m, v)
                    seen[side] = total
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped by user.")

if __name__ == "__main__":
    main()
