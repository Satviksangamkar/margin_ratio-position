# main.py

import sys
import asyncio
import hashlib
import hmac
import json
from urllib.parse import urlencode
from collections import deque

import httpx
import websockets

# ─── Configuration ─────────────────────────────────────────────────────────
API_KEY    = "66d60925b225f5c5d92411ce34c56e6793a776428f6316e5242d614ffcda86f4"
API_SECRET = b"bb7e856ce0d87166c9592a8e1c1455cfa52832ef42ebea520ccabc7c9491abfa"
BASE_URL   = "https://testnet.binancefuture.com"
WS_BASE    = "wss://stream.binancefuture.com/ws/"

# ─── In-memory buffers & globals ────────────────────────────────────────────
liq_buffer = deque(maxlen=100)
ws_clients = set()
listen_key = None

# ─── Endpoint path constants ─────────────────────────────────────────────────
TIME_EP = "/fapi/v1/time"
ACCT_EP = "/fapi/v2/account"
POS_EP  = "/fapi/v2/positionRisk"
LK_EP   = "/fapi/v1/listenKey"

# ─── Helpers ────────────────────────────────────────────────────────────────
def sign(params: dict) -> str:
    return hmac.new(API_SECRET, urlencode(params).encode(), hashlib.sha256).hexdigest()

async def get_time() -> int:
    async with httpx.AsyncClient() as client:
        r = await client.get(BASE_URL + TIME_EP)
        return r.json()["serverTime"]

# ─── Background tasks ───────────────────────────────────────────────────────
async def rotate_key():
    global listen_key
    async with httpx.AsyncClient() as client:
        while True:
            r = await client.post(BASE_URL + LK_EP, headers={"X-MBX-APIKEY": API_KEY})
            listen_key = r.json()["listenKey"]
            await asyncio.sleep(50 * 60)

async def user_stream():
    global listen_key
    # wait for initial key
    while not listen_key:
        await asyncio.sleep(1)

    uri = WS_BASE + listen_key
    async with websockets.connect(uri) as ws:
        async for msg in ws:
            ev = json.loads(msg)
            if ev.get("e") != "ORDER_TRADE_UPDATE":
                continue
            o = ev["o"]
            if o.get("o") == "LIQUIDATION" or o.get("c", "").startswith(("autoclose-", "adl_autoclose")):
                # store & broadcast
                liq_buffer.append(ev)
                text = json.dumps(ev)
                for client in ws_clients.copy():
                    await client.send_text(text)

# ─── Raw ASGI application ───────────────────────────────────────────────────
async def app(scope, receive, send):
    # Lifespan: start background tasks once
    if scope["type"] == "lifespan":
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                asyncio.create_task(rotate_key())
                asyncio.create_task(user_stream())
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    # HTTP handling
    if scope["type"] == "http":
        path = scope["path"]
        # /margin_ratio
        if path == "/margin_ratio":
            ts = await get_time()
            params = {"timestamp": ts}
            params["signature"] = sign(params)
            url = f"{BASE_URL}{ACCT_EP}?{urlencode(params)}"
            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers={"X-MBX-APIKEY": API_KEY})
                d = r.json()
            tm, tb = float(d.get("totalMaintMargin", 0)), float(d.get("totalMarginBalance", 1))
            body = json.dumps({
                "totalMaintMargin": tm,
                "totalMarginBalance": tb,
                "marginRatioPercent": tm / tb * 100 if tb else 0
            }).encode()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": body})
            return

        # /position_risk?symbol=...
        if path == "/position_risk":
            qs = scope.get("query_string", b"").decode()
            symbol = dict([p.split("=") for p in qs.split("&") if "=" in p]).get("symbol")
            ts = await get_time()
            params = {"timestamp": ts}
            if symbol:
                params["symbol"] = symbol.upper()
            params["signature"] = sign(params)
            url = f"{BASE_URL}{POS_EP}?{urlencode(params)}"
            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers={"X-MBX-APIKEY": API_KEY})
                data = r.json()
            body = json.dumps(data).encode()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": body})
            return

        # /liquidation
        if path == "/liquidation":
            body = json.dumps(list(liq_buffer)).encode()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": body})
            return

        # fallback 404
        await send({
            "type": "http.response.start",
            "status": 404,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({"type": "http.response.body", "body": b"Not Found"})
        return

    # WebSocket handling: /ws/liquidation
    if scope["type"] == "websocket" and scope["path"] == "/ws/liquidation":
        await send({"type": "websocket.accept"})
        ws_clients.add(send)
        try:
            while True:
                msg = await receive()
                if msg["type"] == "websocket.disconnect":
                    break
        finally:
            ws_clients.discard(send)
        return

    # any other websocket → close
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1000})

# ─── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    import uvicorn
    uvicorn.run("margin-ratio_positional-risk_liquidation:app", host="127.0.0.1", port=8000, reload=True)





''' output margin ratio 
{"totalMaintMargin": 14.9328, "totalMarginBalance": 11156.71248673, "marginRatioPercent": 0.13384587993785219}

output for positional risk 
[{"symbol": "BTCUSDT", "positionAmt": "0.036", "entryPrice": "103575.9583333", "breakEvenPrice": "103617.3887167", "markPrice": "103778.30422101", "unRealizedProfit": "7.28445195", "liquidationPrice": "0", "leverage": "100", "maxNotionalValue": "250000", "marginType": "cross", "isolatedMargin": "0.00000000", "isAutoAddMargin": "false", "positionSide": "BOTH", "notional": "3736.01895195", "isolatedWallet": "0", "updateTime": 1747195816488, "isolated": false, "adlQuantile": 1}]

output for liquidation on test keys 
[]    '''
