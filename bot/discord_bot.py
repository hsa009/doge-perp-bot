import asyncio
import logging
import os

import discord
from discord import app_commands

logger = logging.getLogger(__name__)


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


def run_discord_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.warning("DISCORD_TOKEN not set — Discord bot disabled")
        return

    async def _entry():
        client = TradingBotClient()
        await client.start(token)

    asyncio.run(_entry())
