import os
import json
import time
import traceback
import threading
import logging
from dataclasses import dataclass
import httpx
import pandas as pd
from flask import Flask, jsonify

from bot.config import (
    TRADE_AMOUNT_USD,
    TAKE_PROFIT_USD,
    STOP_LOSS_USD,
    MIN_CONFIDENCE,
    LEVERAGE,
    MAX_DAILY_LOSS_USD,
    AI_LOOP_INTERVAL,
    GROQ_API_KEY,
    GEMINI_API_KEY,
    ACTIVE_ASSET,
)
from bot.hyperliquid_client import HyperliquidClient
from bot.order_executor import OrderExecutor
from bot.db import Database
from bot.redis_client import RedisClient
from bot.signals import providers as signal_engine
from bot.signals.providers import get_model_defs
from bot.market_data import get_market_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

hl = HyperliquidClient()
executor = OrderExecutor(hl.exchange, hl.info, hl.address)
db = Database()
redis = RedisClient()

start_time = time.time()

app = Flask(__name__)


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
    running = redis.is_bot_running()
    signal = redis.get_current_signal()
    position = redis.get_position()
    cfg = get_runtime_config()
    cfg["ai_loop_interval"] = str(AI_LOOP_INTERVAL)
    cfg["groq_api_key"] = redis.get_config("groq_api_key", GROQ_API_KEY)
    remaining = max(0, (signal.get("timestamp", 0) if signal else 0) + AI_LOOP_INTERVAL - time.time())
    active_asset = cfg.get("active_asset", "DOGE")
    return jsonify({
        "running": running,
        "last_signal": signal,
        "position": position,
        "mark_price": hl.get_current_price(active_asset),
        "config": cfg,
        "remaining_seconds": int(remaining),
    })


@app.route("/api/v1/bot/debug")
def bot_debug():
    from bot.signals.providers import MODEL_KEYS
    enabled = redis.get_enabled_models()
    defs = redis.get_model_defs()
    return jsonify({
        "MODEL_KEYS": MODEL_KEYS,
        "enabled_models": enabled,
        "model_defs": defs,
    })


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
    coin = get_runtime_config().get("active_asset", "DOGE")
    signal = run_ai_signal(coin, allow_wait=True, from_ai_loop=False)
    if signal:
        return jsonify({"ok": True, "signal": signal})
    return jsonify({"ok": False, "error": "Signal generation failed"}), 500


@app.route("/api/v1/bot/force-trade", methods=["POST"])
def force_trade():
    cfg = get_runtime_config()
    coin = cfg.get("active_asset", "DOGE")
    signal = run_ai_signal(coin, allow_wait=False, from_ai_loop=False)
    if signal and signal["direction"] in ("long", "short"):
        opened = open_trade(signal, coin)
        return jsonify({"ok": True, "signal": signal, "trade_opened": opened})
    if signal:
        return jsonify({"ok": True, "signal": signal, "trade_opened": False})
    return jsonify({"ok": False, "error": "Signal generation failed"}), 500


@app.route("/api/v1/bot/set-tp-sl", methods=["POST"])
def set_tp_sl():
    try:
        cfg = get_runtime_config()
        coin = cfg.get("active_asset", "DOGE")
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
        if pos and float(pos["szi"]) != 0:
            open_orders = hl.get_open_orders()
            for o in open_orders:
                executor.exchange.cancel(o["coin"], o["oid"])
            executor.close_position(coin=coin)
            logger.info(f"Position closed via API ({coin})")
        redis.clear_position()
        close_position_in_db()
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
        if asset not in ("DOGE", "SOL"):
            return jsonify({"ok": False, "error": "Asset must be DOGE or SOL"}), 400
        for coin in ("DOGE", "SOL"):
            pos = hl.get_position(coin)
            if pos and float(pos["szi"]) != 0:
                return jsonify({"ok": False, "error": f"Cannot switch asset while {coin} position is open"}), 400
        redis.set_config("active_asset", asset)
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
        "active_asset": redis.get_config("active_asset", ACTIVE_ASSET),
    }


def _place_tp_sl(coin: str, is_buy: bool, notional: float, tp_price: float, sl_price: float) -> dict:
    results = {"tp": None, "sl": None}
    try:
        open_orders = hl.get_open_orders()
        for o in open_orders:
            executor.exchange.cancel(o["coin"], o["oid"])
    except Exception as e:
        logger.warning(f"Cancel existing orders: {e}")
    try:
        results["tp"] = executor.set_take_profit(coin, is_buy, notional, tp_price)
        logger.info(f"TP result: {results['tp']}")
    except Exception as e:
        logger.error(f"TP placement failed: {e}")
    try:
        results["sl"] = executor.set_stop_loss(coin, is_buy, notional, sl_price)
        logger.info(f"SL result: {results['sl']}")
    except Exception as e:
        logger.error(f"SL placement failed: {e}")
    return results


def open_trade(signal: dict, coin: str = "DOGE") -> bool:
    cfg = get_runtime_config()
    is_buy = signal["direction"] == "long"
    entry_price = hl.get_current_price(coin)
    size_usd = cfg["trade_amount"]
    lev = cfg["leverage"]
    notional = size_usd * lev

    if notional < 1.0:
        logger.warning(f"Notional ${notional:.2f} below $1 minimum, refusing trade")
        return False

    logger.info(f"Opening {signal['direction']} {coin} trade — confidence: {signal['confidence']:.2f} @ ${entry_price:.5f} (margin=${size_usd}, leverage={lev}x, notional=${notional:.2f})")

    hl.set_leverage(coin, lev, is_cross=True)
    result = executor.open_market(coin, is_buy, notional)

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

    _place_tp_sl(coin, is_buy, notional, tp_price, sl_price)

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


def trading_loop():
    logger.info("Trading loop started")
    while True:
        try:
            if redis.is_emergency_stop():
                kill_switch()
                break

            if not redis.is_bot_running():
                time.sleep(10)
                continue

            cfg = get_runtime_config()
            coin = cfg.get("active_asset", "DOGE")

            # Handle close-position signal from dashboard
            if redis.get_close_position_signal():
                logger.info("Close position signal received")
                pos = hl.get_position(coin)
                if pos and float(pos["szi"]) != 0:
                    try:
                        open_orders = hl.get_open_orders()
                        for o in open_orders:
                            executor.exchange.cancel(o["coin"], o["oid"])
                        executor.close_position(coin=coin)
                        logger.info(f"Position closed via dashboard signal ({coin})")
                    except Exception as e:
                        logger.exception(f"Close position error: {e}")
                redis.clear_position()
                redis.clear_close_position_signal()
                time.sleep(5)
                continue

            pos = hl.get_position(coin)

            if pos and float(pos["szi"]) != 0:
                direction = "long" if float(pos["szi"]) > 0 else "short"
                cached = redis.get_position()
                entry_px = float(pos["entryPx"])
                sz = abs(float(pos["szi"]))
                notional = sz * entry_px
                tp_price = cached.get("tp_price") if cached else None
                sl_price = cached.get("sl_price") if cached else None
                if tp_price is None or sl_price is None:
                    logger.info("TP/SL missing — placing now")
                    is_buy = float(pos["szi"]) > 0
                    tp_ratio = cfg["tp_usd"] / notional
                    sl_ratio = cfg["sl_usd"] / notional
                    if is_buy:
                        tp_price = entry_px * (1 + tp_ratio)
                        sl_price = entry_px * (1 - sl_ratio)
                    else:
                        tp_price = entry_px * (1 - tp_ratio)
                        sl_price = entry_px * (1 + sl_ratio)
                    _place_tp_sl(coin, is_buy, notional, tp_price, sl_price)
                try:
                    account_value = hl.get_balance()["account_value"]
                except Exception:
                    account_value = cached.get("account_value", 0) if cached else 0
                redis.set_position({
                    "coin": pos["coin"],
                    "direction": direction,
                    "size": float(pos["szi"]),
                    "entry_price": entry_px,
                    "unrealized_pnl": float(pos["unrealizedPnl"]),
                    "account_value": account_value,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                })
                time.sleep(30)
                continue
            elif pos is None:
                cached = redis.get_position()
                if cached and abs(cached.get("size", 0)) > 0:
                    logger.info("Position gone from exchange — closing trade in DB")
                    close_position_in_db(coin)
                time.sleep(5)
            elif float(pos["szi"]) == 0:
                cached = redis.get_position()
                if cached and cached.get("size", 0) != 0:
                    logger.info("Position closed (sz=0)")
                    close_position_in_db(coin)

            signal = redis.get_current_signal()
            if not signal:
                time.sleep(10)
                continue

            if signal["direction"] == "wait":
                time.sleep(30)
                continue

            if signal["confidence"] < cfg["min_confidence"]:
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
                        for o in open_orders:
                            executor.exchange.cancel(o["coin"], o["oid"])
                        executor.close_position(coin=coin)
                        logger.info(f"Closed {coin} position for flip")
                    except Exception as e:
                        logger.exception(f"Flip close error: {e}")
                    redis.clear_position()
                    time.sleep(3)

            open_trade(signal, coin)
            time.sleep(10)

        except Exception as e:
            logger.exception(f"Trading loop error: {e}")
            time.sleep(10)

    logger.info("Trading loop terminated")


_signal_call_count = 0

@dataclass
class _LastRunError:
    error: str | None = None
    traceback: str | None = None
    timestamp: float = 0.0

_last_error = _LastRunError()

def run_ai_signal(coin: str = "DOGE", allow_wait: bool = True, from_ai_loop: bool = True) -> dict | None:
    global _signal_call_count, _last_error
    _signal_call_count += 1
    try:
        candles = hl.info.candles_snapshot(
            coin, "15m",
            int((time.time() - 86400) * 1000),
            int(time.time() * 1000),
        )

        if not candles:
            logger.warning("No candles available")
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

        ohlcv = pd.DataFrame(rows).sort_values("timestamp").tail(100)

        enabled_models = redis.get_enabled_models()
        logger.info("run_ai_signal: enabled_models from Redis=%s", enabled_models)
        if not enabled_models or set(enabled_models) != set(signal_engine.MODEL_KEYS):
            logger.warning("Model mismatch detected — reseeding: redis=%s models=%s", enabled_models, signal_engine.MODEL_KEYS)
            defs = signal_engine.get_model_defs()
            redis.set_model_defs(defs)
            redis.set_enabled_models(list(signal_engine.MODEL_KEYS))
            enabled_models = list(signal_engine.MODEL_KEYS)
            logger.info("Reseeded enabled_models=%s", enabled_models)
        cfg = get_runtime_config()
        groq_key = redis.get_config("groq_api_key", GROQ_API_KEY)
        gemini_key = redis.get_config("gemini_api_key", GEMINI_API_KEY)

        market_context = get_market_context(hl, coin)

        last = redis.get_current_signal()
        last_dir = last["direction"] if last else None
        last_reason = last.get("reasoning")[:120] if last else None
        c_waits = redis.get_consecutive_waits()
        if last_dir == "wait":
            c_waits += 1
            redis.set_consecutive_waits(c_waits)
        else:
            c_waits = 0
            redis.set_consecutive_waits(0)
        pos = redis.get_position()
        current_pnl = float(pos.get("unrealized_pnl")) if pos and pos.get("unrealized_pnl") is not None else None

        signal = signal_engine.generate_signal(
            ohlcv,
            coin=coin,
            enabled_models=enabled_models,
            allow_wait=(c_waits < 3),
            tp_usd=cfg["tp_usd"],
            sl_usd=cfg["sl_usd"],
            leverage=cfg["leverage"],
            trade_amount=cfg["trade_amount"],
            groq_api_key=groq_key,
            last_signal_direction=last_dir,
            last_signal_reasoning=last_reason,
            consecutive_waits=c_waits,
            current_pnl=current_pnl,
            market_context=market_context,
            gemini_api_key=gemini_key,
        )

        signal["_debug_redis_enabled"] = enabled_models
        signal["_debug_call"] = _signal_call_count
        signal["_debug_interval"] = AI_LOOP_INTERVAL
        details = signal.pop("model_details", [])
        signal["model_details"] = details
        signal["timestamp"] = time.time()
        redis.set_current_signal(signal)
        redis.set_model_details(details)
        logger.info(f"Signal: {signal['direction']} ({signal['confidence']:.2f}) — {signal.get('reasoning', '')[:120]}")

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
    except Exception as e:
        logger.exception(f"run_ai_signal error: {e}")
        tb = traceback.format_exc()
        _last_error = _LastRunError(error=str(e), traceback=tb, timestamp=time.time())
        return None


@app.route("/api/v1/bot/last-error")
def last_error():
    return jsonify({
        "error": _last_error.error,
        "traceback": _last_error.traceback,
        "timestamp": _last_error.timestamp,
    })


def ai_loop():
    logger.info("AI engine started")
    while True:
        try:
            if not redis.is_bot_running():
                time.sleep(10)
                continue
            pos = redis.get_position()
            if pos and pos.get("size", 0) != 0:
                time.sleep(30)
                continue

            coin = get_runtime_config().get("active_asset", "DOGE")
            last = redis.get_current_signal()
            last_time = last.get("timestamp", 0) if last else 0
            wait = max(0, last_time + AI_LOOP_INTERVAL - time.time())
            if wait > 0:
                if wait < 60:
                    time.sleep(wait)
                else:
                    time.sleep(60)
                continue

            run_ai_signal(coin, allow_wait=True, from_ai_loop=True)
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
        "groq_api_key": GROQ_API_KEY,
        "gemini_api_key": GEMINI_API_KEY,
        "active_asset": ACTIVE_ASSET,
    }
    for key, val in defaults.items():
        existing = redis.get_config(key, "")
        if not existing:
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


init_bot()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)
