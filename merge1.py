import asyncio
import os
import sys
import hmac
import hashlib
import json
from urllib.parse import urlencode, parse_qs

import httpx
import uvicorn

# ─── Load Credentials from Environment Variables or Use Defaults ──────────────
API_KEY = os.getenv('BINANCE_API_KEY', '66d60925b225f5c5d92411ce34c56e6793a776428f6316e5242d614ffcda86f4')
API_SECRET = os.getenv('BINANCE_API_SECRET', 'bb7e856ce0d87166c9592a8e1c1455cfa52832ef42ebea520ccabc7c9491abfa').encode()

# ─── Base URL ────────────────────────────────────────────────────────────────
BASE_URL = 'https://testnet.binancefuture.com'

# ─── Global HTTP Client ──────────────────────────────────────────────────────
client = httpx.AsyncClient()

# ─── Helpers ──────────────────────────────────────────────────────────────────
async def _get_server_time():
    url = f"{BASE_URL}/fapi/v1/time"
    r = await client.get(url)
    r.raise_for_status()
    return r.json()['serverTime']

def _sign(params: dict) -> str:
    qs = urlencode(params)
    return hmac.new(API_SECRET, qs.encode(), hashlib.sha256).hexdigest()

# ─── Fetch Functions ─────────────────────────────────────────────────────────
async def fetch_margin_ratio():
    ts = await _get_server_time()
    params = {'timestamp': ts}
    params['signature'] = _sign(params)
    url = f"{BASE_URL}/fapi/v2/account?{urlencode(params)}"

    r = await client.get(url, headers={'X-MBX-APIKEY': API_KEY})
    r.raise_for_status()
    d = r.json()
    tm = float(d['totalMaintMargin'])
    tb = float(d['totalMarginBalance'])
    margin_ratio = (tm / tb) * 100 if tb else 0.0
    return {
        'totalMaintMargin': tm,
        'totalMarginBalance': tb,
        'marginRatioPercent': margin_ratio
    }

async def fetch_position_risk(symbol: str | None):
    ts = await _get_server_time()
    params = {'timestamp': ts}
    if symbol:
        params['symbol'] = symbol.upper()
    params['signature'] = _sign(params)
    url = f"{BASE_URL}/fapi/v2/positionRisk?{urlencode(params)}"

    r = await client.get(url, headers={'X-MBX-APIKEY': API_KEY})
    r.raise_for_status()
    return r.json()

# ─── ASGI Application ────────────────────────────────────────────────────────
async def app(scope, receive, send):
    if scope['type'] != 'http':
        return

    path = scope['path']
    method = scope['method']
    qs = scope.get('query_string', b'').decode()
    symbol = parse_qs(qs).get('symbol', [None])[0]

    if method == 'GET' and path == '/margin_ratio':
        out = await fetch_margin_ratio()
        body = json.dumps(out).encode()
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(b'content-type', b'application/json')]
        })
        await send({'type': 'http.response.body', 'body': body})
        return

    if method == 'GET' and path == '/position_risk':
        out = await fetch_position_risk(symbol)
        body = json.dumps(out).encode()
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [(b'content-type', b'application/json')]
        })
        await send({'type': 'http.response.body', 'body': body})
        return

if __name__ == "__main__":
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run("margin:app", host="127.0.0.1", port=8000, reload=True)
