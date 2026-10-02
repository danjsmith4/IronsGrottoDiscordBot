"""Event-ban records, moderation controls, and submission review."""
import datetime
import re
from typing import List, Optional
from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands

from config import (EVENT_BANNED_ROLE_NAME, EVENTBAN_LOG_CHANNEL_ID,
                    APPLY_ROLE_BY_DEFAULT, SUBMISSION_CHANNEL_ID, STAFF_ROLES)
from storage import (
    init_eventban_db, insert_eventban, get_banned_users_with_latest,
    get_user_eventbans, delete_eventban_by_id, delete_eventbans_for_user,
    get_latest_record_id,
)

URL_PATTERN = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')

def allowed_url(url):
    try:
        host = urlsplit(url if '://' in url else 'https://' + url).hostname or ''
        return any(host == domain or host.endswith('.' + domain) for domain in ('imgur.com', 'gyazo.com'))
    except ValueError:
        return False
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
        deleted = delete_eventban_by_id(self.guild_id, self.record_id)
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


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_channel_id = SUBMISSION_CHANNEL_ID
        init_eventban_db()

    eventban_group = app_commands.Group(
        name="eventban",
        description="Manage and view event ban records",
    )

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
            insert_eventban(
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
        rows = get_banned_users_with_latest(interaction.guild_id)

        if not rows:
            return await interaction.followup.send("No event bans recorded for this server.", ephemeral=False)

        lines = []
        for uid, ev, iss, pun, created in rows:
            member = interaction.guild.get_member(uid)
            name = member.mention if member else f"`{uid}`"
            created_short = created.replace("T", " ")
            latest_id = get_latest_record_id(interaction.guild_id, uid)
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

        rows = get_user_eventbans(interaction.guild_id, member.id)
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

        deleted = delete_eventban_by_id(interaction.guild_id, record_id)
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

        count = delete_eventbans_for_user(interaction.guild_id, member.id)
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

    @commands.command(name='purge')
    @commands.has_any_role(*STAFF_ROLES)
    async def purge(self, ctx, amount: int):
        await ctx.channel.purge(limit=amount + 1)
        await ctx.send(f"Purged {amount} messages.")

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

        if not any(role.name in STAFF_ROLES for role in user.roles):
            return

        outcome = {"✅": "accepted", "❌": "denied"}.get(str(reaction.emoji))
        if outcome is None:
            return
        await reaction.message.delete()
        try:
            await reaction.message.author.send(f"Your submission was {outcome}.")
        except discord.Forbidden:
            await reaction.message.channel.send(
                f"{reaction.message.author.mention}, I tried to DM you that your submission was {outcome}, but your DMs are closed.",
                delete_after=10,
            )
