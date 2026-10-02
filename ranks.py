import discord
from discord.ext import commands

RANK_NOTIFIER_CHANNEL_ID = 1361038347266691122
MOD_ROLE_ID = 697877518493155387
STAFF_ROLE_ID = 829386451624001539
DEPUTY_ROLE_ID = 697877518513864784
RANK_NOTIFIER_BOT_ID = 1361038452686065855

class RankHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # Handle thread creation if message is from rank notifier bot
        if (
            message.channel.id == RANK_NOTIFIER_CHANNEL_ID and
            message.author.id == RANK_NOTIFIER_BOT_ID
        ):
            try:
                thread = await message.create_thread(name=f"Rank Request: {message.content[:50]}...")
                mod_role = message.guild.get_role(MOD_ROLE_ID)
                staff_role = message.guild.get_role(STAFF_ROLE_ID)
                deputy_role = message.guild.get_role(DEPUTY_ROLE_ID)
                await thread.send(
                    f"{mod_role.mention} {staff_role.mention} {deputy_role.mention} Please rank this user.")
            except discord.Forbidden:
                print("Bot does not have permissions to create threads.")
            except Exception as e:
                print(f"An error occurred: {e}")
            return  # Prevent further processing

        # Only process user commands (not other bots)
        if not message.author.bot:
            await self.bot.process_commands(message)

async def setup(bot):
    await bot.add_cog(RankHandler(bot))
