import importlib.util
import os
import tempfile
import unittest
from unittest.mock import AsyncMock
from types import SimpleNamespace

import discord
from discord.ext import commands

from cogs.community import Community
from cogs.moderation import Moderation


class BotStartupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous_directory = os.getcwd()
        self.directory = tempfile.TemporaryDirectory()
        os.chdir(self.directory.name)
        self.bot = commands.Bot(command_prefix='.', intents=discord.Intents.none())
        await self.bot.__aenter__()
        self.cog = Community(self.bot)
        await self.bot.add_cog(self.cog)
        await self.bot.add_cog(Moderation(self.bot))

    async def asyncTearDown(self):
        await self.bot.close()
        os.chdir(self.previous_directory)
        self.directory.cleanup()

    async def test_commands_load_without_google_packages_or_credentials(self):
        self.assertIsNone(importlib.util.find_spec('googleapiclient'))
        self.assertIsNotNone(self.bot.get_command('rankcalc'))
        self.assertIsNotNone(self.bot.tree.get_command('eventban'))
        for name in ['ranksheet', 'top_ehb', 'top_ehp', 'top_log', 'sotw', 'botw', 'raidbotw']:
            self.assertIsNone(self.bot.get_command(name))

    async def test_application_instructions_use_existing_rank_calculator(self):
        context = AsyncMock()
        await self.cog.apply.callback(self.cog, context)
        embed = context.send.call_args.kwargs['embed']
        self.assertIn('https://ironsgrotto.xyz', embed.description)
        self.assertNotIn('sheet', embed.description.lower())

    async def test_submission_review_preserves_both_outcomes(self):
        moderation = self.bot.get_cog('Moderation')
        user = SimpleNamespace(bot=False, roles=[SimpleNamespace(name='Owner')])
        for emoji, outcome in [('✅', 'accepted'), ('❌', 'denied')]:
            message = SimpleNamespace(
                channel=SimpleNamespace(id=moderation.target_channel_id),
                delete=AsyncMock(), author=SimpleNamespace(send=AsyncMock()),
            )
            await moderation.on_reaction_add(SimpleNamespace(message=message, emoji=emoji), user)
            message.delete.assert_awaited_once()
            message.author.send.assert_awaited_once_with(f'Your submission was {outcome}.')

    async def test_rankcalc_sends_current_steps_and_screenshot_in_one_message(self):
        context = AsyncMock()
        async def inspect_message(**kwargs):
            for image in kwargs['files']:
                self.assertEqual(image.fp.read(8), b'\x89PNG\r\n\x1a\n')
        context.send.side_effect = inspect_message
        await self.cog.rankcalc.callback(self.cog, context)
        context.send.assert_awaited_once()
        embed, note = context.send.call_args.kwargs['embeds']
        for text in ['Apply for Rank', 'Accounts', 'New Account', 'Plugin Hub',
                     'Token', 'Join Irons Grotto', 'Collection Log']:
            self.assertIn(text, embed.description)
        self.assertNotIn('TempleOSRS', embed.description)
        self.assertEqual(embed.image.url, 'attachment://collection-log-sync.png')
        self.assertEqual(note.title, 'Note: Event Management')
        for text in ['XP Updater', 'TempleOSRS', 'Wise Old Man']:
            self.assertIn(text, note.description)
        self.assertEqual(note.image.url, 'attachment://event-xp-updater.png')


if __name__ == '__main__':
    unittest.main()
