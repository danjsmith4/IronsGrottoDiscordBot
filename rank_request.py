import discord
from discord.ext import commands
import re  # For detecting Google Sheets links

class GoogleSheetResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.specific_channel_id = 1135112081205633105  # Replace with your specific channel ID
        self.role_to_tag_id = 697877518493155387      # Replace with your role ID

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore bot messages
        if message.author.bot:
            return

        # Check if the message is in the specific channel
        if message.channel.id != self.specific_channel_id:
            return

        # Regex to detect Google Sheets links
        google_sheet_regex = r"https://docs\.google\.com/spreadsheets/d/[\w-]+"
        if re.search(google_sheet_regex, message.content):
            # Get the role to tag
            role_to_tag = message.guild.get_role(self.role_to_tag_id)

            if role_to_tag is None:
                # Log a warning if the role is not found
                print(f"Role with ID {self.role_to_tag_id} not found.")
                return  # Exit if the role isn't found

            # Create a nicely formatted response
            embed = discord.Embed(
                title="Rank Sheet Detected",
                description=(
                    "Thanks for submitting your sheet! Someone will check and adjust the rank shortly.\n\n"
                    "To ensure that everyone can view the Google Sheet properly, please make sure it's set to 'Anyone with the link' and not restricted. "
                    "To do this:\n"
                    "1. Open your Google Sheet\n"
                    "2. Click on the 'Share' button at the top right\n"
                    "3. Under 'Get Link', change the setting to 'Anyone with the link'\n"
                    "4. Make sure the permission is set to 'Viewer' to allow others to see it without editing.\n\n"
                    "If you need help with this, please reach out!"
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text="Please make sure your sheet is complete and accurate.")
            embed.set_thumbnail(url="https://i.imgur.com/QjxECj5.gif")

            # Send the role ping and the embed
            await message.reply(content=role_to_tag.mention, embed=embed, mention_author=False)

            # Now send the image at the bottom of the message
            with open('discord.png', 'rb') as file:
                await message.channel.send(file=discord.File(file, 'discord.png'))

# Add the cog to the bot
def setup(bot):
    bot.add_cog(GoogleSheetResponder(bot))
