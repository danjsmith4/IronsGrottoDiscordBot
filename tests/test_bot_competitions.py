import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs.competitions import Competitions, build_embed, is_weekly, member_keys, standings
from config import STAFF_ROLE_ID
from storage import CompetitionStore

NOW = 2_000_000
HOUR = 3600
FILLER = [f'Member {i}' for i in range(25)]  # keeps the member list above the sanity minimum


def comp(comp_id, name, *, status=2, ended=NOW - 3 * HOUR, team=0):
    return {'id': comp_id, 'name': name, 'status': status, 'end_date_unix': ended, 'team_competition': team,
            'skill': 'Thing'}


def info(comp_id, *, skill, ended=NOW - 3 * HOUR, participants=None):
    return {'data': {'info': {'id': comp_id, 'skill_competition': int(skill), 'skill': 'Thing', 'end_date_unix': ended},
                     'participants': participants if participants is not None else [
                         {'username': 'Former Champ', 'player_name_with_capitalization': None, 'gain': 900},
                         {'username': f'winner{comp_id}', 'player_name_with_capitalization': f'Winner{comp_id}',
                          'gain': 500},
                         {'username': 'Second', 'player_name_with_capitalization': None, 'gain': 10}]}}


def keys(*names):
    return {CompetitionStore.name_key(n) for n in names + tuple(FILLER)}


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
        # "Former Champ" beat everyone but has left the clan.
        self.members = ['Winner1', 'winner2', 'Winner7', 'Second'] + FILLER
        self.calls = []

        async def fetch(endpoint, item_id):
            self.calls.append((endpoint, item_id))
            if endpoint == 'groupmembers.php':
                return self.members
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

    def edit(self):
        return self.channel.get_partial_message.return_value.edit

    def board_fields(self):
        call = self.edit().call_args or self.channel.send.call_args
        return {f.name: f.value for f in call.kwargs['embed'].fields}

    def test_weekly_name_matching(self):
        for name in ['Vorkath BOTW', 'Sotw Prayer', 'SOTW - Smithing', 'Hydra BotW', 'Theatre of Blood Hard Mode BOT']:
            self.assertTrue(is_weekly({'name': name}), name)
        for name in ['Herb Lore', 'Bingo Nex', '12 Dos Cox', 'Botwick']:
            self.assertFalse(is_weekly({'name': name}), name)
        self.assertFalse(is_weekly({'name': 'Nex BOTW', 'team_competition': 1}))

    def test_standings(self):
        rows = [{'username': 'low', 'gain': 5}, {'username': 'top guy', 'player_name_with_capitalization': 'Top Guy',
                                                 'gain': '700'}, {'username': 'zero', 'gain': 0}, {'gain': 9}]
        self.assertEqual(standings(rows), [('low', 5), ('Top Guy', 700)])
        self.assertEqual(standings({'1': {'username': 'a', 'gain': 3}}), [('a', 3)])
        self.assertEqual(standings(None), [])

    def test_member_list_sanity(self):
        self.assertIn('iron zeusa', member_keys(['Iron_Zeusa'] + FILLER))
        for bad in [[], ['Only', 'A', 'Few'], {'error': 'x'}.get('data'), 'oops']:
            with self.assertRaises(ValueError):
                member_keys(bad)

    async def test_records_only_finished_weekly_comps_after_grace(self):
        self.cog.store.set_board(55, None)
        self.assertEqual(await self.cog.sync(), 2)
        self.assertEqual(sorted(self.cog.store.known_ids()), [1, 2])
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.cog.store.board()[:2], (55, 900))

    async def test_competitions_won_by_former_members_are_hidden(self):
        self.details[2] = info(2, skill=False, participants=[
            {'username': 'winner2', 'player_name_with_capitalization': 'Winner2', 'gain': 500},
            {'username': 'Second', 'gain': 10}])
        self.cog.store.set_board(55, None)
        await self.cog.sync()
        fields = self.board_fields()
        text = '\n'.join(fields.values())
        # Comp 1 was won by "Former Champ", who left; nobody else is credited with that win.
        self.assertNotIn('Former Champ', text)
        self.assertNotIn('Winner1', text)
        self.assertNotIn('Construction SOTW', text)
        self.assertEqual(fields['Most SOTW Wins'], 'None yet.')
        self.assertIn('**Winner2** with 500 KC', fields['Recent Winners'])  # Temple's capitalisation
        self.assertEqual(fields['Most BOTW Wins'], '1. **Winner2** · 1 win')

    async def test_board_redraws_when_membership_changes(self):
        self.cog.store.set_board(55, None)
        await self.cog.sync()
        await self.cog.sync()
        self.edit().assert_not_awaited()  # nothing changed, Discord untouched
        self.members.append('Former Champ')  # rejoined: their wins come back
        await self.cog.sync()
        self.edit().assert_awaited_once()
        self.assertIn('**Former Champ** with 900 XP', self.board_fields()['Recent Winners'])
        self.assertEqual(self.board_fields()['Most SOTW Wins'], '1. **Former Champ** · 1 win')
        self.assertEqual(self.board_fields()['Most BOTW Wins'], '1. **Former Champ** · 1 win')
        self.members.remove('Former Champ')  # left again
        await self.cog.sync()
        self.assertEqual(self.board_fields()['Recent Winners'], 'No winners yet.')

    async def test_bad_member_list_leaves_board_alone(self):
        self.cog.store.set_board(55, None)
        self.members = []
        with self.assertRaises(ValueError):
            await self.cog.sync()
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.cog.store.known_ids(), set())

    async def test_no_refetch_of_known_competitions(self):
        await self.cog.sync()
        self.calls.clear()
        await self.cog.sync()
        self.assertEqual(self.calls, [('groupmembers.php', 241), ('group_competitions.php', 241)])

    async def test_deleted_board_is_reposted(self):
        self.cog.store.set_board(55, 800)
        self.edit().side_effect = discord.NotFound(MagicMock(status=404), 'gone')
        await self.cog.sync(force=True)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.cog.store.board()[:2], (55, 900))

    async def test_failed_competition_retried_later(self):
        good = self.details.pop(2)
        await self.cog.sync()
        self.assertEqual(self.cog.store.known_ids(), {1})
        self.details[2] = good
        await self.cog.sync()
        self.assertEqual(self.cog.store.known_ids(), {1, 2})

    def test_upgrade_from_winners_only_database(self):
        path = str(Path(self.directory.name) / 'old.sqlite3')
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute('CREATE TABLE competitions (id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, metric TEXT NOT NULL, ended INTEGER NOT NULL, gain INTEGER)')
            conn.execute('CREATE TABLE competition_winners (competition_id INTEGER NOT NULL, position INTEGER NOT NULL, name TEXT NOT NULL, name_key TEXT NOT NULL, PRIMARY KEY (competition_id, position))')
            conn.execute('CREATE TABLE board (id INTEGER PRIMARY KEY, channel_id INTEGER, message_id INTEGER)')
            conn.execute("INSERT INTO competitions VALUES (1, 'Old SOTW', 'SOTW', 'x', 5, 10)")
            conn.execute('INSERT INTO board VALUES (1, 55, 800)')
        store = CompetitionStore(path)
        self.assertEqual(store.known_ids(), set())  # refetched with full standings
        self.assertEqual(store.board(), (55, 800, None))  # existing board message kept
        CompetitionStore(path)  # reopening is harmless

    def test_board_sections(self):
        store = self.cog.store
        for i in range(8):  # SOTW winners alternate, newest last
            store.record(100 + i, f'Skill {i} SOTW', 'SOTW', 'Skill', 1000 + i,
                         [('Alice' if i % 2 else 'bob_', 1000 * (i + 1)), ('Gone', 1)])
        store.record(108, 'Leaver Won SOTW', 'SOTW', 'Skill', 2000, [('Gone', 50), ('Alice', 49)])
        store.record(200, 'Zulrah BOTW', 'BOTW', 'Zulrah', 5000, [('Carol', 42), ('Dave', 42), ('Gone', 41)])
        store.record(204, 'Shared Top BOTW', 'BOTW', 'Obor', 25, [('Carol', 5), ('Gone', 5), ('Dave', 4)])
        store.record(201, 'Old BOTW', 'BOTW', 'Vorkath', 10, [('carol', 7)])
        store.record(202, 'Empty BOTW', 'BOTW', 'Obor', 20, [])
        store.record(203, 'Gone BOTW', 'BOTW', 'Obor', 30, [('Gone', 99)])
        embed = build_embed(store, keys('alice', 'BOB_', 'Carol', 'dave'))
        fields = {f.name: f.value for f in embed.fields}
        self.assertEqual([f.name for f in embed.fields], [
            'Recent Winners', 'Previous SOTW Winners', 'Previous BOTW Winners', 'Most SOTW Wins', 'Most BOTW Wins'])
        self.assertNotIn('Gone', ''.join(fields.values()))
        self.assertNotIn('Leaver Won', ''.join(fields.values()))  # won by a former member
        self.assertIn('Skill 7 SOTW', fields['Recent Winners'])
        self.assertIn('**Alice** with 8,000 XP', fields['Recent Winners'])
        self.assertIn('**Carol** & **Dave** with 42 KC (tie)', fields['Recent Winners'])
        self.assertEqual(fields['Previous SOTW Winners'].count('\n'), 4)  # five, excluding the recent one
        self.assertNotIn('Skill 7', fields['Previous SOTW Winners'])
        self.assertIn('bob\\_', fields['Previous SOTW Winners'])  # markdown escaped
        self.assertNotIn('Empty', fields['Previous BOTW Winners'])
        # Equal win counts share a rank; the most recent winner is listed first.
        self.assertEqual(fields['Most SOTW Wins'], '1. **Alice** · 4 wins\n1. **bob\\_** · 4 wins')
        # case-insensitive, latest spelling; members tied with a former member still get the win
        self.assertEqual(fields['Most BOTW Wins'], '1. **Carol** · 3 wins\n2. **Dave** · 1 win')
        self.assertLess(len(embed), 6000)

    async def test_commands_staff_only(self):
        interaction = SimpleNamespace(guild_id=1, channel_id=55, user=SimpleNamespace(roles=[]),
                                      response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
                                      followup=SimpleNamespace(send=AsyncMock()))
        await self.cog.setup.callback(self.cog, interaction)
        self.assertEqual(self.cog.store.board()[:2], (None, None))
        interaction.user.roles = [SimpleNamespace(id=STAFF_ROLE_ID)]
        await self.cog.setup.callback(self.cog, interaction)
        self.assertEqual(self.cog.store.board()[:2], (55, 900))
        self.assertFalse(self.channel.send.call_args.kwargs['allowed_mentions'].everyone)


if __name__ == '__main__':
    unittest.main()
