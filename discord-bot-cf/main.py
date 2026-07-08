import json
import js


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


async def _redis_get(key, env):
    redis_url = getattr(env, "REDIS_URL", "") or ""
    if not redis_url:
        return None
    resp = await js.fetch(
        f"{redis_url}/get/{key}",
        js.JSON.parse(json.dumps({"method": "GET"})),
    )
    if resp.status != 200:
        return None
    return json.loads(await resp.text())


async def on_fetch(request, env):
    if str(request.method).upper() != "POST":
        return js.Response.new("OK")

    token = getattr(env, "TELEGRAM_BOT_TOKEN", "") or ""
    allowed = getattr(env, "ALLOWED_TELEGRAM_ID", "") or ""
    if not token or not allowed:
        return js.Response.new("OK")

    raw = await request.text()
    if not raw:
        return js.Response.new("OK")

    update = json.loads(raw)
    msg = update.get("message", {})
    user_id = str(msg.get("from", {}).get("id", ""))
    chat_id = msg.get("chat", {}).get("id")

    if user_id != allowed or not chat_id:
        return js.Response.new("OK")

    text = msg.get("text", "")

    if text == "/dashboard":
        bot_key = await _redis_get("bot:running", env)
        pos = await _redis_get("position:current", env)
        bal = await _redis_get("balance:account", env)

        lines = ["*Trading Dashboard*", ""]

        running = (bot_key or {}).get("result")
        lines.append(f"Status: {'Running' if running else 'Stopped'}")

        lines.append("")
        pos_data = (pos or {}).get("result")
        if pos_data:
            p = json.loads(pos_data)
            lines.append("*Position:*")
            lines.append(f"Coin: {p.get('coin', 'N/A')}")
            lines.append(f"Side: {p.get('side', 'N/A')}")
            lines.append(f"Size: {p.get('sz', 'N/A')}")
            lines.append(f"Entry: {p.get('entry_px', 'N/A')}")
            lines.append(f"PnL: {p.get('pnl', 'N/A')}")
        else:
            lines.append("*Position:* No open position")

        lines.append("")
        bal_data = (bal or {}).get("result")
        if bal_data:
            b = json.loads(bal_data)
            lines.append(f"*Balance:* {b.get('total', 'N/A')}")
        else:
            lines.append("*Balance:* N/A")

        await _tg_send(chat_id, "\n".join(lines), token)

    return js.Response.new("OK")


async def _redis_lpop(key, env):
    redis_url = getattr(env, "REDIS_URL", "") or ""
    if not redis_url:
        return None
    resp = await js.fetch(
        f"{redis_url}/lpop/{key}",
        js.JSON.parse(json.dumps({"method": "POST"})),
    )
    if resp.status != 200:
        return None
    return json.loads(await resp.text())


async def on_scheduled(controller, env, ctx):
    token = getattr(env, "TELEGRAM_BOT_TOKEN", "") or ""
    chat_id_str = getattr(env, "ALLOWED_TELEGRAM_ID", "") or ""
    if not token or not chat_id_str:
        return
    chat_id = int(chat_id_str)

    while True:
        try:
            data = await _redis_lpop("queue:discord_alerts", env)
            if not data or not data.get("result"):
                break
            alert = json.loads(data["result"])
            msg = alert.get("message", json.dumps(alert))
            await _tg_send(chat_id, f"Alert: {msg}", token)
        except Exception:
            break
