import asyncio
import logging
import os
import queue
import time

import discord
from discord import app_commands

logger = logging.getLogger(__name__)

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
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"Discord slash commands synced to guild {guild_id}")

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
