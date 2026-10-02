import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from imgur import allowed_url
from leaderboardcommands import LeaderboardCommands, lb_update
from main import GrottoBot
from memberjoin import send_welcome_message


class LeaderboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous_directory = os.getcwd()
        self.directory = tempfile.TemporaryDirectory()
        os.chdir(self.directory.name)
        self.bot = MagicMock()
        self.channel = MagicMock()
        self.channel.send = AsyncMock(return_value=SimpleNamespace(id=123))
        self.channel.get_partial_message.return_value.edit = AsyncMock()
        self.bot.get_channel.return_value = self.channel
        self.cog = LeaderboardCommands(self.bot)

    async def asyncTearDown(self):
        await self.cog.cog_unload()
        os.chdir(self.previous_directory)
        self.directory.cleanup()

    async def test_submission_sorts_and_replaces_in_one_commit(self):
        self.cog.save_entry('Zulrah', 'Alice', '1:30')
        statements = []
        self.cog.conn.set_trace_callback(statements.append)
        self.cog.save_entry('Zulrah', 'Bob', '1:20')
        self.assertEqual(sum(sql == 'COMMIT' for sql in statements), 1)
        self.cog.save_entry('Zulrah', 'Alice', '1:10')
        self.assertEqual([row[0] for row in self.cog.get_all_leaderboard_entries('Zulrah')], ['Alice', 'Bob'])

    async def test_failed_rank_update_preserves_previous_pb(self):
        self.cog.save_entry('Zulrah', 'Alice', '1:30')
        self.cog.conn.execute("CREATE TRIGGER fail_rank BEFORE UPDATE ON leaderboards BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.cog.save_entry('Zulrah', 'Alice', '1:20')
        self.assertEqual(self.cog.get_all_leaderboard_entries('Zulrah'), [('Alice', '1:30', '')])

    async def test_legacy_duplicate_names_can_be_ranked_without_data_loss(self):
        self.cog.conn.executemany(
            'INSERT INTO leaderboards (boss_name, user, time) VALUES (?, ?, ?)',
            [('Zulrah', 'Alice', '1:30'), ('Zulrah', 'Alice', '1:20')],
        )
        self.cog.conn.commit()
        self.cog.re_rank_leaderboard('Zulrah')
        self.assertEqual(self.cog.conn.execute('SELECT rank FROM leaderboards ORDER BY rank').fetchall(), [(1,), (2,)])

    async def test_invalid_input_never_replaces_good_data(self):
        self.cog.save_entry('Zulrah', 'Alice', '1:30')
        for value in ['nan', 'inf', '-5', '0', '1:99', '-1:59', 'garbage', '1:2:1000']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.cog.save_entry('Zulrah', 'Alice', value)
        self.assertEqual(self.cog.get_all_leaderboard_entries('Zulrah')[0][1], '1:30')

    async def test_wave_ranking_and_removal_keep_contiguous_ranks(self):
        self.cog.save_entry('Doom of Mokhaiotl', 'Alice', '12')
        self.cog.save_entry('Doom of Mokhaiotl', 'Bob', '14')
        self.assertEqual(self.cog.get_top_3_leaderboard('Doom of Mokhaiotl')[0][0], 'Bob')
        deleted, bosses = self.cog.remove_entries('Bob')
        self.assertEqual((deleted, bosses), (1, ['Doom of Mokhaiotl']))
        self.assertEqual(self.cog.conn.execute('SELECT rank FROM leaderboards').fetchall(), [(1,)])

    async def test_concurrent_refreshes_send_only_one_message(self):
        async def send(**kwargs):
            await asyncio.sleep(0)
            return SimpleNamespace(id=123)
        self.channel.send.side_effect = send
        await asyncio.gather(*(self.cog.update_specific_leaderboard(None, 'Zulrah') for _ in range(3)))
        self.channel.send.assert_awaited_once()

    async def test_unchanged_update_is_skipped_but_forced_refresh_edits(self):
        await self.cog.update_specific_leaderboard(None, 'Zulrah')
        await self.cog.update_specific_leaderboard(None, 'Zulrah')
        self.channel.get_partial_message.assert_not_called()
        await self.cog.update_specific_leaderboard(None, 'Zulrah', force=True)
        self.channel.get_partial_message.return_value.edit.assert_awaited_once()
        self.channel.fetch_message.assert_not_called()

    async def test_failed_json_replace_preserves_existing_file(self):
        Path('state.json').write_text('{"old": true}')
        with patch('leaderboardcommands.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.cog._save_json('state.json', {'new': True})
        self.assertEqual(json.loads(Path('state.json').read_text()), {'old': True})

    async def test_staff_update_defers_before_network_work(self):
        interaction = MagicMock()
        interaction.client.get_cog.return_value = self.cog
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        async def update(*args, **kwargs):
            interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        self.cog.update_specific_leaderboard = AsyncMock(side_effect=update)
        await lb_update.callback(interaction, 'zulrah', 'Alice', '1:20')
        interaction.followup.send.assert_awaited_once()


class WelcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_miss_fetches_channel_and_sends_welcome(self):
        member = SimpleNamespace(id=5, name='New member', mention='<@5>', guild=SimpleNamespace(id=1))
        channel = SimpleNamespace(guild=member.guild, send=AsyncMock())
        bot = SimpleNamespace(get_channel=lambda _: None, fetch_channel=AsyncMock(return_value=channel))
        settings = dict(WELCOME_CHANNEL_ID='2', HOW_TO_APPLY_CHANNEL_ID='3', WELCOME2_CHANNEL_ID='4', DROPS_CHANNEL_ID='6')
        with patch.dict(os.environ, settings, clear=True):
            await send_welcome_message(member, bot)
        bot.fetch_channel.assert_awaited_once_with(2)
        channel.send.assert_awaited_once()

    async def test_other_guild_cannot_receive_welcome(self):
        member = SimpleNamespace(id=5, guild=SimpleNamespace(id=1))
        channel = SimpleNamespace(guild=SimpleNamespace(id=9), send=AsyncMock())
        bot = SimpleNamespace(get_channel=lambda _: channel)
        with patch.dict(os.environ, {'WELCOME_CHANNEL_ID': '2'}, clear=True):
            await send_welcome_message(member, bot)
        channel.send.assert_not_awaited()


class LinkTests(unittest.TestCase):
    def test_domains_are_checked_as_hostnames(self):
        for url in ['https://imgur.com/a/123', 'https://i.imgur.com/a.png', 'www.gyazo.com/123']:
            self.assertTrue(allowed_url(url), url)
        for url in ['https://imgur.com.evil.example/x', 'https://example.com/imgur.com', 'https://imgur.com@example.com/x']:
            self.assertFalse(allowed_url(url), url)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnects_do_not_sync_commands_again(self):
        previous_directory = os.getcwd()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            os.chdir(directory)
            try:
                async with GrottoBot() as bot:
                    bot.tree.sync = AsyncMock(return_value=[])
                    await bot.setup_hook()
                    bot._connection.user = SimpleNamespace(id=1)
                    await bot.on_ready()
                    await bot.on_ready()
                    bot.tree.sync.assert_awaited_once()
                    self.assertIsNotNone(bot.tree.get_command('lb'))
                    self.assertIsNotNone(bot.tree.get_command('apply'))
            finally:
                os.chdir(previous_directory)
