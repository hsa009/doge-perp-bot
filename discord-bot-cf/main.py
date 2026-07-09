import json
import js

WORKER_URL = "https://telegram-bot.o8673587.workers.dev"


async def _tg_send(chat_id, text, token):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    })
    await js.fetch(
        url,
        js.JSON.parse(
            json.dumps({
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": payload,
            })
        ),
    )


async def _fetch_api(path, env, timeout_ms=0):
    base = getattr(env, "HF_SPACE_URL", "") or ""
    if not base:
        return None
    opts = {"method": "GET"}
    if timeout_ms > 0:
        controller = js.AbortController.new()
        js.setTimeout(controller.abort, timeout_ms)
        opts["signal"] = controller.signal
    try:
        resp = await js.fetch(
            f"{base}{path}",
            js.JSON.parse(json.dumps(opts)),
        )
        if resp.status != 200:
            return None
        return json.loads(await resp.text())
    except Exception as e:
        js.console.log(f"[_fetch_api] error for {path}: {e}")
        return None


async def _call_api(path, method, env, body=None):
    base = getattr(env, "HF_SPACE_URL", "") or ""
    if not base:
        return None
    opts = {"method": method}
    if body:
        opts["headers"] = {"Content-Type": "application/json"}
        opts["body"] = json.dumps(body)
    resp = await js.fetch(
        f"{base}{path}",
        js.JSON.parse(json.dumps(opts)),
    )
    if resp.status >= 400:
        return None
    return json.loads(await resp.text())


async def on_fetch(request, env):
    try:
        method = str(request.method).upper()
        token = getattr(env, "TELEGRAM_BOT_TOKEN", "") or ""

        if method == "GET":
            url_str = str(request.url) if hasattr(request, "url") else ""
            if "reset-webhook" in url_str and token:
                await js.fetch(
                    f"https://api.telegram.org/bot{token}/deleteWebhook",
                    js.JSON.parse(json.dumps({"method": "POST"})),
                )
                await js.fetch(
                    f"https://api.telegram.org/bot{token}/setWebhook?url=https://telegram-bot.o8673587.workers.dev/",
                    js.JSON.parse(json.dumps({"method": "POST"})),
                )
                return js.Response.new("Webhook reset")
            return js.Response.new("OK")

        allowed = getattr(env, "ALLOWED_TELEGRAM_ID", "") or ""

        raw = await request.text()

        # Check webhook by simply returning OK for Telegram's POST
        try:
            update = json.loads(raw) if raw else {}
            msg = update.get("message", {})
            user_id = str(msg.get("from", {}).get("id", ""))
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "")
        except (ValueError, TypeError, AttributeError):
            return js.Response.new("OK")

        if not token or not allowed:
            return js.Response.new("OK")

        if user_id != allowed or not chat_id:
            return js.Response.new("OK")

        if text == "/dashboard":
            try:
                status = await _fetch_api("/api/v1/bot/status", env)
                pos = (status or {}).get("position")

                lines = ["*Trading Dashboard*", ""]
                running = (status or {}).get("running", False)
                lines.append(f"Status: {'Running' if running else 'Stopped'}")

                lines.append("")
                if pos and float(pos.get("size", 0)) > 0 and float(pos.get("entry_price", 0)) > 0:
                    lines.append((pos.get("direction") or "").upper())
                    lines.append(f"{abs(float(pos.get('size', 0)))} {pos.get('coin', '')}")
                    lines.append(f"${float(pos.get('entry_price', 0)):.5f}")
                    lines.append(f"${float(pos.get('unrealized_pnl', 0)):.2f}")
                else:
                    lines.append("No open position")

                await _tg_send(chat_id, "\n".join(lines), token)
            except Exception as e:
                js.console.log(f"[dashboard] error: {e}")

        elif text == "/signal":
            try:
                data = await _fetch_api("/api/v1/bot/multi-asset-data", env)
            except Exception as e:
                js.console.log(f"[signal] error: {e}")
                data = None

            lines = ["*AI Signals*", ""]
            signals = (data or {}).get("signals", {})
            for coin in sorted(signals.keys()):
                s = signals[coin]
                d = s.get("direction", "?")
                c = s.get("confidence", 0)
                if s.get("disabled", False):
                    lines.append(f"{coin} — DISABLED")
                else:
                    lines.append(f"{coin}: {d.upper()} ({c:.2f})")

            lines.append("")
            winner = (data or {}).get("winner", "") or ""
            lines.append(f"Winner: {winner or '—'}")

            await _tg_send(chat_id, "\n".join(lines), token)

        elif text == "/close":
            try:
                result = await _call_api("/api/v1/bot/close-position", "POST", env)
            except Exception:
                result = None
            msg = "Position closed" if (result or {}).get("ok") else "Failed to close or no position open"
            await _tg_send(chat_id, msg, token)

        elif text == "/ping":
            await _tg_send(chat_id, "pong", token)

        elif text == "/debug":
            data = await _fetch_api("/api/v1/debug-keys", env, timeout_ms=20000)
            if not data:
                data = await _fetch_api("/api/v1/coin-key-map", env)
            if not data:
                await _tg_send(chat_id, "Debug: HF Space unreachable", token)
            elif "mapping" in data:
                mapping = data.get("mapping", {})
                msg = "Keys per coin:"
                for coin in sorted(mapping.keys()):
                    info = mapping[coin]
                    count = info.get("count", 0)
                    keys = ", ".join(info.get("keys", []))
                    msg += f"\n{coin}: {count} key(s) {keys}"
                msg += f"\n\nTotal coins: {data.get('total_coins', 0)}"
                await _tg_send(chat_id, msg, token)
            else:
                total = data.get("total", 0)
                working = data.get("working", 0)
                msg = f"Debug: {working}/{total} keys working"
                results = data.get("results", {})
                for coin in sorted(results.keys()):
                    for entry in results[coin]:
                        err = entry.get("error") or entry.get("exc") or ""
                        label = entry.get("label", "")
                        http = entry.get("http", "")
                        key_preview = entry.get("key_preview", "")
                        if entry.get("ok"):
                            msg += f"\n{coin}: {label} ({key_preview}) OK"
                        else:
                            err_snippet = (err[:60] if err else f"HTTP_{http}")
                            msg += f"\n{coin}: {label} ({key_preview}) FAIL {err_snippet}"
                await _tg_send(chat_id, msg, token)

        return js.Response.new("OK")
    except Exception as e:
        js.console.log(f"[on_fetch] unhandled: {e}")
        return js.Response.new("OK")


async def _alert_text(alert):
    event = alert.get("event_type", "")
    coin = alert.get("coin", "?")
    side = (alert.get("side") or "").upper()
    price = alert.get("price", 0)
    pnl = alert.get("pnl")

    if event == "position_opened":
        return f"*POSITION OPENED*\n{side} {coin} @ ${float(price):.5f}"
    elif event == "tp_hit":
        return f"*TAKE PROFIT HIT*\n{side} {coin} @ ${float(price):.5f}  PnL: ${float(pnl):.2f}"
    elif event == "sl_hit":
        return f"*STOP LOSS HIT*\n{side} {coin} @ ${float(price):.5f}  PnL: ${float(pnl):.2f}"
    return json.dumps(alert)


async def on_scheduled(controller, env, ctx):
    token = getattr(env, "TELEGRAM_BOT_TOKEN", "") or ""
    chat_id_str = getattr(env, "ALLOWED_TELEGRAM_ID", "") or ""
    if not token or not chat_id_str:
        return
    chat_id = int(chat_id_str)

    while True:
        try:
            alerts = await _fetch_api("/api/v1/bot/alerts", env)
            if not alerts or not isinstance(alerts, list):
                break
            for alert in alerts:
                text = await _alert_text(alert)
                await _tg_send(chat_id, text, token)
        except Exception:
            break
