# position.py

import asyncio  # asynchronous event loop :contentReference[oaicite:0]{index=0}
import sys        # system-specific parameters 
import time       # time utilities for fallback timestamps 
import hmac       # HMAC signing :contentReference[oaicite:3]{index=3}
import hashlib    # SHA256 hashing :contentReference[oaicite:4]{index=4}
import json       # JSON serialization 
from urllib.parse import urlencode, parse_qs  # query-building/parsing :contentReference[oaicite:6]{index=6}

import httpx      # async HTTP client with pooling :contentReference[oaicite:7]{index=7}
import uvicorn    # ASGI server runner :contentReference[oaicite:8]{index=8}

# ─── Credentials ─────────────────────────────────────────────────────────────
API_KEY    = '66d60925b225f5c5d92411ce34c56e6793a776428f6316e5242d614ffcda86f4'
API_SECRET = b'bb7e856ce0d87166c9592a8e1c1455cfa52832ef42ebea520ccabc7c9491abfa'

# ─── Single Base URL ──────────────────────────────────────────────────────────
BASE_URL = 'https://testnet.binancefuture.com'  # Futures Testnet host :contentReference[oaicite:9]{index=9}

# ─── Helpers ──────────────────────────────────────────────────────────────────
async def _get_server_time(client: httpx.AsyncClient) -> int:
    """Fetch Binance server time to avoid stale-timestamp errors."""
    r = await client.get(f"{BASE_URL}/fapi/v1/time")  # v1 time endpoint :contentReference[oaicite:10]{index=10}
    r.raise_for_status()
    return r.json()['serverTime']

def _sign(params: dict) -> str:
    """Create HMAC-SHA256 signature of URL-encoded parameters."""
    qs = urlencode(params)
    return hmac.new(API_SECRET, qs.encode(), hashlib.sha256).hexdigest()

# ─── Core Fetch Function ──────────────────────────────────────────────────────
async def fetch_position_risk(client: httpx.AsyncClient, symbol: str | None) -> list:
    """
    Retrieve your position-risk data, optionally for a single symbol.
    """
    ts = await _get_server_time(client)  # sync time :contentReference[oaicite:11]{index=11}
    params = {'timestamp': ts}
    if symbol:
        params['symbol'] = symbol.upper()  # filter by symbol :contentReference[oaicite:12]{index=12}
    params['signature'] = _sign(params)    # sign request :contentReference[oaicite:13]{index=13}

    url = f"{BASE_URL}/fapi/v2/positionRisk?{urlencode(params)}"  # v2 positionRisk endpoint :contentReference[oaicite:14]{index=14}
    r = await client.get(url, headers={'X-MBX-APIKEY': API_KEY})   # API key header :contentReference[oaicite:15]{index=15}
    r.raise_for_status()
    return r.json()  # returns list of position-risk objects

# ─── ASGI Application ────────────────────────────────────────────────────────
async def app(scope, receive, send):
    if scope['type'] != 'http':
        return  # only handle HTTP requests

    method = scope['method']
    raw_path = scope['path']
    # Normalize path: strip trailing slash, unify snake/camel case
    normalized = raw_path.rstrip('/').lower().replace('positionrisk', 'position_risk')
    print(f">>> Incoming raw path: {raw_path}, normalized to: {normalized}")

    qs = scope.get('query_string', b'').decode()
    symbol = parse_qs(qs).get('symbol', [None])[0]  # extract ?symbol=BTCUSDT :contentReference[oaicite:16]{index=16}

    if method == 'GET' and normalized == '/position_risk':
        async with httpx.AsyncClient() as client:
            data = await fetch_position_risk(client, symbol)
        body = json.dumps(data).encode()  # serialize to JSON 
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(b'content-type', b'application/json')]
        })
        await send({'type': 'http.response.body', 'body': body})
        return

    # Fallback 404 Not Found
    await send({
        'type': 'http.response.start',
        'status': 404,
        'headers': [(b'content-type', b'text/plain')]
    })
    await send({'type': 'http.response.body', 'body': b'Not Found'})

# ─── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if sys.platform.startswith('win'):
        # Windows-compat asyncio policy :contentReference[oaicite:18]{index=18}
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # Launch the ASGI app with Uvicorn :contentReference[oaicite:19]{index=19}
    uvicorn.run("position:app", host="127.0.0.1", port=8000, reload=True)
