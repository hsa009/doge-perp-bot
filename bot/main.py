import os
import json
import time
import traceback
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
import httpx
import pandas as pd
from flask import Flask, jsonify, request

from bot.config import (
    TRADE_AMOUNT_USD,
    TAKE_PROFIT_USD,
    STOP_LOSS_USD,
    MIN_CONFIDENCE,
    LEVERAGE,
    MAX_DAILY_LOSS_USD,
    AI_LOOP_INTERVAL,
    GROQ_API_KEY,
    ACTIVE_ASSET,
    COIN_LIST,
    get_coin_gemini_keys,
)
from bot.hyperliquid_client import HyperliquidClient
from bot.order_executor import OrderExecutor
from bot.db import Database
from bot.redis_client import RedisClient
from bot.signals import providers as signal_engine
from bot.signals.providers import get_model_defs
from bot.signals.rules import ema as ema_func
from bot.market_data import get_market_context, fetch_all_market_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

hl = HyperliquidClient()
executor = OrderExecutor(hl.exchange, hl.info, hl.address)
db = Database()
redis = RedisClient()

start_time = time.time()

app = Flask(__name__)

# Order-execution mutex — prevents concurrent overlapping trades
_is_placing_order: bool = False
_is_placing_order_lock = threading.Lock()

@app.route("/")
def index():
    cfg = get_runtime_config()
    return jsonify({
        "name": f"{cfg['active_asset']} Perp Bot",
        "status": "running",
        "health": "/health",
        "status_api": "/api/v1/bot/status",
        "account": "/api/v1/account",
        "uptime": int(time.time() - start_time),
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "uptime": int(time.time() - start_time)})


@app.route("/api/v1/bot/status")
def bot_status():
    try:
        running = redis.is_bot_running()
        signal = redis.get_current_signal()
        position = redis.get_position()
        cfg = get_runtime_config()
        cfg["ai_loop_interval"] = str(AI_LOOP_INTERVAL)
        cfg["groq_api_key"] = redis.get_config("groq_api_key", GROQ_API_KEY)
        remaining = max(0, (signal.get("timestamp", 0) if signal else 0) + AI_LOOP_INTERVAL - time.time())
        active_asset = cfg.get("active_asset", "DOGE")
        pending_asset = redis.get_config("pending_asset", "")
        if pending_asset:
            for check_coin in ("DOGE", "SOL"):
                try:
                    check_pos = hl.get_position(check_coin)
                except Exception:
                    check_pos = None
                if check_pos and float(check_pos["szi"]) != 0 and check_coin != active_asset:
                    cfg["active_asset"] = check_coin
                    active_asset = check_coin
                    break
        try:
            mark_price = hl.get_current_price(active_asset)
        except Exception:
            mark_price = 0.0
        return jsonify({
            "running": running,
            "last_signal": signal,
            "position": position,
            "mark_price": mark_price,
            "config": cfg,
            "remaining_seconds": int(remaining),
            "pending_asset": pending_asset,
            "ai_loop_heartbeat": redis.get_config("ai_loop_heartbeat", ""),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/bot/debug")
def bot_debug():
    try:
        from bot.signals.providers import MODEL_KEYS
        enabled = redis.get_enabled_models()
        defs = redis.get_model_defs()
        sig = redis.get_current_signal()
        sig_age = time.time() - sig.get("timestamp", 0) if sig else None
        cfg_now = get_cached_runtime_config()
        return jsonify({
            "MODEL_KEYS": MODEL_KEYS,
            "enabled_models": enabled,
            "model_defs": defs or [],
            "db_enabled": db.enabled,
            "supabase_url_set": bool(os.environ.get("SUPABASE_URL")),
            "supabase_key_set": bool(os.environ.get("SUPABASE_KEY")),
            "gemini_keys_count": len([k for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k]),
            "gemini_keys_str": os.environ.get("GEMINI_API_KEYS", "")[:80] or "per-coin",
            "ai_models": os.environ.get("AI_MODELS", "not set"),
            "sniper": {
                "high_conf_bypass": _HIGH_CONF_OBI_BYPASS,
                "min_confidence": cfg_now.get("min_confidence"),
                "current_signal_direction": sig.get("direction") if sig else None,
                "current_signal_confidence": sig.get("confidence") if sig else None,
                "current_signal_forced": sig.get("_forced") if sig else None,
                "current_signal_age_s": sig_age,
                "would_bypass_high_conf": bool(sig and sig.get("confidence", 0) >= _HIGH_CONF_OBI_BYPASS),
                "would_bypass_forced": bool(sig and sig.get("_forced")),
                "voter_count": len(sig.get("model_details", [])) if sig else 0,
                "last_error": redis.get_sniper_error(),
                "cooldown_active": redis.get_cooldown(cfg_now.get("active_asset", "DOGE")),
                "peak_pnl": float(redis.get_config(f"peak_pnl:{cfg_now.get('active_asset', 'DOGE')}", "0") or "0"),
            },
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/account")
def account():
    try:
        bal = hl.get_balance()
        bal["address"] = hl.address
        return jsonify(bal)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/bot/re-ask", methods=["POST"])
def re_ask():
    try:
        signals = run_multi_asset_signal()
        winner = aggregate_signals(signals)
        if winner:
            return jsonify({"ok": True, "signal": winner})
        return jsonify({"ok": True, "signal": {"direction": "wait", "confidence": 0.0}})
    except Exception as e:
        logger.exception("re-ask failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/bot/force-trade", methods=["POST"])
def force_trade():
    try:
        signals = run_multi_asset_signal()
        winner = aggregate_signals(signals)
        if winner and winner["direction"] in ("long", "short"):
            coin = winner["_coin"]
            opened = open_trade(winner, coin)
            return jsonify({"ok": True, "signal": winner, "trade_opened": opened})
        if winner:
            return jsonify({"ok": True, "signal": winner, "trade_opened": False})
        return jsonify({"ok": False, "error": "Signal generation failed"}), 500
    except Exception as e:
        logger.exception("force-trade failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/bot/set-tp-sl", methods=["POST"])
def set_tp_sl():
    try:
        cfg = get_runtime_config()
        # Find whatever coin has an open position
        coin = cfg.get("active_asset", "")
        all_pos = hl.get_all_positions()
        for c in COIN_LIST:
            if c in all_pos and float(all_pos[c]["szi"]) != 0:
                coin = c
                break
        if not coin:
            return jsonify({"ok": False, "error": "No coin with open position found"}), 400
        pos = hl.get_position(coin)
        if not pos or float(pos["szi"]) == 0:
            return jsonify({"ok": False, "error": "No open position"}), 400
        is_buy = float(pos["szi"]) > 0
        entry_px = float(pos["entryPx"])
        sz = abs(float(pos["szi"]))
        notional = sz * entry_px
        tp_ratio = cfg["tp_usd"] / notional
        sl_ratio = cfg["sl_usd"] / notional
        if is_buy:
            tp_price = entry_px * (1 + tp_ratio)
            sl_price = entry_px * (1 - sl_ratio)
        else:
            tp_price = entry_px * (1 - tp_ratio)
            sl_price = entry_px * (1 + sl_ratio)
        results = _place_tp_sl(coin, is_buy, notional, tp_price, sl_price)
        redis.set_position({
            "coin": coin,
            "direction": "long" if is_buy else "short",
            "size": float(pos["szi"]),
            "entry_price": entry_px,
            "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
            "tp_price": tp_price,
            "sl_price": sl_price,
        })
        return jsonify({"ok": True, "tp_price": tp_price, "sl_price": sl_price, "results": results})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/bot/close-position", methods=["POST"])
def close_position():
    logger.info("Close position requested via API")
    try:
        coin = get_runtime_config().get("active_asset", "DOGE")
        pos = hl.get_position(coin)
        if pos and abs(float(pos["szi"])) >= 0.01:
            open_orders = hl.get_open_orders()
            for i, o in enumerate(open_orders):
                try:
                    executor.exchange.cancel(o["coin"], o["oid"])
                except Exception:
                    logger.warning(f"Failed to cancel order {o.get('oid')}, continuing")
                if i < len(open_orders) - 1:
                    time.sleep(0.5)
            time.sleep(0.5)
            executor.close_position(coin=coin)
            logger.info(f"Position closed via API ({coin})")
        else:
            logger.info(f"No meaningful position to close for {coin} (sz={float(pos['szi']) if pos else 0})")
        redis.clear_position()
        close_position_in_db()
        _apply_pending_asset()
        redis.clear_current_signal()
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception(f"Close position error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/bot/asset", methods=["POST"])
def set_active_asset():
    from flask import request
    try:
        data = request.get_json(force=True)
        asset = data.get("asset", "").upper()
        if asset not in [c.upper() for c in COIN_LIST]:
            return jsonify({"ok": False, "error": f"Asset must be one of: {', '.join(COIN_LIST)}"}), 400
        current = redis.get_config("active_asset", ACTIVE_ASSET)
        if asset == current:
            pending = redis.get_config("pending_asset", "")
            if pending:
                redis.set_config("pending_asset", "")
                logger.info(f"Pending switch to {pending} cancelled")
            return jsonify({"ok": True, "asset": asset})
        has_position = False
        for coin in COIN_LIST:
            pos = hl.get_position(coin)
            if pos and float(pos["szi"]) != 0:
                has_position = True
                break
        if has_position:
            redis.set_config("pending_asset", asset)
            logger.info(f"Pending asset set to {asset} (position open)")
            return jsonify({"ok": True, "pending": True, "asset": asset})
        redis.set_config("active_asset", asset)
        redis.set_config("pending_asset", "")
        logger.info(f"Active asset switched to {asset}")
        return jsonify({"ok": True, "asset": asset})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/bot/version")
def version():
    return jsonify({"version": "2026-05-24-re-ask"})


@app.route("/api/v1/version")
def version2():
    return jsonify({"version": "2026-05-24-re-ask"})


@app.route("/version")
def version3():
    return jsonify({"version": "2026-05-24-re-ask"})


@app.route("/api/v1/bot/start", methods=["POST"])
def bot_start():
    redis.set_bot_running(True)
    logger.info("Bot started via API")
    return jsonify({"ok": True})


@app.route("/api/v1/bot/stop", methods=["POST"])
def bot_stop():
    redis.set_bot_running(False)
    logger.info("Bot stopped via API")
    return jsonify({"ok": True})


@app.route("/api/v1/bot/settings", methods=["POST"])
def bot_settings():
    try:
        body = request.get_json()
        if not body:
            return jsonify({"ok": False, "error": "No body"}), 400
        for key, value in body.items():
            redis.set_config(key, str(value))
        invalidate_config_cache()
        logger.info(f"Settings updated: {body}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/bot/models", methods=["GET", "POST"])
def bot_models():
    if request.method == "GET":
        try:
            from bot.signals.providers import MODEL_KEYS
            defs = redis.get_model_defs()
            enabled = redis.get_enabled_models()
            details = redis.get_model_details()
            models = [
                {
                    "key": d["key"],
                    "name": d["name"],
                    "model_id": d.get("model_id", d.get("model", "")),
                    "enabled": d["key"] in enabled,
                    "last": next((det for det in details if det.get("key") == d["key"]), None),
                }
                for d in defs
            ]
            return jsonify({"models": models})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # POST - toggle model enabled
    try:
        body = request.get_json()
        key = body.get("key")
        enabled = body.get("enabled", False)
        current = redis.get_enabled_models()
        if enabled:
            if key not in current:
                current.append(key)
        else:
            current = [k for k in current if k != key]
        redis.set_enabled_models(current)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def kill_switch():
    logger.critical("EMERGENCY STOP TRIGGERED")
    redis.set_emergency_stop(True)
    try:
        coin = get_runtime_config().get("active_asset", "DOGE")
        open_orders = hl.get_open_orders()
        executor.cancel_all_orders(open_orders)
        executor.close_position(coin=coin)
    except Exception as e:
        logger.exception(f"Kill switch error: {e}")
    db.log("CRITICAL", "Emergency stop triggered")


def _apply_pending_asset():
    pending = redis.get_config("pending_asset", "")
    if pending:
        logger.info(f"Pending asset {pending} detected — activating")
        redis.set_config("active_asset", pending)
        redis.set_config("pending_asset", "")
        logger.info(f"Active asset switched to {pending} (was pending)")

def _safe_float(raw: str, default: str) -> float:
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning("Bad config value %r, falling back to %s", raw, default)
        return float(default)

def _safe_int(raw: str, default: str) -> int:
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.warning("Bad config value %r, falling back to %s", raw, default)
        return int(default)

def get_runtime_config() -> dict:
    return {
        "tp_usd": _safe_float(redis.get_config("tp_usd", str(TAKE_PROFIT_USD)), str(TAKE_PROFIT_USD)),
        "sl_usd": _safe_float(redis.get_config("sl_usd", str(STOP_LOSS_USD)), str(STOP_LOSS_USD)),
        "trade_amount": _safe_float(redis.get_config("trade_amount", str(TRADE_AMOUNT_USD)), str(TRADE_AMOUNT_USD)),
        "leverage": _safe_int(redis.get_config("leverage", str(LEVERAGE)), str(LEVERAGE)),
        "min_confidence": _safe_float(redis.get_config("min_confidence", str(MIN_CONFIDENCE)), str(MIN_CONFIDENCE)),
        "max_daily_loss": _safe_float(redis.get_config("max_daily_loss", str(MAX_DAILY_LOSS_USD)), str(MAX_DAILY_LOSS_USD)),
        "max_daily_loss_enabled": redis.get_config("max_daily_loss_enabled", "1"),
        "force_trade_after_waits": redis.get_config("force_trade_after_waits", "0"),
        "active_asset": redis.get_config("active_asset", ACTIVE_ASSET),
    }


# ---------------------------------------------------------------------------
# Sniper (V3) helpers — local cache to keep the 300ms loop off Upstash/HL.
# ---------------------------------------------------------------------------
# These wrap the existing get_runtime_config() and per-call Redis/HL reads.
# They are intentionally additive: nothing else in the file is replaced.

_config_cache: dict | None = None
_config_cache_ts: float = 0.0
_config_cache_lock = threading.Lock()
_CONFIG_CACHE_TTL = 2.0

# Sniper: a non-forced, non-wait signal with confidence at/above this threshold
# bypasses the OBI gate. Rationale: when the AI consensus is decisive (e.g.,
# 2/2 voters agree long, capped to 0.95) the OBI hunt is just dead time.
# Forced signals already bypass unconditionally; this is the lower bar for
# high-confidence non-forced signals.
_HIGH_CONF_OBI_BYPASS = 0.80

# Generic 1s-TTL cache for high-frequency sniper reads (emergency stop,
# bot running, position). Maps cache-key -> (expiry_monotonic, value).
_sniper_redis_cache: dict[str, tuple[float, object]] = {}


def get_cached_runtime_config() -> dict:
    """Return runtime config, refreshing from Redis at most once per 2 seconds.

    The trading_loop polls every 300ms; calling get_runtime_config() on every
    tick would issue 8 sequential Redis GETs per tick (~1,600 GETs/min). This
    wrapper caps the cascade to 1 refresh per 2-second window, dropping it to
    ~240 GETs/min while still honouring dashboard changes within 2 seconds.
    """
    global _config_cache, _config_cache_ts
    now = time.monotonic()
    if _config_cache is not None and (now - _config_cache_ts) < _CONFIG_CACHE_TTL:
        return _config_cache
    with _config_cache_lock:
        # Double-check after acquiring lock to avoid duplicate reloads.
        if _config_cache is not None and (time.monotonic() - _config_cache_ts) < _CONFIG_CACHE_TTL:
            return _config_cache
        _config_cache = get_runtime_config()
        _config_cache_ts = time.monotonic()
    return _config_cache


def invalidate_config_cache() -> None:
    """Force the next get_cached_runtime_config() call to re-read from Redis.

    Called from bot_settings() so dashboard saves take effect immediately
    instead of after up to 2 seconds of stale cached state.
    """
    global _config_cache, _config_cache_ts
    with _config_cache_lock:
        _config_cache = None
        _config_cache_ts = 0.0


def _sniper_redis_cached(key: str, loader):
    """Generic 1s-TTL cache wrapper. `loader` is a zero-arg callable.

    Used to throttle is_emergency_stop, is_bot_running, and get_position
    to 1Hz so the 300ms sniper tick doesn't hammer Upstash/Hyperliquid.
    A 1-second staleness window is acceptable for these control signals.
    """
    now = time.monotonic()
    cached = _sniper_redis_cache.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]
    try:
        value = loader()
    except Exception:
        # On error, return the previous value if we have one, else None.
        return cached[1] if cached is not None else None
    _sniper_redis_cache[key] = (now + 1.0, value)
    return value


def is_bias_fresh(signal: dict | None) -> bool:
    """A signal/bias is fresh if it's present and younger than 2*AI_LOOP_INTERVAL.

    If the AI engine freezes or rate-limits out, the sniper must safely stand
    down rather than trade on decayed market assumptions.
    """
    if not signal:
        return False
    ts = signal.get("timestamp", 0) or 0
    return (time.time() - ts) < (AI_LOOP_INTERVAL * 2)


def compute_obi(coin: str) -> float | None:
    """Top-3 L2 Order Book Imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol).

    Returns a value in [-1.0, 1.0]. Positive = buy pressure, negative = sell.
    Returns None on any error (book unavailable, empty, malformed). Caller
    should treat None as "no signal this tick" and continue.

    Distinct from market_data.get_market_context() which uses top-5 levels
    for macro context. The sniper uses top-3 for hyper-local liquidity at
    the touch — the most immediate book density to time a 10-cent entry.
    """
    try:
        book = hl.info.l2_book(coin)
        if not book or "levels" not in book:
            return None
        bids = book["levels"][0][:3]
        asks = book["levels"][1][:3]
        bid_vol = sum(float(b["sz"]) for b in bids)
        ask_vol = sum(float(a["sz"]) for a in asks)
        denom = bid_vol + ask_vol
        if denom <= 0:
            return None
        return (bid_vol - ask_vol) / denom
    except Exception as e:
        logger.debug(f"compute_obi error for {coin}: {e}")
        return None


def _validate_trade_config(coin: str, direction: str) -> dict | None:
    cfg = get_runtime_config()
    size_usd = cfg["trade_amount"]
    lev = cfg["leverage"]
    notional = size_usd * lev
    logger.info(f"VALIDATE_CONFIG: coin={coin}, dir={direction}, margin=${size_usd}, lev={lev}x, notional=${notional:.2f}, tp=${cfg['tp_usd']}, sl=${cfg['sl_usd']}")
    if size_usd <= 0 or lev <= 0 or notional < 1.0:
        logger.error(f"INVALID_CONFIG: refusing trade — size={size_usd}, lev={lev}, notional={notional:.2f}")
        return None
    return cfg

def _place_tp_sl(coin: str, is_buy: bool, notional: float, tp_price: float, sl_price: float) -> dict:
    results = {"tp": None, "sl": None}
    try:
        open_orders = hl.get_open_orders()
        for o in open_orders:
            if o.get("coin") != coin:
                continue
            try:
                executor.exchange.cancel(o["coin"], o["oid"])
            except Exception:
                logger.warning(f"Failed to cancel order {o.get('oid')}, continuing")
            time.sleep(0.3)
    except Exception as e:
        logger.warning(f"Cancel existing orders: {e}")
    time.sleep(0.3)
    for attempt in range(3):
        try:
            results["tp"] = executor.set_take_profit(coin, is_buy, notional, tp_price)
            logger.info(f"TP result: {results['tp']}")
            break
        except Exception as e:
            logger.error(f"TP placement failed (attempt {attempt+1}/3): {e}")
            time.sleep(1)
    time.sleep(0.3)
    for attempt in range(3):
        try:
            results["sl"] = executor.set_stop_loss(coin, is_buy, notional, sl_price)
            logger.info(f"SL result: {results['sl']}")
            break
        except Exception as e:
            logger.error(f"SL placement failed (attempt {attempt+1}/3): {e}")
            time.sleep(1)
    return results


def safe_to_trade(coin: str, direction: str) -> bool:
    """Pre-flight validation right before any trade.

    1. Mutex lock — no concurrent order in-flight (#3).
    2. Hard fetch latest dashboard config from Valkey — abort if bot OFF (#1).
    3. Active position check — exchange source of truth (#2).
    4. Redis position check — secondary safety net.
    """
    global _is_placing_order
    with _is_placing_order_lock:
        if _is_placing_order:
            logger.warning("SAFE_TO_TRADE: ABORT — is_placing_order=True, an order is already executing")
            return False
        _is_placing_order = True

    try:
        invalidate_config_cache()
        cfg = get_runtime_config()
        running = redis.is_bot_running()
        logger.info(f"SAFE_TO_TRADE: coin={coin} dir={direction} running={running}")

        if not running:
            logger.warning("SAFE_TO_TRADE: ABORT — bot toggled OFF in dashboard")
            return False

        existing = hl.get_position(coin)
        szi = float(existing.get("szi", 0)) if existing else 0.0
        if abs(szi) > 1e-9:
            logger.warning(f"SAFE_TO_TRADE: ABORT — active {coin} position on exchange (szi={szi})")
            return False

        redis_pos = redis.get_position()
        if redis_pos:
            logger.warning(f"SAFE_TO_TRADE: ABORT — Redis shows active position for {redis_pos.get('coin')}")
            return False

        return True
    except Exception as e:
        logger.error(f"SAFE_TO_TRADE: validation error: {e}")
        return False


def open_trade(signal: dict, coin: str = "DOGE") -> bool:
    global _is_placing_order
    if not safe_to_trade(coin, signal["direction"]):
        with _is_placing_order_lock:
            _is_placing_order = False
        return False

    try:
        cfg = _validate_trade_config(coin, signal["direction"])
        if cfg is None:
            return False
        is_buy = signal["direction"] == "long"
        entry_price = hl.get_current_price(coin)

        # --- DEBUG: capture config just before trade ---
        logger.info(f"DEBUG_CFG: {json.dumps({k: v for k, v in cfg.items() if k != 'groq_api_key'})}")
        # ---

        size_usd = cfg["trade_amount"]
        lev = cfg["leverage"]
        notional = size_usd * lev

        logger.info(f"COMMITTING TRADE: {signal['direction']} {coin} — confidence: {signal['confidence']:.2f} @ ${entry_price:.5f} (margin=${size_usd}, leverage={lev}x, notional=${notional:.2f})")

        lev_result = hl.set_leverage(coin, lev, is_cross=True)
        logger.info(f"DEBUG_LEVERAGE: set_leverage({coin}, {lev}) returned {lev_result}")
        result = executor.open_market(coin, is_buy, notional)
        logger.info(f"DEBUG_OPEN_MARKET: full response: {json.dumps(result, default=str)}")

        statuses = result.get("response", {}).get("data", {}).get("statuses", [{}])
        if not statuses or ("resting" not in statuses[0] and "filled" not in statuses[0]):
            logger.error(f"Order failed: {result}")
            try:
                db.log("ERROR", f"Order failed: {result}")
            except Exception:
                pass
            return False

        entry_price = hl.get_current_price(coin)

        tp_ratio = cfg["tp_usd"] / notional
        sl_ratio = cfg["sl_usd"] / notional
        if is_buy:
            tp_price = entry_price * (1 + tp_ratio)
            sl_price = entry_price * (1 - sl_ratio)
        else:
            tp_price = entry_price * (1 - tp_ratio)
            sl_price = entry_price * (1 + sl_ratio)

        try:
            _place_tp_sl(coin, is_buy, notional, tp_price, sl_price)
        except Exception as e:
            logger.error(f"Initial TP/SL failed (trading loop will retry): {e}")

        try:
            db.save_trade({
                "coin": coin,
                "direction": signal["direction"],
                "entry_price": entry_price,
                "entry_size_usd": size_usd,
                "notional": notional,
                "stop_loss_price": sl_price,
                "take_profit_price": tp_price,
                "leverage": lev,
                "ai_confidence": signal.get("confidence"),
                "ai_regime": signal.get("regime"),
                "status": "open",
            })
        except Exception:
            pass

        redis.set_position({
            "coin": coin,
            "direction": signal["direction"],
            "entry_price": entry_price,
            "size": notional,
            "leverage": lev,
            "margin": size_usd,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "opened_at": time.time(),
        })

        try:
            db.log("INFO", f"Trade opened: {signal['direction']} {coin} @ {entry_price:.5f} (TP: {tp_price:.5f}, SL: {sl_price:.5f})")
        except Exception:
            pass
        logger.info(f"Trade opened successfully")
        return True
    except Exception as e:
        logger.exception(f"open_trade error: {e}")
        return False
    finally:
        with _is_placing_order_lock:
            _is_placing_order = False


def close_position_in_db(coin: str = "DOGE"):
    try:
        open_trades = db.get_open_trades()
        if open_trades:
            t = open_trades[0]
            exit_price = hl.get_current_price(coin)
            entry_px = float(t.get("entry_price", 0))
            notional = float(t.get("notional", 0))
            direction = t.get("direction", "long")
            mult = 1 if direction == "long" else -1
            pnl = (exit_price - entry_px) / entry_px * notional * mult
            db.close_trade(t["id"], {
                "exit_price": exit_price,
                "exit_reason": "tp_sl",
                "net_pnl_usd": pnl,
            })
        db.log("INFO", f"Trade closed by trigger order ({coin})")
    except Exception as ex:
        logger.exception(f"close_position_in_db error: {ex}")
    redis.clear_position()
    redis.set_cooldown(coin, 30)
    redis.set_config(f"peak_pnl:{coin}", "")
    redis.clear_current_signal()


def trading_loop():
    logger.info("Trading loop started")
    # Per-thread local state for the 300ms sniper cadence. Closure-scoped on
    # purpose: never module-global, so Flask request handlers can never read
    # or mutate it. The 1s caches below are the only shared state.
    _state = {"last_order_check": 0.0, "last_pos_write": 0.0}
    while True:
        try:
            if _sniper_redis_cached("emergency_stop", redis.is_emergency_stop):
                kill_switch()
                break

            if not _sniper_redis_cached("bot_running", redis.is_bot_running):
                time.sleep(10)
                continue

            cfg = get_cached_runtime_config()
            coin = cfg.get("active_asset", "DOGE")

            # V5: Scan all coins for existing positions (single user_state call)
            all_positions = _sniper_redis_cached("hl_all_positions", hl.get_all_positions)
            for check_coin in COIN_LIST:
                check_pos = all_positions.get(check_coin)
                if check_pos and float(check_pos["szi"]) != 0:
                    if check_coin != coin:
                        logger.info(f"Position open for {check_coin} — switching from {coin}")
                    coin = check_coin
                    break

            # V4: Cooldown gate — skip entire tick if cooldown is active for this coin
            if redis.get_cooldown(coin):
                time.sleep(0.3)
                continue

            # Handle close-position signal from dashboard
            if redis.get_close_position_signal():
                logger.info("Close position signal received")
                pos = hl.get_position(coin)
                if pos and float(pos["szi"]) != 0:
                    try:
                        open_orders = hl.get_open_orders()
                        for i, o in enumerate(open_orders):
                            try:
                                executor.exchange.cancel(o["coin"], o["oid"])
                            except Exception:
                                logger.warning(f"Close signal cancel failed for order {o.get('oid')}, continuing")
                            if i < len(open_orders) - 1:
                                time.sleep(0.3)
                        time.sleep(0.3)
                        executor.close_position(coin=coin)
                        logger.info(f"Position closed via dashboard signal ({coin})")
                    except Exception as e:
                        logger.exception(f"Close position error: {e}")
                redis.clear_position()
                redis.clear_close_position_signal()
                _apply_pending_asset()
                redis.clear_current_signal()
                time.sleep(5)
                continue

            pos = _sniper_redis_cached(f"hl_pos_{coin}", lambda: hl.get_position(coin))

            if pos and float(pos["szi"]) != 0:
                direction = "long" if float(pos["szi"]) > 0 else "short"
                cached = redis.get_position()
                entry_px = float(pos["entryPx"])
                sz = abs(float(pos["szi"]))
                notional = sz * entry_px
                is_buy = float(pos["szi"]) > 0

                # Immediate TP/SL check when position is first detected
                if cached is None or abs(cached.get("size", 0)) < 1e-9:
                    logger.info(f"New position detected for {coin} — checking TP/SL immediately")
                    _state["last_order_check"] = 0.0

                # V4: Live PnL from exchange
                live_pnl = float(pos.get("unrealizedPnl", 0))

                # V4 Phase 3: Smart Moving Stop Loss
                peak_key = f"peak_pnl:{coin}"
                current_peak = float(redis.get_config(peak_key, "0") or "0")
                if live_pnl > current_peak:
                    redis.set_config(peak_key, str(live_pnl))
                    current_peak = live_pnl

                sl_usd = cfg["sl_usd"]
                if current_peak >= 0.30:
                    floor = 0.20
                elif current_peak >= 0.20:
                    floor = current_peak - 0.05
                else:
                    floor = -sl_usd

                if live_pnl <= floor:
                    logger.info(f"Smart SL triggered: PnL=${live_pnl:.2f} <= floor=${floor:.2f}")
                    try:
                        open_orders = hl.get_open_orders()
                        for i, o in enumerate(open_orders):
                            try:
                                executor.exchange.cancel(o["coin"], o["oid"])
                            except Exception:
                                pass
                            if i < len(open_orders) - 1:
                                time.sleep(0.3)
                        time.sleep(0.5)
                        executor.close_position(coin=coin)
                        logger.info(f"Position closed via smart SL ({coin})")
                    except Exception as e:
                        logger.exception(f"Smart SL close error: {e}")
                    close_position_in_db(coin)
                    _apply_pending_asset()
                    time.sleep(0.3)
                    continue

                # V4: Throttled TP/SL order verification (every 30s)
                now = time.monotonic()
                if now - _state.get("last_order_check", -999) > 30.0:
                    tp_ratio = cfg["tp_usd"] / notional
                    sl_ratio = cfg["sl_usd"] / notional
                    if is_buy:
                        tp_price = entry_px * (1 + tp_ratio)
                        sl_price = entry_px * (1 - sl_ratio)
                    else:
                        tp_price = entry_px * (1 - tp_ratio)
                        sl_price = entry_px * (1 + sl_ratio)
                    open_orders = hl.get_open_orders()
                    existing_coin_orders = [
                        o for o in open_orders
                        if o.get("coin") == coin
                    ]
                    if len(existing_coin_orders) < 2:
                        logger.info(f"TP/SL missing ({len(existing_coin_orders)} coin orders) — placing now")
                        _place_tp_sl(coin, is_buy, notional, tp_price, sl_price)
                    _state["last_order_check"] = now

                # V4: Throttled Redis position write (every 5s)
                if now - _state.get("last_pos_write", -999) > 5.0:
                    try:
                        account_value = hl.get_balance()["account_value"]
                    except Exception:
                        account_value = cached.get("account_value", 0) if cached else 0
                    redis.set_position({
                        "coin": pos["coin"],
                        "direction": direction,
                        "size": float(pos["szi"]),
                        "entry_price": entry_px,
                        "unrealized_pnl": live_pnl,
                        "account_value": account_value,
                        "peak_pnl": current_peak,
                        "floor": floor,
                    })
                    _state["last_pos_write"] = now

                continue
            elif pos is None:
                cached = redis.get_position()
                if cached and abs(cached.get("size", 0)) > 0:
                    logger.info("Position gone from exchange — closing trade in DB")
                    close_position_in_db(coin)
                    _apply_pending_asset()
                    redis.clear_current_signal()
                time.sleep(5)
            elif float(pos["szi"]) == 0:
                cached = redis.get_position()
                if cached and cached.get("size", 0) != 0:
                    logger.info("Position closed (sz=0)")
                    close_position_in_db(coin)
                    _apply_pending_asset()
                    redis.clear_current_signal()

            signal = _sniper_redis_cached("current_signal", redis.get_current_signal)
            if not signal:
                time.sleep(10)
                continue

            # Use signal's coin for entry when no position is open
            if not (pos and float(pos["szi"]) != 0):
                signal_coin = signal.get("_coin")
                if signal_coin and signal_coin != coin:
                    logger.info(f"No position — switching to signal's coin: {signal_coin}")
                    coin = signal_coin

            if not is_bias_fresh(signal):
                logger.warning(f"Stale macro bias: age={time.time() - signal.get('timestamp', 0):.0f}s > {AI_LOOP_INTERVAL * 2}s — sniper standing down")
                time.sleep(10)
                continue

            if signal["direction"] == "wait":
                time.sleep(30)
                continue

            _is_forced = signal.get("_forced", False)
            if signal["confidence"] < cfg["min_confidence"] and not _is_forced:
                time.sleep(30)
                continue

            signal_age = time.time() - signal.get("timestamp", 0)
            if signal_age > AI_LOOP_INTERVAL:
                time.sleep(5)
                continue

            if cfg["max_daily_loss_enabled"] == "1":
                try:
                    today_loss = db.get_todays_pnl()
                except Exception:
                    today_loss = 0.0
                if today_loss < -cfg["max_daily_loss"]:
                    logger.warning(f"Daily loss limit hit: ${today_loss:.2f}")
                    try:
                        db.log("WARN", f"Daily loss limit hit: ${today_loss:.2f}")
                    except Exception:
                        pass
                    redis.set_bot_running(False)
                    time.sleep(60)
                    continue

            # Flip protection: if signal direction differs from existing position, close first
            existing = hl.get_position(coin)
            if existing and float(existing["szi"]) != 0:
                existing_dir = "long" if float(existing["szi"]) > 0 else "short"
                if existing_dir != signal["direction"]:
                    logger.info(f"Flip detected: existing {existing_dir} {coin} vs signal {signal['direction']}")
                    try:
                        open_orders = hl.get_open_orders()
                        for i, o in enumerate(open_orders):
                            try:
                                executor.exchange.cancel(o["coin"], o["oid"])
                            except Exception:
                                logger.warning(f"Flip cancel failed for order {o.get('oid')}, continuing")
                            if i < len(open_orders) - 1:
                                time.sleep(0.3)
                        time.sleep(0.3)
                        executor.close_position(coin=coin)
                        logger.info(f"Closed {coin} position for flip")
                    except Exception as e:
                        logger.exception(f"Flip close error: {e}")
                    redis.clear_position()
                    time.sleep(3)

            validated = _validate_trade_config(coin, signal["direction"])
            if validated is None:
                time.sleep(10)
                continue

            # V3 sniper: gate entry on top-3 L2 OBI ±0.30 aligned with macro bias.
            # If OBI is unavailable (book error) or doesn't cross, 300ms tick and
            # re-evaluate. When OBI fires, fall through to the existing open_trade
            # + post-trade cooldown path — TP/SL math and execution are untouched.
            # Forced signals (consecutive_waits >= 3) bypass BOTH confidence and
            # OBI gates so the sniper commits after a deadlock. Non-forced
            # signals with confidence >= _HIGH_CONF_OBI_BYPASS also bypass OBI
            # so a decisive AI consensus is not held hostage to book depth.
            if _is_forced:
                logger.info(f"FORCED entry: direction={signal['direction']}, confidence={signal['confidence']:.2f} (OBI bypassed, bias={signal['direction']}, coin={coin})")
            elif signal["confidence"] >= _HIGH_CONF_OBI_BYPASS:
                logger.info(f"HIGH-CONF entry: direction={signal['direction']}, confidence={signal['confidence']:.2f} >= {_HIGH_CONF_OBI_BYPASS} (OBI bypassed, bias={signal['direction']}, coin={coin})")
            else:
                obi = compute_obi(coin)
                if obi is None:
                    time.sleep(0.3)
                    continue
                if signal["direction"] == "long" and obi > 0.30:
                    logger.info(f"OBI trigger: long entry, obi={obi:.3f} > 0.30 (bias=long, coin={coin})")
                elif signal["direction"] == "short" and obi < -0.30:
                    logger.info(f"OBI trigger: short entry, obi={obi:.3f} < -0.30 (bias=short, coin={coin})")
                else:
                    time.sleep(0.3)
                    continue

            try:
                _open_ok = open_trade(signal, coin)
                _state["last_order_check"] = 0.0
                if not _open_ok:
                    logger.error(f"open_trade returned False for {signal['direction']} {coin} — check balance/min size/HL rate limit")
                    try:
                        redis.set_sniper_error(f"open_trade returned False at {time.strftime('%H:%M:%S')} for {signal['direction']} {coin} (conf={signal['confidence']:.2f})")
                    except Exception:
                        pass
            except Exception as _ote:
                logger.exception(f"open_trade raised: {_ote}")
                try:
                    redis.set_sniper_error(f"open_trade exception at {time.strftime('%H:%M:%S')}: {_ote}")
                except Exception:
                    pass
            time.sleep(10)

        except Exception as e:
            logger.exception(f"Trading loop error: {e}")
            time.sleep(10)

    logger.info("Trading loop terminated")







def _fetch_ohlcv(coin: str) -> pd.DataFrame | None:
    try:
        import httpx
        resp = httpx.post("https://api.hyperliquid.xyz/info", json={
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": "15m",
                     "startTime": int((time.time() - 86400) * 1000),
                     "endTime": int(time.time() * 1000)},
        }, timeout=30)
        resp.raise_for_status()
        candles = resp.json()
        if not candles:
            return None
        rows = []
        for c in candles:
            rows.append({
                "timestamp": c["t"],
                "open": float(c["o"]),
                "high": float(c["h"]),
                "low": float(c["l"]),
                "close": float(c["c"]),
                "volume": float(c["v"]),
            })
        return pd.DataFrame(rows).sort_values("timestamp").tail(100)
    except Exception as e:
        logger.warning(f"Failed to fetch OHLCV for {coin}: {e}")
        return None


def _compute_macro_trend(coin: str, leverage: int) -> tuple[str, float, float]:
    macro_trend = "mixed"
    close_price = 0.0
    try:
        import httpx
        resp = httpx.post("https://api.hyperliquid.xyz/info", json={
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": "4h",
                     "startTime": int((time.time() - 604800) * 1000),
                     "endTime": int(time.time() * 1000)},
        }, timeout=30)
        resp.raise_for_status()
        candles_4h = resp.json()
        if candles_4h:
            rows_4h = [float(c["c"]) for c in candles_4h]
            closes_4h = pd.Series(rows_4h)
            if len(closes_4h) >= 50:
                ema9 = ema_func(closes_4h, 9).iloc[-1]
                ema21 = ema_func(closes_4h, 21).iloc[-1]
                ema50 = ema_func(closes_4h, 50).iloc[-1]
                macro_trend = "bullish" if ema9 > ema21 > ema50 else "bearish" if ema9 < ema21 < ema50 else "mixed"
            close_price = float(candles_4h[-1]["c"])
    except Exception as e:
        logger.warning(f"Failed to fetch 4h candles for {coin}: {e}")
    liq_dist_pct = round(100.0 / leverage, 1) if leverage else 1.0
    liq_price = round(close_price * (1 - 1.0 / leverage), 4) if close_price and leverage else 0.0
    return macro_trend, liq_price, liq_dist_pct


def _run_single_coin_signal(coin: str, market_context: dict | None = None) -> dict | None:
    cfg = get_runtime_config()
    ohlcv = _fetch_ohlcv(coin)
    if ohlcv is None or ohlcv.empty:
        logger.warning(f"{coin}: no OHLCV — skipping")
        return None

    if not market_context:
        market_context = get_market_context(hl, coin)

    enabled_models = redis.get_enabled_models()
    if not enabled_models or set(enabled_models) != set(signal_engine.MODEL_KEYS):
        logger.warning(f"Model mismatch — reseeding for {coin}")
        redis.set_model_defs(signal_engine.get_model_defs())
        redis.set_enabled_models(list(signal_engine.MODEL_KEYS))
        enabled_models = list(signal_engine.MODEL_KEYS)

    groq_key = redis.get_config("groq_api_key", GROQ_API_KEY) or GROQ_API_KEY
    gemini_keys = get_coin_gemini_keys(coin)

    closes = [round(float(c), 5) for c in ohlcv["close"].tail(15).tolist()]
    market_context["recent_closes"] = closes

    macro_trend, liq_price, liq_dist_pct = _compute_macro_trend(coin, cfg["leverage"])

    last = redis.get_current_signal()
    last_dir = last["direction"] if last else None
    last_reason = last.get("reasoning", "")[:120] if last else None

    pos = redis.get_position()
    current_pnl = float(pos.get("unrealized_pnl")) if pos and pos.get("unrealized_pnl") is not None else None

    signal = signal_engine.generate_signal(
        ohlcv,
        coin=coin,
        enabled_models=enabled_models,
        tp_usd=cfg["tp_usd"],
        sl_usd=cfg["sl_usd"],
        leverage=cfg["leverage"],
        trade_amount=cfg["trade_amount"],
        groq_api_key=groq_key,
        last_signal_direction=last_dir,
        last_signal_reasoning=last_reason,
        consecutive_waits=0,
        current_pnl=current_pnl,
        market_context=market_context,
        gemini_api_keys=gemini_keys,
        db=db,
        macro_trend=macro_trend,
        liq_price=liq_price,
        liq_dist_pct=liq_dist_pct,
    )

    signal["_coin"] = coin
    signal["timestamp"] = time.time()
    details = signal.pop("model_details", [])
    signal["model_details"] = details

    try:
        db.save_signal({
            "coin": coin,
            "direction": signal["direction"],
            "confidence": signal["confidence"],
            "regime": signal.get("regime"),
            "reasoning": signal.get("reasoning"),
            "action_taken": "published",
        })
    except Exception:
        pass

    return signal


def run_multi_asset_signal(coins: list[str] | None = None) -> dict[str, dict]:
    logger.info("=== MULTI-ASSET SIGNAL RUN START ===")
    if coins is None:
        coins = COIN_LIST

    market_data: dict[str, dict] = {}
    try:
        market_data = fetch_all_market_data(coins)
        logger.info(f"Market data fetched for {len(market_data)} coins")
    except Exception as e:
        logger.warning(f"Async market data fetch failed ({e}) — falling back to per-coin sync fetch")

    signals: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(len(coins), 5)) as executor:
        future_to_coin = {}
        for coin in coins:
            ctx = market_data.get(coin)
            future_to_coin[executor.submit(_run_single_coin_signal, coin, ctx)] = coin
            time.sleep(2)

        try:
            for future in as_completed(future_to_coin, timeout=600):
                coin = future_to_coin[future]
                try:
                    result = future.result(timeout=5)
                    if result:
                        signals[coin] = result
                        logger.info(f"{coin}: {result['direction']} ({result['confidence']:.2f})")
                    else:
                        logger.warning(f"{coin}: no signal returned")
                except Exception as e:
                    logger.exception(f"{coin}: signal error: {e}")
        except TimeoutError:
            logger.warning(f"Multi-asset signal run timed out — collected {len(signals)}/{len(coins)} signals")

    logger.info(f"=== MULTI-ASSET SIGNAL RUN END: {len(signals)} signals of {len(coins)} ===")
    return signals


def aggregate_signals(signals: dict[str, dict]) -> dict | None:
    if not signals:
        logger.info("aggregate_signals: no signals to aggregate")
        return None

    candidates: list[dict] = []
    tally: dict[str, int] = {"long": 0, "short": 0, "wait": 0}
    for coin, sig in signals.items():
        d = sig.get("direction", "wait")
        tally[d] = tally.get(d, 0) + 1
        if d in ("long", "short"):
            entry = {**sig, "_coin": coin}
            candidates.append(entry)

    logger.info(f"Aggregation tally: {tally}")

    try:
        redis.client.set("multi_asset_signals", json.dumps({
            k: {"direction": v.get("direction"), "confidence": v.get("confidence"),
                "reasoning": v.get("reasoning", "")[:500]}
            for k, v in signals.items()
        }))
        redis.client.set("multi_asset_prompts", json.dumps({
            k: v.get("prompt", "")
            for k, v in signals.items()
        }))
    except Exception as e:
        logger.warning(f"Failed to save multi-asset data to Redis: {e}")

    if not candidates:
        logger.info("All-Wait fallback — no trade this cycle")
        redis.set_current_signal({
            "direction": "wait",
            "confidence": 0.0,
            "reasoning": "All 10 coins returned WAIT — no trade",
            "tally": tally,
            "timestamp": time.time(),
        })
        return None

    candidates.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    winner = candidates[0]
    coin: str = winner["_coin"]
    logger.info(f"Winner: {coin} {winner['direction']} ({winner['confidence']:.2f}) across {len(candidates)} candidates")

    redis.set_config("active_asset", coin)
    redis.set_current_signal(winner)
    if winner.get("model_details"):
        redis.set_model_details(winner["model_details"])

    try:
        redis.client.set("multi_asset_winner", winner.get("_coin", ""))
    except Exception:
        pass

    try:
        db.save_signal({
            "coin": coin,
            "direction": winner["direction"],
            "confidence": winner["confidence"],
            "regime": winner.get("regime"),
            "reasoning": winner.get("reasoning"),
            "action_taken": "aggregated_winner",
        })
    except Exception:
        pass

    return winner


@app.route("/api/v1/bot/multi-asset-data")
def get_multi_asset_data():
    signals = {}
    prompts = {}
    winner = ""
    try:
        raw = redis.client.get("multi_asset_signals")
        if raw:
            signals = json.loads(raw)
    except Exception:
        pass
    try:
        raw = redis.client.get("multi_asset_prompts")
        if raw:
            prompts = json.loads(raw)
    except Exception:
        pass
    try:
        raw = redis.client.get("multi_asset_winner")
        if raw:
            winner = raw
    except Exception:
        pass
    for coin in COIN_LIST:
        if coin not in signals:
            signals[coin] = {"direction": None, "confidence": None, "reasoning": None}
        if coin not in prompts:
            prompts[coin] = ""
    # Strip any coins no longer in COIN_LIST
    signals = {k: v for k, v in signals.items() if k in COIN_LIST}
    prompts = {k: v for k, v in prompts.items() if k in COIN_LIST}
    return jsonify({"signals": signals, "prompts": prompts, "winner": winner})


@app.route("/api/v1/bot/debug-ohlcv")
def debug_ohlcv():
    coin = request.args.get("coin", "")
    if not coin:
        return jsonify({"error": "missing coin param"}), 400
    result = _fetch_ohlcv(coin)
    if result is not None and not result.empty:
        return jsonify({"ok": True, "rows": len(result), "last_close": float(result["close"].iloc[-1])})
    return jsonify({"ok": False, "rows": 0})


@app.route("/api/v1/bot/debug-signal")
def debug_signal():
    coin = request.args.get("coin", "")
    if not coin:
        return jsonify({"error": "missing coin param"}), 400
    try:
        sig = _run_single_coin_signal(coin)
        if sig is None:
            return jsonify({"ok": False, "error": "signal is None"})
        return jsonify({"ok": True, "direction": sig.get("direction"), "confidence": sig.get("confidence"),
                        "voters": sig.get("reasoning", "")[:200], "details": sig.get("_debug_calls", {})})
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()})


@app.route("/api/v1/bot/debug-multi")
def debug_multi():
    try:
        sigs = run_multi_asset_signal()
        return jsonify({"ok": True, "count": len(sigs), "coins": list(sigs.keys())})
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()})


@app.route("/api/v1/bot/debug-redis")
def debug_redis():
    raw = redis.client.get("multi_asset_signals")
    if raw:
        signals = json.loads(raw)
        return jsonify({"ok": True, "count": len(signals), "coins": list(signals.keys()),
                        "has_none": sum(1 for v in signals.values() if v.get("direction") is None)})
    return jsonify({"ok": False, "raw": None})


@app.route("/api/v1/bot/last-error")
def last_error():
    return jsonify({"error": None, "traceback": None, "timestamp": 0})

@app.route("/api/v1/bot/voter-health")
def voter_health():
    coin = get_runtime_config().get("active_asset", "DOGE")
    try:
        health = db.get_voter_health(coin, limit=10)
        return jsonify(health)
    except Exception as e:
        logger.warning(f"voter-health error: {e}")
        return jsonify({"error": str(e), "db_enabled": db.enabled}), 500


@app.route("/api/v1/bot/test-db")
def test_db():
    """Test DB connectivity and ai_votes table."""
    results = {"db_enabled": db.enabled, "tests": []}
    if not db.enabled:
        return jsonify(results)
    try:
        # Test query
        result = db.client.table("ai_votes").select("count", count="exact").execute()
        results["tests"].append({"name": "count", "ok": True, "count": result.count})
    except Exception as e:
        results["tests"].append({"name": "count", "ok": False, "error": str(e)})
    try:
        # Test insert and delete
        test_data = {"cycle_id": "__test__", "coin": "TEST", "voter": "test", "direction": "test", "confidence": 0.5, "error": None, "created_at": "2025-01-01T00:00:00Z"}
        ins = db.client.table("ai_votes").insert(test_data).execute()
        results["tests"].append({"name": "insert", "ok": True, "id": ins.data[0].get("id") if ins.data else None})
        # Clean up
        db.client.table("ai_votes").delete().eq("cycle_id", "__test__").execute()
        results["tests"].append({"name": "delete", "ok": True})
    except Exception as e:
        results["tests"].append({"name": "insert", "ok": False, "error": str(e)})
    return jsonify(results)

@app.route("/api/v1/test-gemini")
def test_gemini():
    import os, json, httpx
    from bot.signals.providers import _extract_json, _parse_response, GEMINI_MODEL
    keys = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]
    results = {}
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
    
    trade_prompt = """You are a SOL perpetual futures analyst. Analyze the technical data to decide LONG, SHORT, or WAIT.
=== TECHNICAL ANALYSIS ===
Current price: $63.96500
Trend (EMA 9/21/50): bearish
RSI(14): 36.9
MACD histogram: 0.008691
ADX(14): 20.5
ATR(14): $0.92300
Market regime: RANGING
Respond ONLY with valid JSON:
{"direction": "long"|"short"|"wait", "confidence": 0.0-1.0, "reasoning": "..."}"""
    
    for i, k in enumerate(keys[:2]):
        key_label = f"key{i}"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={k}"
        try:
            payload = {
                "contents": [{"parts": [{"text": trade_prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 400},
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ],
            }
            with httpx.Client(timeout=30) as client:
                resp = client.post(url, json=payload)
                r = {"http": resp.status_code}
                if resp.status_code == 200:
                    body = resp.json()
                    candidates = body.get("candidates", [])
                    if candidates:
                        c = candidates[0]
                        r["finish"] = c.get("finishReason")
                        parts = c.get("content", {}).get("parts", [])
                        if parts:
                            raw = parts[0].get("text", "")
                            r["raw_preview"] = raw[:300]
                            ext = _extract_json(raw)
                            r["extracted_preview"] = ext[:300]
                            p = _parse_response(key_label, model, "test", ext)
                            if p:
                                r["parsed_ok"] = True
                                r["direction"] = p["direction"]
                            else:
                                r["parsed_ok"] = False
                                r["parse_error"] = "returned_none"
                        else:
                            r["no_parts"] = True
                    else:
                        r["no_candidates"] = True
                else:
                    r["error"] = resp.text[:200]
                results[key_label] = r
        except Exception as e:
            results[key_label] = {"exc": str(e)}
    return jsonify({
        "key_count": len(keys),
        "results": results,
        "model": model,
    })

@app.route("/api/v1/test-groq")
def test_groq():
    import json, os, httpx
    groq_key = GROQ_API_KEY
    try:
        groq_key = redis.get_config("groq_api_key", GROQ_API_KEY)
    except Exception:
        pass
    results = dict(groq_key_prefix=(groq_key[:20] + "..." if groq_key else "EMPTY"))
    try:
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": 'Reply JSON: {"direction": "long"}'}],
            "temperature": 0.3,
            "max_tokens": 300,
        }
        headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=15) as client:
            resp = client.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers)
            results["http_status"] = resp.status_code
            if resp.status_code == 200:
                results["content"] = resp.json()["choices"][0]["message"]["content"][:100]
            else:
                results["error"] = resp.text[:200]
    except Exception as e:
        results["exc"] = f"{type(e).__name__}: {e}"
    return jsonify(results)


def ai_loop():
    logger.info("AI engine started")
    while True:
        try:
            redis.set_config("ai_loop_heartbeat", str(time.time()))
            if not redis.is_bot_running():
                time.sleep(10)
                continue
            pos = redis.get_position()
            if pos and pos.get("size", 0) != 0:
                coin = pos.get("coin", "")
                if coin:
                    try:
                        live = hl.get_position(coin)
                        if not live or float(live.get("szi", 0)) == 0:
                            logger.info(f"Stale Redis position for {coin} — clearing")
                            redis.clear_position()
                            pos = None
                    except Exception:
                        pass
                if pos and pos.get("size", 0) != 0:
                    time.sleep(30)
                    continue

            last = redis.get_current_signal()
            last_time = last.get("timestamp", 0) if last else 0
            wait = max(0, last_time + AI_LOOP_INTERVAL - time.time())
            if wait > 0:
                if wait < 60:
                    time.sleep(wait)
                else:
                    time.sleep(60)
                continue

            signals = run_multi_asset_signal()
            aggregate_signals(signals)
        except Exception as e:
            logger.exception(f"AI loop error: {e}")
            time.sleep(60)


def seed_redis_config():
    defaults = {
        "tp_usd": str(TAKE_PROFIT_USD),
        "sl_usd": str(STOP_LOSS_USD),
        "trade_amount": str(TRADE_AMOUNT_USD),
        "leverage": str(LEVERAGE),
        "min_confidence": str(MIN_CONFIDENCE),
        "max_daily_loss": str(MAX_DAILY_LOSS_USD),
        "max_daily_loss_enabled": "1",
        "force_trade_after_waits": "0",
        "groq_api_key": GROQ_API_KEY,
        "active_asset": ACTIVE_ASSET,
    }
    for key, val in defaults.items():
        existing = redis.get_config(key, "")
        if not existing or key == "groq_api_key":
            redis.set_config(key, val)
            logger.info(f"Seeded Redis config:{key} = {val}")


def load_supabase_config():
    try:
        configs = db.client.table("bot_config").select("*").execute()
        for row in configs.data:
            redis.set_config(row["key"], row["value"])
            logger.info(f"Loaded from Supabase: config:{row['key']} = {row['value']}")
    except Exception as e:
        logger.info(f"Supabase config not available (will use defaults): {e}")


@app.route("/api/v1/bot/transfer-to-perp", methods=["POST"])
def transfer_endpoint():
    try:
        spot = hl.get_spot_balance()
        return jsonify({"ok": True, "message": "Unified account — spot balance is perp margin", "spot_usdc": spot, "perp_balance": 0.0})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def init_bot():
    try:
        hl.initialize()
    except Exception as e:
        logger.error(f"Hyperliquid init failed: {e}")
    try:
        seed_redis_config()
    except Exception as e:
        logger.error(f"Redis seed failed: {e}")
    try:
        # Clear stale multi-asset data from previous runs (coins may have changed)
        redis.client.delete("multi_asset_signals", "multi_asset_prompts", "multi_asset_winner")
    except Exception:
        pass
    try:
        load_supabase_config()
    except Exception as e:
        logger.info(f"Supabase config load skipped: {e}")
    try:
        defs = get_model_defs()
        redis.set_model_defs(defs)
        enabled = [d["key"] for d in defs]
        redis.set_enabled_models(enabled)
        logger.info(f"Seeded {len(defs)} model defs (enabled: {enabled})")
    except Exception as e:
        logger.warning(f"Failed to seed model defs: {e}")
    try:
        bal = hl.get_balance()
        logger.info(f"Available balance: ${bal['account_value']:.2f} (spot=${bal['spot_usdc']:.2f}, perp=${bal['perp_value']:.2f})")
    except Exception as e:
        logger.warning(f"Could not fetch balance: {e}")
    logger.info(f"Bot starting — wallet: {hl.address}")

    t1 = threading.Thread(target=trading_loop, daemon=True)
    t1.start()

    t2 = threading.Thread(target=ai_loop, daemon=True)
    t2.start()


t_init = threading.Thread(target=init_bot, daemon=True)
t_init.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)
