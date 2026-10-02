import os
import re
import random
import sqlite3
import datetime
from typing import Optional, List, Tuple

import discord
from discord.ext import commands
from discord import app_commands
from googleapiclient.discovery import build
from google.oauth2 import service_account

# =========================
# Event-ban config / DB
# =========================
EVENT_BANNED_ROLE_NAME = os.environ.get("EVENT_BANNED_ROLE_NAME", "Event Banned")
EVENTBAN_LOG_CHANNEL_ID = int(os.environ.get("EVENTBAN_LOG_CHANNEL_ID", "0"))  # optional staff log channel
EVENTBAN_DB_PATH = os.environ.get("EVENTBAN_DB_PATH", "event_bans.sqlite3")
APPLY_ROLE_BY_DEFAULT = os.environ.get("EVENTBAN_APPLY_ROLE_DEFAULT", "true").lower() == "true"


def _db():
    return sqlite3.connect(EVENTBAN_DB_PATH)


def _init_eventban_db():
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS event_bans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            issue TEXT NOT NULL,
            punishment TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bans_guild_user ON event_bans(guild_id, user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bans_guild_created ON event_bans(guild_id, created_at)")
    conn.commit()
    conn.close()


def _insert_eventban(guild_id: int, user_id: int, moderator_id: int, event: str, issue: str, punishment: str) -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO event_bans(guild_id, user_id, moderator_id, event, issue, punishment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (guild_id, user_id, moderator_id, event.strip(), issue.strip(), punishment.strip(),
         datetime.datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def _get_banned_users_with_latest(guild_id: int) -> List[Tuple[int, str, str, str, str]]:
    """
    Returns list of (user_id, latest_event, latest_issue, latest_punishment, latest_created_at).
    """
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT eb.user_id, eb.event, eb.issue, eb.punishment, eb.created_at
        FROM event_bans eb
        JOIN (
            SELECT user_id, MAX(created_at) AS max_created
            FROM event_bans
            WHERE guild_id=?
            GROUP BY user_id
        ) latest ON latest.user_id = eb.user_id AND latest.max_created = eb.created_at
        WHERE eb.guild_id=?
        ORDER BY eb.created_at DESC
        """,
        (guild_id, guild_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------- helpers for view/remove/clear ----------
def _get_user_eventbans(guild_id: int, user_id: int):
    """Return list of rows: (id, event, issue, punishment, created_at, moderator_id) newest first."""
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, event, issue, punishment, created_at, moderator_id
        FROM event_bans
        WHERE guild_id=? AND user_id=?
        ORDER BY created_at DESC, id DESC
        """,
        (guild_id, user_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def _delete_eventban_by_id(guild_id: int, record_id: int) -> int:
    """Delete a single record by its id (scoped to guild). Returns number of rows deleted (0 or 1)."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("DELETE FROM event_bans WHERE id=? AND guild_id=?", (record_id, guild_id))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def _delete_eventbans_for_user(guild_id: int, user_id: int) -> int:
    """Delete all records for a user in a guild. Returns number of rows deleted."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("DELETE FROM event_bans WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def _get_latest_record_id(guild_id: int, user_id: int) -> Optional[int]:
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM event_bans WHERE guild_id=? AND user_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        (guild_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# =========================
# UI: Modal & Views
# =========================
class EventBanModal(discord.ui.Modal, title="Add Event Ban"):
    event = discord.ui.TextInput(label="Event", placeholder="e.g., Summer Bingo — Hydra tile", max_length=100)
    issue = discord.ui.TextInput(label="Issue", style=discord.TextStyle.paragraph, placeholder="What happened?", max_length=1000)
    punishment = discord.ui.TextInput(label="Punishment", placeholder="e.g., 2-week event ban", max_length=200)

    def __init__(self, target_member: discord.Member, apply_role: bool, role_name: str,
                 log_channel: Optional[discord.TextChannel], on_save_callback):
        super().__init__()
        self.target_member = target_member
        self.apply_role = apply_role
        self.role_name = role_name
        self.log_channel = log_channel
        self.on_save_callback = on_save_callback  # coroutine

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.on_save_callback(self, interaction)


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, guild_id: int, record_id: int, requester_id: int, *, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.guild_id = guild_id
        self.record_id = record_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("This confirmation isn’t for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes, delete", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        deleted = _delete_eventban_by_id(self.guild_id, self.record_id)
        if deleted:
            await interaction.response.edit_message(
                content=f"✅ Deleted record **ID {self.record_id}**.",
                view=None
            )
        else:
            await interaction.response.edit_message(
                content=f"⚠️ No record found with ID **{self.record_id}** in this server.",
                view=None
            )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Deletion cancelled.", view=None)


class UnbanRoleView(discord.ui.View):
    """Button to remove the Event Banned role from a member."""
    def __init__(self, guild_id: int, member_id: int, requester_id: int, role_name: str, *, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.guild_id = guild_id
        self.member_id = member_id
        self.requester_id = requester_id
        self.role_name = role_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("This button isn’t for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Remove Event Banned role", style=discord.ButtonStyle.primary, emoji="🧹")
    async def unban(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.client.get_guild(self.guild_id)
        if not guild:
            return await interaction.response.edit_message(content="Guild not found.", view=None)

        member = guild.get_member(self.member_id)
        if not member:
            return await interaction.response.edit_message(content="Member not found in this guild.", view=None)

        role = discord.utils.get(guild.roles, name=self.role_name)
        if not role:
            return await interaction.response.edit_message(content=f"Role **{self.role_name}** does not exist.", view=None)

        if role not in member.roles:
            return await interaction.response.edit_message(content=f"{member.mention} does not have **{role.name}**.", view=None)

        try:
            await member.remove_roles(role, reason="Manual unban via /eventban")
            await interaction.response.edit_message(content=f"✅ Removed role **{role.name}** from {member.mention}.", view=None)
        except discord.Forbidden:
            await interaction.response.edit_message(content="I’m missing permission to remove that role.", view=None)
        except Exception:
            await interaction.response.edit_message(content="Something went wrong removing the role.", view=None)


class RecordListView(discord.ui.View):
    """
    Renders up to 5 'Delete' buttons for record IDs on a page.
    Clicking a button opens a confirm Yes/No prompt.
    Also includes an optional 'Remove Event Banned role' button for that member.
    """
    def __init__(self, guild_id: int, record_ids: List[int], requester_id: int,
                 member_id: Optional[int] = None, role_name: str = EVENT_BANNED_ROLE_NAME, *, timeout: int = 180):
        super().__init__(timeout=timeout)
        self.guild_id = guild_id
        self.record_ids = record_ids[:5]  # safety: max 5 buttons
        self.requester_id = requester_id

        for rid in self.record_ids:
            self.add_item(self._make_button(rid))

        # Add an Unban role button when viewing a single member’s records
        if member_id is not None:
            self.add_item(self._make_unban_button(member_id, requester_id, role_name))

    def _make_button(self, record_id: int) -> discord.ui.Button:
        btn = discord.ui.Button(
            label=f"Delete ID {record_id}",
            style=discord.ButtonStyle.danger,
            custom_id=f"del:{record_id}",
        )

        async def _callback(interaction: discord.Interaction):
            if interaction.user.id != self.requester_id:
                return await interaction.response.send_message("This menu isn’t for you.", ephemeral=True)
            view = ConfirmDeleteView(self.guild_id, record_id, self.requester_id)
            await interaction.response.send_message(
                f"Are you sure you want to delete record **ID {record_id}**?",
                view=view,
                ephemeral=True
            )

        btn.callback = _callback
        return btn

    def _make_unban_button(self, member_id: int, requester_id: int, role_name: str) -> discord.ui.Button:
        btn = discord.ui.Button(
            label="Remove Event Banned role",
            style=discord.ButtonStyle.primary,
            emoji="🧹",
            custom_id=f"unban:{member_id}",
        )

        async def _callback(interaction: discord.Interaction):
            if interaction.user.id != requester_id:
                return await interaction.response.send_message("This button isn’t for you.", ephemeral=True)
            view = UnbanRoleView(self.guild_id, member_id, requester_id, role_name)
            await interaction.response.send_message(
                f"Remove **{role_name}** from <@{member_id}>?",
                view=view,
                ephemeral=True
            )

        btn.callback = _callback
        return btn


# =========================
# Main Cog
# =========================
class BotCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.invite_link = "https://discord.gg/HPuwhhXnD5"
        self.temple_link = "https://templeosrs.com/groups/overview.php?id=241"
        self.ranksheet_link = "https://docs.google.com/spreadsheets/d/1IlcOiTEA9OM-eIvERsfS7JFtxxfbbbdtOFogiLWANm8/edit?usp=sharing"
        self.rank_calculator_app_link = "https://ironsgrotto.xyz"  # New link added

        self.staff_role_id = 829386451624001539

        self.SERVICE_ACCOUNT_FILE = 'lively-folder-427321-q7-eecd6c0329ea.json'
        self.SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        self.SPREADSHEET_ID = '1zwYdTFH29sqGYAw0HDUDI6IfB-7kJz3W1MkEDq9b3fg'
        self.EHB_RANGE = 'hof_overall!B37:C46'
        self.EHP_RANGE = 'hof_overall!B22:C31'
        self.LOG_RANGE = 'sheet41!K2:L11'

        self.creds = service_account.Credentials.from_service_account_file(
            self.SERVICE_ACCOUNT_FILE, scopes=self.SCOPES)
        self.service = build('sheets', 'v4', credentials=self.creds)

        # Image URLs for the rankcalc command
        self.image_url_1 = "https://i.imgur.com/pgg0TUv.png"
        self.image_url_2 = "https://i.imgur.com/GEJw9cA.png"
        self.image_url_3 = "https://i.imgur.com/HAPQdyX.png"

        # IDs for optional on_message logic (currently commented out below)
        self.target_user_id = 1384631480373870612
        self.trigger_channel_id = 1135112081205633105
        self.output_channel_id = 1386801415116029984

        self.ping_role_ids = [
            697877518493155387,  # MOD
            829386451624001539,  # STAFF
            697877518513864784  # DEPUTY
        ]

        # init event-ban DB
        _init_eventban_db()

    # Create the eventban group as a class attribute
    eventban_group = app_commands.Group(
        name="eventban",
        description="Manage and view event ban records",
    )

    # ========= Helpers for eventban =========
    async def _ensure_event_banned_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        role = discord.utils.get(guild.roles, name=EVENT_BANNED_ROLE_NAME)
        if role:
            return role
        try:
            return await guild.create_role(name=EVENT_BANNED_ROLE_NAME, reason="Auto-created by /eventban")
        except discord.Forbidden:
            return None

    async def _get_log_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        if not EVENTBAN_LOG_CHANNEL_ID:
            return None
        ch = guild.get_channel(EVENTBAN_LOG_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            return ch
        try:
            ch = await guild.fetch_channel(EVENTBAN_LOG_CHANNEL_ID)
            return ch if isinstance(ch, discord.TextChannel) else None
        except Exception:
            return None

    # ========= Slash commands on the eventban group =========
    @eventban_group.command(name="add", description="Open a form to record an event ban for a member")
    @app_commands.describe(target="Server member to record", apply="Also add the Event Banned role")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def eb_add(self, interaction: discord.Interaction, target: discord.Member,
                     apply: Optional[bool] = None):
        if interaction.guild is None:
            return await interaction.response.send_message("Run this in a server.", ephemeral=False)

        apply_flag = APPLY_ROLE_BY_DEFAULT if apply is None else apply
        log_ch = await self._get_log_channel(interaction.guild)

        async def _save(modal: EventBanModal, inter: discord.Interaction):
            _insert_eventban(
                guild_id=inter.guild_id,
                user_id=modal.target_member.id,
                moderator_id=inter.user.id,
                event=str(modal.event),
                issue=str(modal.issue),
                punishment=str(modal.punishment),
            )

            role_msg = "Role unchanged."
            if apply_flag:
                role = await self._ensure_event_banned_role(inter.guild)
                if role:
                    try:
                        if role not in modal.target_member.roles:
                            await modal.target_member.add_roles(role, reason="Event ban recorded")
                            role_msg = f"Role **{role.name}** added."
                        else:
                            role_msg = f"Role **{role.name}** already present."
                    except discord.Forbidden:
                        role_msg = "Missing permission to add role."
                else:
                    role_msg = f"Could not create/find **{EVENT_BANNED_ROLE_NAME}**."

            embed = discord.Embed(
                title="Event Ban Recorded",
                description=f"{modal.target_member.mention} (`{modal.target_member.id}`)",
                color=discord.Color.red(),
            )
            embed.add_field(name="Event", value=str(modal.event), inline=False)
            embed.add_field(name="Issue", value=str(modal.issue)[:1000] or "—", inline=False)
            embed.add_field(name="Punishment", value=str(modal.punishment) or "—", inline=False)
            embed.set_footer(text=f"By {inter.user} • {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

            await inter.response.send_message(embed=embed, ephemeral=False)

            if log_ch:
                try:
                    await log_ch.send(embed=embed)
                except Exception:
                    pass

            try:
                await inter.followup.send(role_msg, ephemeral=False)
            except Exception:
                pass

        modal = EventBanModal(
            target_member=target,
            apply_role=apply_flag,
            role_name=EVENT_BANNED_ROLE_NAME,
            log_channel=log_ch,
            on_save_callback=_save,
        )
        await interaction.response.send_modal(modal)

    @eventban_group.command(name="list", description="List members with any event ban record in this server")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def eb_list(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("Run this in a server.", ephemeral=False)

        await interaction.response.defer(ephemeral=False)
        rows = _get_banned_users_with_latest(interaction.guild_id)

        if not rows:
            return await interaction.followup.send("No event bans recorded for this server.", ephemeral=False)

        lines = []
        for uid, ev, iss, pun, created in rows:
            member = interaction.guild.get_member(uid)
            name = member.mention if member else f"`{uid}`"
            created_short = created.replace("T", " ")
            latest_id = _get_latest_record_id(interaction.guild_id, uid)
            id_part = f" (ID {latest_id})" if latest_id else ""
            lines.append(f"• {name} — **{ev}**{id_part} | *{pun}* | {created_short} UTC")

        # Chunk long messages safely
        chunks: List[str] = []
        buf = ""
        for line in lines:
            if len(buf) + len(line) + 1 > 3800:
                chunks.append(buf)
                buf = ""
            buf += line + "\n"
        if buf:
            chunks.append(buf)

        for i, chunk in enumerate(chunks, start=1):
            e = discord.Embed(
                title=f"Event Bans ({len(rows)} total)",
                description=chunk,
                color=discord.Color.blurple(),
            )
            if len(chunks) > 1:
                e.set_footer(text=f"Page {i}/{len(chunks)}")
            await interaction.followup.send(embed=e, ephemeral=False)

    @eventban_group.command(name="view", description="Show all event-ban records for a member")
    @app_commands.describe(member="Member to view")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def eb_view(self, interaction: discord.Interaction, member: discord.Member):
        if interaction.guild is None:
            return await interaction.response.send_message("Run this in a server.", ephemeral=False)

        await interaction.response.defer(ephemeral=False)

        rows = _get_user_eventbans(interaction.guild_id, member.id)
        if not rows:
            # Even with no records, offer an Unban role button if they still have the role
            view = UnbanRoleView(interaction.guild_id, member.id, interaction.user.id, EVENT_BANNED_ROLE_NAME)
            return await interaction.followup.send(f"{member.mention} has **no** event-ban records.", view=view, ephemeral=False)

        # Split into pages of up to 5 records (so we can attach up to 5 buttons)
        PAGE_SIZE = 5
        pages = [rows[i:i+PAGE_SIZE] for i in range(0, len(rows), PAGE_SIZE)]

        for page_index, page_rows in enumerate(pages, start=1):
            desc = ""
            record_ids_on_page: List[int] = []
            for (rid, ev, iss, pun, created, mod_id) in page_rows:
                created_short = created.replace("T", " ")
                record_ids_on_page.append(rid)
                desc += (
                    f"**ID {rid}** — **{ev}**\n"
                    f"*Punishment:* {pun}\n"
                    f"*Issue:* {iss[:300] + ('…' if len(iss) > 300 else '')}\n"
                    f"*By:* <@{mod_id}> • {created_short} UTC\n\n"
                )

            embed = discord.Embed(
                title=f"Event-ban history for {member} ({len(rows)} record{'s' if len(rows)!=1 else ''})",
                description=desc,
                color=discord.Color.red(),
            )
            if len(pages) > 1:
                embed.set_footer(text=f"Page {page_index}/{len(pages)}")

            view = RecordListView(
                guild_id=interaction.guild_id,
                record_ids=record_ids_on_page,
                requester_id=interaction.user.id,
                member_id=member.id,  # include Unban role button on view pages
                role_name=EVENT_BANNED_ROLE_NAME
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=False)

    @eventban_group.command(name="remove", description="Remove one event-ban record by its ID")
    @app_commands.describe(record_id="The record ID to delete (see /eventban view)")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def eb_remove(self, interaction: discord.Interaction, record_id: int):
        if interaction.guild is None:
            return await interaction.response.send_message("Run this in a server.", ephemeral=False)

        deleted = _delete_eventban_by_id(interaction.guild_id, record_id)
        if deleted:
            await interaction.response.send_message(f"✅ Deleted record **ID {record_id}**.", ephemeral=False)
        else:
            await interaction.response.send_message(f"⚠️ No record found with ID **{record_id}** in this server.", ephemeral=False)

    @eventban_group.command(name="clear", description="Remove ALL event-ban records for a member")
    @app_commands.describe(member="Member whose records to clear")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def eb_clear(self, interaction: discord.Interaction, member: discord.Member):
        if interaction.guild is None:
            return await interaction.response.send_message("Run this in a server.", ephemeral=False)

        count = _delete_eventbans_for_user(interaction.guild_id, member.id)
        view = UnbanRoleView(interaction.guild_id, member.id, interaction.user.id, EVENT_BANNED_ROLE_NAME)
        if count:
            await interaction.response.send_message(
                f"✅ Cleared **{count}** record(s) for {member.mention}.",
                view=view,
                ephemeral=False
                )
        else:
            await interaction.response.send_message(
                f"{member.mention} had no records to clear.",
                view=view,
                ephemeral=False
            )

    # ========= Your existing text commands =========
    @commands.command(name='invite')
    async def invite(self, ctx):
        await ctx.send(f"Here is the invite link to the server: {self.invite_link}")

    @commands.command(name='temple')
    async def temple(self, ctx):
        await ctx.send(f"Here is the link to the TempleOSRS page: {self.temple_link}")

    @commands.command(name='ranksheet')
    async def ranksheet(self, ctx):
        instructions = (
            "To rank up, please follow these steps:\n"
            "1. Open the Google Sheet and Make a Copy, ensure this can be shared with others\n"
            "2. Input your times and select the boss you are ranking for.\n"
            "3. Your rank will be automatically updated!\n\n"
            f"Here is the link to the rank sheet: {self.ranksheet_link}"
        )
        await ctx.send(instructions)

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
                "1. Open the Google sheet linked below and make a copy of the sheet. Please rename this sheet to your OSRS username. "
                "Under the 'file' tab, please click on the following: share > share with others > anyone with the link.\n\n"
                "2. Complete the spreadsheet by following the directions in the READ ME tab. You will need to do the following: Enter your username, "
                "double-click and enter your clan join date, select all boxes that apply to your account, and enter #s where indicated. Your rank will auto-calculate "
                "based on what you enter.\n\n"
                "3. Under the 'Provide Screenshots Here' section, you will need to link your Collectionlog.net URL. You can do this by installing the collectionlog "
                "plugin on Runelite and following the directions in the plugin. This plugin will be used to verify the information you enter on your application.\n\n"
                "4. When your application is complete, just copy & paste a link to your sheet in the appropriate channel. A member of the leadership team will look "
                "over your application and give you a rank in the clan. If you do not follow step 1 above, we will not be able to view your application.\n\n"
                f"[Application link]({self.ranksheet_link})\n\n"
                "If you have any questions, comments, or concerns, please don't hesitate to ask 😄"
            ),
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    @apply.error
    async def apply_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You do not have permission to use this command.")

    @commands.command(name='purge')
    @commands.has_any_role("Owner", "Deputy Owner")
    async def purge(self, ctx, amount: int):
        await ctx.channel.purge(limit=amount + 1)
        await ctx.send(f"Purged {amount} messages.")

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

    @commands.command(name='top_ehb')
    async def top_ehb(self, ctx):
        sheet = self.service.spreadsheets()
        result = sheet.values().get(spreadsheetId=self.SPREADSHEET_ID, range=self.EHB_RANGE).execute()
        values = result.get('values', [])

        if not values:
            await ctx.send('No EHB data found.')
        else:
            response = "EHB:\n"
            for rank, row in enumerate(values, start=1):
                if len(row) == 2:
                    username, ehb = row
                    response += f"{rank}. {username} | {ehb}\n"
                else:
                    response += f"Rank {rank}: Invalid data\n"
            await ctx.send(response)

    @commands.command(name='top_ehp')
    async def top_ehp(self, ctx):
        sheet = self.service.spreadsheets()
        result = sheet.values().get(spreadsheetId=self.SPREADSHEET_ID, range=self.EHP_RANGE).execute()
        values = result.get('values', [])

        if not values:
            await ctx.send('No EHP data found.')
        else:
            response = "EHP:\n"
            for rank, row in enumerate(values, start=1):
                if len(row) == 2:
                    username, ehp = row
                    response += f"{rank}. {username} | {ehp}\n"
                else:
                    response += f"Rank {rank}: Invalid data\n"
            await ctx.send(response)

    @commands.command(name='top_log')
    async def top_log(self, ctx):
        sheet = self.service.spreadsheets()
        result = sheet.values().get(spreadsheetId=self.SPREADSHEET_ID, range=self.LOG_RANGE).execute()
        values = result.get('values', [])

        if not values:
            await ctx.send('No Log data found.')
        else:
            response = "Top Collection Logs:\n"
            for rank, row in enumerate(values, start=1):
                if len(row) == 2:
                    username, log = row
                    response += f"{rank}. {username} | {log}\n"
                else:
                    response += f"Rank {rank}: Invalid data\n"
            await ctx.send(response)

    @commands.command(name='sotw')
    async def sotw(self, ctx, url: str):
        digits = re.findall(r'\d{5}$', url)
        if digits:
            extracted_digits = digits[0]
            values = [[extracted_digits]]
            body = {'values': values}
            try:
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.SPREADSHEET_ID,
                    range='Links!B10',
                    valueInputOption='USER_ENTERED',
                    body=body
                ).execute()
                await ctx.send(f'Extracted digits "{extracted_digits}" added to Links!B10.')
            except Exception as e:
                await ctx.send(f'An error occurred')

    @commands.command(name='botw')
    async def botw(self, ctx, url: str):
        digits = re.findall(r'\d{5}$', url)
        if digits:
            extracted_digits = digits[0]
            values = [[extracted_digits]]
            body = {'values': values}
            try:
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.SPREADSHEET_ID,
                    range='Links!B9',
                    valueInputOption='USER_ENTERED',
                    body=body
                ).execute()
                await ctx.send(f'Extracted digits "{extracted_digits}" added to Links!B9.')
            except Exception as e:
                await ctx.send(f'An error occurred: {e}')
        else:
            await ctx.send('Could not extract 5 digits from the URL.')

    @commands.command(name='raidbotw')
    async def raidbotw(self, ctx, url1: str, url2: str):
        digits1 = re.findall(r'\d{5}$', url1)
        digits2 = re.findall(r'\d{5}$', url2)

        if digits1 and digits2:
            extracted_digits1 = digits1[0]
            extracted_digits2 = digits2[0]

            try:
                body1 = {'values': [[extracted_digits1]]}
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.SPREADSHEET_ID,
                    range='Links!B9',
                    valueInputOption='USER_ENTERED',
                    body=body1
                ).execute()

                body2 = {'values': [[extracted_digits2]]}
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.SPREADSHEET_ID,
                    range='Links!B11',
                    valueInputOption='USER_ENTERED',
                    body=body2
                ).execute()

                await ctx.send(f'Extracted digits "{extracted_digits1}" added to Links!B9 and "{extracted_digits2}" added to Links!B11.')
            except Exception as e:
                await ctx.send(f'An error occurred: {e}')
        else:
            await ctx.send('Could not extract 5 digits from both URLs.')

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
                "Rank applications are posted to <#1135112081205633105> for review. 😄\n\n"
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

    """
    @commands.Cog.listener()
    async def on_message(self, message):
        # Example listener block left commented
        pass
    """

    @commands.command(name='diary')
    @commands.has_any_role("Owner", "Deputy Owner")
    async def diary(self, ctx):
        embed = discord.Embed(
            title="📓 The Grotto Diary",
            description=(
                "**What is the Grotto Diaries?**\n"
                "Boss speed-running + Collection Log challenges from Easy to Grandmaster, with rewards.\n\n"
                "**Rewards**\n"
                "Speedrun tiers award up to 4 points; Collection Log tiers awarded via Ranksheet.\n\n"
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
                "Head to <#1386920119619289210> and submit your times using the official sheet."
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
                "you must manually mark your ranksheet and resubmit."
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
            value="All drops must be posted in <#1399077840523104326> to count.",
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


# =========================
# Setup
# =========================
# Leave this commented if you add the cog directly in main.py
# async def setup(bot):
#     await bot.add_cog(BotCommands(bot))
