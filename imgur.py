import discord
from discord.ext import commands
import re
from urllib.parse import urlsplit

URL_PATTERN = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')


def allowed_url(url):
    try:
        host = urlsplit(url if '://' in url else 'https://' + url).hostname or ''
        return any(host == domain or host.endswith('.' + domain) for domain in ('imgur.com', 'gyazo.com'))
    except ValueError:
        return False

async def setup(bot):
    await bot.add_cog(ImgurOnly(bot))

class ImgurOnly(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_channel_id = 1357560551219396628  # Replace with your target channel ID

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if message.channel.id != self.target_channel_id:
            return

        urls = []

        if message.attachments:
            for attachment in message.attachments:
                if not attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4')):
                    await message.reply("All image and video links must be Imgur or Gyazo links.")
                    await message.delete()
                    return
                urls.append(attachment.url)

        else:
            urls = URL_PATTERN.findall(message.content)

            for url in urls:
                if not allowed_url(url):
                    await message.reply("All image and video links must be Imgur or Gyazo links.")
                    await message.delete()
                    return

        # Add reactions if at least one valid link exists
        if urls:
            await message.add_reaction("✅")
            await message.add_reaction("❌")

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if reaction.message.channel.id != self.target_channel_id:
            return

        if user.bot:
            return

        if not any(role.name in ["Owner", "Deputy Owner"] for role in user.roles):
            return

        if reaction.emoji == "✅":
            await reaction.message.delete()
            try:
                await reaction.message.author.send("Your submission was accepted.")
            except discord.Forbidden:
                await reaction.message.channel.send(
                    f"{reaction.message.author.mention}, I tried to DM you that your submission was accepted, but your DMs are closed.",
                    delete_after=10
                )

        elif reaction.emoji == "❌":
            await reaction.message.delete()
            try:
                await reaction.message.author.send("Your submission was denied.")
            except discord.Forbidden:
                await reaction.message.channel.send(
                    f"{reaction.message.author.mention}, I tried to DM you that your submission was denied, but your DMs are closed.",
                    delete_after=10
                )
