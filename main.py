import os
import asyncio
import logging
from dotenv import load_dotenv

import discord
from discord.ext import commands
from discord import app_commands


# ---- Logging ----
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---- Env ----
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

if not TOKEN:
    raise SystemExit("DISCORD_BOT_TOKEN not set in environment")

# ---- Intents ----
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.messages = True
intents.reactions = True

# ---- Bot ----
bot = commands.Bot(command_prefix=".", intents=intents, case_insensitive=True)

# ---- Import cog classes (no need to import the groups directly) ----
#from invite import InviteFilter
from bot_commands import BotCommands
from imgur import ImgurOnly
from leaderboardcommands import LeaderboardCommands
from memberjoin import send_welcome_message
from apply import Apply
async def add_cogs():
    """Adds all cogs to the bot."""
    #await bot.add_cog(InviteFilter(bot))
    await bot.add_cog(BotCommands(bot))
    await bot.add_cog(ImgurOnly(bot))
    await bot.add_cog(LeaderboardCommands(bot))
    await bot.add_cog(Apply(bot))

    
    logging.info(f"Prefix cmds: {[c.qualified_name for c in bot.walk_commands()]}")

@bot.event
async def on_ready():
    """
    This event is triggered when the bot is ready.
    It's the correct place to sync commands.
    """
    logging.info(f"Logged in as {bot.user} (id={bot.user.id})")
    
    try:
        if os.getenv("FORCE_CLEAR") == "1":
            logging.info("FORCE_CLEAR is set. Clearing all commands.")
            if GUILD_ID:
                guild_obj = discord.Object(id=int(GUILD_ID))
                bot.tree.clear_commands(guild=guild_obj)
                await bot.tree.sync(guild=guild_obj)
                logging.info(f"Cleared and synced commands for guild {GUILD_ID}.")
            
            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()
            logging.info("Cleared and synced all global commands.")
        else:
            if GUILD_ID:
                guild_obj = discord.Object(id=int(GUILD_ID))
                synced = await bot.tree.sync(guild=guild_obj)
                logging.info(f"Synced {len(synced)} slash cmds to guild {GUILD_ID}.")
            else:
                synced = await bot.tree.sync()
                logging.info(f"Synced {len(synced)} global slash cmds.")

        logging.info(f"Slash cmds after sync: {[c.qualified_name for c in bot.tree.walk_commands()]}")
    except Exception as e:
        logging.error(f"Slash command sync failed: {e}")

@bot.event
async def on_message(message: discord.Message):
    """Ensures prefix commands still fire if any cog overrides on_message."""
    await bot.process_commands(message)

@bot.event
async def on_member_join(member: discord.Member):
    """Sends a welcome message to a new member."""
    if member.bot:
        return
    try:
        await send_welcome_message(member, bot)
    except Exception as e:
        logging.exception(f"Welcome message failed: {e}")

async def main():
    """The main entry point for the bot."""
    async with bot:
        await add_cogs()
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except discord.errors.LoginFailure:
        logging.error("Invalid Discord token.")
    except Exception as e:
        logging.error(f"Bot failed to start: {e}")
