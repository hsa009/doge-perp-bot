import asyncio
import json
import logging
import time
import threading

import httpx
import websockets

from bot.redis_client import RedisClient

logger = logging.getLogger(__name__)

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"

COINS = ["SOL", "JUP", "PYTH", "DOGE", "SUI", "WIF", "POPCAT"]
HISTORY_DEPTH = 250

market_history: dict[str, list[float]] = {}
_lock = threading.Lock()

_redis: RedisClient | None = None

def _get_redis() -> RedisClient:
    global _redis
    if _redis is None:
        _redis = RedisClient()
    return _redis


def get_market_history() -> dict[str, list[float]]:
    with _lock:
        return {coin: closes[:] for coin, closes in market_history.items()}


async def boot_bootstrap() -> dict[str, list[float]]:
    end_time_ms = int(time.time() * 1000)
    start_time_ms = end_time_ms - (HISTORY_DEPTH + 1) * 900 * 1000

    async def fetch_one(coin: str) -> tuple[str, list[float]]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(HYPERLIQUID_INFO_URL, json={
                    "type": "candleSnapshot",
                    "req": {
                        "coin": coin,
                                "interval": "15m",
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
        self.processed_coins: set[str] = set()

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
                        "interval": "15m",
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

                        try:
                            _get_redis().set_config("ai_loop_heartbeat", str(time.time()))
                        except Exception:
                            pass

                        if coin not in self._last_ts:
                            self._last_ts[coin] = ts
                            self._last_price[coin] = price
                        elif ts > self._last_ts[coin]:
                            with _lock:
                                self._history[coin].append(self._last_price[coin])
                                if len(self._history[coin]) > HISTORY_DEPTH:
                                    self._history[coin].pop(0)
                            self._last_ts[coin] = ts

                            self.processed_coins.add(coin)

                            if len(self.processed_coins) == 7:
                                logger.info(
                                    "[AI-BATCH] All 7 coins have new candles. "
                                    "Running Gemini evaluation..."
                                )
                                ai_signals = {}
                                from bot.main import _run_single_coin_signal
                                loop = asyncio.get_event_loop()
                                tasks = [
                                    loop.run_in_executor(None, _run_single_coin_signal, c, None)
                                    for c in COINS
                                ]
                                results = await asyncio.gather(*tasks, return_exceptions=True)

                                for coin_idx, result in enumerate(results):
                                    c = COINS[coin_idx]
                                    if isinstance(result, Exception):
                                        logger.error(f"[AI-BATCH] {c} error: {result}")
                                        continue
                                    if not result:
                                        logger.warning(f"[AI-BATCH] {c} returned None")
                                        continue
                                    direction = result.get("direction", "wait")
                                    confidence = result.get("confidence", 0.0)
                                    logger.info(
                                        f"[AI-BATCH] {c}: {direction.upper()} "
                                        f"(conf={confidence:.2f})"
                                    )
                                    if direction != "wait":
                                        ai_signals[c] = result

                                if ai_signals:
                                    best_coin = max(
                                        ai_signals,
                                        key=lambda k: ai_signals[k].get("confidence", 0),
                                    )
                                    best_data = ai_signals[best_coin]
                                    logger.info(
                                        f"[AI-BATCH] Winner: {best_coin} "
                                        f"{best_data['direction'].upper()} "
                                        f"conf={best_data['confidence']:.2f}"
                                    )
                                    try:
                                        _get_redis().set_config_with_ttl(
                                            "batch_winner",
                                            json.dumps({
                                                "coin": best_coin,
                                                "suggestion": best_data["direction"],
                                                "confidence_score": best_data.get("confidence", 0),
                                                "timestamp": time.time(),
                                            }),
                                            ttl=600,
                                        )
                                    except Exception:
                                        pass
                                    from bot.main import safe_to_trade, open_trade
                                    if safe_to_trade(best_coin, best_data["direction"]):
                                        best_data["_coin"] = best_coin
                                        open_trade(best_data, coin=best_coin)
                                else:
                                    logger.info(
                                        "[AI-BATCH] All coins returned 'wait'. No trade this cycle."
                                    )
                                self.processed_coins.clear()

                        self._last_price[coin] = price

            except websockets.ConnectionClosed:
                logger.warning("WS disconnected — reconnecting in 5s")
                self.processed_coins.clear()
                await asyncio.sleep(5)
            except Exception as e:
                logger.exception(f"WS error: {e}")
                await asyncio.sleep(5)
