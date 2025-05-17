#!/usr/bin/env python3
"""
3_top_levels.py

Fetch and display the top N price levels from the order book.
"""

import json
import time
import heapq
import redis

# Redis connection details
REDIS = dict(
    host="redis-11972.c9.us-east-1-2.ec2.redns.redis-cloud.com",
    port=11972, db=0,
    username="default",
    password="sgP7uvhkNQvn9bV57hRQiHQSkU2MU46A",
    decode_responses=True
)

class Book:
    __slots__ = ("bids", "asks", "n")

    def __init__(self, n=10):
        self.bids, self.asks = {}, {}
        self.n = n

    def apply(self, msg):
        for p, q in msg.get("b", []):
            qf = float(q)
            if qf == 0:
                self.bids.pop(p, None)
            else:
                self.bids[p] = qf
        for p, q in msg.get("a", []):
            qf = float(q)
            if qf == 0:
                self.asks.pop(p, None)
            else:
                self.asks[p] = qf

    def top_levels(self):
        heap = []
        for p, q in self.bids.items():
            heapq.heappush(heap, (-q, p, "bid"))
        for p, q in self.asks.items():
            heapq.heappush(heap, (-q, p, "ask"))
        return [(p, -q, s) for q, p, s in heapq.nsmallest(self.n, heap)]

def print_top_levels(side, top, n, price_prec, size_prec):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"{ts} [{side}] TOP-LEVELS (N={n})")
    print("+" + "-" * 50 + "+")
    print("| {:<10} | {:<15} | {:<15} |".format("Level", "Price", "Size"))
    print("+" + "-" * 50 + "+")
    for i, (p, q, lvl) in enumerate(top, 1):
        print("| {:<10} | {:<15} | {:<15} |".format(
            i, f"{float(p):.{price_prec}f}", f"{q:.{size_prec}f}"))
    print("+" + "-" * 50 + "+")
    print("-" * 50)

def main():
    symbol = input("Symbol [BTCUSDT]: ") or "BTCUSDT"
    side   = input("Side [spot/futures/both]: ") or "both"
    top_n  = int(input("Top-Levels N [10]: ") or 10)
    price_prec = int(input("Price precision [2]: ") or 2)
    size_prec  = int(input("Size precision [3]: ") or 3)

    sides = ["spot", "futures"] if side == "both" else [side]

    r = redis.Redis(**REDIS)
    try:
        r.ping()
    except Exception as e:
        print(f"Redis connection failed: {e}")
        return

    keys = [f"{s}:{symbol}:depth" for s in sides]

    books = {s: Book(top_n) for s in sides}
    seen = {s: 0 for s in sides}

    # Process historical data
    for side, key in zip(sides, keys):
        raws = r.lrange(key, 0, -1)
        for raw in raws:
            books[side].apply(json.loads(raw))
            top = books[side].top_levels()
            if top:
                print_top_levels(side, top, top_n, price_prec, size_prec)
        seen[side] = len(raws)

    # Continuously tail live data
    print("\n...live tail started (Ctrl-C to stop)...\n")
    try:
        while True:
            for side, key in zip(sides, keys):
                total = r.llen(key)
                if total > seen[side]:
                    book = books[side]
                    for raw in r.lrange(key, seen[side], total - 1):
                        book.apply(json.loads(raw))
                    top = book.top_levels()
                    if top:
                        print_top_levels(side, top, top_n, price_prec, size_prec)
                    seen[side] = total
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped by user.")

if __name__ == "__main__":
    main()
