import json
import time
import random
import logging
import httpx
import pandas as pd

from bot.config import OPENROUTER_API_KEYS, OPENROUTER_MODELS
from bot.signals.rules import ema, rsi, macd, atr, bollinger_bands, adx, sma

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"

ALL_MODEL_IDS = [m.strip() for m in OPENROUTER_MODELS.split(",") if m.strip()]

def _build_model_keys() -> dict[str, str]:
    seen: dict[str, int] = {}
    keys: dict[str, str] = {}
    for m in ALL_MODEL_IDS:
        short = m.split("/")[-1].split(":")[0]
        idx = seen.get(short, 0)
        seen[short] = idx + 1
        key = f"{short}#{idx}"
        keys[key] = m
    return keys

MODELS: dict[str, str] = _build_model_keys()
MODEL_KEYS: list[str] = list(MODELS.keys())

def get_model_defs() -> list[dict]:
    defs = []
    for key, model_id in MODELS.items():
        name = key.rsplit("#", 1)[0]
        defs.append({"key": key, "model_id": model_id, "name": name})
    return defs


def compute_indicators(ohlcv: pd.DataFrame) -> dict:
    closes = ohlcv["close"]
    highs = ohlcv["high"]
    lows = ohlcv["low"]
    volumes = ohlcv["volume"]

    ema_9 = ema(closes, 9)
    ema_21 = ema(closes, 21)
    ema_50 = ema(closes, 50)
    rsi_v = rsi(closes, 14)
    macd_v = macd(closes)
    atr_v = atr(highs, lows, closes, 14)
    bb = bollinger_bands(closes, 20)
    vol_ma_20 = sma(volumes, 20)
    adx_v = adx(highs, lows, closes, 14)

    last = lambda s: float(s.iloc[-1]) if s is not None and not s.empty else 0.0
    prev = lambda s: float(s.iloc[-2]) if s is not None and len(s) > 1 else 0.0

    return {
        "close": last(closes),
        "open": last(ohlcv["open"]),
        "high": last(highs),
        "low": last(lows),
        "volume": last(volumes),
        "ema_9": last(ema_9),
        "ema_21": last(ema_21),
        "ema_50": last(ema_50),
        "rsi": last(rsi_v),
        "macd_line": last(macd_v["macd"]),
        "macd_signal": last(macd_v["signal"]),
        "macd_histogram": last(macd_v["histogram"]),
        "atr": last(atr_v),
        "bb_upper": last(bb["upper"]),
        "bb_mid": last(bb["mid"]),
        "bb_lower": last(bb["lower"]),
        "vol_ma_20": last(vol_ma_20),
        "adx": last(adx_v),
        "ema_9_prev": prev(ema_9),
        "ema_21_prev": prev(ema_21),
    }


def build_prompt(indicators: dict, regime: str = "UNKNOWN", allow_wait: bool = True,
                 tp_usd: float = 3.0, sl_usd: float = 3.0,
                 leverage: int = 10, trade_amount: float = 10.0) -> str:
    i = indicators
    vol_ratio = i["volume"] / i["vol_ma_20"] if i["vol_ma_20"] > 0 else 1.0
    bb_pct = (i["close"] - i["bb_lower"]) / (i["bb_upper"] - i["bb_lower"]) if (i["bb_upper"] - i["bb_lower"]) > 0 else 0.5

    trend = "bullish" if i["ema_9"] > i["ema_21"] > i["ema_50"] else "bearish" if i["ema_9"] < i["ema_21"] < i["ema_50"] else "mixed"

    notional = trade_amount * leverage
    tp_pct = (tp_usd / notional) * 100
    sl_pct = (sl_usd / notional) * 100

    wait_rule = "\n- WAIT if trend is unclear or volatility too high" if allow_wait else ""
    direction_enum = '"long"|"short"|"wait"' if allow_wait else '"long"|"short"'

    return f"""You are a DOGE perpetual futures analyst. Analyze this market data and decide LONG, SHORT, or WAIT.

Current price: ${i['close']:.5f}
24h range: ${i['low']:.5f} - ${i['high']:.5f}
Trend (EMA 9/21/50): {trend}
RSI(14): {i['rsi']:.1f}
MACD histogram: {i['macd_histogram']:.6f}
ADX(14): {i['adx']:.1f}
ATR(14): ${i['atr']:.5f}
Bollinger %B: {bb_pct:.2f}
Volume ratio (vs 20-avg): {vol_ratio:.2f}x
Market regime: {regime}

Trade config:
- Position: ${trade_amount} margin @ {leverage}x = ${notional:.0f} notional
- Target profit: ${tp_usd} ({tp_pct:.2f}% move needed)
- Stop loss: ${sl_usd} ({sl_pct:.2f}% adverse move)
- Only enter if the market can realistically move {tp_pct:.2f}% in your direction{wait_rule}

Respond ONLY with valid JSON:
{{"direction": {direction_enum}, "confidence": 0.0-1.0, "reasoning": "..."}}"""


def call_model(key: str, model: str, prompt: str, timeout: int = 15, api_keys: list[str] | None = None) -> dict | None:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 300,
    }
    keys = api_keys or OPENROUTER_API_KEYS
    time.sleep(random.uniform(1, 3))
    for attempt, api_key in enumerate(keys):
        if attempt > 0:
            time.sleep(random.uniform(3, 6))
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://doge-perp-bot.vercel.app",
            "X-Title": "DOGE Perp Bot",
        }
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(OPENROUTER_BASE, json=payload, headers=headers)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    logger.warning(f"{key} (key#{attempt}): 429 — retry-after={retry_after}s, trying next key")
                    time.sleep(min(retry_after, 10))
                    continue
                if resp.status_code != 200:
                    logger.warning(f"{key}: HTTP {resp.status_code} {resp.text[:200]}")
                    return None
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                if parsed.get("direction") not in ("long", "short", "wait"):
                    logger.warning(f"{key}: invalid direction {parsed.get('direction')}")
                    return None
                name = key.rsplit("#", 1)[0]
                return {
                    "key": key,
                    "model": model,
                    "name": name,
                    "direction": parsed["direction"],
                    "confidence": float(parsed.get("confidence", 0.5)),
                    "reasoning": parsed.get("reasoning", ""),
                }
        except Exception as e:
            logger.debug(f"{key} (key#{attempt}): {e}")
            continue
    logger.warning(f"{key}: all {len(keys)} api keys exhausted")
    return None


def generate_signal(ohlcv: pd.DataFrame, enabled_models: list[str] | None = None, api_keys: list[str] | None = None, allow_wait: bool = True,
                   tp_usd: float = 3.0, sl_usd: float = 3.0,
                   leverage: int = 10, trade_amount: float = 10.0) -> dict:
    if ohlcv.empty or len(ohlcv) < 50:
        logger.warning("Not enough data for OpenRouter signal")
        return {"direction": "wait", "confidence": 0.3, "regime": "UNKNOWN", "reasoning": "Insufficient data", "model_details": []}

    keys_to_run = [k for k in MODEL_KEYS if enabled_models is None or k in enabled_models]
    if not keys_to_run:
        logger.warning("No models enabled — returning wait")
        return {"direction": "wait", "confidence": 0.3, "regime": "UNKNOWN", "reasoning": "All models disabled", "model_details": []}

    regime = _detect_regime(ohlcv)
    indicators = compute_indicators(ohlcv)
    prompt = build_prompt(indicators, regime, allow_wait, tp_usd, sl_usd, leverage, trade_amount)

    votes = {"long": 0.0, "short": 0.0, "wait": 0.0}
    details = []

    for i, k in enumerate(keys_to_run):
        if i > 0:
            time.sleep(random.uniform(2, 5))
        result = call_model(k, MODELS[k], prompt, 15, api_keys)
        if result:
            votes[result["direction"]] += result["confidence"]
            details.append(result)

    if not details:
        logger.warning("All OpenRouter models failed — returning wait")
        return {"direction": "wait", "confidence": 0.3, "regime": regime, "reasoning": "AI models unavailable", "model_details": [], "prompt": prompt}

    sorted_dirs = sorted(votes, key=lambda d: votes[d], reverse=True)
    winner = sorted_dirs[0]
    runner_up = sorted_dirs[1]

    if len(details) >= 2 and votes[winner] - votes[runner_up] < 0.1 and allow_wait:
        winner = "wait"

    avg_conf = votes[winner] / max(len([d for d in details if d["direction"] == winner]), 1)

    reasons = "; ".join(f"{d['name']}: {d['direction']} ({d['confidence']:.2f})" for d in details)

    logger.info(f"OpenRouter vote: winner={winner} conf={avg_conf:.2f} models={len(details)}")
    return {
        "direction": winner,
        "confidence": round(min(avg_conf, 0.95), 2),
        "regime": regime,
        "reasoning": reasons,
        "prompt": prompt,
        "model_details": details,
    }


def _detect_regime(ohlcv: pd.DataFrame) -> str:
    closes = ohlcv["close"]
    highs = ohlcv["high"]
    lows = ohlcv["low"]
    volumes = ohlcv["volume"]

    adx_v = adx(highs, lows, closes, 14)
    atr_v = atr(highs, lows, closes, 14)
    vol_ma = sma(volumes, 20)

    adx_last = float(adx_v.iloc[-1]) if not adx_v.empty else 0
    atr_last = float(atr_v.iloc[-1]) if not atr_v.empty else 0
    close_last = float(closes.iloc[-1])
    vol_ratio = float(volumes.iloc[-1]) / float(vol_ma.iloc[-1]) if float(vol_ma.iloc[-1]) > 0 else 1.0

    ema_9 = float(ema(closes, 9).iloc[-1])
    ema_21 = float(ema(closes, 21).iloc[-1])
    ema_50 = float(ema(closes, 50).iloc[-1])

    vol_pct = atr_last / close_last if close_last > 0 else 0
    if vol_pct > 0.03 or vol_ratio > 2.0:
        return "HIGH_VOL"
    if adx_last > 25:
        if ema_9 > ema_21 > ema_50:
            return "TRENDING_UP"
        if ema_9 < ema_21 < ema_50:
            return "TRENDING_DOWN"
        return "TRENDING"
    return "RANGING"
