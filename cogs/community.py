"""Welcome messages, applications, and community information commands."""
import logging
import random

import discord
from discord import app_commands, Embed
from discord.ext import commands

from config import (channel_id, INVITE_LINK, TEMPLE_LINK, RANK_CALCULATOR_LINK,
                    STAFF_ROLE_ID, STAFF_ROLES, RANK_APPLICATION_CHANNEL_ID,
                    DIARY_CHANNEL_ID, BINGO_DROPS_CHANNEL_ID)

logger = logging.getLogger(__name__)

async def send_welcome_message(member, bot):
    welcome_id = channel_id('WELCOME_CHANNEL_ID')
    channel = bot.get_channel(welcome_id)
    if channel is None:
        channel = await bot.fetch_channel(welcome_id)
    if channel.guild.id != member.guild.id:
        logger.warning('Welcome channel %s belongs to a different guild; skipped member %s', welcome_id, member.id)
        return
    embed = discord.Embed(
        title=f'Welcome to Irons Grotto, {member.name}!',
        description=(
            'Please have a look around at all the things we offer, but your first stop should be to our '
            f"<#{channel_id('HOW_TO_APPLY_CHANNEL_ID')}> channel, where you can apply for a rank.\n\n"
            f"Next, be sure to check out the <#{channel_id('WELCOME2_CHANNEL_ID')}> channel for more information.\n\n"
            f"Lastly, if you get any cool drops or items, post them in the <#{channel_id('DROPS_CHANNEL_ID')}> "
            "channel - we'd love to see them!"
        ),
        color=discord.Color.green(),
    )
    embed.set_footer(text=f'Welcome {member.name} to Grotto <3!')
    await channel.send(content=member.mention, embed=embed)
    logger.info('Welcomed member %s in channel %s', member.id, welcome_id)


class Community(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.invite_link = INVITE_LINK
        self.temple_link = TEMPLE_LINK
        self.rank_calculator_app_link = RANK_CALCULATOR_LINK
        self.staff_role_id = STAFF_ROLE_ID
        self.image_url_1 = 'https://i.imgur.com/pgg0TUv.png'
        self.image_url_2 = 'https://i.imgur.com/GEJw9cA.png'
        self.image_url_3 = 'https://i.imgur.com/HAPQdyX.png'

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not member.bot:
            try:
                await send_welcome_message(member, self.bot)
            except Exception:
                logger.exception('Welcome failed for member %s in guild %s', member.id, member.guild.id)

    @commands.command(name='invite')
    async def invite(self, ctx):
        await ctx.send(f"Here is the invite link to the server: {self.invite_link}")

    @commands.command(name='temple')
    async def temple(self, ctx):
        await ctx.send(f"Here is the link to the TempleOSRS page: {self.temple_link}")

    @commands.command(name='submit')
    async def submit(self, ctx):
        embed = discord.Embed(
            title="Submitting a Personal Best",
            description="Guidelines and checklist for submission.",
            color=0x00ff00
        )
        embed.set_image(url="https://i.imgur.com/Pq2iRnN.jpeg")
        await ctx.send(embed=embed)

    @commands.command(name='apply')
    @commands.has_permissions(administrator=True)
    async def apply(self, ctx):
        embed = discord.Embed(
            title="How to Apply / Request a Rank",
            description=(
                f"1. Open {self.rank_calculator_app_link} and log in with Discord.\n\n"
                "2. Add your player and complete the rank calculator.\n\n"
                "3. Save your progress and select Apply for promotion. "
                "A member of the leadership team will review your application.\n\n"
                "If you have any questions, comments, or concerns, please don't hesitate to ask 😄"
            ),
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    @apply.error
    async def apply_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You do not have permission to use this command.")

    @commands.command(name='roll_user')
    async def roll_user(self, ctx):
        if ctx.guild is None:
            await ctx.send("Run this command in a server.")
            return

        staff_role = ctx.guild.get_role(self.staff_role_id)
        if staff_role is None:
            await ctx.send("Couldn't find the Staff role in this server.")
            return

        staff_members = [member for member in staff_role.members if not member.bot]
        if not staff_members:
            await ctx.send("No Staff role members found to choose from.")
            return

        chosen_user = random.choice(staff_members)
        await ctx.send(f"{chosen_user.mention}, you've been chosen to do this week's event.")

    @commands.command(name='rankcalc')
    async def rankcalc(self, ctx):
        main_embed = discord.Embed(
            title="How to Use the Irons Grotto Rank Calculator ",
            description=(
                f"Head on over to {self.rank_calculator_app_link} and log in with Discord (we cannot see your login credentials).\n\n"
                "**1. Add Your Player:**\n"
                "   After logging in, click \"Add new player\", and enter your player name, join date, and whether you're a mobile player or not.\n"
                "**2. Access the Calculator:**\n"
                "   After you have added your player, click it in the list to go to the rank calculator.\n\n"
                "**3. Fill Out the Form (Automatic or Manual):**\n"
                "   With TempleOSRS + WikiSync, the form auto-fills; otherwise fill manually.\n\n"
                "**4. Save & Apply for Promotion:**\n"
                "   Click \"Save\" then \"Apply for promotion\".\n\n"
                f"Rank applications are posted to <#{RANK_APPLICATION_CHANNEL_ID}> for review. 😄\n\n"
                "---"
            ),
            color=discord.Color.dark_purple()
        )

        name_change_embed = discord.Embed(
            title="❓ I changed my name, what do I do?",
            description=(
                f"Update it at {self.rank_calculator_app_link} (pencil icon).\n"
                "If validation glitches, message Avios or try a temporary name change."
            ),
            color=discord.Color.gold()
        )

        plugins_embed = discord.Embed(
            title="🛠️ Helpful RuneLite Plugins",
            description=(
                "Install **WikiSync** and **TempleOSRS** to let the site see your log, CAs, diaries, and quests.\n"
                "First time? **Upload your log** and **enable auto sync**."
            ),
            color=discord.Color.blue()
        )

        embed_img1 = discord.Embed(title="1️⃣ Upload your collection log to TempleOSRS", color=discord.Color.green())
        embed_img1.set_image(url=self.image_url_1)
        embed_img2 = discord.Embed(title="2️⃣ Enable TempleOSRS plugin auto-sync", color=discord.Color.green())
        embed_img2.set_image(url=self.image_url_2)
        embed_img3 = discord.Embed(title="3️⃣ Enable in-game setting for TempleOSRS sync", color=discord.Color.green())
        embed_img3.set_image(url=self.image_url_3)

        await ctx.send(embed=main_embed)
        await ctx.send(embed=name_change_embed)
        await ctx.send(embed=plugins_embed)
        await ctx.send(embed=embed_img1)
        await ctx.send(embed=embed_img2)
        await ctx.send(embed=embed_img3)

    @commands.command(name='diary')
    @commands.has_any_role(*STAFF_ROLES)
    async def diary(self, ctx):
        embed = discord.Embed(
            title="📓 The Grotto Diary",
            description=(
                "**What is the Grotto Diaries?**\n"
                "Boss speed-running + Collection Log challenges from Easy to Grandmaster, with rewards.\n\n"
                "**Rewards**\n"
                "Speedrun tiers award up to 4 points; Collection Log tiers awarded via the rank calculator.\n\n"
                "**Speedrun Diary Tiers:**\n"
                "• Easy: 12 pts → 500 Points\n"
                "• Medium: 24 pts → 1000 Points\n"
                "• Hard: 36 pts → 2000 Points + In-game Rank\n"
                "• Elite: 48 pts → 4000 Points + In-game Rank\n\n"
                "**Collection Log Diary Tiers:**\n"
                "• Easy: 500 Points\n"
                "• Medium: 750 Points\n"
                "• Hard: 1000 Points\n"
                "• Elite: 2000 Points + In-game Rank\n"
                "• Grandmaster: 4000 Points + In-game Rank\n\n"
                "**How in game Ranks Work** \n"
                "• Hard Speedrun OR Log Elite → In-game rank\n"
                "• Elite Speedrun OR Log Grandmaster → In-game rank\n"
                "• Both Elite Speedrun AND Log Grandmaster → elusive in-game rank\n\n"
                "**How to Participate**\n"
                f"Head to <#{DIARY_CHANNEL_ID}> for time submission instructions."
            ),
            color=discord.Color.dark_teal()
        )
        await ctx.send(embed=embed)

    @diary.error
    async def diary_error(self, ctx, error):
        if isinstance(error, commands.MissingAnyRole):
            await ctx.send("You do not have permission to use this command.")

    @commands.command(name='gim')
    async def gim(self, ctx):
        embed = discord.Embed(
            title="📢 Important Info for Group Ironmen",
            description=(
                "If your team provided **Rigour**, **Augury**, **DWH**, **BGS**, or **Elder Maul**, "
                "you must update your rank calculator and resubmit."
            ),
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)

    @commands.command(name='collectionlog')
    async def collectionlog(self, ctx):
        embed = discord.Embed(
            title="📘 Grotto Collection Log Diary",
            description="Show off your clog progress and achievements!",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="<:steellog:1399743910699466864> Easy",
            value=(
                "• 150 Clue Collection logs\n"
                "• 2 green logs under **Bosses**\n"
                "• 3 green logs under **Minigames**\n"
                "• 4 green logs under **Other**\n"
                "• **Steel Staff of Collection** (500+)"
            ),
            inline=False
        )
        embed.add_field(
            name="<:blacklog:1399743909315215430> Medium",
            value=(
                "• 250 Clue Collection logs\n"
                "• Green log **Shared Clue Rewards**\n"
                "• 5 green logs under **Bosses**\n"
                "• 5 green logs under **Minigames**\n"
                "• 8 green logs under **Other**\n"
                "• **Black Staff of Collection** (700+)"
            ),
            inline=False
        )
        embed.add_field(
            name="<:addylog:1399743908040282183> Hard",
            value=(
                "• 375 Clue Collection logs\n"
                "• Green log **Beginner Clues**\n"
                "• **Expert Dragon Archer Chompy Hat**\n"
                "• 8 green logs under **Minigames**\n"
                "• 12 green logs under **Other**\n"
                "• **Adamant Staff of Collection** (1k+)"
            ),
            inline=False
        )
        embed.add_field(
            name="<:DragonLog:1399743906836386034> Elite",
            value=(
                "• 475 Clue Collection logs\n"
                "• Green log any **Raid** minus KC capes\n"
                "• **Champion's Cape**\n"
                "• 12 green logs under **Minigames**\n"
                "• 16 green logs under **Other**\n"
                "• **Dragon Staff of Collection** (1.2k+)"
            ),
            inline=False
        )
        embed.add_field(
            name="<:gildedlog:1399743905133629601> Grandmaster",
            value=(
                "• 525 Clue Collection logs\n"
                "• Any 5 unique **Gilded items**\n"
                "• Any piece of **3rd Age**\n"
                "• Green log any **Raid** including KC capes\n"
                "• **Gilded Staff of Collection** (1.4k+)"
            ),
            inline=False
        )
        embed.set_footer(text="The Collection Log never sleeps 🧾")
        await ctx.send(embed=embed)

    @commands.command(name='speedruns')
    async def speedruns(self, ctx):
        embed = discord.Embed(
            title="⏱️ Grotto Speedrun Diary",
            description="Complete Speed Run Challenges for Certain bosses and content",
            color=discord.Color.red()
        )
        embed.add_field(name="<:olm:1011385799167721562> Chambers of Xeric (Solo)",
                        value="• Easy: sub 18:00\n• Medium: sub 16:00\n• Hard: sub 14:30\n• Elite: sub 13:00",
                        inline=False)
        embed.add_field(name="<:olm:1011385799167721562> Chambers of Xeric (3-Man)",
                        value="• Easy: sub 15:00\n• Medium: sub 13:30\n• Hard: sub 11:45\n• Elite: sub 10:30",
                        inline=False)
        embed.add_field(name="<:olm:1011385799167721562> Chambers of Xeric (5-Man)",
                        value="• Easy: sub 14:30\n• Medium: sub 13:00\n• Hard: sub 11:15\n• Elite: sub 10:00",
                        inline=False)
        embed.add_field(name="<:cm:1011384808003338250> CoX Challenge Mode (Solo)",
                        value="• Easy: sub 38:30\n• Medium: sub 35:00\n• Hard: sub 31:30\n• Elite: sub 28:00",
                        inline=False)
        embed.add_field(name="<:cm:1011384808003338250> CoX Challenge Mode (3-Man)",
                        value="• Easy: sub 27:00\n• Medium: sub 24:30\n• Hard: sub 22:00\n• Elite: sub 20:00",
                        inline=False)
        embed.add_field(name="<:cm:1011384808003338250> CoX Challenge Mode (5-Man)",
                        value="• Easy: sub 25:00\n• Medium: sub 23:00\n• Hard: sub 21:00\n• Elite: sub 19:30",
                        inline=False)
        embed.add_field(name="<:jad:1399742220621451264> Fight Caves",
                        value="• Easy: sub 30:00\n• Medium: sub 27:00\n• Hard: sub 24:00\n• Elite: sub 21:00",
                        inline=False)
        embed.add_field(name="<:infernal:1399742560544493639> Inferno",
                        value="• Easy: sub 70:00\n• Medium: sub 64:00\n• Hard: sub 58:00\n• Elite: sub 52:00",
                        inline=False)
        embed.add_field(name="<:sol:1399742240057851996> Colosseum",
                        value="• Easy: sub 26:00\n• Medium: sub 23:00\n• Hard: sub 21:00\n• Elite: sub 19:00",
                        inline=False)
        embed.add_field(name="<:crystalhunleff:1399742689129398282> Gauntlet",
                        value="• Easy: sub 04:30\n• Medium: sub 04:00\n• Hard: sub 03:45\n• Elite: sub 03:30",
                        inline=False)
        embed.add_field(name="<:hunleff:1399742473076736010> Corrupted Gauntlet",
                        value="• Easy: sub 07:00\n• Medium: sub 06:30\n• Hard: sub 06:00\n• Elite: sub 05:30",
                        inline=False)
        embed.add_field(name="<:token:1399742378750771304> Hallowed Sepulchre",
                        value="• Easy: sub 07:30\n• Medium: sub 07:00\n• Hard: sub 06:30\n• Elite: sub 06:00",
                        inline=False)
        embed.set_footer(text="Times must be recorded and verified to count toward your Grotto Diary.")
        await ctx.send(embed=embed)

    @commands.command(name="bingorules", help="View Grotto Summer Bingo 2025 rules")
    async def bingorules(self, ctx):
        embed = discord.Embed(
            title="🎉 Grotto Summer Bingo 2025 Rules",
            color=discord.Color.blue(),
            description="Here's a quick overview of the rules and details for the upcoming bingo event!"
        )
        embed.add_field(
            name="📅 Dates",
            value=(
                "Start: <t:1754654400:F> (<t:1754654400:R>)\n"
                "End: <t:1755475200:F> (<t:1755475200:R>)"
            ),
            inline=False
        )
        embed.add_field(
            name="📦 Stacking Rules",
            value="You **can** stack **clue scrolls** and **boxes**.\nYou **cannot** stack other content (e.g. **minigame points**, etc).",
            inline=False
        )
        embed.add_field(
            name="📸 Drop Posting",
            value=f"All drops must be posted in <#{BINGO_DROPS_CHANNEL_ID}> to count.",
            inline=False
        )
        embed.add_field(
            name="<:ironman:712770183256866947> Ironman Rules",
            value="Two mains are participating but will play like irons.\nThey are **long-standing, trusted members**.",
            inline=False
        )
        embed.add_field(
            name="🧩 Tile Completion",
            value="Each bingo tile has **3 tasks**, Bronze, Silver and Gold.\nYou may attempt tasks in any order, but points are only awarded if all lower-tier tasks have been completed first.",
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name='joly')
    async def joly(self, ctx):
        await ctx.send(
            "My name is Joly and I do not use runelite, using plugins makes me sick, "
            "you can simply just count to 15 using a reference point, its shrimple as, "
            "I was born with this natural talent"
        )

    @app_commands.command(
        name="apply",
        description="Send an application request to a user with world instructions."
    )
    @app_commands.describe(
        user="The user you want to notify.",
        world="The world number they should hop to."
    )
    async def apply_to_clan(
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
