# invite.py

import discord
import re
from discord.ext import commands

class InviteFilter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.invite_regex = re.compile(r"https:\/\/(www\.)?discord\.(gg|io|me|li|com\/invite)\/[a-zA-Z0-9]+", re.IGNORECASE)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        if self.invite_regex.search(message.content):
            try:
                await message.delete()
                response = "We do not allow Discord invite links here. If you feel this was in error, please reach out to the admin team."
                await message.channel.send(f"{message.author.mention}, {response}")
            except discord.Forbidden:
                # Log or handle the exception as needed
                pass
            except discord.HTTPException as e:
                # Log or handle the exception as needed
                pass

def setup(bot):
    bot.add_cog(InviteFilter(bot))
