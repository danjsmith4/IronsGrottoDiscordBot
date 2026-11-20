"""TempleOSRS Skill/Boss of the Week winners board."""
import asyncio
import logging
import re
import time

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
# Temple keeps polling players briefly after the end time; wait before locking in a winner.
RESULT_GRACE_SECONDS = 2 * 60 * 60
REQUEST_SPACING_SECONDS = 1
GROUP_COMPETITIONS_URL = f'https://templeosrs.com/groups/competitions.php?id={TEMPLE_GROUP_ID}'
CATEGORIES = ('SOTW', 'BOTW')
UNITS = {'SOTW': 'XP', 'BOTW': 'KC'}


def standings_url(comp_id):
    return f'https://templeosrs.com/competitions/standings.php?id={comp_id}'


def is_weekly(comp):
    return not comp.get('team_competition') and bool(WEEKLY_NAME.search(comp.get('name') or ''))


def pick_winner(participants):
    """Everyone tied on the highest positive gain; returns (names, gain) or ([], None)."""
    if isinstance(participants, dict):
        participants = list(participants.values())
    names, best = [], None
    for player in participants or []:
        try:
            gain = int(player.get('gain') or 0)
        except (TypeError, ValueError):
            continue
        name = player.get('player_name_with_capitalization') or player.get('username')
        if gain <= 0 or not name or (best is not None and gain < best):
            continue
        if best is None or gain > best:
            names, best = [], gain
        names.append(name)
    return names, best


def names(row):
    return ' & '.join(f'**{discord.utils.escape_markdown(name)}**' for name in row['winners'])


def build_embed(store):
    esc = discord.utils.escape_markdown
    embed = discord.Embed(
        title='🏆 SOTW & BOTW Winners', color=discord.Color.gold(),
        description=f'Updates automatically after each Skill and Boss of the Week ends. '
                    f'Full results on [TempleOSRS]({GROUP_COMPETITIONS_URL}).')
    recent, previous = [], {}
    for category in CATEGORIES:
        rows = store.winners(category, 6)
        previous[category] = rows[1:]
        if rows:
            row = rows[0]
            recent.append(f"**{category}** · [{esc(row['name'])}]({standings_url(row['id'])}) · ended <t:{row['ended']}:d>\n"
                          f"🥇 {names(row)} with {row['gain']:,} {UNITS[category]}"
                          + (' (tie)' if len(row['winners']) > 1 else ''))
    embed.add_field(name='Recent Winners', value='\n\n'.join(recent) or 'No winners yet.', inline=False)
    for category in CATEGORIES:
        lines = [f"<t:{row['ended']}:d> · [{esc(row['name'])}]({standings_url(row['id'])}) · "
                 f"{names(row)} ({row['gain']:,} {UNITS[category]})" for row in previous[category]]
        embed.add_field(name=f'Previous {category} Winners', value='\n'.join(lines) or 'None yet.', inline=False)
    for category in CATEGORIES:
        leaders = store.most_wins(category, 10)
        # Shared ranks for equal win counts: 1, 2, 2, 2, 5...
        lines = [f'{1 + sum(c > count for _, c in leaders)}. **{esc(name)}** · {count} win{"s" if count != 1 else ""}'
                 for name, count in leaders]
        embed.add_field(name=f'Most {category} Wins', value='\n'.join(lines) or 'None yet.', inline=True)
    embed.set_footer(text=MARKER)
    return embed


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

    async def fetch_json(self, endpoint, comp_or_group_id):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={'User-Agent': 'IronsGrottoDiscordBot (Discord clan bot)'})
        async with self.session.get(f'{TEMPLE_API_URL}/{endpoint}', params={'id': comp_or_group_id}) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def collect_results(self):
        """Store every newly finished SOTW/BOTW; returns how many were added."""
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
                winners, gain = pick_winner(details.get('participants'))
                self.store.record(comp['id'], ' '.join(comp['name'].split()), category,
                                  info.get('skill') or comp.get('skill', ''),
                                  int(info.get('end_date_unix') or comp['end_date_unix']), winners, gain)
                added += 1
            except Exception:
                logger.exception('Could not load TempleOSRS competition %s; will retry', comp.get('id'))
            await asyncio.sleep(REQUEST_SPACING_SECONDS)
        if added:
            logger.info('Recorded %s finished SOTW/BOTW competitions', added)
        return added

    async def publish(self, *, force=False):
        channel_id, message_id = self.store.board()
        if channel_id is None or (message_id is not None and not force):
            return
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        embed = build_embed(self.store)
        if message_id is not None:
            try:
                await channel.get_partial_message(message_id).edit(
                    content=None, embed=embed, allowed_mentions=discord.AllowedMentions.none())
                return
            except discord.NotFound:
                logger.warning('Winners board message was deleted; posting a new one')
        message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        self.store.set_board(channel_id, message.id)

    async def sync(self, *, force=False):
        async with self.lock:
            added = await self.collect_results()
            await self.publish(force=force or bool(added))
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
            old_channel, old_message = self.store.board()
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
