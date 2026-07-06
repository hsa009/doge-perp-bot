import asyncio
import json
import logging
import time
import threading

import httpx
import websockets

import pandas as pd
from functools import partial

from bot.indicators import evaluate_coin_momentum
from bot.redis_client import RedisClient
from bot.config import get_coin_gemini_keys
from bot.signals.providers import generate_signal

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
        self._last_ai_request: dict[str, float] = {}

    async def _dispatch_ai_confirmation(self, coin: str, sentiment: str,
                                        rsi_value: float, logic: str,
                                        price: float, ts: int):
        now = time.time()
        last = self._last_ai_request.get(coin, 0.0)
        if now - last < 60:
            logger.debug(f"[AI-COOLDOWN] {coin} — skipping, only {now-last:.0f}s since last request")
            return
        self._last_ai_request[coin] = now

        logger.info(f"[AI-WAKEUP] {coin} {sentiment} breakout (RSI={rsi_value}). Dispatching to Gemini...")

        try:
            closes = self._history[coin]
            df = pd.DataFrame({
                "close": closes,
                "high": [c * 1.001 for c in closes],
                "low": [c * 0.999 for c in closes],
                "open": closes,
                "volume": [0.0] * len(closes),
            })

            r = _get_redis()
            tp_usd = float(r.get_config("tp_usd", "3.0"))
            sl_usd = float(r.get_config("sl_usd", "3.0"))
            leverage = int(r.get_config("leverage", "10"))
            trade_amount = float(r.get_config("trade_amount", "10.0"))
            gemini_keys = get_coin_gemini_keys(coin)

            loop = asyncio.get_event_loop()
            signal = await loop.run_in_executor(
                None,
                partial(
                    generate_signal,
                    df,
                    coin=coin,
                    enabled_models=[],
                    tp_usd=tp_usd,
                    sl_usd=sl_usd,
                    leverage=leverage,
                    trade_amount=trade_amount,
                    market_context={},
                    gemini_api_keys=gemini_keys,
                    db=None,
                    macro_trend="mixed",
                    liq_price=0.0,
                    liq_dist_pct=0.0,
                ),
            )

            if signal and signal.get("direction") == sentiment:
                logger.info(
                    f"[TRADE-CONFIRMED] {coin} {sentiment} "
                    f"(conf={signal.get('confidence', 0):.2f}). Executing..."
                )
                from bot.main import safe_to_trade, open_trade
                if safe_to_trade(coin, sentiment):
                    signal["_coin"] = coin
                    open_trade(signal, coin=coin)
                else:
                    logger.warning(f"[TRADE-BLOCKED] {coin} — safe_to_trade returned False")
            else:
                logger.info(
                    f"[TRADE-REJECTED] {coin} Gemini ({signal.get('direction', '?')}) "
                    f"disagreed with RSI ({sentiment})."
                )

        except Exception as e:
            logger.error(f"[AI-ERROR] {coin}: {e}")

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

                            # --- RSI Gatekeeper ---
                            try:
                                r = _get_redis()
                                pos_tp = r.get_config(f"position_tp_usd:{coin}", "")
                                tp_usd = float(pos_tp) if pos_tp else float(r.get_config("tp_usd", "1.0"))
                                cur = self._last_price.get(coin, 0.0)
                                active_tp_pct = (tp_usd / cur) if cur > 0 else 0.01
                                active_tp_pct = max(0.001, min(active_tp_pct, 0.1))
                            except Exception:
                                active_tp_pct = 0.01

                            analysis = evaluate_coin_momentum(self._history[coin], active_tp_pct)
                            try:
                                _get_redis().set_config_with_ttl(
                                    f"rsi_status:{coin}",
                                    json.dumps({
                                        "value": analysis["rsi_value"],
                                        "suggestion": analysis["suggestion"],
                                        "logic": analysis["logic"],
                                    }),
                                    ttl=120,
                                )
                            except Exception:
                                pass
                            if analysis["suggestion"] == "wait":
                                logger.debug(f"[RSI-GATE] {coin} flat at {analysis['rsi_value']}. Suppressing AI.")
                            else:
                                logger.info(f"[RSI-TRIGGER] {coin} breakout! RSI: {analysis['rsi_value']} | Dir: {analysis['suggestion'].upper()}")
                                asyncio.create_task(
                                    self._dispatch_ai_confirmation(
                                        coin=coin,
                                        sentiment=analysis["suggestion"],
                                        rsi_value=analysis["rsi_value"],
                                        logic=analysis["logic"],
                                        price=price,
                                        ts=ts,
                                    )
                                )

                        self._last_price[coin] = price

            except websockets.ConnectionClosed:
                logger.warning("WS disconnected — reconnecting in 5s")
                await asyncio.sleep(5)
            except Exception as e:
                logger.exception(f"WS error: {e}")
                await asyncio.sleep(5)
