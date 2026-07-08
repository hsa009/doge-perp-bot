import asyncio
import logging
import os
import queue
import time
import traceback

import discord
from discord import app_commands
import httpx

from bot.redis_client import RedisClient

logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:7860"

alert_queue: queue.Queue[dict] = queue.Queue()


def send_trade_alert_to_queue(
    event_type: str,
    coin: str,
    side: str,
    price: float,
    pnl: float | None = None,
):
    alert_queue.put({
        "event_type": event_type,
        "coin": coin,
        "side": side,
        "price": price,
        "pnl": pnl,
        "timestamp": time.time(),
    })


class TradingBotClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        try:
            self._register_commands()
            guild_id = os.getenv("DISCORD_GUILD_ID")
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"Discord slash commands synced to guild {guild_id}")
            else:
                logger.warning("DISCORD_GUILD_ID not set — commands use global sync (1h delay)")
                await self.tree.sync()
        except Exception as e:
            logger.exception(f"Discord command sync failed: {e}")

    def _register_commands(self):
        @self.tree.command(name="dashboard", description="Show full bot dashboard overview")
        async def cmd_dashboard(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                r = RedisClient()
                embed = discord.Embed(title="🤖 Trading Bot Dashboard", color=discord.Color.blue())

                running = r.is_bot_running()
                heartbeat = r.get_config("ai_loop_heartbeat", "")
                embed.add_field(name="Status", value="🟢 Running" if running else "🔴 Stopped", inline=True)
                if heartbeat:
                    age = time.time() - float(heartbeat)
                    embed.add_field(name="Heartbeat", value=f"{age:.0f}s ago", inline=True)

                pos = r.get_position()
                if pos and abs(pos.get("size", 0)) > 1e-9:
                    side = pos.get("direction", "").upper()
                    embed.add_field(name="Position", value=f"{side} {pos['coin']} {abs(pos['size']):.0f} @ ${float(pos['entry_price']):.5f}", inline=False)
                    pnl = pos.get("unrealized_pnl", 0)
                    embed.add_field(name="Unrealized PnL", value=f"{'+' if pnl >= 0 else ''}${float(pnl):.2f}", inline=True)

                raw = r.client.get("multi_asset_signals")
                if raw:
                    signals = __import__("json").loads(raw)
                    non_wait = [c for c, s in signals.items() if s.get("direction") not in (None, "wait")]
                    embed.add_field(name="Non-Wait Signals", value=", ".join(non_wait) if non_wait else "None", inline=True)

                embed.set_footer(text=f"Next cycle in {r.get_config('remaining_seconds', '?')}s • Trading Bot")
                await interaction.followup.send(embed=embed)
            except Exception as e:
                logger.exception("dashboard command error")
                await interaction.followup.send(f"❌ Error: {e}")

        @self.tree.command(name="status", description="Show bot status and current position")
        async def cmd_status(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                r = RedisClient()
                embed = discord.Embed(title="📊 Bot Status", color=discord.Color.blue())

                running = r.is_bot_running()
                heartbeat = r.get_config("ai_loop_heartbeat", "")
                embed.add_field(name="Status", value="🟢 Running" if running else "🔴 Stopped", inline=True)
                if heartbeat:
                    age = time.time() - float(heartbeat)
                    embed.add_field(name="Heartbeat", value=f"{age:.0f}s ago" if age < 120 else "⚠️ Stale", inline=True)
                remaining = r.get_config("remaining_seconds", "?")
                embed.add_field(name="Next Signal", value=f"{remaining}s", inline=True)

                pos = r.get_position()
                if pos and abs(pos.get("size", 0)) > 1e-9:
                    side = pos.get("direction", "").upper()
                    color = discord.Color.green() if side == "LONG" else discord.Color.red()
                    embed.color = color
                    embed.add_field(name="Coin", value=pos.get("coin", "?"), inline=True)
                    embed.add_field(name="Side", value=side, inline=True)
                    embed.add_field(name="Size", value=f"{abs(float(pos.get('size', 0))):.0f}", inline=True)
                    embed.add_field(name="Entry", value=f"${float(pos.get('entry_price', 0)):.5f}", inline=True)
                    pnl = float(pos.get("unrealized_pnl", 0))
                    embed.add_field(name="Unrealized PnL", value=f"{'+' if pnl >= 0 else ''}${pnl:.2f}", inline=True)
                    tp = pos.get("tp_price")
                    sl = pos.get("sl_price")
                    if tp:
                        embed.add_field(name="TP", value=f"${float(tp):.5f}", inline=True)
                    if sl:
                        embed.add_field(name="SL", value=f"${float(sl):.5f}", inline=True)
                else:
                    embed.add_field(name="Position", value="None", inline=False)

                await interaction.followup.send(embed=embed)
            except Exception as e:
                logger.exception("status command error")
                await interaction.followup.send(f"❌ Error: {e}")

        @self.tree.command(name="signals", description="Show all coin signals from Gemini")
        async def cmd_signals(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                r = RedisClient()
                embed = discord.Embed(title="📈 Multi-Coin Signals", color=discord.Color.blue())

                raw = r.client.get("multi_asset_signals")
                signals = __import__("json").loads(raw) if raw else {}

                bw_raw = r.client.get("config:batch_winner")
                bw = __import__("json").loads(bw_raw) if bw_raw else None

                for coin in ["WIF", "POPCAT", "DOGE", "SUI", "JUP", "PYTH", "SOL"]:
                    s = signals.get(coin, {})
                    dir = s.get("direction", "wait").upper()
                    conf = s.get("confidence", 0)
                    reason = s.get("reasoning", "")[:80] or "—"
                    star = "⭐" if bw and bw.get("coin") == coin else ""
                    emoji = {"LONG": "🟢", "SHORT": "🔴", "WAIT": "⚪", None: "⚪"}.get(s.get("direction"), "⚪")
                    embed.add_field(
                        name=f"{emoji} {coin} {star}",
                        value=f"`{dir}` conf={conf:.2f}\n{reason}",
                        inline=False,
                    )

                embed.set_footer(text=f"Batch winner: {bw.get('coin', 'None')} • Trading Bot")
                await interaction.followup.send(embed=embed)
            except Exception as e:
                logger.exception("signals command error")
                await interaction.followup.send(f"❌ Error: {e}")

        @self.tree.command(name="signal", description="Show signal for a specific coin")
        @app_commands.describe(coin="Coin ticker (e.g. WIF, DOGE, SOL)")
        async def cmd_signal(interaction: discord.Interaction, coin: str):
            await interaction.response.defer()
            try:
                coin = coin.upper()
                r = RedisClient()
                embed = discord.Embed(title=f"🔍 {coin} Signal", color=discord.Color.blue())

                raw = r.client.get("multi_asset_signals")
                signals = __import__("json").loads(raw) if raw else {}
                s = signals.get(coin, {})

                dir = s.get("direction", "wait").upper()
                conf = s.get("confidence", 0)
                reason = s.get("reasoning", "") or "No signal yet"
                disabled = s.get("disabled", False)

                if disabled:
                    embed.add_field(name="Status", value="⛔ Disabled", inline=False)
                else:
                    embed.add_field(name="Direction", value=dir, inline=True)
                    embed.add_field(name="Confidence", value=f"{conf:.2f}", inline=True)
                    embed.add_field(name="Reasoning", value=reason[:500], inline=False)

                prompts_raw = r.client.get("multi_asset_prompts")
                if prompts_raw:
                    prompts = __import__("json").loads(prompts_raw)
                    prompt_text = prompts.get(coin, "")
                    if prompt_text:
                        embed.add_field(name="Prompt", value=f"```{prompt_text[:800]}```", inline=False)

                await interaction.followup.send(embed=embed)
            except Exception as e:
                logger.exception("signal command error")
                await interaction.followup.send(f"❌ Error: {e}")

        @self.tree.command(name="settings", description="Show current bot configuration")
        async def cmd_settings(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                r = RedisClient()
                cfg = r.get_all_config()
                embed = discord.Embed(title="⚙️ Bot Settings", color=discord.Color.blue())
                embed.add_field(name="TP", value=f"${cfg.get('tp_usd', '?')}", inline=True)
                embed.add_field(name="SL", value=f"${cfg.get('sl_usd', '?')}", inline=True)
                embed.add_field(name="Trade Amount", value=f"${cfg.get('trade_amount', '?')}", inline=True)
                embed.add_field(name="Leverage", value=f"{cfg.get('leverage', '?')}x", inline=True)
                embed.add_field(name="Min Confidence", value=cfg.get("min_confidence", "?"), inline=True)
                embed.add_field(name="Max Daily Loss", value=f"${cfg.get('max_daily_loss', '?')}", inline=True)
                enabled = r.get_enabled_coins()
                embed.add_field(name="Enabled Coins", value=", ".join(enabled) if enabled else "All", inline=False)
                await interaction.followup.send(embed=embed)
            except Exception as e:
                logger.exception("settings command error")
                await interaction.followup.send(f"❌ Error: {e}")

        @self.tree.command(name="close", description="Close current position")
        async def cmd_close(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                r = RedisClient()
                r.set_close_position_signal()
                logger.info("Discord: close position signal sent")
                embed = discord.Embed(title="✅ Close Signal Sent", description="Position will close in the next cycle.", color=discord.Color.green())
                await interaction.followup.send(embed=embed)
            except Exception as e:
                logger.exception("close command error")
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

        @self.tree.command(name="re-ask", description="Force Gemini re-evaluation now")
        async def cmd_re_ask(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(f"{BASE_URL}/api/v1/bot/re-ask")
                    data = resp.json()
                    if resp.status_code == 200 and data.get("ok"):
                        sig = data.get("signal", {})
                        dir = sig.get("direction", "wait").upper()
                        conf = sig.get("confidence", 0)
                        embed = discord.Embed(title="🔄 Re-Ask Complete", description=f"Result: {dir} ({conf:.2f})", color=discord.Color.blue())
                        await interaction.followup.send(embed=embed)
                    else:
                        await interaction.followup.send(f"❌ Re-ask failed: {data.get('error', 'unknown')}", ephemeral=True)
            except Exception as e:
                logger.exception("re-ask command error")
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

        @self.tree.command(name="force-trade", description="Force a trade on a coin")
        @app_commands.describe(coin="Coin ticker")
        async def cmd_force_trade(interaction: discord.Interaction, coin: str):
            await interaction.response.defer(ephemeral=True)
            try:
                coin = coin.upper()
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(f"{BASE_URL}/api/v1/bot/force-trade")
                    data = resp.json()
                    if resp.status_code == 200 and data.get("ok"):
                        sig = data.get("signal", {})
                        dir = sig.get("direction", "wait").upper()
                        conf = sig.get("confidence", 0)
                        opened = data.get("trade_opened", False)
                        if opened:
                            embed = discord.Embed(title="🚀 Trade Opened", description=f"{coin} {dir} ({conf:.2f})", color=discord.Color.green())
                        else:
                            embed = discord.Embed(title="⏸️ No Trade", description=f"Signal was {dir} ({conf:.2f}) — skipped", color=discord.Color.orange())
                        await interaction.followup.send(embed=embed)
                    else:
                        await interaction.followup.send(f"❌ Force trade failed: {data.get('error', 'unknown')}", ephemeral=True)
            except Exception as e:
                logger.exception("force-trade command error")
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

        logger.info("Discord slash commands registered")

    async def on_ready(self):
        logger.info(f"🟢 Discord Bot logged in as: {self.user}")
        asyncio.create_task(self._background_consumer())

    async def _background_consumer(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                payload = await asyncio.to_thread(alert_queue.get_nowait)
            except queue.Empty:
                await asyncio.sleep(1)
                continue

            channel_id = os.getenv("DISCORD_CHANNEL_ID")
            if not channel_id:
                continue
            channel = self.get_channel(int(channel_id))
            if not channel:
                logger.warning(f"Discord channel {channel_id} not found")
                continue

            embed = self._build_embed(payload)
            await channel.send(embed=embed)

    def _build_embed(self, payload: dict) -> discord.Embed:
        event_type = payload["event_type"]
        coin = payload["coin"]
        side = payload["side"].upper()
        price = payload["price"]
        pnl = payload.get("pnl")

        if event_type == "position_opened":
            embed = discord.Embed(
                title="🔵 Position Opened",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Asset", value=coin, inline=True)
            embed.add_field(name="Side", value=side, inline=True)
            embed.add_field(name="Entry Price", value=f"${price:.5f}", inline=True)

        elif event_type == "tp_hit":
            embed = discord.Embed(
                title="🟢 Take Profit Hit!",
                color=discord.Color.green(),
            )
            embed.add_field(name="Asset", value=coin, inline=True)
            embed.add_field(name="Exit Price", value=f"${price:.5f}", inline=True)
            pnl_str = f"+${pnl:.2f}" if pnl is not None else "—"
            embed.add_field(name="Realized PnL", value=pnl_str, inline=True)

        elif event_type == "sl_hit":
            embed = discord.Embed(
                title="🔴 Stop Loss Hit",
                color=discord.Color.red(),
            )
            embed.add_field(name="Asset", value=coin, inline=True)
            embed.add_field(name="Exit Price", value=f"${price:.5f}", inline=True)
            pnl_str = f"-${abs(pnl):.2f}" if pnl is not None else "—"
            embed.add_field(name="Realized PnL", value=pnl_str, inline=True)

        else:
            embed = discord.Embed(
                title="Trade Event",
                color=discord.Color.greyple(),
            )

        embed.set_footer(
            text=f"Trading Bot • {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
        )
        return embed


def run_discord_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.warning("DISCORD_TOKEN not set — Discord bot disabled")
        return

    async def _entry():
        client = TradingBotClient()
        await client.start(token)

    asyncio.run(_entry())
