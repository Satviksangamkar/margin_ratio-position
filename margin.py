# margin.py

import asyncio
import sys
import time
import hmac
import hashlib
import json
from urllib.parse import urlencode

import httpx
import uvicorn
 
# ─── Your Futures Testnet Credentials ────────────────────────────────────────
API_KEY    = '66d60925b225f5c5d92411ce34c56e6793a776428f6316e5242d614ffcda86f4'
API_SECRET = 'bb7e856ce0d87166c9592a8e1c1455cfa52832ef42ebea520ccabc7c9491abfa'.encode()

# ─── Binance Futures Testnet Endpoints ─────────────────────────────────────
TIME_URL    = 'https://testnet.binancefuture.com/fapi/v1/time'
ACCOUNT_URL = 'https://testnet.binancefuture.com/fapi/v2/account'

async def fetch_margin_ratio():
    async with httpx.AsyncClient() as client:
        # 1) Sync to server time
        r = await client.get(TIME_URL)
        r.raise_for_status()
        server_ts = r.json()['serverTime']

        # 2) Prepare signature
        qs  = urlencode({'timestamp': server_ts})
        sig = hmac.new(API_SECRET, qs.encode(), hashlib.sha256).hexdigest()

        # 3) Fetch account info
        url = f"{ACCOUNT_URL}?{qs}&signature={sig}"
        r2 = await client.get(url, headers={'X-MBX-APIKEY': API_KEY})
        r2.raise_for_status()
        data = r2.json()

        # 4) Compute margin ratio (%)
        tm    = float(data.get('totalMaintMargin', 0))
        tb    = float(data.get('totalMarginBalance', 1))
        ratio = (tm / tb) * 100 if tb else 0.0

        return {
            'totalMaintMargin': tm,
            'totalMarginBalance': tb,
            'marginRatioPercent': ratio
        }

async def app(scope, receive, send):
    # Handle only GET /margin_ratio
    if scope['type'] == 'http' and scope['method'] == 'GET' and scope['path'] == '/margin_ratio':
        result = await fetch_margin_ratio()
        body = json.dumps(result).encode()

        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [
                (b'content-type', b'application/json'),
                (b'cache-control', b'no-store'),
            ]
        })
        await send({'type': 'http.response.body', 'body': body})
        return

    # All other routes -> 404
    await send({
        'type': 'http.response.start',
        'status': 404,
        'headers': [(b'content-type', b'text/plain')]
    })
    await send({'type': 'http.response.body', 'body': b'Not Found'})

if __name__ == "__main__":
    # Ensure compatibility on Windows
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Note: module is "margin", app is "app"
    uvicorn.run("margin:app", host="127.0.0.1", port=8000, reload=True)
