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


async def _fetch_status(env):
    base = getattr(env, "HF_SPACE_URL", "") or ""
    if not base:
        return None
    resp = await js.fetch(
        f"{base}/api/v1/bot/status",
        js.JSON.parse(json.dumps({"method": "GET"})),
    )
    if resp.status != 200:
        return None
    return await resp.json()


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
        status = await _fetch_status(env)

        lines = ["*Trading Dashboard*", ""]
        running = (status or {}).get("running", False)
        lines.append(f"Status: {'Running' if running else 'Stopped'}")

        lines.append("")
        pos = (status or {}).get("position")
        if pos:
            direction = (pos.get("direction") or "").upper()
            size = pos.get("size", 0)
            coin = pos.get("coin", "")
            entry = float(pos.get("entry_price", 0))
            pnl = float(pos.get("unrealized_pnl", 0))
            lines.append(f"{direction}  {size} {coin}  ${entry:.5f}  ${pnl:.2f}")
        else:
            lines.append("No open position")

        await _tg_send(chat_id, "\n".join(lines), token)

    return js.Response.new("OK")


async def _redis_headers(env):
    token = getattr(env, "REDIS_TOKEN", "") or ""
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


async def _redis_lpop(key, env):
    redis_url = getattr(env, "REDIS_URL", "") or ""
    if not redis_url:
        return None
    headers = await _redis_headers(env)
    headers["Content-Type"] = "application/json"
    resp = await js.fetch(
        f"{redis_url}/lpop/{key}",
        js.JSON.parse(json.dumps({"method": "POST", "headers": headers})),
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
