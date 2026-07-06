import asyncio
import json
import logging
import time
import threading

import httpx
import websockets

logger = logging.getLogger(__name__)

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"

COINS = ["SOL", "JUP", "PYTH", "DOGE", "SUI", "WIF", "POPCAT"]
HISTORY_DEPTH = 250

market_history: dict[str, list[float]] = {}
_lock = threading.Lock()


def get_market_history() -> dict[str, list[float]]:
    with _lock:
        return {coin: closes[:] for coin, closes in market_history.items()}


async def boot_bootstrap() -> dict[str, list[float]]:
    end_time_ms = int(time.time() * 1000)
    start_time_ms = end_time_ms - (HISTORY_DEPTH + 1) * 60 * 1000

    async def fetch_one(coin: str) -> tuple[str, list[float]]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(HYPERLIQUID_INFO_URL, json={
                    "type": "candleSnapshot",
                    "req": {
                        "coin": coin,
                        "interval": "1m",
                        "startTime": start_time_ms,
                        "endTime": end_time_ms,
                    },
                })
                resp.raise_for_status()
                candles = resp.json()
                if not candles:
                    logger.warning(f"{coin}: REST bootstrap returned no candles")
                    return coin, []
                closes = [float(c["c"]) for c in candles]
                finalized = closes[:HISTORY_DEPTH]
                if len(finalized) < HISTORY_DEPTH:
                    logger.warning(f"{coin}: only {len(finalized)} closed candles from REST (need {HISTORY_DEPTH})")
                return coin, finalized
        except Exception as e:
            logger.error(f"{coin}: REST bootstrap failed: {e}")
            return coin, []

    tasks = [fetch_one(coin) for coin in COINS]
    results = await asyncio.gather(*tasks)
    return dict(results)


class HyperliquidStream:
    def __init__(self, history: dict[str, list[float]]):
        self._history = history
        self._last_ts: dict[str, int] = {}
        self._last_price: dict[str, float] = {}

    async def run(self):
        while True:
            try:
                async with websockets.connect(HYPERLIQUID_WS_URL) as ws:
                    logger.info("WebSocket connected")
                    for coin in COINS:
                        await ws.send(json.dumps({
                            "method": "subscribe",
                            "subscription": {
                                "type": "candle",
                                "coin": coin,
                                "interval": "1m",
                            },
                        }))
                    logger.info(f"Subscribed to {len(COINS)} candle channels")

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(msg, dict):
                            continue
                        if msg.get("channel") != "candle":
                            continue
                        candle = msg.get("data")
                        if not isinstance(candle, dict):
                            continue

                        coin = candle.get("s", "")
                        ts = candle.get("t", 0)
                        price = float(candle.get("c", 0.0))

                        if coin not in COINS:
                            continue

                        if coin not in self._last_ts:
                            self._last_ts[coin] = ts
                            self._last_price[coin] = price
                        elif ts > self._last_ts[coin]:
                            with _lock:
                                self._history[coin].append(self._last_price[coin])
                                if len(self._history[coin]) > HISTORY_DEPTH:
                                    self._history[coin].pop(0)
                            self._last_ts[coin] = ts

                        self._last_price[coin] = price

            except websockets.ConnectionClosed:
                logger.warning("WS disconnected — reconnecting in 5s")
                await asyncio.sleep(5)
            except Exception as e:
                logger.exception(f"WS error: {e}")
                await asyncio.sleep(5)
