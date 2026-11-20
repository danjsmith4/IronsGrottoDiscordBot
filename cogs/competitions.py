"""TempleOSRS Skill/Boss of the Week winners board, limited to current clan members."""
import asyncio
import hashlib
import json
import logging
import re
import time
from collections import Counter
from datetime import datetime

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import COMPETITION_CHECK_MINUTES, STAFF_ROLE_ID, TEMPLE_API_URL, TEMPLE_GROUP_ID
from cogs.events import EASTERN, parse_date
from storage import CompetitionStore

logger = logging.getLogger(__name__)
MARKER = 'Irons Grotto SOTW/BOTW winners'
# Names like "Vorkath BOTW", "Sotw Prayer" or the truncated "Theatre of Blood Hard Mode BOT".
WEEKLY_NAME = re.compile(r'\b[sb]otw?\b', re.IGNORECASE)
# Temple keeps polling players briefly after the end time; wait before locking in results.
RESULT_GRACE_SECONDS = 2 * 60 * 60
REQUEST_SPACING_SECONDS = 1
# A member list this short is treated as a Temple glitch rather than a mass exodus.
MIN_MEMBERS = 20
GROUP_COMPETITIONS_URL = f'https://templeosrs.com/groups/competitions.php?id={TEMPLE_GROUP_ID}'
CATEGORIES = ('SOTW', 'BOTW')
UNITS = {'SOTW': 'XP', 'BOTW': 'KC'}
RECENT_EVENTS = 5
MAX_EVENT_WINNERS = 50
# Discord allows 6000 characters across all embeds in one message.
MESSAGE_EMBED_LIMIT = 6000


def standings_url(comp_id):
    return f'https://templeosrs.com/competitions/standings.php?id={comp_id}'


def is_weekly(comp):
    return not comp.get('team_competition') and bool(WEEKLY_NAME.search(comp.get('name') or ''))


def standings(participants):
    """(display name, gain) for every participant with a positive gain."""
    if isinstance(participants, dict):
        participants = list(participants.values())
    players = []
    for player in participants or []:
        try:
            gain = int(player.get('gain') or 0)
        except (TypeError, ValueError):
            continue
        name = player.get('player_name_with_capitalization') or player.get('username')
        if gain > 0 and name:
            players.append((name, gain))
    return players


def member_keys(members):
    if isinstance(members, dict):
        members = list(members.values())
    if not isinstance(members, list):
        raise ValueError('TempleOSRS member list has an unexpected format')
    keys = {CompetitionStore.name_key(name) for name in members if isinstance(name, str) and name.strip()}
    if len(keys) < MIN_MEMBERS:
        raise ValueError(f'TempleOSRS member list has only {len(keys)} names; not trusting it')
    return keys


def names(row):
    return ' & '.join(f'**{discord.utils.escape_markdown(name)}**' for name in row['winners'])


def most_wins(rows, limit):
    """(latest display name, wins) for current members, most wins first, then most recent win."""
    counts, display, latest = Counter(), {}, {}
    for row in rows:  # newest first
        for name, key in zip(row['winners'], row['winner_keys']):
            counts[key] += 1
            display.setdefault(key, name)
            latest.setdefault(key, row['ended'])
    ranked = sorted(counts, key=lambda key: (-counts[key], -latest[key]))
    return [(display[key], counts[key]) for key in ranked[:limit]]


def build_embed(store, members):
    esc = discord.utils.escape_markdown
    embed = discord.Embed(
        title='🏆 SOTW & BOTW Winners', color=discord.Color.gold(),
        description=f'Current clan members only. Updates automatically after each Skill and Boss of the Week '
                    f'ends. Full results on [TempleOSRS]({GROUP_COMPETITIONS_URL}).')
    results = {category: store.results(category, members) for category in CATEGORIES}
    recent = []
    for category in CATEGORIES:
        if results[category]:
            row = results[category][0]
            recent.append(f"**{category}** · [{esc(row['name'])}]({standings_url(row['id'])}) · ended <t:{row['ended']}:d>\n"
                          f"🥇 {names(row)} with {row['gain']:,} {UNITS[category]}"
                          + (' (tie)' if len(row['winners']) > 1 else ''))
    embed.add_field(name='Recent Winners', value='\n\n'.join(recent) or 'No winners yet.', inline=False)
    for category in CATEGORIES:
        lines = [f"<t:{row['ended']}:d> · [{esc(row['name'])}]({standings_url(row['id'])}) · "
                 f"{names(row)} ({row['gain']:,} {UNITS[category]})" for row in results[category][1:6]]
        embed.add_field(name=f'Previous {category} Winners', value='\n'.join(lines) or 'None yet.', inline=False)
    for category in CATEGORIES:
        leaders = most_wins(results[category], 10)
        # Shared ranks for equal win counts: 1, 2, 2, 2, 5...
        lines = [f'{1 + sum(c > count for _, c in leaders)}. **{esc(name)}** · {count} win{"s" if count != 1 else ""}'
                 for name, count in leaders]
        embed.add_field(name=f'Most {category} Wins', value='\n'.join(lines) or 'None yet.', inline=True)
    embed.set_footer(text=MARKER)
    return embed


def parse_winners(text):
    """Split on commas, semicolons or new lines; drop blanks and repeats (any case), keep order."""
    seen, winners = set(), []
    for part in re.split(r'[,;\n]+', text):
        name = ' '.join(part.split())
        if name and name.lower() not in seen:
            seen.add(name.lower())
            winners.append(name)
    return winners


def event_value(event, shown):
    """Date and note on one line, then winners; any beyond `shown` become '+N more'."""
    esc = discord.utils.escape_markdown
    header = f"<t:{event['ended']}:D>" + (f" · {esc(event['note'])}" if event['note'] else '')
    winners = event['winners']
    listed = ', '.join(f'**{esc(name)}**' for name in winners[:shown])
    extra = len(winners) - shown
    if extra > 0:
        listed += f' +{extra} more'
    medal = '🥇 ' if len(winners) == 1 else '🏆 '
    return f'{header}\n{medal}{listed}'


def build_events_embed(events, budget):
    """The most recent manual events; winner lists are shortened only if needed to fit `budget` characters."""
    if not events:
        return None
    longest = max(len(event['winners']) for event in events)
    for shown in range(longest, 0, -1):
        embed = discord.Embed(title='🎉 Event Winners', color=discord.Color.purple(),
                              description='Bingos, weekend events and more. The five most recent.')
        values = [event_value(event, shown) for event in events]
        if all(len(value) <= 1024 for value in values):
            for event, value in zip(events, values):
                embed.add_field(name=discord.utils.escape_markdown(event['name'])[:256], value=value, inline=False)
            if len(embed) <= budget:
                return embed
    return embed


def board_embeds(store, members):
    first = build_embed(store, members)
    second = build_events_embed(store.events(RECENT_EVENTS), MESSAGE_EMBED_LIMIT - len(first))
    return [first] + ([second] if second else [])


def embed_hash(embeds):
    return hashlib.sha256(json.dumps([e.to_dict() for e in embeds], sort_keys=True).encode()).hexdigest()


class Competitions(commands.Cog):
    winners_group = app_commands.Group(name='winners', description='SOTW/BOTW winners board', guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.store = CompetitionStore()
        self.lock = asyncio.Lock()
        self.session = None
        self.members = None  # last good Temple member list

    async def cog_load(self):
        self.sync_loop.start()

    async def cog_unload(self):
        self.sync_loop.cancel()
        if self.session is not None:
            await self.session.close()

    async def fetch_json(self, endpoint, item_id):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={'User-Agent': 'IronsGrottoDiscordBot (Discord clan bot)'})
        async with self.session.get(f'{TEMPLE_API_URL}/{endpoint}', params={'id': item_id}) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def collect_results(self):
        """Store standings for every newly finished SOTW/BOTW; returns how many were added."""
        data = await self.fetch_json('group_competitions.php', TEMPLE_GROUP_ID)
        comps = data.get('data') or []
        known = self.store.known_ids()
        cutoff = time.time() - RESULT_GRACE_SECONDS
        due = sorted((c for c in comps if c.get('status') == 2 and is_weekly(c) and c.get('id') not in known
                      and (c.get('end_date_unix') or 0) <= cutoff), key=lambda c: c['end_date_unix'])
        added = 0
        for comp in due:
            try:
                details = (await self.fetch_json('competition_info_v2.php', comp['id']))['data']
                info = details['info']
                category = 'SOTW' if info.get('skill_competition') else 'BOTW'
                self.store.record(comp['id'], ' '.join(comp['name'].split()), category,
                                  info.get('skill') or comp.get('skill', ''),
                                  int(info.get('end_date_unix') or comp['end_date_unix']),
                                  standings(details.get('participants')))
                added += 1
            except Exception:
                logger.exception('Could not load TempleOSRS competition %s; will retry', comp.get('id'))
            await asyncio.sleep(REQUEST_SPACING_SECONDS)
        if added:
            logger.info('Recorded %s finished SOTW/BOTW competitions', added)
        return added

    async def publish(self, members, *, force=False):
        """Draw the board; Discord is only touched when its contents changed (or force)."""
        channel_id, message_id, old_hash = self.store.board()
        if channel_id is None:
            return False
        embeds = board_embeds(self.store, members)
        new_hash = embed_hash(embeds)
        if message_id is not None and new_hash == old_hash and not force:
            return False
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if message_id is not None:
            try:
                await channel.get_partial_message(message_id).edit(
                    content=None, embeds=embeds, allowed_mentions=discord.AllowedMentions.none())
                self.store.set_board(channel_id, message_id, new_hash)
                return True
            except discord.NotFound:
                logger.warning('Winners board message was deleted; posting a new one')
        message = await channel.send(embeds=embeds, allowed_mentions=discord.AllowedMentions.none())
        self.store.set_board(channel_id, message.id, new_hash)
        return True

    async def sync(self, *, force=False):
        async with self.lock:
            # Membership first: never draw the board from a missing or broken member list.
            members = member_keys(await self.fetch_json('groupmembers.php', TEMPLE_GROUP_ID))
            self.members = members
            added = await self.collect_results()
            await self.publish(members, force=force)
            return added

    @tasks.loop(minutes=COMPETITION_CHECK_MINUTES)
    async def sync_loop(self):
        try:
            await self.sync()
        except Exception:
            logger.exception('Winners board update failed; will retry')

    @sync_loop.before_loop
    async def before_sync(self):
        await self.bot.wait_until_ready()

    async def authorized(self, interaction):
        if interaction.guild_id and any(r.id == STAFF_ROLE_ID for r in getattr(interaction.user, 'roles', [])):
            return True
        await interaction.response.send_message('Only Staff can manage the winners board.', ephemeral=True)
        return False

    @winners_group.command(name='setup', description='Post the SOTW/BOTW winners board in this channel')
    async def setup(self, interaction: discord.Interaction):
        if not await self.authorized(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            old_channel, old_message, _ = self.store.board()
            self.store.set_board(interaction.channel_id, None)
        try:
            await self.sync(force=True)
        except Exception:
            logger.exception('Winners board setup failed')
            await interaction.followup.send('Board channel saved, but TempleOSRS or Discord failed. '
                                            'It will retry automatically every 30 minutes.', ephemeral=True)
            return
        if old_message and old_channel:
            try:
                old = self.bot.get_channel(old_channel) or await self.bot.fetch_channel(old_channel)
                await old.get_partial_message(old_message).delete()
            except discord.HTTPException:
                pass
        await interaction.followup.send('Winners board posted. It updates automatically when each competition ends.',
                                        ephemeral=True)

    @winners_group.command(name='refresh', description='Check TempleOSRS now and redraw the winners board')
    async def refresh(self, interaction: discord.Interaction):
        if not await self.authorized(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            added = await self.sync(force=True)
        except Exception:
            logger.exception('Winners board refresh failed')
            await interaction.followup.send('Refresh failed; TempleOSRS may be down. Try again later.', ephemeral=True)
            return
        if self.store.board()[0] is None:
            await interaction.followup.send('No board yet. Use `/winners setup` in the channel it should live in.',
                                            ephemeral=True)
            return
        await interaction.followup.send(f'Board refreshed ({added} new results).', ephemeral=True)

    async def redraw(self):
        """Show an event change right away; uses the last member list instead of waiting on Temple."""
        if self.members is None:
            await self.sync()
            return
        async with self.lock:
            await self.publish(self.members)

    @winners_group.command(name='event-add', description='Add winners of a bingo, weekend event or other event')
    @app_commands.describe(event='Event name, e.g. "Winter Bingo 2026"',
                           winners='Winner names separated by commas (or new lines)',
                           date='Day the event ended, YYYY-MM-DD (Eastern); defaults to today',
                           note='Optional extra line, e.g. team name or prize')
    async def event_add(self, interaction: discord.Interaction, event: app_commands.Range[str, 1, 100],
                        winners: app_commands.Range[str, 1, 2000], date: str = None,
                        note: app_commands.Range[str, 1, 150] = None):
        if not await self.authorized(interaction):
            return
        names = parse_winners(winners)
        try:
            if not event.strip():
                raise ValueError('Give the event a name.')
            if not names:
                raise ValueError('List at least one winner, separated by commas.')
            if len(names) > MAX_EVENT_WINNERS:
                raise ValueError(f'That is {len(names)} winners; the limit is {MAX_EVENT_WINNERS}.')
            if any(len(name) > 50 for name in names):
                raise ValueError('Each winner name must be 50 characters or less. Separate names with commas.')
            # Noon Eastern so the date shows as the same day for viewers in any US time zone.
            day = parse_date(date) if date else parse_date(datetime.now(EASTERN).date().isoformat())
            ended = day + 12 * 60 * 60
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        note = ' '.join(note.split()) if note else None
        event_id = self.store.add_event(' '.join(event.split()), ended, names, note or None, interaction.user.id)
        message = f'Added event #{event_id}: {" ".join(event.split())} with {len(names)} winner{"s" if len(names) != 1 else ""}.'
        try:
            await self.redraw()
        except Exception:
            logger.exception('Winners board redraw after event add failed')
            message += ' The board could not be updated right now; it will catch up within 30 minutes.'
        if self.store.board()[0] is None:
            message += ' No board yet: use `/winners setup` in the channel it should live in.'
        elif event_id not in {e['id'] for e in self.store.events(RECENT_EVENTS)}:
            message += ' It is older than the five most recent events, so it is saved but not shown.'
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @winners_group.command(name='event-list', description='List saved event winners with their IDs')
    async def event_list(self, interaction: discord.Interaction):
        if not await self.authorized(interaction):
            return
        events = self.store.events(25)
        if not events:
            await interaction.response.send_message('No events saved yet. Add one with `/winners event-add`.',
                                                    ephemeral=True)
            return
        lines = [f"#{e['id']} · <t:{e['ended']}:d> · {discord.utils.escape_markdown(e['name'])} "
                 f"({len(e['winners'])} winner{'s' if len(e['winners']) != 1 else ''})" for e in events]
        embed = discord.Embed(title='Saved events (newest 25)', description='\n'.join(lines),
                              color=discord.Color.purple())
        embed.set_footer(text=f'The board shows the newest {RECENT_EVENTS}. Remove with /winners event-remove.')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @winners_group.command(name='event-remove', description='Remove an event using its ID from /winners event-list')
    async def event_remove(self, interaction: discord.Interaction, event_id: int):
        if not await self.authorized(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not self.store.remove_event(event_id):
            await interaction.followup.send('Event not found. Check `/winners event-list` for IDs.', ephemeral=True)
            return
        message = f'Removed event #{event_id}.'
        try:
            await self.redraw()
        except Exception:
            logger.exception('Winners board redraw after event remove failed')
            message += ' The board will update within 30 minutes.'
        await interaction.followup.send(message, ephemeral=True)
