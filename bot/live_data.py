import asyncio
import json
import logging
import time
import threading

import httpx
import websockets

from bot.indicators import evaluate_coin_momentum
from bot.redis_client import RedisClient

logger = logging.getLogger(__name__)

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"

COINS = ["SOL", "JUP", "PYTH", "DOGE", "SUI", "WIF", "POPCAT"]
HISTORY_DEPTH = 250

market_history: dict[str, dict[str, list[float]]] = {}
_lock = threading.Lock()

_redis: RedisClient | None = None

def _get_redis() -> RedisClient:
    global _redis
    if _redis is None:
        _redis = RedisClient()
    return _redis


def get_market_history() -> dict[str, list[float]]:
    with _lock:
        return {coin: data["close"][:] for coin, data in market_history.items()}


async def boot_bootstrap() -> dict[str, dict[str, list[float]]]:
    end_time_ms = int(time.time() * 1000)
    start_time_ms = end_time_ms - (HISTORY_DEPTH + 1) * 900 * 1000

    async def fetch_one(coin: str) -> tuple[str, dict[str, list[float]]]:
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
                    return coin, {"close": [], "high": [], "low": []}
                closes = [float(c["c"]) for c in candles]
                highs = [float(c["h"]) for c in candles]
                lows = [float(c["l"]) for c in candles]
                truncated = {
                    "close": closes[:HISTORY_DEPTH],
                    "high": highs[:HISTORY_DEPTH],
                    "low": lows[:HISTORY_DEPTH],
                }
                count = len(truncated["close"])
                if count < HISTORY_DEPTH:
                    logger.warning(f"{coin}: only {count} closed candles from REST (need {HISTORY_DEPTH})")
                return coin, truncated
        except Exception as e:
            logger.error(f"{coin}: REST bootstrap failed: {e}")
            return coin, {"close": [], "high": [], "low": []}

    tasks = [fetch_one(coin) for coin in COINS]
    results = await asyncio.gather(*tasks)
    return dict(results)


class HyperliquidStream:
    def __init__(self, ohlcv: dict[str, dict[str, list[float]]]):
        self._ohlcv = ohlcv
        self._last_ts: dict[str, int] = {}
        self._last_price: dict[str, float] = {}
        self._last_high: dict[str, float] = {}
        self._last_low: dict[str, float] = {}
        self._last_ai_request: dict[str, float] = {}
        self.current_15m_signals: dict[str, dict] = {}
        self.processed_coins: set[str] = set()

    async def _dispatch_ai_confirmation(self, coin: str, sentiment: str,
                                        rsi_value: float, logic: str,
                                        price: float, ts: int):
        # DISABLED: Preserved for potential future AI consensus re-activation.
        pass

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
                        high = float(candle.get("h", price))
                        low = float(candle.get("l", price))

                        if coin not in COINS:
                            continue

                        if coin not in self._last_ts:
                            self._last_ts[coin] = ts
                            self._last_price[coin] = price
                            self._last_high[coin] = high
                            self._last_low[coin] = low
                        elif ts > self._last_ts[coin]:
                            with _lock:
                                self._ohlcv[coin]["close"].append(self._last_price[coin])
                                self._ohlcv[coin]["high"].append(self._last_high[coin])
                                self._ohlcv[coin]["low"].append(self._last_low[coin])
                                if len(self._ohlcv[coin]["close"]) > HISTORY_DEPTH:
                                    self._ohlcv[coin]["close"].pop(0)
                                    self._ohlcv[coin]["high"].pop(0)
                                    self._ohlcv[coin]["low"].pop(0)
                            self._last_ts[coin] = ts
                            self._last_high[coin] = high
                            self._last_low[coin] = low

                            _get_redis().set_config("ai_loop_heartbeat", str(time.time()))

                            # --- Double RSI Trend Gatekeeper ---
                            try:
                                r = _get_redis()
                                pos_tp = r.get_config(f"position_tp_usd:{coin}", "")
                                tp_usd = float(pos_tp) if pos_tp else float(r.get_config("tp_usd", "1.0"))
                                cur = self._last_price.get(coin, 0.0)
                                active_tp_pct = (tp_usd / cur) if cur > 0 else 0.01
                                active_tp_pct = max(0.001, min(active_tp_pct, 0.1))
                            except Exception:
                                active_tp_pct = 0.01

                            analysis = evaluate_coin_momentum(
                                self._ohlcv[coin]["close"],
                                self._ohlcv[coin]["high"],
                                self._ohlcv[coin]["low"],
                                active_tp_pct,
                            )
                            try:
                                _get_redis().set_config_with_ttl(
                                    f"rsi_status:{coin}",
                                    json.dumps({
                                        "value": analysis["rsi_value"],
                                        "suggestion": analysis["suggestion"],
                                        "logic": analysis["logic"],
                                        "confidence_score": analysis["confidence_score"],
                                    }),
                                    ttl=300,
                                )
                            except Exception:
                                pass

                            if analysis["suggestion"] == "wait":
                                logger.debug(f"[FILTER-SKIP] {coin} is flat. Skipping.")
                            else:
                                logger.info(
                                    f"[RSI-BREAKOUT] {coin} {analysis['suggestion'].upper()} | "
                                    f"Score: {analysis['score']}"
                                )
                                self.current_15m_signals[coin] = {
                                    "suggestion": analysis["suggestion"],
                                    "confidence_score": analysis["confidence_score"],
                                }

                            self.processed_coins.add(coin)

                            if len(self.processed_coins) == 7:
                                if self.current_15m_signals:
                                    best_coin = max(
                                        self.current_15m_signals,
                                        key=lambda k: self.current_15m_signals[k]["confidence_score"],
                                    )
                                    best_data = self.current_15m_signals[best_coin]
                                    logger.info(
                                        f"[EXECUTION-FILTER] Sniper Triggered! Top Signal: {best_coin} "
                                        f"{best_data['suggestion'].upper()} | Score: {best_data['confidence_score']}"
                                    )
                                    try:
                                        _get_redis().set_config_with_ttl(
                                            "batch_winner",
                                            json.dumps({
                                                "coin": best_coin,
                                                "suggestion": best_data["suggestion"],
                                                "confidence_score": best_data["confidence_score"],
                                                "timestamp": time.time(),
                                            }),
                                            ttl=600,
                                        )
                                    except Exception:
                                        pass
                                    # DISABLED: Old RSI→Gemini bridge — superseded by Double RSI Trend direct execution.
                                    # from bot.main import _run_single_coin_signal
                                    # ...
                                    from bot.main import open_trade
                                    trade_signal = {
                                        "direction": best_data["suggestion"],
                                        "confidence": best_data["confidence_score"],
                                    }
                                    logger.info(
                                        f"[EXECUTION-FILTER] Routing {best_coin} {trade_signal['direction']} "
                                        f"to open_trade..."
                                    )
                                    try:
                                        result = open_trade(trade_signal, coin=best_coin)
                                        if result:
                                            logger.info(
                                                f"[EXECUTION] {best_coin} {trade_signal['direction']} "
                                                f"trade placed successfully!"
                                            )
                                        else:
                                            logger.warning(
                                                f"[EXECUTION] {best_coin} trade rejected by open_trade."
                                            )
                                    except Exception as e:
                                        logger.exception(
                                            f"[EXECUTION-ERROR] {best_coin} open_trade failed: {e}"
                                        )
                                else:
                                    logger.info(
                                        "[EXECUTION-FILTER] All 7 coins returned 'wait'. No trade this cycle."
                                    )
                                self.current_15m_signals.clear()
                                self.processed_coins.clear()

                        else:
                            if high > self._last_high[coin]:
                                self._last_high[coin] = high
                            if low < self._last_low[coin]:
                                self._last_low[coin] = low

                        self._last_price[coin] = price

            except websockets.ConnectionClosed:
                logger.warning("WS disconnected — reconnecting in 5s")
                self.current_15m_signals.clear()
                self.processed_coins.clear()
                await asyncio.sleep(5)
            except Exception as e:
                logger.exception(f"WS error: {e}")
                await asyncio.sleep(5)
