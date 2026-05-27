import os
import json
import time
import threading
import logging
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
    OPENROUTER_API_KEYS,
    GROQ_API_KEY,
)
from bot.hyperliquid_client import HyperliquidClient
from bot.order_executor import OrderExecutor
from bot.db import Database
from bot.redis_client import RedisClient
from bot.signals import providers as signal_engine
from bot.signals.providers import get_model_defs

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
    return jsonify({
        "name": "DOGE Perp Bot",
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
    return jsonify({
        "running": running,
        "last_signal": signal,
        "position": position,
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
    signal = run_ai_signal(allow_wait=True)
    if signal:
        return jsonify({"ok": True, "signal": signal})
    return jsonify({"ok": False, "error": "Signal generation failed"}), 500


@app.route("/api/v1/bot/force-trade", methods=["POST"])
def force_trade():
    signal = run_ai_signal(allow_wait=False)
    if signal and signal["direction"] in ("long", "short"):
        opened = open_trade(signal)
        return jsonify({"ok": True, "signal": signal, "trade_opened": opened})
    if signal:
        return jsonify({"ok": True, "signal": signal, "trade_opened": False})
    return jsonify({"ok": False, "error": "Signal generation failed"}), 500


@app.route("/api/v1/bot/close-position", methods=["POST"])
def close_position():
    logger.info("Close position requested via API")
    try:
        doge_pos = hl.get_doge_position()
        if doge_pos and float(doge_pos["szi"]) != 0:
            open_orders = hl.get_open_orders()
            for o in open_orders:
                executor.exchange.cancel(o["coin"], o["oid"])
            executor.close_position()
            logger.info("Position closed via API")
        redis.clear_position()
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception(f"Close position error: {e}")
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
        open_orders = hl.get_open_orders()
        executor.cancel_all_orders(open_orders)
        executor.close_position()
    except Exception as e:
        logger.exception(f"Kill switch error: {e}")
    db.log("CRITICAL", "Emergency stop triggered")


def get_runtime_config() -> dict:
    return {
        "tp_usd": float(redis.get_config("tp_usd", str(TAKE_PROFIT_USD))),
        "sl_usd": float(redis.get_config("sl_usd", str(STOP_LOSS_USD))),
        "trade_amount": float(redis.get_config("trade_amount", str(TRADE_AMOUNT_USD))),
        "leverage": int(redis.get_config("leverage", str(LEVERAGE))),
        "min_confidence": float(redis.get_config("min_confidence", str(MIN_CONFIDENCE))),
        "max_daily_loss": float(redis.get_config("max_daily_loss", str(MAX_DAILY_LOSS_USD))),
        "max_daily_loss_enabled": redis.get_config("max_daily_loss_enabled", "1"),
    }


def open_trade(signal: dict) -> bool:
    cfg = get_runtime_config()
    is_buy = signal["direction"] == "long"
    entry_price = hl.get_current_price()
    size_usd = cfg["trade_amount"]
    lev = cfg["leverage"]
    notional = size_usd * lev

    logger.info(f"Opening {signal['direction']} trade — confidence: {signal['confidence']:.2f} @ ${entry_price:.5f} (margin=${size_usd}, leverage={lev}x, notional=${notional:.2f})")

    hl.set_leverage("DOGE", lev, is_cross=True)
    result = executor.open_market(is_buy, notional)

    statuses = result.get("response", {}).get("data", {}).get("statuses", [{}])
    if not statuses or ("resting" not in statuses[0] and "filled" not in statuses[0]):
        logger.error(f"Order failed: {result}")
        try:
            db.log("ERROR", f"Order failed: {result}")
        except Exception:
            pass
        return False

    entry_price = hl.get_current_price()

    tp_ratio = cfg["tp_usd"] / notional
    sl_ratio = cfg["sl_usd"] / notional
    if is_buy:
        tp_price = entry_price * (1 + tp_ratio)
        sl_price = entry_price * (1 - sl_ratio)
    else:
        tp_price = entry_price * (1 - tp_ratio)
        sl_price = entry_price * (1 + sl_ratio)

    tp_result = executor.set_take_profit(is_buy, notional, tp_price)
    tp_statuses = tp_result.get("response", {}).get("data", {}).get("statuses", [])
    if tp_statuses and "error" in str(tp_statuses[0]):
        logger.error(f"TP order failed: {tp_statuses[0]}")
        try:
            db.log("ERROR", f"TP order failed: {tp_statuses[0]}")
        except Exception:
            pass
    else:
        logger.info(f"TP order placed: {tp_result}")

    sl_result = executor.set_stop_loss(is_buy, notional, sl_price)
    sl_statuses = sl_result.get("response", {}).get("data", {}).get("statuses", [])
    if sl_statuses and "error" in str(sl_statuses[0]):
        logger.error(f"SL order failed: {sl_statuses[0]}")
        try:
            db.log("ERROR", f"SL order failed: {sl_statuses[0]}")
        except Exception:
            pass
    else:
        logger.info(f"SL order placed: {sl_result}")

    try:
        db.save_trade({
            "coin": "DOGE",
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
        "coin": "DOGE",
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
        db.log("INFO", f"Trade opened: {signal['direction']} @ {entry_price:.5f} (TP: {tp_price:.5f}, SL: {sl_price:.5f})")
    except Exception:
        pass
    logger.info(f"Trade opened successfully")
    return True


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

            # Handle close-position signal from dashboard
            if redis.get_close_position_signal():
                logger.info("Close position signal received")
                doge_pos = hl.get_doge_position()
                if doge_pos and float(doge_pos["szi"]) != 0:
                    try:
                        open_orders = hl.get_open_orders()
                        for o in open_orders:
                            executor.exchange.cancel(o["coin"], o["oid"])
                        executor.close_position()
                        logger.info("Position closed via dashboard signal")
                    except Exception as e:
                        logger.exception(f"Close position error: {e}")
                redis.clear_position()
                redis.clear_close_position_signal()
                run_ai_signal(allow_wait=True)
                time.sleep(5)
                continue

            doge_pos = hl.get_doge_position()

            if doge_pos and float(doge_pos["szi"]) != 0:
                direction = "long" if float(doge_pos["szi"]) > 0 else "short"
                cached = redis.get_position()
                redis.set_position({
                    "coin": doge_pos["coin"],
                    "direction": direction,
                    "size": float(doge_pos["szi"]),
                    "entry_price": float(doge_pos["entryPx"]),
                    "unrealized_pnl": float(doge_pos["unrealizedPnl"]),
                    "account_value": hl.get_balance()["account_value"],
                    "tp_price": cached.get("tp_price") if cached else None,
                    "sl_price": cached.get("sl_price") if cached else None,
                })
                time.sleep(30)
                continue
            else:
                cached = redis.get_position()
                if cached and cached.get("size", 0) != 0:
                    logger.info("Position closed by TP/SL trigger")
                    try:
                        open_trades = db.get_open_trades()
                        if open_trades:
                            t = open_trades[0]
                            exit_price = hl.get_current_price()
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
                        db.log("INFO", "Trade closed by trigger order")
                    except Exception as ex:
                        logger.exception(f"close_trade error: {ex}")
                    redis.clear_position()
                    run_ai_signal(allow_wait=True)

            signal = redis.get_current_signal()
            if not signal:
                time.sleep(10)
                continue

            if signal["direction"] == "wait":
                time.sleep(30)
                continue

            cfg = get_runtime_config()
            if signal["confidence"] < cfg["min_confidence"]:
                time.sleep(30)
                continue

            signal_age = time.time() - signal.get("timestamp", 0)
            if signal_age > AI_LOOP_INTERVAL - 600:
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

            open_trade(signal)
            time.sleep(10)

        except Exception as e:
            logger.exception(f"Trading loop error: {e}")
            time.sleep(10)

    logger.info("Trading loop terminated")


def run_ai_signal(allow_wait: bool = True) -> dict | None:
    try:
        result = hl.info.meta_and_asset_ctxs()
        meta, ctxs = result[0], result[1]
        doge_ctx = None
        for i, asset in enumerate(meta["universe"]):
            if asset["name"] == "DOGE":
                doge_ctx = ctxs[i]
                break

        candles = hl.info.candles_snapshot(
            "DOGE", "15m",
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
        keys_str = redis.get_config("openrouter_keys", ",".join(OPENROUTER_API_KEYS))
        api_keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        cfg = get_runtime_config()
        groq_key = redis.get_config("groq_api_key", GROQ_API_KEY)
        signal = signal_engine.generate_signal(
            ohlcv,
            enabled_models=enabled_models if enabled_models else None,
            api_keys=api_keys if api_keys else None,
            allow_wait=allow_wait,
            tp_usd=cfg["tp_usd"],
            sl_usd=cfg["sl_usd"],
            leverage=cfg["leverage"],
            trade_amount=cfg["trade_amount"],
            groq_api_key=groq_key,
        )

        details = signal.pop("model_details", [])
        redis.set_current_signal(signal)
        redis.set_model_details(details)
        logger.info(f"Signal: {signal['direction']} ({signal['confidence']:.2f}) — {signal.get('reasoning', '')[:120]}")

        try:
            db.save_signal({
                "coin": "DOGE",
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
        return None


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
            run_ai_signal(allow_wait=True)
        except Exception as e:
            logger.exception(f"AI loop error: {e}")
        time.sleep(AI_LOOP_INTERVAL)


def seed_redis_config():
    defaults = {
        "tp_usd": str(TAKE_PROFIT_USD),
        "sl_usd": str(STOP_LOSS_USD),
        "trade_amount": str(TRADE_AMOUNT_USD),
        "leverage": str(LEVERAGE),
        "min_confidence": str(MIN_CONFIDENCE),
        "max_daily_loss": str(MAX_DAILY_LOSS_USD),
        "max_daily_loss_enabled": "1",
        "openrouter_keys": ",".join(OPENROUTER_API_KEYS),
        "groq_api_key": GROQ_API_KEY,
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
        existing_defs = redis.get_model_defs()
        existing_keys = {d["key"] for d in existing_defs} if existing_defs else set()
        new_keys = {d["key"] for d in defs}
        redis.set_model_defs(defs)
        if existing_defs is None or existing_keys != new_keys:
            enabled = [d["key"] for d in defs]
            redis.set_enabled_models(enabled)
            logger.info(f"Seeded {len(defs)} model defs in Redis (enabled: {enabled})")
        else:
            logger.info(f"Model defs unchanged ({len(defs)} models)")
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
