import json
import uuid
import time
import random
import threading
import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

import httpx
import pandas as pd

from bot.config import AI_MODELS, get_coin_gemini_keys
from bot.signals.rules import ema, rsi, macd, atr, bollinger_bands, adx, sma

logger = logging.getLogger(__name__)

from bot.signals.throttle import ProviderThrottle

SECONDARY_PROVIDERS: dict[str, dict] = {
    "WIF":    {"base_url": "https://api.sambanova.ai/v1/chat/completions", "env_var": "WIF_SAMBANOVA_KEY",    "model": "Meta-Llama-3.3-70B-Instruct", "provider": "SambaNova", "throttle": "sambanova"},
    "POPCAT": {"base_url": "https://api.sambanova.ai/v1/chat/completions", "env_var": "POPCAT_SAMBANOVA_KEY", "model": "Meta-Llama-3.3-70B-Instruct", "provider": "SambaNova", "throttle": "sambanova"},
    "DOGE":   {"base_url": "https://api.cerebras.ai/v1/chat/completions",  "env_var": "DOGE_CEREBRAS_KEY",    "model": "gemma-4-31b",                  "provider": "Cerebras",  "throttle": "cerebras"},
    "SUI":    {"base_url": "https://api.cerebras.ai/v1/chat/completions",  "env_var": "SUI_CEREBRAS_KEY",     "model": "gemma-4-31b",                  "provider": "Cerebras",  "throttle": "cerebras"},
    "SOL":    {"base_url": "https://api.groq.com/openai/v1/chat/completions", "env_var": "SOL_GROQ_KEY",     "model": "qwen/qwen3.6-27b", "provider": "Groq",      "throttle": "groq"},
    "JUP":    {"base_url": "https://api.groq.com/openai/v1/chat/completions", "env_var": "JUP_GROQ_KEY",     "model": "qwen/qwen3.6-27b", "provider": "Groq",      "throttle": "groq"},
    "PYTH":   {"base_url": "https://api.groq.com/openai/v1/chat/completions", "env_var": "PYTH_GROQ_KEY",    "model": "qwen/qwen3.6-27b", "provider": "Groq",      "throttle": "groq"},
}

_provider_throttles: dict[str, ProviderThrottle] = {
    "sambanova": ProviderThrottle(1000),
    "cerebras":  ProviderThrottle(2000),
    "groq":      ProviderThrottle(2000),
}

SECONDARY_PROVIDER_INFO: dict[str, str] = {coin: info["provider"] for coin, info in SECONDARY_PROVIDERS.items()}

MAX_SIGNAL_AGE_S = 4.0

VOTER_DEADLINE_S = 180

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


_GEMINI_KEY_RING: list[str] = []
_GEMINI_KEY_INDEX = 0
_GEMINI_RING_LOCK = threading.Lock()


def _build_gemini_key_ring() -> list[str]:
    from bot.config import COIN_LIST
    keys: list[str] = []
    for coin in COIN_LIST:
        k = os.environ.get(f"{coin}_GEMINI_KEY", "")
        if k:
            keys.append(k)
    logger.info(f"Gemini key ring: {len(keys)} keys from {len(COIN_LIST)} coins")
    return keys


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


def build_prompt(indicators: dict, regime: str = "UNKNOWN", coin: str = "DOGE",
                 tp_usd: float = 3.0, sl_usd: float = 3.0,
                 leverage: int = 10, trade_amount: float = 10.0,
                 last_signal_direction: str | None = None,
                 last_signal_reasoning: str | None = None,
                 consecutive_waits: int = 0,
                 current_pnl: float | None = None,
                 market_context: dict | None = None,
                 macro_trend: str = "mixed",
                 liq_price: float = 0.0,
                 liq_dist_pct: float = 0.0) -> str:
    i = indicators
    vol_ratio = i["volume"] / i["vol_ma_20"] if i["vol_ma_20"] > 0 else 1.0
    bb_pct = (i["close"] - i["bb_lower"]) / (i["bb_upper"] - i["bb_lower"]) if (i["bb_upper"] - i["bb_lower"]) > 0 else 0.5

    notional = trade_amount * leverage
    tp_pct = (tp_usd / notional) * 100
    sl_pct = (sl_usd / notional) * 100

    close_price = i["close"]
    atr_val = i["atr"]
    tp_pct_dist = (tp_usd / close_price) * 100
    sl_pct_dist = (sl_usd / close_price) * 100
    atr_vel_pct = (atr_val / close_price) * 100

    history_block = ""
    if last_signal_direction:
        history_block += f"\nPrevious signal: {last_signal_direction.upper()}"
        if last_signal_reasoning:
            history_block += f" — \"{last_signal_reasoning[:80]}\""
    if current_pnl is not None:
        history_block += f"\nUnrealized PnL: ${current_pnl:.2f}"

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
  Order Book: Bids {int(bid_vol)} @ {bid_px_str} vs Asks {int(ask_vol)} @ {ask_px_str}
  Bid/Ask Ratio: {ratio_str}
  Spread: {spread_pct:.4f}%
  Funding Rate: {funding_rate:.6f}% hourly ({funding_ann:.2f}% APR) — {funding_sig}
  Open Interest: ${oi:,.0f}
  Recent Close Trend (last 15): {closes_str}"""

    if consecutive_waits >= 3:
        conditional_block = (
            "=== CRITICAL CONDITIONALS ===\n"
            "\u26a0\ufe0f FORCED TIE-BREAKER PROTOCOL ACTIVE: You have chosen WAIT 3+ times "
            "consecutively. You are now REQUIRED to break the deadlock and select LONG or SHORT.\n"
            "1. Use the Order Book Ratio or Macro Trend to break the tie\u2014lean heavily in "
            "the direction of the macro bias.\n"
            "2. Because this is a forced choice under ambiguous conditions, your "
            '"confidence" score MUST reflect this. Set confidence strictly between '
            "0.1 and 0.4 to signal a low-probability forced entry."
        )
        direction_enum = '"long"|"short"'
    else:
        conditional_block = (
            "=== CRITICAL EXECUTION RULE ===\n"
            "Your primary directive is execution efficiency based on immediate math and order-flow.\n\n"
            "* TRIGGER LONG: Order book heavily favors bids, short-term price trend is accelerating upward, volume is high, and the calculated TP % is easily achievable within current ATR limits.\n"
            "* TRIGGER SHORT: Order book heavily favors asks, short-term price trend is cascading downward, volume confirms selling, and the calculated TP % is within current ATR limits.\n"
            "* TRIGGER WAIT: If the calculated TP % requires a price move that is too large relative to the current ATR (market is too dead to reach your target), if the risk/reward ratio is mathematically unfavorable, or if the order book is balanced 1:1."
        )
        direction_enum = '"long"|"short"|"wait"'

    return f"""You are a hyper-aggressive, high-frequency {coin} perpetual futures scalping engine. Your sole objective is to exploit micro-level order-flow imbalances and rapid liquidity shifts. You dynamically calculate risk-to-reward viability on every single tick.

=== TECHNICAL & CONFIG DATA ===
Current Price: ${close_price:.5f}
ATR(14): ${atr_val:.5f}
Bollinger %B: {bb_pct:.2f}
Volume ratio (vs 20-avg): {vol_ratio:.2f}x
Market regime: {regime}
Macro trend (4H/1D): {macro_trend}
Estimated Liquidation Price: ${liq_price} ({liq_dist_pct}% from current)
Position: ${trade_amount} margin @ {leverage}x = ${notional:.0f} notional
Target Profit: ${tp_usd} ({tp_pct:.2f}% of notional)
Stop Loss: ${sl_usd} ({sl_pct:.2f}% of notional)
{market_block}
{history_block}

=== REQUIRED PRE-TRADE MATHEMATICAL ASSESSMENT ===
1. TP % Distance = ({tp_usd} / {close_price}) * 100 = {tp_pct_dist:.4f}%
2. SL % Distance = ({sl_usd} / {close_price}) * 100 = {sl_pct_dist:.4f}%
3. ATR % Velocity = ({atr_val} / {close_price}) * 100 = {atr_vel_pct:.4f}%

=== SCALPER EVALUATION CHECKLIST ===
1. Volatility Feasibility: Compare TP % Distance ({tp_pct_dist:.4f}%) to ATR % Velocity ({atr_vel_pct:.4f}%). For a fast scalp, the TP % must be achievable within 1 to 3 average candle moves (ATR). If the target requires a massive, multi-ATR extension without explosive volume, flag it as unviable.
2. Order Book Delta (CRITICAL): Analyze the Bid/Ask ratio and spread. Massive imbalances (e.g., >3x) indicate immediate aggressive market orders hitting the book.
3. Micro-Momentum Velocity: Check the last 15 close prices. Is price accelerating toward the target? Ignore macro EMAs (4H/1D) if immediate short-term velocity is explosive.
4. Execution Environment: If Bollinger %B is near extremes (>= 0.90 or <= 0.10) combined with heavy volume, expect an immediate breakout extension toward your TP.

{conditional_block}

Respond ONLY with valid JSON. Keep reasoning under 50 words:
{{"direction": {direction_enum}, "confidence": 0.0-1.0, "reasoning": "[Include calculated TP% vs ATR% here] ..."}}"""


def call_openai_compat(base_url: str, api_key: str, model: str, prompt: str, key_label: str = "secondary", timeout: int = 30) -> dict | None:
    if not api_key:
        logger.warning(f"{key_label}: no API key configured")
        return None

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(base_url, json=payload, headers=headers)
            if resp.status_code == 429:
                logger.warning(f"{key_label}: 429 rate limited")
                return {"_error": "rate_limited_429"}
            if resp.status_code != 200:
                logger.warning(f"{key_label}: HTTP {resp.status_code} {resp.text[:200]}")
                return {"_error": f"HTTP_{resp.status_code}"}
            body = resp.json()
            content = body["choices"][0]["message"]["content"]
            extracted = _extract_json(content)
            parsed = _parse_response(key_label, model, key_label, extracted)
            return parsed
    except Exception as e:
        logger.warning(f"{key_label}: {e}")
        return {"_error": f"EXC_{e}"}


GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

def call_gemini_http(api_key: str, key_label: str, prompt: str) -> dict | None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
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
            parsed = _parse_response(key_label, "gemini-2.5-flash", key_label, extracted)
            if parsed is None:
                return {"_error": f"parse_fail_{parse_err or 'unknown'}"}
            return parsed
    except Exception as e:
        logger.warning(f"{key_label}: Gemini HTTP call failed — {e}")
        return {"_error": f"EXC_{e}"}


def call_gemini_http_with_retry(prompt: str, max_retries: int = 5) -> dict | None:
    global _GEMINI_KEY_RING, _GEMINI_KEY_INDEX

    if not _GEMINI_KEY_RING:
        _GEMINI_KEY_RING = _build_gemini_key_ring()
    if not _GEMINI_KEY_RING:
        logger.error("No Gemini keys available in key ring")
        return None

    last = None
    for attempt in range(max_retries):
        with _GEMINI_RING_LOCK:
            ring_len = len(_GEMINI_KEY_RING)
            key = _GEMINI_KEY_RING[_GEMINI_KEY_INDEX % ring_len]
            idx = _GEMINI_KEY_INDEX
            _GEMINI_KEY_INDEX += 1
        key_label = f"gemini#{idx}"
        last = call_gemini_http(key, key_label, prompt)
        if last and "_error" not in last:
            return last
        if last and ("HTTP_429" in str(last.get("_error", "")) or "HTTP_503" in str(last.get("_error", ""))):
            if attempt < max_retries - 1:
                delay = min(2 ** attempt, 30)
                logger.info(f"{key_label}: retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue
        else:
            return last

    return last


def _extract_json(text: str) -> str:
    # Find all balanced JSON objects and return the last valid one
    candidates: list[str] = []
    i = 0
    while True:
        start = text.find("{", i)
        if start == -1:
            break
        depth = 0
        in_string = False
        escaped = False
        end = 0
        for j in range(start, len(text)):
            ch = text[j]
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
                    end = j + 1
                    break
        if end > 0:
            candidates.append(text[start:end])
        i = start + 1 if end <= 0 else end
    if not candidates:
        return text
    return _clean_json(candidates[-1])


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
    content = content.strip()
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
    except (json.JSONDecodeError, KeyError):
        pass

    # fallback: try to extract direction from text
    import re
    m = re.search(r'"direction"\s*:\s*"(long|short|wait)"', content)
    if m:
        direction = m.group(1)
        m2 = re.search(r'"confidence"\s*:\s*([\d.]+)', content)
        confidence = float(m2.group(1)) if m2 else 0.5
        m3 = re.search(r'"reasoning"\s*:\s*"(.+?)"(?:\s*[,}])', content, re.DOTALL)
        reasoning = m3.group(1)[:200] if m3 else ""
        logger.warning(f"{key}: JSON parse failed, extracted direction={direction}")
        return {
            "key": key,
            "model": model,
            "name": name,
            "direction": direction,
            "confidence": confidence,
            "reasoning": reasoning,
        }

    logger.warning(f"{key}: failed to parse response")
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


def generate_signal(ohlcv: pd.DataFrame, coin: str = "DOGE", enabled_models: list[str] | None = None,
                   tp_usd: float = 3.0, sl_usd: float = 3.0,
                   leverage: int = 10, trade_amount: float = 10.0,
                   last_signal_direction: str | None = None,
                   last_signal_reasoning: str | None = None,
                   consecutive_waits: int = 0,
                   current_pnl: float | None = None,
                   market_context: dict | None = None,
                   gemini_api_keys: list[str] | None = None,
                   db=None,
                   macro_trend: str = "mixed",
                   liq_price: float = 0.0,
                   liq_dist_pct: float = 0.0) -> dict:
    signal_start = time.time()

    if ohlcv.empty or len(ohlcv) < 50:
        logger.warning("Not enough data for AI signal")
        return {"direction": "wait", "confidence": 0.3, "regime": "UNKNOWN", "reasoning": "Insufficient data", "model_details": [], "vote_tally": {}}

    regime = _detect_regime(ohlcv)
    indicators = compute_indicators(ohlcv)

    if market_context and ohlcv is not None and not ohlcv.empty:
        closes = [round(float(c), 5) for c in ohlcv["close"].tail(15).tolist()]
        market_context["recent_closes"] = closes

    prompt = build_prompt(indicators, regime, coin,
                          tp_usd=tp_usd, sl_usd=sl_usd, leverage=leverage, trade_amount=trade_amount,
                          last_signal_direction=last_signal_direction,
                          last_signal_reasoning=last_signal_reasoning,
                          consecutive_waits=consecutive_waits, current_pnl=current_pnl,
                          market_context=market_context,
                          macro_trend=macro_trend, liq_price=liq_price, liq_dist_pct=liq_dist_pct)

    cycle_id = uuid.uuid4().hex[:12]
    gemini_keys = gemini_api_keys if gemini_api_keys is not None else []

    _debug_calls: dict[str, str] = {}

    # # --- Secondary provider setup ---
    # provider_info = SECONDARY_PROVIDERS.get(coin)
    # secondary_key = ""
    # if provider_info:
    #     secondary_key = os.environ.get(provider_info["env_var"], "")
    # if secondary_key:
    #     _debug_calls["secondary"] = f"provider={provider_info['provider']}"
    # else:
    #     _debug_calls["secondary"] = "no_key"

    # --- Build voter tasks ---
    voter_tasks: list[tuple[str, callable, tuple]] = []

    # Gemini voter
    if gemini_keys or _GEMINI_KEY_RING:
        voter_tasks.append(("gemini", call_gemini_http_with_retry, (prompt,)))

    # # Secondary voter (with throttle, staleness check) — DISABLED
    # def _call_secondary() -> dict | None:
    #     if not secondary_key or not provider_info:
    #         return None
    #     elapsed = time.time() - signal_start
    #     throttle = _provider_throttles.get(provider_info["throttle"])
    #     wait = throttle.acquire() if throttle else 0.0
    #     if elapsed + wait > MAX_SIGNAL_AGE_S:
    #         logger.info(f"secondary:{coin}: stale signal (elapsed={elapsed:.1f}s wait={wait:.1f}s > {MAX_SIGNAL_AGE_S}s) — dropping")
    #         return {"_error": "STALE_DROPPED"}
    #     if wait > 0:
    #         time.sleep(wait)
    #     result = call_openai_compat(
    #         provider_info["base_url"],
    #         secondary_key,
    #         provider_info["model"],
    #         prompt,
    #         key_label=f"{coin}_secondary",
    #         timeout=30,
    #     )
    #     return result
    #
    # if secondary_key:
    #     voter_tasks.append(("secondary", _call_secondary, ()))

    # --- Run voters concurrently ---
    results: dict[str, dict | None] = {}
    if voter_tasks:
        executor = ThreadPoolExecutor(max_workers=len(voter_tasks))
        try:
            future_to_label = {}
            for label, fn, args in voter_tasks:
                time.sleep(random.uniform(0, 0.5))
                future_to_label[executor.submit(fn, *args)] = label
            for future in as_completed(future_to_label, timeout=VOTER_DEADLINE_S):
                label = future_to_label[future]
                try:
                    results[label] = future.result()
                except Exception as e:
                    results[label] = {"_error": f"EXC_{e}"}
        except TimeoutError:
            pass
        finally:
            executor.shutdown(wait=False)

    # --- Collect results ---
    details: list[dict] = []

    def _is_valid(entry: dict | None) -> bool:
        return bool(entry and "_error" not in entry and entry.get("direction"))

    for label, result in results.items():
        if isinstance(result, dict) and "_error" in result:
            _debug_calls[label] = result["_error"]
        elif result:
            _debug_calls[label] = "ok"
        else:
            _debug_calls[label] = "returned_none"
        if _is_valid(result):
            details.append(result)
        if db and db.enabled:
            try:
                safe_dir = result.get("direction") if result and isinstance(result, dict) else None
                safe_conf = result.get("confidence") if result and isinstance(result, dict) else None
                safe_reas = result.get("reasoning", "")[:500] if result and isinstance(result, dict) else None
                data = {
                    "cycle_id": str(uuid.uuid4()),
                    "coin": coin,
                    "voter": label,
                    "direction": safe_dir,
                    "confidence": safe_conf,
                    "reasoning": safe_reas,
                    "error": None if safe_dir else "call_failed",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                db.client.table("ai_votes").insert(data).execute()
            except Exception as e:
                _debug_calls[f"save_{label}"] = f"DB_ERR: {e}"

    # # --- Consensus logic (dual-model) — DISABLED ---
    # gemini_result = results.get("gemini", {})
    # sec_result = results.get("secondary", {})
    # gemini_valid = _is_valid(gemini_result)
    # sec_valid = _is_valid(sec_result)
    #
    # forced = False
    # winner = "wait"
    # confidence = 0.0
    # reasons = ""
    #
    # if gemini_valid and sec_valid:
    #     gemini_dir = gemini_result["direction"]
    #     sec_dir = sec_result["direction"]
    #     if gemini_dir == sec_dir:
    #         winner = gemini_dir
    #         confidence = (float(gemini_result.get("confidence", 0.5)) + float(sec_result.get("confidence", 0.5))) / 2.0
    #         reasons = f"Consensus: Gemini={gemini_dir.upper()}({gemini_result['confidence']:.2f}) + {sec_result.get('name','secondary')}={sec_dir.upper()}({sec_result['confidence']:.2f})"
    #     else:
    #         reasons = f"Disagreement: Gemini={gemini_dir.upper()}({gemini_result['confidence']:.2f}) vs {sec_result.get('name','secondary')}={sec_dir.upper()}({sec_result['confidence']:.2f}) — defaulting to wait"
    #         if consecutive_waits >= 3:
    #             forced = True
    #             if regime.startswith("TRENDING_UP"):
    #                 winner = "long"
    #             elif regime.startswith("TRENDING_DOWN"):
    #                 winner = "short"
    #             else:
    #                 winner = "long"
    #             confidence = 0.25
    #             _debug_calls["forced"] = "true"
    # elif gemini_valid:
    #     logger.debug(f"[CONSENSUS] Dropping signal: Secondary model missing/failed for {coin}")
    #     reasons = "Secondary model missing/failed — wait"
    # elif sec_valid:
    #     logger.debug(f"[CONSENSUS] Dropping signal: Gemini model missing/failed for {coin}")
    #     reasons = "Gemini model missing/failed — wait"
    # else:
    #     reasons = "No valid model responses"

    # --- Gemini-only pass-through (secondary disabled) ---
    gemini_result = results.get("gemini", {})
    gemini_valid = _is_valid(gemini_result)
    forced = False
    if gemini_valid:
        winner = gemini_result["direction"]
        confidence = float(gemini_result.get("confidence", 0.5))
        reasons = f"Gemini: {winner.upper()}({confidence:.2f})"
    else:
        winner = "wait"
        confidence = 0.0
        reasons = "No valid model response"

    vote_tally = {"long": 0, "short": 0, "wait": 0}
    for d in details:
        vote_tally[d["direction"]] = vote_tally.get(d["direction"], 0) + 1

    logger.info(f"{coin}: gemini={gemini_valid} winner={winner} conf={confidence:.2f} cycle={cycle_id}")

    # secondary_provider = provider_info["provider"] if provider_info and secondary_key else None
    secondary_provider = None

    return {
        "direction": winner,
        "confidence": round(min(confidence, 0.95), 2),
        "regime": regime,
        "reasoning": reasons,
        "prompt": prompt,
        "model_details": details,
        "vote_tally": vote_tally,
        "cycle_id": cycle_id,
        "_debug_calls": _debug_calls,
        "_forced": forced,
        "secondary_provider": secondary_provider,
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
