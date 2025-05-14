import asyncio
import json
import websockets

# Base WebSocket URL for USDⓈ-M futures market streams
BASE_URL = "wss://fstream.binance.com"  # Raw streams under /ws/<streamName> :contentReference[oaicite:4]{index=4}

async def subscribe_all_liquidations():
    uri = f"{BASE_URL}/ws/!forceOrder@arr"  # All-market liquidation snapshot stream :contentReference[oaicite:5]{index=5}
    async with websockets.connect(uri) as ws:  # Establish raw stream connection :contentReference[oaicite:6]{index=6}
        print("📡 Subscribed to !forceOrder@arr (all-market liquidations)")
        while True:
            message = await ws.recv()
            data = json.loads(message)
            # e.g., data["o"]["s"] symbol, data["o"]["l"] last filled qty, data["o"]["p"] price, etc.
            print("All-market event:", data)

async def subscribe_symbol_liquidation(symbol: str):
    stream = symbol.lower() + "@forceOrder"  # Symbols must be lowercase in stream names :contentReference[oaicite:7]{index=7}
    uri = f"{BASE_URL}/ws/{stream}"  # Single-symbol liquidation snapshot stream :contentReference[oaicite:8]{index=8}
    async with websockets.connect(uri) as ws:  # Raw stream connection :contentReference[oaicite:9]{index=9}
        print(f"📡 Subscribed to {stream} (liquidation for {symbol.upper()})")
        while True:
            message = await ws.recv()
            data = json.loads(message)
            # e.g., data["o"]["s"] symbol, data["o"]["z"] cumulative filled qty, data["o"]["ap"] avg price, etc.
            print(f"{symbol.upper()} event:", data)

async def main():
    # Run both subscriptions concurrently;
    # adjust or remove subscribe_symbol_liquidation if you only need one stream
    await asyncio.gather(
        subscribe_all_liquidations(),
        subscribe_symbol_liquidation("BTCUSDT")
    )

if __name__ == "__main__":
    asyncio.run(main())

