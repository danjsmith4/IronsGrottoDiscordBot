import discord
from discord.ext import commands
from discord import app_commands
from discord import Embed

class Apply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="apply",
        description="Send an application request to a user with world instructions."
    )
    @app_commands.describe(
        user="The user you want to notify.",
        world="The world number they should hop to."
    )
    async def apply(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        world: str
    ):
        author = interaction.user

        # Main message
        await interaction.response.send_message(
            f"Hello {user.mention}, {author.mention} has applications open on **World {world}**.\n"
            f"Please hop to that world, **join as a guest**, and apply.\n\n"
            f"**Here are the instructions on how apply to Irons Grotto:**\n"
            f"1. Hop to **W{world}**\n"
            f"2. Open your **Clan Panel**\n"
            f"3. Join as **Guest**\n"
            f"4. Navigate to **Settings**\n"
            f"5. Apply\n"
        )

        # 5 Embeds showing images directly
        embed_links = [
            ("Step 1", "https://i.imgur.com/H3wRUcv.png"),
            ("Step 2", "https://i.imgur.com/c0wYRqq.png"),
            ("Step 3", "https://i.imgur.com/eafN6Vh.png"),
            ("Step 4", "https://i.imgur.com/hwRP8CG.png"),
            ("Step 5", "https://i.imgur.com/fLuNEFD.png")
        ]

        channel = interaction.channel

        for title, url in embed_links:
            embed = Embed(title=title, color=0x00ADEF)
            embed.set_image(url=url)  # <-- This makes the image show directly
            await channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Apply(bot))
