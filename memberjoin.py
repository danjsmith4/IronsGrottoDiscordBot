import discord
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

WELCOME_CHANNEL_ID = int(os.getenv('WELCOME_CHANNEL_ID'))
HOW_TO_APPLY_CHANNEL_ID = int(os.getenv('HOW_TO_APPLY_CHANNEL_ID'))
RANK_REQUESTS_CHANNEL_ID = int(os.getenv('RANK_REQUESTS_CHANNEL_ID'))
DROPS_CHANNEL_ID = int(os.getenv('DROPS_CHANNEL_ID'))
WELCOME2_CHANNEL_ID = int(os.getenv('WELCOME2_CHANNEL_ID'))
ROLE_CHANNEL_ID = int(os.getenv('ROLE_CHANNEL_ID'))

async def send_welcome_message(member, bot):
    # Get the welcome channel using the ID
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title=f"Welcome to Irons Grotto, {member.name}!",
            description=(
                f"Please have a look around at all the things we offer, but your first stop should be to our "
                f"<#{HOW_TO_APPLY_CHANNEL_ID}> channel, where you can apply for a rank.\n\n"
                f"Next, be sure to check out the <#{WELCOME2_CHANNEL_ID}> channel for more information.\n\n"
                f"Lastly, if you get any cool drops or items, post them in the <#{DROPS_CHANNEL_ID}> channel—we'd love to see them!"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Welcome {member.name} to Grotto <3!")  # Optional footer to add extra welcome text
        await channel.send(content=f"{member.mention}", embed=embed)
