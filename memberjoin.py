import logging
import os

import discord

logger = logging.getLogger(__name__)


def channel_id(name):
    try:
        value = int(os.environ[name])
        if value <= 0:
            raise ValueError
        return value
    except (KeyError, ValueError):
        raise ValueError(f'{name} must contain a valid Discord channel ID') from None


async def send_welcome_message(member, bot):
    welcome_id = channel_id('WELCOME_CHANNEL_ID')
    channel = bot.get_channel(welcome_id)
    if channel is None:
        channel = await bot.fetch_channel(welcome_id)
    if channel.guild.id != member.guild.id:
        logger.warning('Welcome channel %s belongs to a different guild; skipped member %s', welcome_id, member.id)
        return
    embed = discord.Embed(
        title=f'Welcome to Irons Grotto, {member.name}!',
        description=(
            'Please have a look around at all the things we offer, but your first stop should be to our '
            f"<#{channel_id('HOW_TO_APPLY_CHANNEL_ID')}> channel, where you can apply for a rank.\n\n"
            f"Next, be sure to check out the <#{channel_id('WELCOME2_CHANNEL_ID')}> channel for more information.\n\n"
            f"Lastly, if you get any cool drops or items, post them in the <#{channel_id('DROPS_CHANNEL_ID')}> "
            "channel - we'd love to see them!"
        ),
        color=discord.Color.green(),
    )
    embed.set_footer(text=f'Welcome {member.name} to Grotto <3!')
    await channel.send(content=member.mention, embed=embed)
    logger.info('Welcomed member %s in channel %s', member.id, welcome_id)
