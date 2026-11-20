"""TempleOSRS Skill/Boss of the Week winners board, limited to current clan members."""
import asyncio
import hashlib
import json
import logging
import re
import time
from collections import Counter

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import COMPETITION_CHECK_MINUTES, STAFF_ROLE_ID, TEMPLE_API_URL, TEMPLE_GROUP_ID
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


def embed_hash(embed):
    return hashlib.sha256(json.dumps(embed.to_dict(), sort_keys=True).encode()).hexdigest()


class Competitions(commands.Cog):
    winners_group = app_commands.Group(name='winners', description='SOTW/BOTW winners board', guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.store = CompetitionStore()
        self.lock = asyncio.Lock()
        self.session = None

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
        embed = build_embed(self.store, members)
        new_hash = embed_hash(embed)
        if message_id is not None and new_hash == old_hash and not force:
            return False
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if message_id is not None:
            try:
                await channel.get_partial_message(message_id).edit(
                    content=None, embed=embed, allowed_mentions=discord.AllowedMentions.none())
                self.store.set_board(channel_id, message_id, new_hash)
                return True
            except discord.NotFound:
                logger.warning('Winners board message was deleted; posting a new one')
        message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        self.store.set_board(channel_id, message.id, new_hash)
        return True

    async def sync(self, *, force=False):
        async with self.lock:
            # Membership first: never draw the board from a missing or broken member list.
            members = member_keys(await self.fetch_json('groupmembers.php', TEMPLE_GROUP_ID))
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
