# listenkey.py

import asyncio
import json
import hmac
import hashlib
import logging
import time

import aiohttp
import websockets

# ─── Configuration ──────────────────────────────────────────────────────────
API_KEY    = "66d60925b225f5c5d92411ce34c56e6793a776428f6316e5242d614ffcda86f4"
API_SECRET = b"bb7e856ce0d87166c9592a8e1c1455cfa52832ef42ebea520ccabc7c9491abfa"
HTTP_BASE  = "https://testnet.binancefuture.com"
WS_USER    = "wss://stream.binancefuture.com/ws"  # user-data stream base

# ─── Logging Setup ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("user-liquidation")

# ─── Global listenKey ───────────────────────────────────────────────────────
listen_key: str = None

async def rotate_listen_key():
    """
    Every 50 min, POST /fapi/v1/listenKey → rotate user-data listenKey.
    """
    global listen_key
    async with aiohttp.ClientSession() as sess:
        while True:
            try:
                async with sess.post(
                    f"{HTTP_BASE}/fapi/v1/listenKey",
                    headers={"X-MBX-APIKEY": API_KEY},
                    timeout=10
                ) as resp:
                    resp.raise_for_status()
                    listen_key = (await resp.json())["listenKey"]
                    logger.info(f"👉 New listenKey: {listen_key}")
            except Exception as e:
                logger.error(f"❌ ListenKey rotation failed: {e}")
            await asyncio.sleep(50 * 60)  # sleep 50 minutes

async def user_liquidation_listener():
    """
    Connects to wss://…/ws/<listenKey> and logs only ORDER_TRADE_UPDATE
    events where the order was a forced liquidation or ADL.
    """
    global listen_key
    # wait for first key
    while not listen_key:
        await asyncio.sleep(1)

    uri = f"{WS_USER}/{listen_key}"
    while True:
        try:
            async with websockets.connect(
                uri,
                ping_interval=180,
                ping_timeout=600,
            ) as ws:
                logger.info("✅ Connected to User Data Stream")
                async for msg in ws:
                    ev = json.loads(msg)
                    if ev.get("e") != "ORDER_TRADE_UPDATE":
                        continue

                    o = ev["o"]
                    client_id  = o.get("c", "")
                    order_type = o.get("o")   # e.g. "MARKET","LIMIT","LIQUIDATION"
                    exec_type  = o.get("x")   # e.g. "NEW","CALCULATED",...

                    # filter liquidations & ADL
                    if (
                        order_type == "LIQUIDATION" or
                        client_id.startswith("autoclose-") or
                        client_id.startswith("adl_autoclose")
                    ):
                        logger.info(f"[USER LIQUIDATION] {json.dumps(ev)}")
        except Exception as e:
            logger.error(f"⚠ Connection error: {e!r}. Reconnecting in 5 s…")
            await asyncio.sleep(5)

# ─── ASGI APP WITH LIFESPAN ─────────────────────────────────────────────────
async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                # start our background tasks
                asyncio.create_task(rotate_listen_key())
                asyncio.create_task(user_liquidation_listener())
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    # no HTTP or WS endpoints here
    elif scope["type"] == "http":
        await send({
            "type": "http.response.start",
            "status": 404,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({"type": "http.response.body", "body": b"Not Found"})
    elif scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1000})
