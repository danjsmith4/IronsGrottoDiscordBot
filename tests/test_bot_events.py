import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.events import Events, parse_date
from config import STAFF_ROLE_ID, EVENT_INTERVAL_SECONDS
from storage import EventStore


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'events.sqlite3')
        self.bot = MagicMock()
        self.bot.user.id = 50
        self.channel = MagicMock()
        self.channel.guild.id = 1
        self.channel.send = AsyncMock(return_value=SimpleNamespace(id=123))
        self.latest = []
        async def history(**kwargs):
            for message in self.latest:
                yield message
        self.channel.history = history
        self.bot.get_channel.return_value = self.channel
        with patch('cogs.events.EventStore', return_value=EventStore(self.path)):
            self.cog = Events(self.bot)
        self.clock = patch('cogs.events.time.time', return_value=1000)
        self.clock.start()

    async def asyncTearDown(self):
        self.clock.stop()
        self.directory.cleanup()

    def interaction(self, role=STAFF_ROLE_ID):
        return SimpleNamespace(guild_id=1, user=SimpleNamespace(roles=[SimpleNamespace(id=role)]),
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))

    def add_event(self, starts=0, ends=100000, guild=1):
        return self.cog.store.add(guild, 'Event', 'Join in!', starts, ends)

    async def test_optional_start_and_inclusive_end(self):
        interaction = self.interaction()
        await self.cog.add.callback(self.cog, interaction, 'Event', 'Details', '2027-01-01')
        row = self.cog.store.list(1, 1000, active=True)[0]
        self.assertEqual(row['starts'], 1000)
        self.assertEqual(row['ends'], parse_date('2027-01-02'))
        self.assertEqual(parse_date('2026-03-08', end=True) - parse_date('2026-03-08'), 23 * 3600)
        self.assertEqual(parse_date('2026-11-01', end=True) - parse_date('2026-11-01'), 25 * 3600)

    async def test_invalid_dates_rejected(self):
        for end, start in [('bad', None), ('1960-01-01', None), ('2027-01-01', '2027-01-03')]:
            await self.cog.add.callback(self.cog, self.interaction(), 'Event', 'Details', end, start)
        self.assertEqual(self.cog.store.list(1, 0), [])

    async def test_random_selection_only_contains_active_events(self):
        good = self.add_event()
        second = self.add_event()
        self.add_event(starts=2000)
        self.add_event(ends=1000)
        self.add_event(guild=2)
        with patch('cogs.events.random.choice', side_effect=lambda rows: rows[0]) as choice:
            await self.cog.announce_if_due()
        self.assertEqual([row['id'] for row in choice.call_args.args[0]], [good, second])
        self.channel.send.assert_awaited_once()
        self.assertFalse(self.channel.send.call_args.kwargs['allowed_mentions'].everyone)

    async def test_eight_hour_schedule_survives_restart(self):
        self.add_event()
        await self.cog.announce_if_due()
        self.cog.store = EventStore(self.path)
        with patch('cogs.events.time.time', return_value=1000 + EVENT_INTERVAL_SECONDS - 1):
            await self.cog.announce_if_due()
        self.channel.send.assert_awaited_once()

    async def test_latest_announcement_is_edited_not_reposted(self):
        self.add_event()
        self.cog.store.announced(1, 0, 123)
        message = SimpleNamespace(id=123, author=SimpleNamespace(id=50), embeds=[], edit=AsyncMock())
        self.latest = [message]
        await self.cog.announce_if_due()
        message.edit.assert_awaited_once()
        self.channel.send.assert_not_awaited()

    async def test_conversation_after_announcement_allows_new_post(self):
        self.add_event()
        self.cog.store.announced(1, 0, 123)
        self.latest = [SimpleNamespace(id=456, author=SimpleNamespace(id=7), embeds=[])]
        await self.cog.announce_if_due()
        self.channel.send.assert_awaited_once()

    async def test_empty_or_expired_pool_never_posts(self):
        self.add_event(ends=999)
        await self.cog.announce_if_due()
        self.channel.send.assert_not_awaited()

    async def test_expired_latest_announcement_is_cleared(self):
        self.add_event(ends=999)
        self.cog.store.announced(1, 0, 123)
        message = SimpleNamespace(id=123, author=SimpleNamespace(id=50), embeds=[], edit=AsyncMock())
        self.latest = [message]
        await self.cog.announce_if_due()
        self.assertIsNone(message.edit.call_args.kwargs['embed'])
        self.channel.send.assert_not_awaited()

    async def test_all_commands_require_staff(self):
        interaction = self.interaction(role=9)
        event_id = self.add_event()
        await self.cog.add.callback(self.cog, interaction, 'Bad', 'Details', '2027-01-01')
        await self.cog.remove.callback(self.cog, interaction, event_id)
        await self.cog.list_events.callback(self.cog, interaction)
        self.assertEqual(interaction.response.send_message.await_count, 3)
        self.assertEqual(len(self.cog.store.list(1, 1000)), 1)

    async def test_removal_is_guild_scoped(self):
        event_id = self.add_event(guild=2)
        self.assertEqual(self.cog.store.remove(1, event_id), 0)
        self.assertEqual(self.cog.store.remove(2, event_id), 1)

    async def test_failed_send_does_not_advance_schedule(self):
        self.add_event()
        self.channel.send.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            await self.cog.announce_if_due()
        self.assertEqual(self.cog.store.schedule(1), (0, None))
