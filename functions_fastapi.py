# functions_fastapi.py
import sys
import asyncio
import hashlib
import hmac
import json
from urllib.parse import urlencode
from collections import deque
from typing import Set, Optional

import httpx
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# ─── Configuration ─────────────────────────────────────────────────────────
API_KEY    = "66d60925b225f5c5d92411ce34c56e6793a776428f6316e5242d614ffcda86f4"
API_SECRET = b"bb7e856ce0d87166c9592a8e1c1455cfa52832ef42ebea520ccabc7c9491abfa"
BASE_URL   = "https://testnet.binancefuture.com"
WS_BASE    = "wss://stream.binancefuture.com/ws/"

# ─── In-memory buffers & globals ───────────────────────────────────────────
liq_buffer: deque = deque(maxlen=100)
ws_clients: Set[WebSocket] = set()
listen_key: Optional[str] = None

# ─── Endpoint path constants ───────────────────────────────────────────────
TIME_EP = "/fapi/v1/time"
ACCT_EP = "/fapi/v2/account"
POS_EP  = "/fapi/v2/positionRisk"
LK_EP   = "/fapi/v1/listenKey"

# ─── Helpers ───────────────────────────────────────────────────────────────
def sign(params: dict) -> str:
    return hmac.new(API_SECRET, urlencode(params).encode(), hashlib.sha256).hexdigest()

async def get_time() -> int:
    async with httpx.AsyncClient() as client:
        r = await client.get(BASE_URL + TIME_EP)
        r.raise_for_status()
        return r.json()["serverTime"]

# ─── Background tasks ──────────────────────────────────────────────────────
async def rotate_key(update_event: asyncio.Event):
    """
    Generate a fresh listenKey every 50 minutes and notify user_stream.
    """
    global listen_key
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.post(BASE_URL + LK_EP, headers={"X-MBX-APIKEY": API_KEY})
            resp.raise_for_status()
            new_key = resp.json()["listenKey"]
            listen_key = new_key
            update_event.set()
            update_event.clear()
            await asyncio.sleep(50 * 60)

async def user_stream(update_event: asyncio.Event):
    """
    Connect to user data stream; reconnect when listen_key rotates.
    """
    global listen_key
    last_key = None
    ws = None

    while True:
        # wait for a valid listen_key
        if not listen_key:
            await asyncio.sleep(1)
            continue

        # if key has changed, (re)connect
        if listen_key != last_key:
            last_key = listen_key
            if ws:
                await ws.close()
            uri = WS_BASE + listen_key
            ws = await websockets.connect(uri)

        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=30)
            ev = json.loads(msg)
            if ev.get("e") != "ORDER_TRADE_UPDATE":
                continue
            o = ev.get("o", {})
            if o.get("o") == "LIQUIDATION" or o.get("c", "").startswith(("autoclose-", "adl_autoclose")):
                liq_buffer.append(ev)
                text = json.dumps(ev)
                for client in set(ws_clients):
                    try:
                        await client.send_text(text)
                    except WebSocketDisconnect:
                        ws_clients.discard(client)
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            # reconnect on timeout or socket close
            await asyncio.sleep(1)
        # also reconnect immediately when rotate_key signals
        if update_event.is_set():
            continue

# ─── FastAPI setup ─────────────────────────────────────────────────────────
app = FastAPI()

@app.on_event("startup")
async def startup():
    # event to notify of key rotation
    update_event = asyncio.Event()
    # start background tasks
    asyncio.create_task(rotate_key(update_event))
    asyncio.create_task(user_stream(update_event))

# ─── REST Endpoints ────────────────────────────────────────────────────────
@app.get("/margin_ratio")
async def margin_ratio():
    ts = await get_time()
    params = {"timestamp": ts}
    params["signature"] = sign(params)
    url = f"{BASE_URL}{ACCT_EP}?{urlencode(params)}"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers={"X-MBX-APIKEY": API_KEY})
        r.raise_for_status()
        d = r.json()
    tm = float(d.get("totalMaintMargin", 0))
    tb = float(d.get("totalMarginBalance", 1))
    return {"totalMaintMargin": tm, "totalMarginBalance": tb, "marginRatioPercent": tm / tb * 100 if tb else 0.0}

@app.get("/position_risk")
async def position_risk(symbol: Optional[str] = None):
    ts = await get_time()
    params = {"timestamp": ts}
    if symbol:
        params["symbol"] = symbol.upper()
    params["signature"] = sign(params)
    url = f"{BASE_URL}{POS_EP}?{urlencode(params)}"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers={"X-MBX-APIKEY": API_KEY})
        r.raise_for_status()
        data = r.json()
    return data

@app.get("/liquidation")
async def recent_liquidations():
    return list(liq_buffer)

# ─── WebSocket Endpoint ────────────────────────────────────────────────────
@app.websocket("/ws/liquidation")
async def ws_liquidation(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(websocket)

# ─── Entry point for `python functions_fastapi.py` ───────────────────────────
if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    import uvicorn
    uvicorn.run("functions_fastapi:app", host="127.0.0.1", port=8000, reload=True)
