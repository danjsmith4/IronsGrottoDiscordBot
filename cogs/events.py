"""Staff-managed events and low-volume announcements."""
import asyncio
from datetime import date, datetime, time as day_time, timedelta
import logging
import random
import time
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import EVENT_CHANNEL_ID, EVENT_INTERVAL_SECONDS, STAFF_ROLE_ID
from storage import EventStore

logger = logging.getLogger(__name__)
EASTERN = ZoneInfo('America/New_York')
MARKER = 'Irons Grotto event reminder'


def parse_date(value, *, end=False):
    """Date-only ends include the whole Eastern calendar day, including DST days."""
    try:
        parsed = date.fromisoformat(value.strip())
        if parsed.isoformat() != value.strip():
            raise ValueError
        if end:
            parsed += timedelta(days=1)
        return int(datetime.combine(parsed, day_time.min, EASTERN).timestamp())
    except (ValueError, OverflowError):
        raise ValueError('Use dates in YYYY-MM-DD format, for example 2027-01-01.') from None


class Events(commands.Cog):
    events = app_commands.Group(name='event', description='Staff event management', guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.store = EventStore()
        self.lock = asyncio.Lock()

    async def cog_load(self):
        self.announcements.start()

    async def cog_unload(self):
        self.announcements.cancel()

    async def authorized(self, interaction):
        if interaction.guild_id and any(r.id == STAFF_ROLE_ID for r in getattr(interaction.user, 'roles', [])):
            return True
        await interaction.response.send_message('Only Staff can manage events.', ephemeral=True)
        return False

    @events.command(name='add', description='Add an event; dates are Eastern time (YYYY-MM-DD)')
    @app_commands.describe(title='Event name', description='Announcement text, details, or signup link',
                           end='Required last day, inclusive (YYYY-MM-DD)',
                           start='Optional first day (YYYY-MM-DD); omit for active immediately')
    async def add(self, interaction: discord.Interaction, title: app_commands.Range[str, 1, 200],
                  description: app_commands.Range[str, 1, 3000], end: str, start: str = None):
        if not await self.authorized(interaction):
            return
        now = int(time.time())
        try:
            ends = parse_date(end, end=True)
            starts = parse_date(start) if start else now
            if ends <= now:
                raise ValueError('The end date has already passed.')
            if starts >= ends:
                raise ValueError('The start date must be on or before the end date.')
            if not title.strip() or not description.strip():
                raise ValueError('Provide a title and announcement text.')
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            event_id = self.store.add(interaction.guild_id, title.strip(), description.strip(), starts, ends)
        await interaction.followup.send(
            f'Added event #{event_id}: {title}. Ends after {end} Eastern time. '
            'It will enter the random announcement rotation while active.',
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @events.command(name='list', description='List ongoing and future events with their IDs')
    async def list_events(self, interaction: discord.Interaction):
        if not await self.authorized(interaction):
            return
        rows = self.store.list(interaction.guild_id, int(time.time()))
        await interaction.response.defer(ephemeral=True)
        if not rows:
            await interaction.followup.send('No ongoing or future events.', ephemeral=True)
        for offset in range(0, len(rows), 10):
            embed = discord.Embed(title='Events', color=discord.Color.green())
            for row in rows[offset:offset + 10]:
                embed.add_field(name=f"#{row['id']} - {row['title']}",
                                value=f"Starts <t:{row['starts']}:f>\nEnds <t:{row['ends'] - 1}:f>", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

    @events.command(name='remove', description='Remove an event using its ID from /event list')
    async def remove(self, interaction: discord.Interaction, event_id: int):
        if not await self.authorized(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            removed = self.store.remove(interaction.guild_id, event_id)
        await interaction.followup.send('Event removed.' if removed else 'Event not found.', ephemeral=True)

    @tasks.loop(seconds=60)
    async def announcements(self):
        try:
            await self.announce_if_due()
        except Exception:
            logger.exception('Event announcement failed; will retry')

    @announcements.before_loop
    async def before_announcements(self):
        await self.bot.wait_until_ready()

    async def announce_if_due(self):
        async with self.lock:
            channel = self.bot.get_channel(EVENT_CHANNEL_ID)
            if channel is None:
                channel = await self.bot.fetch_channel(EVENT_CHANNEL_ID)
            now = int(time.time())
            next_due, previous_id = self.store.schedule(channel.guild.id)
            if now < next_due:
                return
            active = self.store.list(channel.guild.id, now, active=True)
            if not active and previous_id is None:
                return
            # Read actual history: cached last_message_id can be stale after restarts/deletions.
            latest = next(iter([message async for message in channel.history(limit=1)]), None)
            ours = latest is not None and latest.author.id == self.bot.user.id and (
                latest.id == previous_id or any(e.footer.text == MARKER for e in latest.embeds))
            if not active:
                if ours:
                    await latest.edit(content='No active events right now.', embed=None,
                                      allowed_mentions=discord.AllowedMentions.none())
                self.store.announced(channel.guild.id, now + EVENT_INTERVAL_SECONDS, previous_id)
                return
            event = random.choice(active)
            embed = discord.Embed(title=event['title'], description=event['description'],
                                  color=discord.Color.green())
            embed.add_field(name='Ends', value=f"<t:{event['ends'] - 1}:F> (<t:{event['ends'] - 1}:R>)")
            embed.set_footer(text=MARKER)
            if ours:
                await latest.edit(content=None, embed=embed, allowed_mentions=discord.AllowedMentions.none())
                message_id = latest.id
            else:
                message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                message_id = message.id
            self.store.announced(channel.guild.id, now + EVENT_INTERVAL_SECONDS, message_id)
