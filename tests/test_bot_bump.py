import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.community import Community
from config import BUMP_CHANNEL_ID, STAFF_ROLE_ID
from storage import BumpStore


class BumpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'bump.sqlite3')
        self.bot = MagicMock()
        self.channel = MagicMock()
        self.channel.send = AsyncMock(return_value=SimpleNamespace(id=123))
        self.channel.get_partial_message.return_value.edit = AsyncMock()
        self.bot.get_channel.return_value = self.channel
        with patch('cogs.community.BumpStore', return_value=BumpStore(self.path)):
            self.cog = Community(self.bot)

    async def asyncTearDown(self):
        self.cog.bump_view.stop()
        self.directory.cleanup()

    def interaction(self, role=STAFF_ROLE_ID, message_id=123):
        return SimpleNamespace(
            guild_id=1, channel_id=BUMP_CHANNEL_ID, channel=self.channel,
            user=SimpleNamespace(id=42, roles=[SimpleNamespace(id=role)]),
            message=SimpleNamespace(id=message_id),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    async def test_one_ping_until_done_even_after_reopening(self):
        await asyncio.gather(*(self.cog.send_bump_if_due() for _ in range(3)))
        self.cog.bump_store = BumpStore(self.path)
        await self.cog.send_bump_if_due()
        self.channel.send.assert_awaited_once()
        mentions = self.channel.send.call_args.kwargs['allowed_mentions']
        self.assertEqual([role.id for role in mentions.roles], [STAFF_ROLE_ID])
        self.assertFalse(mentions.everyone)
        self.assertTrue(self.cog.bump_view.is_persistent())

    async def test_done_waits_four_hours_and_rejects_stale_button(self):
        await self.cog.send_bump_if_due()
        with patch('cogs.community.time.time', return_value=1000):
            await self.cog.complete_bump(self.interaction(), from_button=True)
        self.assertEqual(BumpStore(self.path).read()['next_due'], 15400)
        await self.cog.complete_bump(self.interaction(), from_button=True)
        self.assertEqual(self.cog.bump_store.read()['next_due'], 15400)
        with patch('cogs.community.time.time', return_value=15399):
            await self.cog.send_bump_if_due()
        self.channel.send.assert_awaited_once()
        with patch('cogs.community.time.time', return_value=15400):
            await self.cog.send_bump_if_due()
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_nonstaff_cannot_reset_timer(self):
        interaction = self.interaction(role=999)
        await self.cog.complete_bump(interaction)
        interaction.response.send_message.assert_awaited_once()
        self.assertEqual(self.cog.bump_store.read()['next_due'], 0)

    async def test_pause_survives_restart_and_resume_sends(self):
        await self.cog.bump.callback(self.cog, self.interaction(), 'pause')
        self.cog.bump_store = BumpStore(self.path)
        await self.cog.send_bump_if_due()
        self.channel.send.assert_not_awaited()
        await self.cog.bump.callback(self.cog, self.interaction(), 'resume')
        await self.cog.send_bump_if_due()
        self.channel.send.assert_awaited_once()

    async def test_failed_send_can_retry(self):
        self.channel.send.side_effect = RuntimeError('network unavailable')
        with self.assertRaises(RuntimeError):
            await self.cog.send_bump_if_due()
        self.assertIsNone(self.cog.bump_store.read()['message_id'])
        self.channel.send.side_effect = None
        await self.cog.send_bump_if_due()
        self.assertEqual(self.cog.bump_store.read()['message_id'], 123)
