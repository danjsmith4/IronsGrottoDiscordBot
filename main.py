import asyncio
import logging
import signal

import discord
from discord.ext import commands
import config
from cogs.community import Community
from cogs.moderation import Moderation
from cogs.leaderboards import Leaderboards

logger = logging.getLogger(__name__)


class GrottoBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents, case_insensitive=True)

    async def setup_hook(self):
        for cog_type in (Community, Moderation, Leaderboards):
            await self.add_cog(cog_type(self))
        guild_id = config.guild_id()
        guild = discord.Object(id=int(guild_id)) if guild_id else None
        if config.force_clear():
            self.tree.clear_commands(guild=guild)
            await self.tree.sync(guild=guild)
            if guild is not None:
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
            logger.warning('Slash commands cleared because FORCE_CLEAR=1')
        else:
            if guild is not None:
                self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info('Synced %s slash command groups', len(synced))

    async def on_ready(self):
        logger.info('Logged in as %s (id=%s)', self.user, self.user.id)

async def main():
    token = config.bot_token()
    async with GrottoBot() as bot:
        loop = asyncio.get_running_loop()
        previous_handler = signal.signal(
            signal.SIGTERM,
            lambda *_: loop.call_soon_threadsafe(lambda: asyncio.create_task(bot.close())),
        )
        try:
            await bot.start(token)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception('Bot stopped unexpectedly')
        raise SystemExit(1)
