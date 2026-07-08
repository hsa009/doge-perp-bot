import hashlib
import json
import os
import time

from workers import Response, fetch

from ed25519 import verify

DISCORD_PUBLIC_KEY: str = ""
DISCORD_TOKEN: str = ""
DISCORD_WEBHOOK_URL: str = ""
APPLICATION_ID: str = ""
REDIS_URL: str = ""
REDIS_REST: str = ""
REDIS_TOKEN: str = ""


def _init(env):
    global DISCORD_PUBLIC_KEY, DISCORD_TOKEN, DISCORD_WEBHOOK_URL, APPLICATION_ID, REDIS_URL, REDIS_REST, REDIS_TOKEN
    DISCORD_PUBLIC_KEY = env.get("DISCORD_PUBLIC_KEY", "")
    DISCORD_TOKEN = env.get("DISCORD_TOKEN", "")
    DISCORD_WEBHOOK_URL = env.get("DISCORD_WEBHOOK_URL", "")
    APPLICATION_ID = env.get("DISCORD_APPLICATION_ID", "")
    REDIS_URL = env.get("REDIS_URL", "")
    rest = REDIS_URL.replace("redis://", "https://")
    if rest.endswith(":6379"):
        rest = rest[:-5]
    user, rest = (rest.split("@", 1) if "@" in rest else ("", rest))
    REDIS_REST = rest
    REDIS_TOKEN = (user.split(":", 1)[1] if ":" in user else "")


async def _redis(*args):
    body = json.dumps(args).encode()
    resp = await fetch(
        REDIS_REST,
        method="POST",
        body=body,
        headers={
            "Authorization": f"Bearer {REDIS_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    text = await resp.text()
    return json.loads(text) if text else None


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
    embed = {"color": 0x3498DB, "title": "🤖 Trading Bot Dashboard", "fields": []}

    running = await _redis("GET", "bot:running")
    status = "🟢 Running" if running == "1" else "🔴 Stopped"
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
    body = json.dumps({"embeds": [embed]}).encode()
    try:
        await fetch(
            DISCORD_WEBHOOK_URL,
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
    except Exception:
        pass


async def on_fetch(request, env):
    _init(env)
    method = str(getattr(request, "method", "GET")).upper()
    url = str(getattr(request, "url", "/"))

    if method == "POST" and ("/interaction" in url or url.endswith("/interaction")):
        raw = await request.bytes() if hasattr(request, "bytes") else (await request.body)
        sig = (request.headers.get("X-Signature-Ed25519") or "").strip()
        ts = (request.headers.get("X-Signature-Timestamp") or "").strip()

        if not _verify_request(raw, sig, ts):
            return Response("Invalid signature", status=401)

        payload = json.loads(raw) if isinstance(raw, bytes) else raw
        if payload.get("type") == 1:
            return Response(json.dumps({"type": 1}), headers={"Content-Type": "application/json"})

        if payload.get("type") == 2:
            name = payload.get("data", {}).get("name", "")

            if name == "dashboard":
                try:
                    embed = await _embed_dashboard()
                    return Response(
                        json.dumps({"type": 4, "data": {"embeds": [embed]}}),
                        headers={"Content-Type": "application/json"},
                    )
                except Exception as e:
                    return Response(
                        json.dumps({"type": 4, "data": {"content": f"\u274c Error: {e}", "flags": 64}}),
                        headers={"Content-Type": "application/json"},
                    )

            return Response(
                json.dumps({"type": 4, "data": {"content": f"Unknown command: {name}", "flags": 64}}),
                headers={"Content-Type": "application/json"},
            )

        return Response("Bad request", status=400)

    return Response("OK", status=200)


async def on_cron(event, env):
    _init(env)
    while True:
        try:
            raw = await _redis("LPOP", "queue:discord_alerts")
        except Exception:
            break
        if not raw:
            break
        if isinstance(raw, str):
            alert = json.loads(raw)
        else:
            alert = raw
        embed = _build_alert_embed(alert)
        await _send_webhook(embed)
