import json
import uuid
import time
import random
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import pandas as pd

from bot.config import AI_MODELS, GROQ_API_KEY, GEMINI_API_KEY, GEMINI_API_KEYS, GEMINI_MODEL
from bot.signals.rules import ema, rsi, macd, atr, bollinger_bands, adx, sma

logger = logging.getLogger(__name__)

GROQ_BASE = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

ALL_MODEL_IDS = [m.strip() for m in AI_MODELS.split(",") if m.strip()]


def _build_model_keys() -> dict[str, str]:
    seen: dict[str, int] = {}
    keys: dict[str, str] = {}
    for m in ALL_MODEL_IDS:
        short = m.split(":")[-1].replace("-", "").replace(".", "").replace("_", "")
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
        name = model_id.split(":")[-1]
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


def build_prompt(indicators: dict, regime: str = "UNKNOWN", coin: str = "DOGE", allow_wait: bool = True,
                 tp_usd: float = 3.0, sl_usd: float = 3.0,
                 leverage: int = 10, trade_amount: float = 10.0,
                 last_signal_direction: str | None = None,
                 last_signal_reasoning: str | None = None,
                 consecutive_waits: int = 0,
                 current_pnl: float | None = None,
                 market_context: dict | None = None) -> str:
    i = indicators
    vol_ratio = i["volume"] / i["vol_ma_20"] if i["vol_ma_20"] > 0 else 1.0
    bb_pct = (i["close"] - i["bb_lower"]) / (i["bb_upper"] - i["bb_lower"]) if (i["bb_upper"] - i["bb_lower"]) > 0 else 0.5

    trend = "bullish" if i["ema_9"] > i["ema_21"] > i["ema_50"] else "bearish" if i["ema_9"] < i["ema_21"] < i["ema_50"] else "mixed"

    notional = trade_amount * leverage
    tp_pct = (tp_usd / notional) * 100
    sl_pct = (sl_usd / notional) * 100

    history_block = ""
    if last_signal_direction:
        history_block += f"\nPrevious signal: {last_signal_direction.upper()}"
        if last_signal_reasoning:
            history_block += f" — \"{last_signal_reasoning[:80]}\""
    if current_pnl is not None:
        history_block += f"\nUnrealized PnL: ${current_pnl:.2f}"
    if consecutive_waits >= 3:
        allow_wait = False
        history_block += "\nYou have chosen WAIT multiple times. You MUST choose LONG or SHORT now."

    market_block = ""
    if market_context:
        ob = market_context.get("order_book", {})
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        bid_vol = ob.get("bid_volume", 0)
        ask_vol = ob.get("ask_volume", 0)
        spread_pct = ob.get("spread_pct", 0)
        funding_rate = market_context.get("funding_rate", 0)
        funding_ann = market_context.get("funding_annualized_pct", 0)
        funding_sig = market_context.get("funding_signal", "neutral")
        oi = market_context.get("open_interest", 0)

        closes_str = ", ".join(f"${c:.5f}" for c in market_context.get("recent_closes", []))

        bid_px_str = f"${bids[0][0]:.5f}" if bids else "?"
        ask_px_str = f"${asks[0][0]:.5f}" if asks else "?"
        ratio_str = f"{bid_vol / ask_vol:.2f}x" if ask_vol > 0 else "N/A"

        market_block = f"""
Market Context:
  Order Book: Bids {int(bid_vol)} @ {bid_px_str} vs Asks {int(ask_vol)} @ {ask_px_str}
  Bid/Ask Ratio: {ratio_str}
  Spread: {spread_pct:.4f}%
  Funding Rate: {funding_rate:.6f}% hourly ({funding_ann:.2f}% APR) — {funding_sig}
  Open Interest: ${oi:,.0f}
  Recent Close Trend (last 15): {closes_str}"""

    wait_rule = "\n- WAIT if trend is unclear or volatility too high" if allow_wait else ""
    direction_enum = '"long"|"short"|"wait"' if allow_wait else '"long"|"short"'

    return f"""You are a {coin} perpetual futures analyst. Analyze the technical data to decide LONG, SHORT, or WAIT.

=== TECHNICAL ANALYSIS ===
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
{market_block}
Trade config:
- Position: ${trade_amount} margin @ {leverage}x = ${notional:.0f} notional
- Target profit: ${tp_usd} ({tp_pct:.2f}% move needed)
- Stop loss: ${sl_usd} ({sl_pct:.2f}% adverse move)

Analysis checklist:
- Trend direction and strength (EMA alignment, ADX)
- Momentum (RSI, MACD histogram direction)
- Volume confirmation
- Support/resistance from Bollinger Bands
- ATR for volatility assessment
- Overall risk/reward for a {tp_pct:.2f}% target vs {sl_pct:.2f}% stop
{history_block}
Respond ONLY with valid JSON. Keep reasoning under 50 words:
{{"direction": {direction_enum}, "confidence": 0.0-1.0, "reasoning": "..."}}"""


def call_groq(key: str, model: str, prompt: str, timeout: int = 15, groq_api_key: str | None = None) -> dict | None:
    if not groq_api_key:
        groq_api_key = GROQ_API_KEY
    if not groq_api_key:
        logger.warning(f"{key}: no Groq API key configured")
        return None

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 300,
    }
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(GROQ_BASE, json=payload, headers=headers)
            if resp.status_code == 429:
                logger.warning(f"{key}: 429 rate limited")
                return None
            if resp.status_code != 200:
                logger.warning(f"{key}: HTTP {resp.status_code} {resp.text[:200]}")
                return None
            body = resp.json()
            content = body["choices"][0]["message"]["content"]
            return _parse_response(key, model, model, content)
    except Exception as e:
        logger.debug(f"{key}: {e}")
        return None


GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

def call_gemini_http(api_key: str, key_label: str, prompt: str) -> dict | None:
    url = f"{GEMINI_BASE}/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 1500,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning(f"{key_label}: HTTP {resp.status_code} {resp.text[:200]}")
                return {"_error": f"HTTP_{resp.status_code}"}
            body = resp.json()
            candidates = body.get("candidates", [])
            if not candidates:
                logger.warning(f"{key_label}: no candidates")
                return {"_error": "no_candidates"}
            c = candidates[0]
            finish = c.get("finishReason", "unknown")
            parts = c.get("content", {}).get("parts", [])
            if not parts or not parts[0].get("text", ""):
                logger.warning(f"{key_label}: no text finishReason={finish}")
                return {"_error": f"no_text_{finish}"}
            content = parts[0]["text"]
            extracted = _extract_json(content)
            import json as _json
            parse_err = ""
            try:
                _json.loads(extracted)
            except Exception as e:
                parse_err = str(e)[:100]
            parsed = _parse_response(key_label, GEMINI_MODEL, key_label, extracted)
            if parsed is None:
                return {"_error": f"parse_fail_{parse_err or 'unknown'}"}
            return parsed
    except Exception as e:
        logger.warning(f"{key_label}: Gemini HTTP call failed — {e}")
        return {"_error": f"EXC_{e}"}


def _extract_json(text: str) -> str:
    idx = text.find("{")
    if idx == -1:
        return text
    text = text[idx:]
    depth = 0
    in_string = False
    escaped = False
    end = 0
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == 0:
        return text
    return _clean_json(text[:end])


def _clean_json(s: str) -> str:
    s = s.strip()
    if s.endswith("```"):
        s = s[:-3]
    s = s.strip()
    import re
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*]", "]", s)
    return s


def _parse_response(key: str, model: str, name: str, content: str) -> dict | None:
    try:
        parsed = json.loads(content)
        if parsed.get("direction") not in ("long", "short", "wait"):
            logger.warning(f"{key}: invalid direction {parsed.get('direction')}")
            return None
        return {
            "key": key,
            "model": model,
            "name": name,
            "direction": parsed["direction"],
            "confidence": float(parsed.get("confidence", 0.5)),
            "reasoning": parsed.get("reasoning", ""),
        }
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"{key}: failed to parse response: {e}")
        return None


def build_tiebreaker_prompt(original_prompt: str, all_details: list[dict], coin: str = "DOGE") -> str:
    models_block = ""
    for d in all_details:
        models_block += f"\n{d['name']}: {d['direction'].upper()} ({d['confidence']:.2f})"
        if d.get("reasoning"):
            models_block += f"\n  Reasoning: \"{d['reasoning']}\""

    return f"""{original_prompt}

=== TIEBREAKER ===
Two models disagreed:{models_block}

You are the tiebreaker. Analyze the market data and both arguments, then decide.
Respond ONLY with valid JSON:
{{"direction": "long"|"short"|"wait", "confidence": 0.0-1.0, "reasoning": "..."}}"""


def generate_signal(ohlcv: pd.DataFrame, coin: str = "DOGE", enabled_models: list[str] | None = None, allow_wait: bool = True,
                   tp_usd: float = 3.0, sl_usd: float = 3.0,
                   leverage: int = 10, trade_amount: float = 10.0,
                   groq_api_key: str | None = None,
                   last_signal_direction: str | None = None,
                   last_signal_reasoning: str | None = None,
                   consecutive_waits: int = 0,
                   current_pnl: float | None = None,
                   market_context: dict | None = None,
                   gemini_api_keys: list[str] | None = None,
                   db=None) -> dict:
    if ohlcv.empty or len(ohlcv) < 50:
        logger.warning("Not enough data for AI signal")
        return {"direction": "wait", "confidence": 0.3, "regime": "UNKNOWN", "reasoning": "Insufficient data", "model_details": [], "vote_tally": {}}

    if enabled_models is not None and not enabled_models:
        logger.warning("enabled_models is empty list — falling back to MODEL_KEYS")
        enabled_models = None

    keys_to_run = [k for k in MODEL_KEYS if enabled_models is None or k in enabled_models]
    logger.info("MODEL_KEYS=%s enabled_models=%s keys_to_run=%s", MODEL_KEYS, enabled_models, keys_to_run)
    if not keys_to_run:
        logger.warning("No models enabled — returning wait")
        return {"direction": "wait", "confidence": 0.3, "regime": "UNKNOWN", "reasoning": "All models disabled", "model_details": [],
                "_debug_enabled_models": enabled_models, "_debug_model_keys": MODEL_KEYS, "vote_tally": {}}

    regime = _detect_regime(ohlcv)
    indicators = compute_indicators(ohlcv)

    if market_context and ohlcv is not None and not ohlcv.empty:
        closes = [round(float(c), 5) for c in ohlcv["close"].tail(15).tolist()]
        market_context["recent_closes"] = closes

    prompt = build_prompt(indicators, regime, coin, allow_wait, tp_usd, sl_usd, leverage, trade_amount,
                          last_signal_direction, last_signal_reasoning, consecutive_waits, current_pnl,
                          market_context=market_context)

    cycle_id = uuid.uuid4().hex[:12]
    votes = {"long": 0, "short": 0, "wait": 0}
    details: list[dict] = []
    gemini_keys = gemini_api_keys if gemini_api_keys is not None else GEMINI_API_KEYS

    def _save_vote(entry: dict | None, voter_label: str, voter_type: str):
        if entry and "_error" not in entry:
            votes[entry["direction"]] += 1
            details.append(entry)
        if db and db.enabled:
            try:
                db.client.table("ai_votes").insert({
                    "cycle_id": cycle_id,
                    "coin": coin,
                    "voter": voter_label,
                    "voter_type": voter_type,
                    "direction": entry["direction"] if entry else None,
                    "confidence": entry.get("confidence") if entry else None,
                    "reasoning": (entry.get("reasoning", "")[:500] if entry else None),
                    "error": None if entry else "call_failed",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }).execute()
            except Exception as e:
                logger.debug(f"save_ai_vote error for {voter_label}: {e}")

    _debug_calls: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(keys_to_run)) as executor:
        futures = {}
        for k in keys_to_run:
            futures[executor.submit(call_groq, k, MODELS[k].split(":")[-1], prompt, 15, groq_api_key)] = k
        for future in as_completed(futures):
            key = futures[future]
            try:
                result = future.result()
                _debug_calls[f"groq_{key}"] = "ok" if result else "returned_none"
                _save_vote(result, key, "groq")
            except Exception as e:
                _debug_calls[f"groq_{key}"] = f"EXC: {e}"
                logger.warning(f"{key}: exception {e}")

    for i, key in enumerate(gemini_keys):
        if i > 0:
            time.sleep(random.uniform(2, 5))
        result = call_gemini_http(key, f"gemini#{i}", prompt)
        _debug_calls[f"gemini#{i}"] = result.get("_error", "ok") if isinstance(result, dict) else ("ok" if result else "returned_none")
        _save_vote(result, f"gemini#{i}", "gemini")

    if not details:
        logger.warning("All voters failed — returning wait")
        return {"direction": "wait", "confidence": 0.3, "regime": regime, "reasoning": "AI models unavailable", "model_details": [], "prompt": prompt, "vote_tally": dict(votes), "cycle_id": cycle_id, "_debug_calls": _debug_calls}

    max_count = max(votes.values())
    winners = [d for d, c in votes.items() if c == max_count]

    if len(winners) > 1 and allow_wait:
        winner = "wait"
    else:
        winner = winners[0]

    total_voters = len(details)
    confidence = max_count / total_voters if total_voters > 0 else 0.0

    reasons = "; ".join(f"{d['name']}: {d['direction']} ({d['confidence']:.2f})" for d in details)

    logger.info(f"Vote: winner={winner} conf={confidence:.2f} voters={total_voters} tally={dict(votes)} cycle={cycle_id}")
    return {
        "direction": winner,
        "confidence": round(min(confidence, 0.95), 2),
        "regime": regime,
        "reasoning": reasons,
        "prompt": prompt,
        "model_details": details,
        "vote_tally": dict(votes),
        "cycle_id": cycle_id,
        "_debug_calls": _debug_calls,
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
