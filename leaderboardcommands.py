# leaderboardcommands.py
import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import json
import asyncio
import hashlib
from typing import List, Optional

EMBED_DESC_LIMIT = 4096
PAGE_DESC_TARGET = 3500  # headroom for footer/title/thumbnail
LEADERBOARD_CHANNEL_ID = 1357210920882798763

MSG_IDS_PATH = "leaderboard_messages.json"
HASHES_PATH = "leaderboard_hashes.json"

# Bosses that are ranked by deepest wave (higher is better)
WAVE_BOSSES = {"Doom of Mokhaiotl"}


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
class LeaderboardCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('leaderboards.db')
        self.cursor = self.conn.cursor()
        self.create_leaderboard_table()
        self.leaderboard_messages = self._load_json(MSG_IDS_PATH)
        self.leaderboard_hashes = self._load_json(HASHES_PATH)

        self.boss_images = {
            "Alchemical Hydra": "https://i.imgur.com/ABJ2QsO.png",
            "Amoxliatl": "https://i.imgur.com/paHwkUF.png",
            "Araxxor": "https://i.imgur.com/vFEON5R.png",
            "Chambers of Xeric CM 5-Man": "https://i.imgur.com/nbAhM3s.png",
            "Chambers of Xeric CM Solo": "https://i.imgur.com/FRr4gyR.png",
            "Chambers of Xeric CM Trio": "https://i.imgur.com/5K1z9eb.png",
            "Chambers of Xeric Duo": "https://tinypic.host/images/2025/04/04/duo-olm.png",
            "Chambers of Xeric Solo": "https://i.imgur.com/JyhvZaS.png",
            "Chambers of Xeric Trio": "https://tinypic.host/images/2025/04/04/olm-trio.png",
            "Corrupted Gauntlet": "https://i.imgur.com/joKX3Pm.png",
            "Duke": "https://i.imgur.com/lSI3PLw.png",
            "Doom of Mokhaiotl": "https://i.imgur.com/dyqGBrK.png",
            "Fight Caves": "https://i.imgur.com/E4tRuPx.png",
            "Fortis Colosseum": "https://i.imgur.com/j72p8V5.png",
            "Grotesque Guardians": "https://i.imgur.com/Peh7PuU.png",
            "Hallowed Sepulchre": "https://i.imgur.com/ynD3Exh.png",
            "Hard Mode ToB 4-Man": "https://i.imgur.com/7NKkNNF.png",
            "Hard Mode ToB 5-Man": "https://i.imgur.com/abuq8ZO.png",
            "Hard Mode ToB Trio": "https://i.imgur.com/hYfqlVa.png",
            "Hespori": "https://i.imgur.com/bFvQ5O2.png",
            "Inferno": "https://i.imgur.com/HpQOARB.png",
            "Leviathan": "https://i.imgur.com/ZmzZVt1.png",
            "Phantom Muspah": "https://i.imgur.com/zg468rf.png",
            "Phosani's Nightmare": "https://i.imgur.com/iZ8lyZE.png",
            "Regular Gauntlet": "https://i.imgur.com/9J34UrO.png",
            "Royal Titans": "https://i.imgur.com/owZjOoq.png",
            "Theater of Blood 4-Man": "https://i.imgur.com/wErk9ne.png",
            "Theater of Blood 5-Man": "https://i.imgur.com/5jKMQ5W.png",
            "Theater of Blood Duo": "https://i.imgur.com/9ONRE2u.png",
            "Theater of Blood Solo": "https://i.imgur.com/P5UBxSn.png",
            "Theater of Blood Trio": "https://i.imgur.com/ksWmzR1.png",
            "Tomb's of Amascut": "https://i.imgur.com/dfW2MgK.png",
            "Tomb's of Amascut Expert": "https://i.imgur.com/rcS4UBT.png",
            "Vardorvis": "https://i.imgur.com/q3WbSIQ.png",
            "Vorkath": "https://i.imgur.com/0JZJxD8.png",
            "Whisperer": "https://i.imgur.com/EaIZEKi.png",
            "Zulrah": "https://i.imgur.com/XhAQFSb.png",
            "Yama": "https://i.imgur.com/4GGXfVi.gif",
        }

        self.boss_aliases = {
            "Araxxor": ["araxxor"],
            "Zulrah": ["zulrah"],
            "Grotesque Guardians": ["grotesque guardians", "gg"],
            "Vorkath": ["vorkath"],
            "Chambers of Xeric Solo": ["chambers of xeric solo", "cox solo", "cox 1"],
            "Chambers of Xeric Duo": ["chambers of xeric duo", "cox duo", "cox 2"],
            "Chambers of Xeric Trio": ["chambers of xeric trio", "cox trio", "cox 3"],
            "Chambers of Xeric CM Solo": ["chambers of xeric cm solo", "cox cm solo", "cox cm 1"],
            "Chambers of Xeric CM Trio": ["chambers of xeric cm trio", "cox cm trio", "cox cm 3"],
            "Chambers of Xeric CM 5-Man": ["chambers of xeric cm 5-man", "cox cm 5-man", "cox cm 5"],
            "Doom of Mokhaiotl": ["dom", "doom", "doom of mokhaiotl", "doom of mok"],
            "Theater of Blood Solo": ["tob solo", "theater of blood solo"],
            "Theater of Blood Duo": ["tob duo", "theater of blood duo", "tob 2"],
            "Theater of Blood Trio": ["tob trio", "theater of blood trio", "tob 3"],
            "Theater of Blood 4-Man": ["tob 4-man", "theater of blood 4-man", "tob 4"],
            "Theater of Blood 5-Man": ["tob 5-man", "theater of blood 5-man", "tob 5"],
            "Hard Mode ToB Trio": ["hard mode tob trio", "hard mode theater of blood trio", "hmt 3"],
            "Hard Mode ToB 4-Man": ["hard mode tob 4-man", "hard mode theater of blood 4-man", "hmt 4"],
            "Hard Mode ToB 5-Man": ["hard mode tob 5-man", "hard mode theater of blood 5-man", "hmt 5"],
            "Tomb's of Amascut": ["tomb's of amascut", "tombs of amascut", "toa"],
            "Tomb's of Amascut Expert": ["tomb's of amascut expert", "tombs of amascut expert", "toa expert"],
            "Phosani's Nightmare": ["phosani's nightmare", "pnm"],
            "Phantom Muspah": ["phantom muspah", "muspah"],
            "Royal Titans": ["royal titans"],
            "Alchemical Hydra": ["alchemical hydra", "hydra"],
            "Amoxliatl": ["amoxliatl"],
            "Vardorvis": ["vardorvis"],
            "Leviathan": ["leviathan", "levi"],
            "Duke": ["duke"],
            "Whisperer": ["whisperer"],
            "Regular Gauntlet": ["regular gauntlet", "gauntlet"],
            "Corrupted Gauntlet": ["corrupted gauntlet", "cg"],
            "Hespori": ["hespori"],
            "Inferno": ["inferno"],
            "Fight Caves": ["fight caves"],
            "Fortis Colosseum": ["fortis colosseum", "colo", "sol"],
            "Hallowed Sepulchre": ["hallowed sepulchre"],
            "Yama": ["yama"],
        }

    async def cog_load(self):
        """Register the /lb slash group ONCE when this cog is loaded."""
        if self.bot.tree.get_command("lb") is None:
            self.bot.tree.add_command(lb_group)

    async def cog_unload(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # ---------- DB ----------
    def create_leaderboard_table(self):
        self.cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS leaderboards (
                boss_name TEXT,
                rank INTEGER,
                user TEXT,
                time TEXT,
                proof_link TEXT,
                PRIMARY KEY (boss_name, rank)
            )
            '''
        )
        self.conn.commit()

    # ---------- JSON helpers ----------
    def _load_json(self, path: str) -> dict:
        try:
            with open(path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def _save_json(self, path: str, data: dict):
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # ---------- Helpers ----------
    def _proof_part(self, link: str) -> str:
        return f"([Proof]({link}))" if link else ""

    def _all_known_bosses(self) -> List[str]:
        return sorted(set(list(self.boss_aliases.keys()) + list(self.boss_images.keys())))

    def standardize_boss_name(self, boss_name: str) -> Optional[str]:
        name = boss_name.strip().lower()
        for standard, aliases in self.boss_aliases.items():
            if name == standard.lower() or name in (a.lower() for a in aliases):
                return standard
        for standard in self._all_known_bosses():
            if name == standard.lower():
                return standard
        return None

    def _convert_time(self, time_str: str) -> float:
        parts = time_str.split(':')
        try:
            if len(parts) == 3:
                m, s, ms = map(float, parts)
                return m * 60 + s + ms / 1000.0
            elif len(parts) == 2:
                m = float(parts[0]); s = float(parts[1])
                return m * 60 + s
            return float(time_str)
        except Exception:
            return float('inf')

    def _embed_hash(self, boss_name: str, lines: List[str]) -> str:
        thumb = self.boss_images.get(boss_name, "")
        payload = boss_name + "|" + thumb + "|" + "\n".join(lines)
        return hashlib.sha1(payload.encode('utf-8')).hexdigest()

    def distinct_users(self, prefix: str = "") -> List[str]:
        """Return up to 25 distinct usernames, optionally filtering by prefix (case-insensitive)."""
        like = f"%{prefix.strip().lower()}%"
        try:
            self.cursor.execute(
                "SELECT DISTINCT user FROM leaderboards WHERE lower(user) LIKE ? ORDER BY user LIMIT 25",
                (like,)
            )
            return [row[0] for row in self.cursor.fetchall()]
        except Exception:
            return []

    def _is_wave_boss(self, boss_name: str) -> bool:
        return boss_name in WAVE_BOSSES

    def _parse_wave(self, s: str) -> int:
        try:
            return int(str(s).strip())
        except Exception:
            return -1  # treat invalid as very low

    def _display_value(self, boss: str, value_str: str) -> str:
        """How to show the stored metric to users."""
        if self._is_wave_boss(boss):
            v = self._parse_wave(value_str)
            return f"Wave {v if v >= 0 else '—'}"
        return value_str  # time text as-is

    def _sort_key_for_boss(self, boss: str):
        """Return a sort key function for ranking."""
        if self._is_wave_boss(boss):
            # Higher wave is better → sort by negative wave (desc). Tie-breaker by user to stabilize.
            return lambda row: (-self._parse_wave(row[1]), row[0].lower())
        # default: lower time better
        return lambda row: (self._convert_time(row[1]), row[0].lower())

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
    def get_top_3_leaderboard(self, boss_name):
        self.cursor.execute(
            '''
            SELECT user, time, proof_link FROM leaderboards
            WHERE boss_name = ?
            ORDER BY (rank IS NULL), rank ASC, user ASC
            LIMIT 3
            ''',
            (boss_name,)
        )
        return self.cursor.fetchall()

    def get_all_leaderboard_entries(self, boss_name):
        self.cursor.execute(
            '''
            SELECT user, time, proof_link FROM leaderboards
            WHERE boss_name = ?
            ORDER BY (rank IS NULL), rank ASC, user ASC
            ''',
            (boss_name,)
        )
        return self.cursor.fetchall()

    def re_rank_leaderboard(self, boss_name):
        self.cursor.execute(
            '''
            SELECT user, time, proof_link FROM leaderboards
            WHERE boss_name = ?
            ''',
            (boss_name,)
        )
        entries = self.cursor.fetchall()

        key_fn = self._sort_key_for_boss(boss_name)
        sorted_entries = sorted(entries, key=key_fn)

        self.cursor.execute('UPDATE leaderboards SET rank = NULL WHERE boss_name = ?', (boss_name,))
        self.conn.commit()

        for rank, (user, time, _) in enumerate(sorted_entries, start=1):
            self.cursor.execute(
                '''
                UPDATE leaderboards
                SET rank = ?
                WHERE boss_name = ? AND user = ?
                ''',
                (rank, boss_name, user)
            )
        self.conn.commit()

    # ---------- Channel updater with no-op skip ----------
    async def update_specific_leaderboard(self, ctx_or_inter, boss_name: str):
        channel = self.bot.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(LEADERBOARD_CHANNEL_ID)
            except Exception:
                await self._respond(ctx_or_inter, "Leaderboard channel not found.")
                return

        top_3 = self.get_top_3_leaderboard(boss_name)
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
        if new_hash == old_hash and boss_name in self.leaderboard_messages:
            return

        description = "\n".join(lines)
        embed = discord.Embed(
            title=f"{boss_name} Leaderboard",
            description=description,
            color=discord.Color.green()
        )
        if boss_name in self.boss_images:
            embed.set_thumbnail(url=self.boss_images[boss_name])

        if boss_name in self.leaderboard_messages:
            try:
                msg = await channel.fetch_message(self.leaderboard_messages[boss_name])
                await msg.edit(embed=embed)
            except discord.NotFound:
                msg = await channel.send(embed=embed)
                self.leaderboard_messages[boss_name] = msg.id
        else:
            msg = await channel.send(embed=embed)
            self.leaderboard_messages[boss_name] = msg.id

        self._save_json(MSG_IDS_PATH, self.leaderboard_messages)
        self.leaderboard_hashes[boss_name] = new_hash
        self._save_json(HASHES_PATH, self.leaderboard_hashes)

        # Gentle pacing against rate limits on PATCH/POST
        await asyncio.sleep(1.1)

    # ---------- Prefix Commands (still available) ----------
    @commands.command(case_insensitive=True)
    async def leaderboard(self, ctx, *, boss_name: str):
        boss = self.standardize_boss_name(boss_name)
        if boss is None:
            await ctx.send(f"Boss '{boss_name}' not found. Please recheck the name and try again.")
            return

        entries = self.get_all_leaderboard_entries(boss)
        if not entries:
            await ctx.send(
                f"No entries found for {boss}. If the boss has spaces, use quotes, e.g. `.leaderboard \"Grotesque Guardians\"`."
            )
            return

        lines = [
            f"Rank {rank}: {user} - {self._display_value(boss, time)} {self._proof_part(proof)}".strip()
            for rank, (user, time, proof) in enumerate(entries, start=1)
        ]

        pages, buf = [], ""
        for line in lines:
            add = line + "\n"
            if len(buf) + len(add) > PAGE_DESC_TARGET:
                pages.append(buf)
                buf = ""
            buf += add
        if buf:
            pages.append(buf)

        total = len(pages)
        for i, page in enumerate(pages, start=1):
            embed = discord.Embed(title=f"{boss} Leaderboard", description=page, color=discord.Color.blue())
            if i == 1 and boss in self.boss_images:
                embed.set_thumbnail(url=self.boss_images[boss])
            if total > 1:
                embed.set_footer(text=f"Page {i}/{total}")
            await ctx.send(embed=embed)
            await asyncio.sleep(0.3)

    @commands.command(case_insensitive=True)
    @commands.has_any_role("Owner", "Deputy Owner")
    async def update_leaderboard(self, ctx, boss_name, user, time, proof_link=None):
        boss = self.standardize_boss_name(boss_name)
        if boss is None:
            await ctx.send(f"Boss '{boss_name}' not found. Please recheck the name and try again.")
            return

        self.cursor.execute('DELETE FROM leaderboards WHERE boss_name = ? AND user = ?', (boss, user))
        self.cursor.execute(
            '''
            INSERT INTO leaderboards (boss_name, user, time, proof_link, rank)
            VALUES (?, ?, ?, ?, NULL)
            ''',
            (boss, user, time, proof_link or "")
        )
        self.conn.commit()

        self.re_rank_leaderboard(boss)
        await self.update_specific_leaderboard(ctx, boss)
        await ctx.send(f"{boss} leaderboard updated for {user}.")

    @commands.command(case_insensitive=True)
    @commands.has_any_role("Owner", "Deputy Owner")
    async def remove_entry(self, ctx, boss_name, user):
        boss = self.standardize_boss_name(boss_name)
        if boss is None:
            await ctx.send(f"Boss '{boss_name}' not found. Please recheck the name and try again.")
            return

        self.cursor.execute('DELETE FROM leaderboards WHERE boss_name = ? AND user = ?', (boss, user))
        self.conn.commit()

        self.re_rank_leaderboard(boss)
        await self.update_specific_leaderboard(ctx, boss)
        await ctx.send(f"Removed {user} from {boss} leaderboard.")

    @commands.command(case_insensitive=True)
    @commands.has_role("Owner")
    async def remove_entry_all(self, ctx, user):
        self.cursor.execute('DELETE FROM leaderboards WHERE user = ?', (user,))
        self.conn.commit()
        await ctx.send(f"Removed all entries for {user}.")

    @commands.command(case_insensitive=True)
    @commands.has_role("Owner")
    async def phugmaprotocol(self, ctx):
        self.cursor.execute('DELETE FROM leaderboards')
        self.conn.commit()
        await ctx.send("All leaderboard data has been wiped.")

    @commands.command(name='lbfaq', help='Displays information about the Irons Grotto Hall of Fame.')
    async def lbfaq(self, ctx):
        embed = discord.Embed(
            title="🏆 Irons Grotto Hall of Fame 🏆",
            description=(
                "Welcome to the Irons Grotto Hall of Fame! This is where we celebrate and showcase the incredible achievements of our clan members.\n\n"
                "**Our Goals:**\n"
                "🥇 Display the **top 3 fastest times** for bosses and activities on our main leaderboard at <#1357210920882798763>\n"
                "📊 Maintain a **full leaderboard** of all submitted times for detailed comparisons using the `.leaderboard` command.\n"
                "⚔️ Foster a spirit of friendly competition within the clan.\n"
                "🤝 Encourage active participation and engagement among clanmates.\n\n"
                "**Want to Contribute?**\n"
                "If you've achieved a new personal best and would like to see your name in the Hall of Fame, here's how:\n"
                "📝 Check out <#1357560608635097229> for detailed submission guidelines.\n"
                "📜 Visit <#1357560551219396628> to understand the submission process.\n\n"
                "We encourage everyone to submit their times and be a part of our community's achievements!"
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="May your drops be plentiful and your times be swift!")
        await ctx.send(embed=embed)

    @commands.command(case_insensitive=True)
    @commands.has_any_role("Owner", "Deputy Owner")
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
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return

    entries = cog.get_all_leaderboard_entries(std)
    if not entries:
        await interaction.response.send_message(f"No entries found for {std}.", ephemeral=True)
        return

    lines = [
        f"Rank {rank}: {user} - {cog._display_value(std, time)} {cog._proof_part(proof)}".strip()
        for rank, (user, time, proof) in enumerate(entries, start=1)
    ]

    pages, buf = [], ""
    for line in lines:
        add = line + "\n"
        if len(buf) + len(add) > PAGE_DESC_TARGET:
            pages.append(buf)
            buf = ""
        buf += add
    if buf:
        pages.append(buf)

    await interaction.response.defer(ephemeral=True)
    total = len(pages)
    for i, page in enumerate(pages, start=1):
        embed = discord.Embed(title=f"{std} Leaderboard", description=page, color=discord.Color.blurple())
        if i == 1 and std in cog.boss_images:
            embed.set_thumbnail(url=cog.boss_images[std])
        if total > 1:
            embed.set_footer(text=f"Page {i}/{total}")
        await interaction.followup.send(embed=embed, ephemeral=True)
        await asyncio.sleep(0.15)


@lb_view.autocomplete('boss')
async def lb_view_boss_autocomplete(interaction: discord.Interaction, current: str):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        return []
    current = (current or "").lower()
    choices = [b for b in cog._all_known_bosses() if current in b.lower()]
    return [app_commands.Choice(name=b, value=b) for b in choices[:25]]


@lb_group.command(name="submit", description="Submit your PB for a boss (opens a form)")
@app_commands.describe(boss="Choose a boss")
async def lb_submit(interaction: discord.Interaction, boss: str):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return

    async def _save_modal(interaction: discord.Interaction, boss: str, osrs_name: str, time: str, proof_link: str):
        # interpret metric
        if boss in WAVE_BOSSES:
            wave = cog._parse_wave(time)
            if wave < 0:
                await interaction.response.send_message("Please enter a valid wave number (integer).", ephemeral=True)
                return
            store_value = str(wave)
        else:
            store_value = time

        cog.cursor.execute('DELETE FROM leaderboards WHERE boss_name = ? AND user = ?', (boss, osrs_name))
        cog.cursor.execute(
            '''
            INSERT INTO leaderboards (boss_name, user, time, proof_link, rank)
            VALUES (?, ?, ?, ?, NULL)
            ''',
            (boss, osrs_name, store_value, proof_link or "")
        )
        cog.conn.commit()

        cog.re_rank_leaderboard(boss)
        await cog.update_specific_leaderboard(interaction, boss)

        label = f"Wave {store_value}" if boss in WAVE_BOSSES else store_value
        await interaction.response.send_message(
            f"✅ Submitted PB for **{boss}** as **{osrs_name}** ({label}).",
            ephemeral=True
        )

    modal = SubmitPBModal(std, on_save=_save_modal)
    modal.title = f"Submit PB — {std}"
    await interaction.response.send_modal(modal)


@lb_submit.autocomplete('boss')
async def lb_submit_boss_autocomplete(interaction: discord.Interaction, current: str):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        return []
    current = (current or "").lower()
    choices = [b for b in cog._all_known_bosses() if current in b.lower()]
    return [app_commands.Choice(name=b, value=b) for b in choices[:25]]


@lb_group.command(name="update", description="(Staff) Update a PB directly")
@app_commands.describe(
    boss="Choose a boss",
    osrs_name="The OSRS username for the entry",
    time="Time (mm:ss or mm:ss.ms)",
    proof_link="Optional proof URL"
)
@app_commands.checks.has_any_role("Owner", "Deputy Owner")
async def lb_update(
    interaction: discord.Interaction,
    boss: str,
    osrs_name: str,
    time: str,
    proof_link: Optional[str] = None
):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return

    # interpret metric
    if std in WAVE_BOSSES:
        wave = cog._parse_wave(time)
        if wave < 0:
            await interaction.response.send_message("Please enter a valid wave number (integer).", ephemeral=True)
            return
        store_value = str(wave)
    else:
        store_value = time

    cog.cursor.execute('DELETE FROM leaderboards WHERE boss_name = ? AND user = ?', (std, osrs_name))
    cog.cursor.execute(
        '''
        INSERT INTO leaderboards (boss_name, user, time, proof_link, rank)
        VALUES (?, ?, ?, ?, NULL)
        ''',
        (std, osrs_name, store_value, proof_link or "")
    )
    cog.conn.commit()

    cog.re_rank_leaderboard(std)
    await cog.update_specific_leaderboard(interaction, std)

    label = f"Wave {store_value}" if std in WAVE_BOSSES else store_value
    await interaction.response.send_message(f"✅ Updated **{std}** for **{osrs_name}** ({label}).", ephemeral=True)


@lb_update.autocomplete('boss')
async def lb_update_boss_autocomplete(interaction: discord.Interaction, current: str):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        return []
    current = (current or "").lower()
    choices = [b for b in cog._all_known_bosses() if current in b.lower()]
    return [app_commands.Choice(name=b, value=b) for b in choices[:25]]


# -------- NEW: Remove / Clear / Refresh (staff) --------

@lb_group.command(name="remove", description="(Staff) Remove a user's PB from a boss")
@app_commands.describe(
    boss="Choose a boss",
    osrs_name="OSRS username to remove from this boss"
)
@app_commands.checks.has_any_role("Owner", "Deputy Owner")
async def lb_remove(
    interaction: discord.Interaction,
    boss: str,
    osrs_name: str
):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return

    cog.cursor.execute('DELETE FROM leaderboards WHERE boss_name = ? AND user = ?', (std, osrs_name))
    deleted = cog.cursor.rowcount
    cog.conn.commit()

    if deleted:
        cog.re_rank_leaderboard(std)
        await cog.update_specific_leaderboard(interaction, std)
        await interaction.response.send_message(f"🗑️ Removed **{osrs_name}** from **{std}**.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Nothing to remove: **{osrs_name}** had no entry for **{std}**.", ephemeral=True)


@lb_remove.autocomplete('boss')
async def lb_remove_boss_autocomplete(interaction: discord.Interaction, current: str):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        return []
    current = (current or "").lower()
    choices = [b for b in cog._all_known_bosses() if current in b.lower()]
    return [app_commands.Choice(name=b, value=b) for b in choices[:25]]


@lb_remove.autocomplete('osrs_name')
async def lb_remove_user_autocomplete(interaction: discord.Interaction, current: str):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        return []
    users = cog.distinct_users(current or "")
    return [app_commands.Choice(name=u, value=u) for u in users]


@lb_group.command(name="clear-user", description="(Staff) Remove ALL PBs for a user across all bosses")
@app_commands.describe(
    osrs_name="OSRS username to clear"
)
@app_commands.checks.has_any_role("Owner", "Deputy Owner")
async def lb_clear_user(
    interaction: discord.Interaction,
    osrs_name: str
):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    # Find bosses impacted first
    cog.cursor.execute('SELECT DISTINCT boss_name FROM leaderboards WHERE user = ?', (osrs_name,))
    bosses = [row[0] for row in cog.cursor.fetchall()]

    cog.cursor.execute('DELETE FROM leaderboards WHERE user = ?', (osrs_name,))
    deleted = cog.cursor.rowcount
    cog.conn.commit()

    if not deleted:
        await interaction.response.send_message(f"Nothing to clear: **{osrs_name}** has no entries.", ephemeral=True)
        return

    # Re-rank + refresh affected boss embeds
    for b in bosses:
        cog.re_rank_leaderboard(b)
        await cog.update_specific_leaderboard(interaction, b)
        await asyncio.sleep(0.5)

    await interaction.response.send_message(
        f"🧹 Cleared **{deleted}** record(s) for **{osrs_name}** across **{len(bosses)}** boss(es).",
        ephemeral=True
    )


@lb_clear_user.autocomplete('osrs_name')
async def lb_clear_user_autocomplete(interaction: discord.Interaction, current: str):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        return []
    users = cog.distinct_users(current or "")
    return [app_commands.Choice(name=u, value=u) for u in users]


@lb_group.command(name="clear-boss", description="(Staff) Wipe an entire boss leaderboard")
@app_commands.describe(
    boss="Choose a boss to clear"
)
@app_commands.checks.has_any_role("Owner", "Deputy Owner")
async def lb_clear_boss(
    interaction: discord.Interaction,
    boss: str
):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return

    cog.cursor.execute('DELETE FROM leaderboards WHERE boss_name = ?', (std,))
    deleted = cog.cursor.rowcount
    cog.conn.commit()

    cog.re_rank_leaderboard(std)
    await cog.update_specific_leaderboard(interaction, std)

    await interaction.response.send_message(
        f"🧨 Cleared **{deleted}** record(s) from **{std}**.",
        ephemeral=True
    )


@lb_clear_boss.autocomplete('boss')
async def lb_clear_boss_autocomplete(interaction: discord.Interaction, current: str):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        return []
    current = (current or "").lower()
    choices = [b for b in cog._all_known_bosses() if current in b.lower()]
    return [app_commands.Choice(name=b, value=b) for b in choices[:25]]


@lb_group.command(name="refresh", description="(Staff) Rebuild a single leaderboard embed")
@app_commands.describe(boss="Choose a boss")
@app_commands.checks.has_any_role("Owner", "Deputy Owner")
async def lb_refresh(interaction: discord.Interaction, boss: str):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return
    std = cog.standardize_boss_name(boss)
    if std is None:
        await interaction.response.send_message(f"Boss '{boss}' not found.", ephemeral=True)
        return
    cog.re_rank_leaderboard(std)
    await cog.update_specific_leaderboard(interaction, std)
    await interaction.response.send_message(f"🔄 Refreshed **{std}**.", ephemeral=True)


@lb_refresh.autocomplete('boss')
async def lb_refresh_boss_autocomplete(interaction: discord.Interaction, current: str):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        return []
    current = (current or "").lower()
    choices = [b for b in cog._all_known_bosses() if current in b.lower()]
    return [app_commands.Choice(name=b, value=b) for b in choices[:25]]


@lb_group.command(name="refresh-all", description="(Staff) Rebuild all leaderboard embeds (slow & rate-limit safe)")
@app_commands.checks.has_any_role("Owner", "Deputy Owner")
async def lb_refresh_all(interaction: discord.Interaction):
    cog: LeaderboardCommands = interaction.client.get_cog("LeaderboardCommands")  # type: ignore
    if not cog:
        await interaction.response.send_message("Leaderboard system not ready.", ephemeral=True)
        return

    bosses = cog._all_known_bosses()
    await interaction.response.send_message(f"Starting full refresh for **{len(bosses)}** bosses…", ephemeral=True)

    for b in bosses:
        cog.re_rank_leaderboard(b)
        await cog.update_specific_leaderboard(interaction, b)
        await asyncio.sleep(0.6)

    await interaction.followup.send("✅ Finished refreshing all leaderboards.", ephemeral=True)
