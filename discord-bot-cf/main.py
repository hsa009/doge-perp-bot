import json
import time

import js

from ed25519 import verify

DISCORD_PUBLIC_KEY: str = ""
DISCORD_TOKEN: str = ""
DISCORD_WEBHOOK_URL: str = ""
APPLICATION_ID: str = ""
REDIS_REST: str = ""
REDIS_TOKEN: str = ""


def _init(env):
    global DISCORD_PUBLIC_KEY, DISCORD_TOKEN, DISCORD_WEBHOOK_URL, APPLICATION_ID, REDIS_REST, REDIS_TOKEN
    DISCORD_PUBLIC_KEY = env.get("DISCORD_PUBLIC_KEY", "")
    DISCORD_TOKEN = env.get("DISCORD_TOKEN", "")
    DISCORD_WEBHOOK_URL = env.get("DISCORD_WEBHOOK_URL", "")
    APPLICATION_ID = env.get("DISCORD_APPLICATION_ID", "")
    url = env.get("REDIS_URL", "")
    rest = url.replace("redis://", "https://")
    if rest.endswith(":6379"):
        rest = rest[:-5]
    if "@" in rest:
        user, host = rest.split("@", 1)
        REDIS_REST = f"https://{host}"
        REDIS_TOKEN = user.split(":", 1)[1] if ":" in user else ""
    else:
        REDIS_REST = rest
        REDIS_TOKEN = ""


async def _redis(*args):
    body = json.dumps([*args])
    opts = js.JSON.parse(
        json.dumps({
            "method": "POST",
            "body": body,
            "headers": {
                "Authorization": f"Bearer {REDIS_TOKEN}",
                "Content-Type": "application/json",
            },
        })
    )
    resp = await js.fetch(REDIS_REST, opts)
    text = await resp.text()
    if not text:
        return None
    return json.loads(text).get("result")


def _verify_request(body: bytes, signature: str, timestamp: str) -> bool:
    if not signature or not timestamp or not DISCORD_PUBLIC_KEY:
        return False
    try:
        sig = bytes.fromhex(signature)
        pub = bytes.fromhex(DISCORD_PUBLIC_KEY)
        return verify(pub, timestamp.encode() + body, sig)
    except Exception:
        return False


async def _embed_dashboard() -> dict:
    embed: dict = {"color": 0x3498DB, "title": "\U0001f916 Trading Bot Dashboard", "fields": []}

    running = await _redis("GET", "bot:running")
    status = "\U0001f7e2 Running" if running == "1" else "\U0001f534 Stopped"
    embed["fields"].append({"name": "Status", "value": status, "inline": True})

    hb = await _redis("GET", "config:ai_loop_heartbeat")
    if hb and isinstance(hb, str):
        age = time.time() - float(hb)
        embed["fields"].append({"name": "Heartbeat", "value": f"{age:.0f}s ago", "inline": True})

    pos_raw = await _redis("GET", "position:current")
    if pos_raw and isinstance(pos_raw, str):
        pos = json.loads(pos_raw)
        if abs(pos.get("size", 0)) > 1e-9:
            side = pos.get("direction", "?").upper()
            pnl = float(pos.get("unrealized_pnl", 0))
            embed["fields"].append({
                "name": "Position",
                "value": f"{side} {pos['coin']} {abs(pos['size']):.0f} @ ${float(pos['entry_price']):.5f}",
                "inline": False,
            })
            embed["fields"].append({
                "name": "Unrealized PnL",
                "value": f"{'+' if pnl >= 0 else ''}${pnl:.2f}",
                "inline": True,
            })

    sigs_raw = await _redis("GET", "multi_asset_signals")
    if sigs_raw and isinstance(sigs_raw, str):
        sigs = json.loads(sigs_raw)
        non_wait = [c for c, s in sigs.items() if s.get("direction") not in (None, "wait")]
        embed["fields"].append({
            "name": "Non-Wait Signals",
            "value": ", ".join(non_wait) if non_wait else "None",
            "inline": True,
        })

    remaining = (await _redis("GET", "config:remaining_seconds")) or "?"
    embed["footer"] = {"text": f"Next cycle in {remaining}s \u2022 Trading Bot"}
    return embed


def _build_alert_embed(alert: dict) -> dict:
    event_type = alert.get("event_type", "")
    coin = alert.get("coin", "?")
    side = alert.get("side", "?").upper()
    price = alert.get("price", 0)
    pnl = alert.get("pnl")

    if event_type == "position_opened":
        return {
            "color": 0x3498DB,
            "title": "\U0001f535 Position Opened",
            "fields": [
                {"name": "Asset", "value": coin, "inline": True},
                {"name": "Side", "value": side, "inline": True},
                {"name": "Entry Price", "value": f"${price:.5f}", "inline": True},
            ],
        }
    elif event_type == "tp_hit":
        return {
            "color": 0x2ECC71,
            "title": "\U0001f7e2 Take Profit Hit",
            "fields": [
                {"name": "Asset", "value": coin, "inline": True},
                {"name": "Exit Price", "value": f"${price:.5f}", "inline": True},
                {"name": "Realized PnL", "value": f"+${pnl:.2f}" if pnl is not None else "\u2014", "inline": True},
            ],
        }
    elif event_type == "sl_hit":
        return {
            "color": 0xE74C3C,
            "title": "\U0001f534 Stop Loss Hit",
            "fields": [
                {"name": "Asset", "value": coin, "inline": True},
                {"name": "Exit Price", "value": f"${price:.5f}", "inline": True},
                {"name": "Realized PnL", "value": f"-${abs(pnl):.2f}" if pnl is not None else "\u2014", "inline": True},
            ],
        }
    return {
        "color": 0x95A5A6,
        "title": "Trade Event",
        "fields": [{"name": "Asset", "value": coin, "inline": False}],
    }


async def _send_webhook(embed: dict):
    if not DISCORD_WEBHOOK_URL:
        return
    body = json.dumps({"embeds": [embed]})
    try:
        await js.fetch(
            DISCORD_WEBHOOK_URL,
            js.JSON.parse(
                json.dumps({
                    "method": "POST",
                    "body": body,
                    "headers": {"Content-Type": "application/json"},
                })
            ),
        )
    except Exception:
        pass


def _json_response(data: dict, status: int = 200):
    return js.Response.new(
        json.dumps(data),
        js.JSON.parse(
            json.dumps({
                "status": status,
                "headers": {"Content-Type": "application/json"},
            })
        ),
    )


async def on_fetch(request, env):
    _init(env)
    url = str(request.url)
    method = str(request.method).upper()

    if method == "POST" and "/interaction" in url:
        text = await request.text()
        raw = text.encode("utf-8")
        sig = str(request.headers.get("X-Signature-Ed25519") or "").strip()
        ts = str(request.headers.get("X-Signature-Timestamp") or "").strip()

        if not _verify_request(raw, sig, ts):
            return js.Response.new(
                "Invalid signature",
                js.JSON.parse(json.dumps({"status": 401})),
            )

        payload = json.loads(text)
        if payload.get("type") == 1:
            return _json_response({"type": 1})

        if payload.get("type") == 2:
            name = payload.get("data", {}).get("name", "")

            if name == "dashboard":
                try:
                    embed = await _embed_dashboard()
                    return _json_response({"type": 4, "data": {"embeds": [embed]}})
                except Exception as e:
                    return _json_response(
                        {"type": 4, "data": {"content": f"\u274c Error: {e}", "flags": 64}},
                    )

            return _json_response(
                {"type": 4, "data": {"content": f"Unknown command: {name}", "flags": 64}},
            )

        return js.Response.new(
            "Bad request",
            js.JSON.parse(json.dumps({"status": 400})),
        )

    return js.Response.new("OK", js.JSON.parse(json.dumps({"status": 200})))


async def on_scheduled(controller, env, ctx):
    _init(env)
    while True:
        try:
            raw = await _redis("LPOP", "queue:discord_alerts")
        except Exception:
            break
        if not raw:
            break
        alert = json.loads(raw) if isinstance(raw, str) else raw
        embed = _build_alert_embed(alert)
        await _send_webhook(embed)
