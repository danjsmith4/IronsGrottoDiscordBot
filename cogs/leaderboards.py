"""Leaderboard commands and Discord presentation."""
import asyncio
import hashlib
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import (LEADERBOARD_CHANNEL_ID, MSG_IDS_PATH, HASHES_PATH, WAVE_BOSSES,
                    BOSS_IMAGES, BOSS_ALIASES, STAFF_ROLES, OWNER_ROLE,
                    SUBMISSION_CHANNEL_ID, SUBMISSION_GUIDELINES_CHANNEL_ID)
from storage import LeaderboardStore

PAGE_DESC_TARGET = 3500

# ---------- Modal for /lb submit ----------
class SubmitPBModal(discord.ui.Modal, title="Submit Personal Best"):
    time = discord.ui.TextInput(
        label="Time",
        placeholder="mm:ss or mm:ss.ms",
        max_length=20
    )
    osrs_name = discord.ui.TextInput(
        label="OSRS Name",
        placeholder="Your in-game name (as you want it to appear)",
        max_length=32
    )
    proof_link = discord.ui.TextInput(
        label="Proof Link",
        placeholder="https://imgur.com/..., https://clips.twitch.tv/..., etc.",
        required=False,
        max_length=250
    )

    def __init__(self, boss: str, on_save):
        super().__init__()
        self.boss = boss
        self.on_save = on_save
        # Adjust field labels/placeholders for wave bosses
        if self.boss in WAVE_BOSSES:
            self.time.label = "Deepest Wave"
            self.time.placeholder = "e.g., 14"
            self.time.max_length = 4

    async def on_submit(self, interaction: discord.Interaction):
        await self.on_save(
            interaction=interaction,
            boss=self.boss,
            osrs_name=str(self.osrs_name),
            time=str(self.time),
            proof_link=str(self.proof_link),
        )


# ---------- Cog ----------
class Leaderboards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store = LeaderboardStore()
        self.leaderboard_messages = self.store.load_json(MSG_IDS_PATH)
        self.leaderboard_hashes = self.store.load_json(HASHES_PATH)
        self._update_locks = {}
        self.boss_images = BOSS_IMAGES
        self.boss_aliases = BOSS_ALIASES
        self._boss_names = sorted(self.boss_aliases.keys() | self.boss_images.keys())
        self._boss_lookup = {name.lower(): name for name in self._boss_names}
        for name, aliases in self.boss_aliases.items():
            self._boss_lookup.update((alias.lower(), name) for alias in aliases)

    async def cog_load(self):
        """Register the /lb slash group ONCE when this cog is loaded."""
        if self.bot.tree.get_command("lb") is None:
            self.bot.tree.add_command(lb_group)

    async def cog_unload(self):
        self.store.close()
        self.bot.tree.remove_command("lb")

    # ---------- Helpers ----------
    def build_pages(self, boss, entries, color):
        pages, lines = [], ""
        for rank, (user, value, proof) in enumerate(entries, start=1):
            line = f"Rank {rank}: {user} - {self._display_value(boss, value)} {self._proof_part(proof)}".strip() + "\n"
            if lines and len(lines) + len(line) > PAGE_DESC_TARGET:
                pages.append(lines)
                lines = ""
            lines += line
        if lines:
            pages.append(lines)
        embeds = []
        for index, page in enumerate(pages, start=1):
            embed = discord.Embed(title=f"{boss} Leaderboard", description=page, color=color)
            if index == 1 and boss in self.boss_images:
                embed.set_thumbnail(url=self.boss_images[boss])
            if len(pages) > 1:
                embed.set_footer(text=f"Page {index}/{len(pages)}")
            embeds.append(embed)
        return embeds

    def _proof_part(self, link: str) -> str:
        return f"([Proof]({link}))" if link else ""

    def _all_known_bosses(self) -> List[str]:
        return self._boss_names.copy()

    def standardize_boss_name(self, boss_name: str) -> Optional[str]:
        return self._boss_lookup.get(boss_name.strip().lower())


    def _embed_hash(self, boss_name: str, lines: List[str]) -> str:
        thumb = self.boss_images.get(boss_name, "")
        payload = boss_name + "|" + thumb + "|" + "\n".join(lines)
        return hashlib.sha1(payload.encode('utf-8')).hexdigest()


    def _display_value(self, boss: str, value_str: str) -> str:
        """How to show the stored metric to users."""
        if self.store.is_wave_boss(boss):
            v = self.store.parse_wave(value_str)
            return f"Wave {v if v >= 0 else '—'}"
        return value_str  # time text as-is


    async def _respond(self, target, content: str, *, ephemeral: bool = False):
        """Send to ctx or interaction safely."""
        if isinstance(target, discord.Interaction):
            if target.response.is_done():
                await target.followup.send(content, ephemeral=ephemeral)
            else:
                await target.response.send_message(content, ephemeral=ephemeral)
        else:
            await target.send(content)

    # ---------- Queries ----------


    # ---------- Channel updater with no-op skip ----------
    async def update_specific_leaderboard(self, ctx_or_inter, boss_name: str, *, force=False):
        lock = self._update_locks.setdefault(boss_name, asyncio.Lock())
        async with lock:
            await self._update_specific_leaderboard(ctx_or_inter, boss_name, force=force)

    async def _update_specific_leaderboard(self, ctx_or_inter, boss_name, *, force=False):
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(LEADERBOARD_CHANNEL_ID)
            except Exception:
                await self._respond(ctx_or_inter, "Leaderboard channel not found.")
                return

        top_3 = self.store.get_top_3_leaderboard(boss_name)
        if top_3:
            lines = [
                f"Rank {rank}: {user} - {self._display_value(boss_name, time)} {self._proof_part(proof_link)}".strip()
                for rank, (user, time, proof_link) in enumerate(top_3, start=1)
            ]
        else:
            lines = ["No entries yet."]

        new_hash = self._embed_hash(boss_name, lines)
        old_hash = str(self.leaderboard_hashes.get(boss_name, ""))

        # Skip if nothing changed and we already have a message
        if not force and new_hash == old_hash and boss_name in self.leaderboard_messages:
            return

        description = "\n".join(lines)
        embed = discord.Embed(
            title=f"{boss_name} Leaderboard",
            description=description,
            color=discord.Color.green()
        )
        if boss_name in self.boss_images:
            embed.set_thumbnail(url=self.boss_images[boss_name])

        previous_id = self.leaderboard_messages.get(boss_name)
        if boss_name in self.leaderboard_messages:
            try:
                msg = channel.get_partial_message(self.leaderboard_messages[boss_name])
                await msg.edit(embed=embed)
            except discord.NotFound:
                msg = await channel.send(embed=embed)
                self.leaderboard_messages[boss_name] = msg.id
        else:
            msg = await channel.send(embed=embed)
            self.leaderboard_messages[boss_name] = msg.id

        if previous_id != self.leaderboard_messages[boss_name]:
            self.store.save_json(MSG_IDS_PATH, self.leaderboard_messages)
        self.leaderboard_hashes[boss_name] = new_hash
        self.store.save_json(HASHES_PATH, self.leaderboard_hashes)

    # ---------- Prefix Commands (still available) ----------
    @commands.command(case_insensitive=True)
    async def leaderboard(self, ctx, *, boss_name: str):
        boss = self.standardize_boss_name(boss_name)
        if boss is None:
            await ctx.send(f"Boss '{boss_name}' not found. Please recheck the name and try again.")
            return

        entries = self.store.get_all_leaderboard_entries(boss)
        if not entries:
            await ctx.send(
                f"No entries found for {boss}. If the boss has spaces, use quotes, e.g. `.leaderboard \"Grotesque Guardians\"`."
            )
            return

        for embed in self.build_pages(boss, entries, discord.Color.blue()):
            await ctx.send(embed=embed)
            await asyncio.sleep(0.3)

    @commands.command(case_insensitive=True)
    @commands.has_any_role(*STAFF_ROLES)
    async def update_leaderboard(self, ctx, boss_name, user, time, proof_link=None):
        boss = self.standardize_boss_name(boss_name)
        if boss is None:
            await ctx.send(f"Boss '{boss_name}' not found. Please recheck the name and try again.")
            return

        try:
            self.store.save_entry(boss, user, time, proof_link)
        except ValueError as error:
            await ctx.send(str(error))
            return
        await self.update_specific_leaderboard(ctx, boss)
        await ctx.send(f"{boss} leaderboard updated for {user}.")

    @commands.command(case_insensitive=True)
    @commands.has_any_role(*STAFF_ROLES)
    async def remove_entry(self, ctx, boss_name, user):
        boss = self.standardize_boss_name(boss_name)
        if boss is None:
            await ctx.send(f"Boss '{boss_name}' not found. Please recheck the name and try again.")
            return

        self.store.remove_entries(user, boss)
        await self.update_specific_leaderboard(ctx, boss)
        await ctx.send(f"Removed {user} from {boss} leaderboard.")

    @commands.command(case_insensitive=True)
    @commands.has_role(OWNER_ROLE)
    async def remove_entry_all(self, ctx, user):
        _, bosses = self.store.remove_entries(user)
        for boss in bosses:
            await self.update_specific_leaderboard(ctx, boss)
        await ctx.send(f"Removed all entries for {user}.")

    @commands.command(case_insensitive=True)
    @commands.has_role(OWNER_ROLE)
    async def phugmaprotocol(self, ctx):
        self.store.clear()
        await ctx.send("All leaderboard data has been wiped.")

    @commands.command(name='lbfaq', help='Displays information about the Irons Grotto Hall of Fame.')
    async def lbfaq(self, ctx):
        embed = discord.Embed(
            title="🏆 Irons Grotto Hall of Fame 🏆",
            description=(
                "Welcome to the Irons Grotto Hall of Fame! This is where we celebrate and showcase the incredible achievements of our clan members.\n\n"
                "**Our Goals:**\n"
                f"🥇 Display the **top 3 fastest times** for bosses and activities on our main leaderboard at <#{LEADERBOARD_CHANNEL_ID}>\n"
                "📊 Maintain a **full leaderboard** of all submitted times for detailed comparisons using the `.leaderboard` command.\n"
                "⚔️ Foster a spirit of friendly competition within the clan.\n"
                "🤝 Encourage active participation and engagement among clanmates.\n\n"
                "**Want to Contribute?**\n"
                "If you've achieved a new personal best and would like to see your name in the Hall of Fame, here's how:\n"
                f"📝 Check out <#{SUBMISSION_GUIDELINES_CHANNEL_ID}> for detailed submission guidelines.\n"
                f"📜 Visit <#{SUBMISSION_CHANNEL_ID}> to understand the submission process.\n\n"
                "We encourage everyone to submit their times and be a part of our community's achievements!"
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="May your drops be plentiful and your times be swift!")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive=True)
    @commands.has_any_role(*STAFF_ROLES)
    async def leaderboards(self, ctx):
        groups = {
            "# Raids": [
                "Chambers of Xeric Solo", "Chambers of Xeric Duo", "Chambers of Xeric Trio",
                "Chambers of Xeric CM Solo", "Chambers of Xeric CM Trio", "Chambers of Xeric CM 5-Man",
                "Theater of Blood Solo", "Theater of Blood Duo", "Theater of Blood Trio",
                "Theater of Blood 4-Man", "Theater of Blood 5-Man",
                "Hard Mode ToB Trio", "Hard Mode ToB 4-Man", "Hard Mode ToB 5-Man",
                "Tomb's of Amascut Expert"
            ],
            "# Bosses": [
                "Amoxliatl", "Doom of Mokhaiotl", "Duke", "Leviathan", "Phantom Muspah",
                "Phosani's Nightmare", "Royal Titans", "Vardorvis", "Vorkath",
                "Whisperer", "Yama", "Zulrah"
            ],
            "# Minigames": [
                "Regular Gauntlet", "Corrupted Gauntlet", "Fight Caves", "Fortis Colosseum", "Inferno"
            ],
            "# Slayer Bosses": [
                "Alchemical Hydra", "Araxxor", "Grotesque Guardians"
            ],
            "# Misc": [
                "Hallowed Sepulchre", "Hespori"
            ]
        }

        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(LEADERBOARD_CHANNEL_ID)
            except Exception:
                await ctx.send("Leaderboard channel not found.")
                return

        for group, bosses in groups.items():
            await channel.send(f"**{group}**")
            await asyncio.sleep(0.8)
            for boss in bosses:
                await self.update_specific_leaderboard(ctx, boss)
        await ctx.send("All leaderboard messages have been posted or updated.")


# ---------- Module-level slash group (added in cog_load) ----------
lb_group = app_commands.Group(name="lb", description="Leaderboard commands")


@lb_group.command(name="view", description="View a full leaderboard (ephemeral, paginated)")
@app_commands.describe(boss="Choose a boss")
async def lb_view(interaction: discord.Interaction, boss: str):
    cog: Leaderboards = interaction.client.get_cog("Leaderboards")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return

    entries = cog.store.get_all_leaderboard_entries(std)
    if not entries:
        await interaction.response.send_message(f"No entries found for {std}.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    for embed in cog.build_pages(std, entries, discord.Color.blurple()):
        await interaction.followup.send(embed=embed, ephemeral=True)
        await asyncio.sleep(0.15)


@lb_group.command(name="submit", description="Submit your PB for a boss (opens a form)")
@app_commands.describe(boss="Choose a boss")
async def lb_submit(interaction: discord.Interaction, boss: str):
    cog: Leaderboards = interaction.client.get_cog("Leaderboards")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return

    async def _save_modal(interaction: discord.Interaction, boss: str, osrs_name: str, time: str, proof_link: str):
        await interaction.response.defer(ephemeral=True)
        try:
            store_value = cog.store.save_entry(boss, osrs_name, time, proof_link)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        await cog.update_specific_leaderboard(interaction, boss)

        label = f"Wave {store_value}" if boss in WAVE_BOSSES else store_value
        await interaction.followup.send(
            f"✅ Submitted PB for **{boss}** as **{osrs_name}** ({label}).",
            ephemeral=True
        )

    modal = SubmitPBModal(std, on_save=_save_modal)
    modal.title = f"Submit PB — {std}"[:45]
    await interaction.response.send_modal(modal)


@lb_group.command(name="update", description="(Staff) Update a PB directly")
@app_commands.describe(
    boss="Choose a boss",
    osrs_name="The OSRS username for the entry",
    time="Time (mm:ss or mm:ss.ms)",
    proof_link="Optional proof URL"
)
@app_commands.checks.has_any_role(*STAFF_ROLES)
async def lb_update(
    interaction: discord.Interaction,
    boss: str,
    osrs_name: str,
    time: str,
    proof_link: Optional[str] = None
):
    cog: Leaderboards = interaction.client.get_cog("Leaderboards")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        store_value = cog.store.save_entry(std, osrs_name, time, proof_link)
    except ValueError as error:
        await interaction.followup.send(str(error), ephemeral=True)
        return
    await cog.update_specific_leaderboard(interaction, std)

    label = f"Wave {store_value}" if std in WAVE_BOSSES else store_value
    await interaction.followup.send(f"✅ Updated **{std}** for **{osrs_name}** ({label}).", ephemeral=True)


# -------- NEW: Remove / Clear / Refresh (staff) --------

@lb_group.command(name="remove", description="(Staff) Remove a user's PB from a boss")
@app_commands.describe(
    boss="Choose a boss",
    osrs_name="OSRS username to remove from this boss"
)
@app_commands.checks.has_any_role(*STAFF_ROLES)
async def lb_remove(
    interaction: discord.Interaction,
    boss: str,
    osrs_name: str
):
    cog: Leaderboards = interaction.client.get_cog("Leaderboards")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    deleted, _ = cog.store.remove_entries(osrs_name, std)

    if deleted:
        await cog.update_specific_leaderboard(interaction, std)
        await interaction.followup.send(f"🗑️ Removed **{osrs_name}** from **{std}**.", ephemeral=True)
    else:
        await interaction.followup.send(f"Nothing to remove: **{osrs_name}** had no entry for **{std}**.", ephemeral=True)


@lb_group.command(name="clear-user", description="(Staff) Remove ALL PBs for a user across all bosses")
@app_commands.describe(
    osrs_name="OSRS username to clear"
)
@app_commands.checks.has_any_role(*STAFF_ROLES)
async def lb_clear_user(
    interaction: discord.Interaction,
    osrs_name: str
):
    cog: Leaderboards = interaction.client.get_cog("Leaderboards")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    deleted, bosses = cog.store.remove_entries(osrs_name)

    if not deleted:
        await interaction.followup.send(f"Nothing to clear: **{osrs_name}** has no entries.", ephemeral=True)
        return

    # Re-rank + refresh affected boss embeds
    for b in bosses:
        await cog.update_specific_leaderboard(interaction, b)

    await interaction.followup.send(
        f"🧹 Cleared **{deleted}** record(s) for **{osrs_name}** across **{len(bosses)}** boss(es).",
        ephemeral=True
    )


@lb_group.command(name="clear-boss", description="(Staff) Wipe an entire boss leaderboard")
@app_commands.describe(
    boss="Choose a boss to clear"
)
@app_commands.checks.has_any_role(*STAFF_ROLES)
async def lb_clear_boss(
    interaction: discord.Interaction,
    boss: str
):
    cog: Leaderboards = interaction.client.get_cog("Leaderboards")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    deleted = cog.store.clear(std)

    cog.store.re_rank_leaderboard(std)
    await cog.update_specific_leaderboard(interaction, std)

    await interaction.followup.send(
        f"🧨 Cleared **{deleted}** record(s) from **{std}**.",
        ephemeral=True
    )


@lb_group.command(name="refresh", description="(Staff) Rebuild a single leaderboard embed")
@app_commands.describe(boss="Choose a boss")
@app_commands.checks.has_any_role(*STAFF_ROLES)
async def lb_refresh(interaction: discord.Interaction, boss: str):
    cog: Leaderboards = interaction.client.get_cog("Leaderboards")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return
    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    cog.store.re_rank_leaderboard(std)
    await cog.update_specific_leaderboard(interaction, std, force=True)
    await interaction.followup.send(f"🔄 Refreshed **{std}**.", ephemeral=True)


@lb_group.command(name="refresh-all", description="(Staff) Rebuild all leaderboard embeds (slow & rate-limit safe)")
@app_commands.checks.has_any_role(*STAFF_ROLES)
async def lb_refresh_all(interaction: discord.Interaction):
    cog: Leaderboards = interaction.client.get_cog("Leaderboards")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    bosses = cog._all_known_bosses()
    await interaction.response.send_message(f"Starting full refresh for **{len(bosses)}** bosses…", ephemeral=True)

    for b in bosses:
        cog.store.re_rank_leaderboard(b)
        await cog.update_specific_leaderboard(interaction, b, force=True)

    await interaction.followup.send("✅ Finished refreshing all leaderboards.", ephemeral=True)


async def boss_autocomplete(interaction: discord.Interaction, current: str):
    cog = interaction.client.get_cog('Leaderboards')
    if not cog:
        return []
    names = [name for name in cog._all_known_bosses() if current.lower() in name.lower()]
    return [app_commands.Choice(name=name, value=name) for name in names[:25]]


async def user_autocomplete(interaction: discord.Interaction, current: str):
    cog = interaction.client.get_cog('Leaderboards')
    return [app_commands.Choice(name=name, value=name) for name in cog.store.distinct_users(current)] if cog else []


for command in (lb_view, lb_submit, lb_update, lb_remove, lb_clear_boss, lb_refresh):
    command.autocomplete('boss')(boss_autocomplete)
for command in (lb_remove, lb_clear_user):
    command.autocomplete('osrs_name')(user_autocomplete)
