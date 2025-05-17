#!/usr/bin/env python3
"""
fetch_bands_incremental.py
──────────────────────────
Historical dump + live tail + Top-Levels with TRDR-style summary stats, precision table,
optional Sticky mode, and display-mode toggle (total/ratio/both).
"""

import json, time, sys, heapq, math
from typing import Any, Dict, List
import redis

# ─── Redis connection ──────────────────────────────────────────────────────
REDIS_HOST     = "redis-11972.c9.us-east-1-2.ec2.redns.redis-cloud.com"
REDIS_PORT     = 11972
REDIS_DB       = 0
REDIS_USERNAME = "default"
REDIS_PASS     = "sgP7uvhkNQvn9bV57hRQiHQSkU2MU46A"

# Depth-band ranges
RANGES     = [(0, 1), (1, 2.5), (2.5, 5), (5, 10), (10, 25)]
RANGE_KEYS = [f"{lo}-{hi}" for lo, hi in RANGES]

# ─── Terminal colors ───────────────────────────────────────────────────────
RESET = "\033[0m"
BID_COLOR = "\033[92m"
ASK_COLOR = "\033[91m"
HEADER_COLOR = "\033[96m"
TABLE_COLOR = "\033[93m"

# ─── Precision Table ───────────────────────────────────────────────────────
def show_precision_table():
    print(f"\n{HEADER_COLOR}Precision Table (matches TRDR widget):{RESET}")
    print(f"{TABLE_COLOR}┌──────────┬─────────┬───────┬───────┐")
    print("│Precision │ Price   │ Bid   │ Ask   │")
    print("├──────────┼─────────┼───────┼───────┤")
    print("│    1     │ 1.23456 │ 1     │ 2     │")
    print("│    2     │ 1.23456 │ 1.2   │ 1.3   │")
    print("│    3     │ 1.23456 │ 1.23  │ 1.24  │")
    print("│    4     │ 1.23456 │ 1.234 │ 1.235 │")
    print("│    5     │ 1.23456 │ 1.2345│ 1.2346│")
    print(f"└──────────┴─────────┴───────┴───────┘{RESET}\n")
    print("The order book supports aggregation, customizable precisions (see table),\n"
          "depth charts, cumulation, and band categories highlighted by dotted lines in the GUI.\n"
          "This terminal script matches TRDR widget logic for all quantitative/statistical output.\n")

# ─── Helpers ───────────────────────────────────────────────────────────────
def ask(prompt, cast=None, default=None):
    raw = input(f"{prompt} [{default}]: ").strip()
    return default if raw == "" else (cast(raw) if cast else raw)

def filter_record(rec: Dict[str, Any], stg: Dict[str, Any]):
    if stg["min_bids"] and all(rec.get(f"{rk}_bid", 0) < stg["min_bids"] for rk in RANGE_KEYS):
        return None
    if stg["min_asks"] and all(rec.get(f"{rk}_ask", 0) < stg["min_asks"] for rk in RANGE_KEYS):
        return None
    if stg["bands"]:
        slim = {"timestamp": rec["timestamp"], "datetime": rec["datetime"]}
        for rk in stg["bands"]:
            slim[f"{rk}_bid"] = rec.get(f"{rk}_bid", 0)
            slim[f"{rk}_ask"] = rec.get(f"{rk}_ask", 0)
        return slim
    return rec

def enrich_view(v: Dict[str, Any]):
    for rk in RANGE_KEYS:
        if f"{rk}_bid" not in v: continue
        b, a = v[f"{rk}_bid"], v[f"{rk}_ask"]
        v[f"{rk}_ratio"] = math.inf if b == 0 else round(a / b, 4)
        tot = b + a
        v[f"{rk}_imb%"] = 0.0 if tot == 0 else round((b - a) / tot * 100, 2)
        v[f"{rk}_pred"] = "ask" if a > b else "bid" if b > a else "neutral"

def make_view(rec: Dict[str, Any], cum: bool):
    out, rb, ra = {"datetime": rec["datetime"]}, 0.0, 0.0
    for rk in RANGE_KEYS:
        b, a = rec.get(f"{rk}_bid", 0.0), rec.get(f"{rk}_ask", 0.0)
        if cum:
            rb += b; ra += a; b, a = rb, ra
        out[f"{rk}_bid"], out[f"{rk}_ask"] = b, a
    enrich_view(out)
    return out

def fmt_price(p: str, prec: int): return f"{float(p):.{prec}f}"
def fmt_size(q: float, prec: int):  return f"{q:.{prec}f}"

def compute_summary(prev: Dict[str, Any], curr: Dict[str, Any], bands: List[str]):
    adds = subs = 0.0
    keys = bands or RANGE_KEYS
    for rk in keys:
        for side in ("_bid", "_ask"):
            pk = prev.get(f"{rk}{side}", 0.0)
            ck = curr.get(f"{rk}{side}", 0.0)
            diff = ck - pk
            if diff > 0: adds += diff
            else:        subs += -diff
    return round(adds, 6), round(subs, 6), round(adds - subs, 6)

def select_sticky_band(v: Dict[str, Any], side: str):
    best_rk, best_vol = RANGE_KEYS[0], -1.0
    for rk in RANGE_KEYS:
        vol = v.get(f"{rk}_{side}", 0.0)
        if vol > best_vol:
            best_vol, best_rk = vol, rk
    return best_rk

def print_line(side, mode, v, bands, size_prec, verbose,
               summary, first, sticky, sticky_side, display_mode):
    adds, subs, net = summary
    if not verbose:
        print("[OK] Band record received")
        return

    summ = f"{HEADER_COLOR}[+{adds:.{size_prec}f}/-{subs:.{size_prec}f}/Δ{net:.{size_prec}f}]{RESET}"
    use = [select_sticky_band(v, sticky_side)] if sticky else (bands or RANGE_KEYS)

    parts = [summ, v["datetime"], side.upper(), mode]
    for rk in use:
        if display_mode in ("total", "both"):
            parts += [
                f"{BID_COLOR}{rk}_bid={fmt_size(v[f'{rk}_bid'], size_prec)}{RESET}",
                f"{ASK_COLOR}{rk}_ask={fmt_size(v[f'{rk}_ask'], size_prec)}{RESET}",
            ]
        if display_mode in ("ratio", "both"):
            parts += [
                f"{rk}_ratio={'∞' if math.isinf(v[f'{rk}_ratio']) else v[f'{rk}_ratio']}",
                f"{rk}_imb%={v[f'{rk}_imb%']:.2f}",
                f"{rk}_pred={v[f'{rk}_pred']}",
            ]
    print(" | ".join(parts))

def print_top_levels(side, top, n, price_prec, size_prec, verbose):
    if not verbose:
        print("[OK] Top-Levels updated")
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    parts = [f"{HEADER_COLOR}{ts}{RESET}", side.upper(), f"TOP-LEVELS (N={n})"]
    for p, q, lvl in top:
        color = BID_COLOR if lvl == "bid" else ASK_COLOR
        parts.append(f"{color}{lvl}@{fmt_price(p, price_prec)}={fmt_size(q, size_prec)}{RESET}")
    print(" | ".join(parts))

# ─── Order-book class ──────────────────────────────────────────────────────
class Book:
    __slots__ = ("bids","asks","n")
    def __init__(self,n:int=10):
        self.bids, self.asks = {}, {}
        self.n = n
    def apply(self,msg):
        for p,q in msg.get("b", []):
            qf = float(q)
            if qf == 0: self.bids.pop(p, None)
            else:       self.bids[p] = qf
        for p,q in msg.get("a", []):
            qf = float(q)
            if qf == 0: self.asks.pop(p, None)
            else:       self.asks[p] = qf
    def top_levels(self):
        heap = []
        for p,q in self.bids.items(): heapq.heappush(heap,(-q,p,"bid"))
        for p,q in self.asks.items(): heapq.heappush(heap,(-q,p,"ask"))
        return [(p,-q,s) for q,p,s in heapq.nsmallest(self.n, heap)]

# ─── Main ──────────────────────────────────────────────────────────────────
def main():
    print(f"{HEADER_COLOR}=== Overlay Settings (↵ = default) ==={RESET}")
    show_precision_table()
    symbol      = ask("Symbol", str, "BTCUSDT")
    side_in     = ask("Side [spot/futures/both]", str, "both").lower()
    mode        = ask("Depth mode [noncum/cum/both]", str, "both").lower()
    min_bids    = ask("Min bids (blank = none)", float, None)
    min_asks    = ask("Min asks (blank = none)", float, None)
    bands_raw   = ask("Bands to INCLUDE (comma-sep, blank = all)", str, None)
    top_n       = ask("Top-Levels N", int, 10)
    price_dp    = ask("Price precision", int, 2)
    size_dp     = ask("Size precision", int, 3)
    verbose     = ask("Verbose output? [y/n]", str, "n").lower() == "y"

    display_mode = ask("Display mode [total/ratio/both]", str, "both").lower()
    if display_mode not in ("total", "ratio", "both"):
        print("Invalid display mode; defaulting to both.")
        display_mode = "both"

    sticky      = ask("Sticky mode? [y/n]", str, "n").lower() == "y"
    sticky_side = "bid"
    if sticky:
        sticky_side = ask("Track side [bid/ask]", str, "bid").lower()

    settings = {
        "min_bids": min_bids,
        "min_asks": min_asks,
        "bands":   [b.strip() for b in bands_raw.split(",")] if bands_raw else None
    }
    want_non = mode in ("noncum","both")
    want_cum = mode in ("cum","both")

    # Redis connect
    r = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
        username=REDIS_USERNAME, password=REDIS_PASS,
        decode_responses=True, socket_connect_timeout=5
    )
    try: r.ping()
    except Exception as e: sys.exit(f"Redis connect failed → {e}")

    if side_in != "both":
        sides = [side_in]
    else:
        sides = [k.split(":",1)[0] for k in r.scan_iter(f"*:{symbol}:bands")]
    if not sides: sys.exit("No matching Redis keys.")

    books      = {s:Book(top_n) for s in sides}
    last_band  = {}
    last_depth = {}
    prev_rec   = {(s,m):None for s in sides for m in ("Non-Cum","Cumulative")}

    # ── Historical ────────────────────────────────────────────────────────────
    for s in sides:
        bkey, dkey   = f"{s}:{symbol}:bands", f"{s}:{symbol}:depth"
        b_raws       = r.lrange(bkey, 0, -1); last_band[s]  = len(b_raws)
        d_raws       = r.lrange(dkey, 0, -1); last_depth[s] = len(d_raws)

        for raw in b_raws:
            rec = json.loads(raw)
            if filter_record(rec, settings) is None: continue
            for mode_name,cum_flag in (("Non-Cum",False),("Cumulative",True)):
                if (mode_name=="Non-Cum" and not want_non) or (mode_name=="Cumulative" and not want_cum):
                    continue
                view    = make_view(rec, cum_flag)
                prev    = prev_rec[(s,mode_name)]
                summary = compute_summary(prev or view, view, settings["bands"])
                print_line(s, mode_name, view, settings["bands"],
                           size_dp, verbose, summary, prev is None,
                           sticky, sticky_side, display_mode)
                prev_rec[(s,mode_name)] = view

        book, prev_sig = books[s], None
        for raw in d_raws:
            book.apply(json.loads(raw))
            top = book.top_levels()
            sig = tuple((p,round(q,8),sd) for p,q,sd in top)
            if top and sig != prev_sig:
                print_top_levels(s, top, top_n, price_dp, size_dp, verbose)
                prev_sig = sig

    print(f"\n{HEADER_COLOR}--- Live tail (Ctrl-C to stop) ---{RESET}\n")

    # ── Live tail ─────────────────────────────────────────────────────────────
    try:
        while True:
            for s in sides:
                bkey, dkey = f"{s}:{symbol}:bands", f"{s}:{symbol}:depth"

                total = r.llen(bkey)
                if total > last_band[s]:
                    for raw in r.lrange(bkey, last_band[s], total-1):
                        rec = json.loads(raw)
                        if filter_record(rec, settings) is None: continue
                        for mode_name,cum_flag in (("Non-Cum",False),("Cumulative",True)):
                            if (mode_name=="Non-Cum" and not want_non) or (mode_name=="Cumulative" and not want_cum):
                                continue
                            view    = make_view(rec, cum_flag)
                            prev    = prev_rec[(s,mode_name)]
                            summary = compute_summary(prev or view, view, settings["bands"])
                            print_line(s, mode_name, view, settings["bands"],
                                       size_dp, verbose, summary, prev is None,
                                       sticky, sticky_side, display_mode)
                            prev_rec[(s,mode_name)] = view
                    last_band[s] = total

                d_total = r.llen(dkey)
                if d_total > last_depth[s]:
                    book, changed = books[s], False
                    for raw in r.lrange(dkey, last_depth[s], d_total-1):
                        book.apply(json.loads(raw)); changed = True
                    last_depth[s] = d_total
                    if changed:
                        top = book.top_levels()
                        if top:
                            print_top_levels(s, top, top_n, price_dp, size_dp, verbose)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
