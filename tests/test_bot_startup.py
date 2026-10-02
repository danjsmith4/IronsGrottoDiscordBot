import importlib.util
import os
import tempfile
import unittest
from unittest.mock import AsyncMock

import discord
from discord.ext import commands

from bot_commands import BotCommands


class BotStartupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous_directory = os.getcwd()
        self.directory = tempfile.TemporaryDirectory()
        os.chdir(self.directory.name)
        self.bot = commands.Bot(command_prefix='.', intents=discord.Intents.none())
        self.cog = BotCommands(self.bot)
        await self.bot.add_cog(self.cog)

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


if __name__ == '__main__':
    unittest.main()
