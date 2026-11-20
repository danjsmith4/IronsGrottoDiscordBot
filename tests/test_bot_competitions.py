import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs.competitions import Competitions, build_embed, is_weekly, pick_winner
from config import STAFF_ROLE_ID
from storage import CompetitionStore

NOW = 2_000_000
HOUR = 3600


def comp(comp_id, name, *, status=2, ended=NOW - 3 * HOUR, team=0):
    return {'id': comp_id, 'name': name, 'status': status, 'end_date_unix': ended, 'team_competition': team,
            'skill': 'Thing'}


def info(comp_id, *, skill, ended=NOW - 3 * HOUR, participants=None):
    return {'data': {'info': {'id': comp_id, 'skill_competition': int(skill), 'skill': 'Thing', 'end_date_unix': ended},
                     'participants': participants if participants is not None else [
                         {'username': 'Second', 'player_name_with_capitalization': None, 'gain': 10},
                         {'username': f'winner{comp_id}', 'player_name_with_capitalization': f'Winner{comp_id}',
                          'gain': 500}]}}


class CompetitionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'competitions.sqlite3')
        self.bot = MagicMock()
        self.channel = MagicMock()
        self.channel.send = AsyncMock(return_value=SimpleNamespace(id=900))
        self.channel.get_partial_message.return_value.edit = AsyncMock()
        self.bot.get_channel.return_value = self.channel
        with patch('cogs.competitions.CompetitionStore', return_value=CompetitionStore(self.path)):
            self.cog = Competitions(self.bot)
        self.group = [comp(1, 'Construction SOTW'), comp(2, 'Zalcano BOTW'),
                      comp(3, 'Prayer SOTW', status=0), comp(4, 'Vorkath BOTW', status=1),
                      comp(5, 'Bingo Nex', team=1), comp(6, 'Herb Lore'),
                      comp(7, 'Firemaking Sotw', ended=NOW - HOUR)]  # still in the grace period
        self.details = {1: info(1, skill=True), 2: info(2, skill=False), 7: info(7, skill=True)}
        self.calls = []

        async def fetch(endpoint, item_id):
            self.calls.append((endpoint, item_id))
            return {'data': self.group} if endpoint == 'group_competitions.php' else self.details[item_id]
        self.cog.fetch_json = fetch
        self.patches = [patch('cogs.competitions.time.time', return_value=NOW),
                        patch('cogs.competitions.asyncio.sleep', new=AsyncMock())]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        self.directory.cleanup()

    def test_weekly_name_matching(self):
        for name in ['Vorkath BOTW', 'Sotw Prayer', 'SOTW - Smithing', 'Hydra BotW', 'Theatre of Blood Hard Mode BOT']:
            self.assertTrue(is_weekly({'name': name}), name)
        for name in ['Herb Lore', 'Bingo Nex', '12 Dos Cox', 'Botwick']:
            self.assertFalse(is_weekly({'name': name}), name)
        self.assertFalse(is_weekly({'name': 'Nex BOTW', 'team_competition': 1}))

    def test_pick_winner(self):
        rows = [{'username': 'low', 'gain': 5}, {'username': 'top guy', 'player_name_with_capitalization': None,
                                                 'gain': '700'}, {'username': 'zero', 'gain': 0}]
        self.assertEqual(pick_winner(rows), (['top guy'], 700))
        self.assertEqual(pick_winner({'1': {'username': 'a', 'gain': 3}}), (['a'], 3))
        self.assertEqual(pick_winner([{'username': 'idle', 'gain': 0}]), ([], None))
        self.assertEqual(pick_winner([]), ([], None))
        tie = [{'username': 'Solo Sens', 'gain': 100}, {'username': 'esnape btw',
               'player_name_with_capitalization': 'eSnape btw', 'gain': 100}, {'username': 'x', 'gain': 73}]
        self.assertEqual(pick_winner(tie), (['Solo Sens', 'eSnape btw'], 100))

    async def test_records_only_finished_weekly_comps_after_grace(self):
        self.cog.store.set_board(55, None)
        self.assertEqual(await self.cog.sync(), 2)
        self.assertEqual(sorted(self.cog.store.known_ids()), [1, 2])
        self.assertEqual(self.cog.store.winners('SOTW', 5)[0]['winners'], ['Winner1'])
        self.assertEqual(self.cog.store.winners('BOTW', 5)[0]['gain'], 500)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.cog.store.board(), (55, 900))

    async def test_no_refetch_or_repost_when_nothing_new(self):
        self.cog.store.set_board(55, None)
        await self.cog.sync()
        self.calls.clear()
        await self.cog.sync()
        self.assertEqual(self.calls, [('group_competitions.php', 241)])
        self.channel.send.assert_awaited_once()
        self.channel.get_partial_message.return_value.edit.assert_not_awaited()

    async def test_new_result_edits_existing_board(self):
        self.cog.store.set_board(55, None)
        await self.cog.sync()
        self.group[-1]['end_date_unix'] = NOW - 3 * HOUR
        self.assertEqual(await self.cog.sync(), 1)
        self.channel.get_partial_message.assert_called_with(900)
        self.channel.get_partial_message.return_value.edit.assert_awaited_once()
        self.channel.send.assert_awaited_once()

    async def test_deleted_board_is_reposted(self):
        self.cog.store.set_board(55, 800)
        self.channel.get_partial_message.return_value.edit.side_effect = discord.NotFound(
            MagicMock(status=404), 'gone')
        await self.cog.sync(force=True)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.cog.store.board(), (55, 900))

    async def test_failed_competition_retried_later(self):
        good = self.details.pop(2)
        await self.cog.sync()
        self.assertEqual(self.cog.store.known_ids(), {1})
        self.details[2] = good
        await self.cog.sync()
        self.assertEqual(self.cog.store.known_ids(), {1, 2})

    async def test_no_winner_comp_is_remembered_but_not_shown(self):
        self.details[2] = info(2, skill=False, participants=[{'username': 'idle', 'gain': 0}])
        await self.cog.sync()
        self.calls.clear()
        await self.cog.sync()
        self.assertNotIn(('competition_info_v2.php', 2), self.calls)
        self.assertEqual(self.cog.store.winners('BOTW', 5), [])

    def test_board_sections(self):
        store = self.cog.store
        for i in range(8):  # SOTW winners alternate, newest last
            store.record(100 + i, f'Skill {i} SOTW', 'SOTW', 'Skill', 1000 + i, ['Alice' if i % 2 else 'bob_'], 1000 * i)
        store.record(200, 'Zulrah BOTW', 'BOTW', 'Zulrah', 5000, ['Carol', 'Dave'], 42)
        store.record(201, 'Old BOTW', 'BOTW', 'Vorkath', 10, ['carol'], 7)
        store.record(202, 'Empty BOTW', 'BOTW', 'Obor', 20, [], None)
        embed = build_embed(store)
        fields = {f.name: f.value for f in embed.fields}
        self.assertEqual([f.name for f in embed.fields], [
            'Recent Winners', 'Previous SOTW Winners', 'Previous BOTW Winners', 'Most SOTW Wins', 'Most BOTW Wins'])
        self.assertIn('Skill 7 SOTW', fields['Recent Winners'])
        self.assertIn('**Alice** with 7,000 XP', fields['Recent Winners'])
        self.assertIn('**Carol** & **Dave** with 42 KC (tie)', fields['Recent Winners'])
        self.assertNotIn('Empty', fields['Previous BOTW Winners'])
        self.assertEqual(fields['Previous SOTW Winners'].count('\n'), 4)  # five, excluding the recent one
        self.assertNotIn('Skill 7', fields['Previous SOTW Winners'])
        self.assertIn('Skill 2', fields['Previous SOTW Winners'])
        self.assertIn('bob\\_', fields['Previous SOTW Winners'])  # markdown escaped
        # Equal win counts share a rank; the most recent winner is listed first.
        self.assertEqual(fields['Most SOTW Wins'], '1. **Alice** · 4 wins\n1. **bob\\_** · 4 wins')
        # case-insensitive, latest spelling; tied winners each get a win
        self.assertEqual(fields['Most BOTW Wins'], '1. **Carol** · 2 wins\n2. **Dave** · 1 win')
        self.assertLess(len(embed), 6000)

    async def test_commands_staff_only(self):
        interaction = SimpleNamespace(guild_id=1, channel_id=55, user=SimpleNamespace(roles=[]),
                                      response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        await self.cog.setup.callback(self.cog, interaction)
        self.assertEqual(self.cog.store.board(), (None, None))
        interaction.user.roles = [SimpleNamespace(id=STAFF_ROLE_ID)]
        await self.cog.setup.callback(self.cog, interaction)
        self.assertEqual(self.cog.store.board(), (55, 900))
        self.assertFalse(self.channel.send.call_args.kwargs['allowed_mentions'].everyone)


if __name__ == '__main__':
    unittest.main()
