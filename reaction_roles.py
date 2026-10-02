import discord
from dotenv import load_dotenv
import os
import sqlite3

load_dotenv()

ROLE_REACTIONS = {
    '<:olm:1011385799167721562>': int(os.getenv('OLM_ROLE_ID')),
    '<:theatre:1273727700141477970>': int(os.getenv('THEATRE_ROLE_ID')),
    '<:cm:1011384808003338250>': int(os.getenv('CM_ROLE_ID')),
    '<:hmt:1011384615438647316>': int(os.getenv('HMT_ROLE_ID')),
    '🪦': int(os.getenv('TOMB_ROLE_ID')),
    '<:nex:1011386572240855100>': int(os.getenv('NEX_ROLE_ID')),
    '<:CA:1011386555346210876>': int(os.getenv('CA_ROLE_ID')),
    '<:zalcano:1011386613550555157>': int(os.getenv('ZALCANO_ROLE_ID')),
    '<:BA:1011385814254633130>': int(os.getenv('BA_ROLE_ID')),
    '🌋': int(os.getenv('VOLCANIC_ROLE_ID')),
    '🌀': int(os.getenv('TEMPOROSS_ROLE_ID')),
    '<:other:1011386588397305946>': int(os.getenv('OTHER_ROLE_ID'))
}

MESSAGE_ID_KEY = 'reaction_role_message_id'

def get_message_id_from_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS bot_data (key TEXT PRIMARY KEY, value TEXT)')
    cursor.execute('SELECT value FROM bot_data WHERE key = ?', (MESSAGE_ID_KEY,))
    result = cursor.fetchone()
    conn.close()
    if result:
        print(f"Message ID retrieved from DB: {result[0]}")
        return int(result[0])
    else:
        print("No message ID found in DB.")
        return None

def save_message_id_to_db(message_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS bot_data (key TEXT PRIMARY KEY, value TEXT)')
    cursor.execute('INSERT OR REPLACE INTO bot_data (key, value) VALUES (?, ?)', (MESSAGE_ID_KEY, str(message_id)))
    conn.commit()
    conn.close()

async def setup_reaction_role_message(bot):
    channel = bot.get_channel(int(os.getenv('ROLE_CHANNEL_ID')))
    if not channel:
        print("Channel not found.")
        return

    message_id = get_message_id_from_db()

    if message_id:
        try:
            message = await channel.fetch_message(message_id)
            print(f"Loaded existing reaction role message with ID: {message_id}")
            if len(message.reactions) != len(ROLE_REACTIONS):
                await message.clear_reactions()
                for emoji in ROLE_REACTIONS:
                    await message.add_reaction(emoji)
            return message
        except discord.NotFound:
            print(f"Message with ID {message_id} not found. Creating new message.")
            message_id = None
        except Exception as e:
            print(f"An error occured while trying to retrieve the old message: {e}")
            message_id = None

    if not message_id:
        embed = discord.Embed(
            title="Looking for Group - Reaction Role",
            description=(
                "Welcome to the Looking for Group reaction channel!\n\n"
                "This is another way to form groups together with your fellow clan mates!\n\n"
                "<:hmm:1011388883809882123>: **What should I do?**\n"
                "Great question! Below this post, you will notice different reactions. Each reaction will represent a different group you can join and get reactions for. You can react to as many, or as little, groups as you'd like!\n\n"
                "<:olm:1011385799167721562>: Chambers of Xeric\n"
                "<:theatre:1273727700141477970>: Theatre of Blood\n"
                "<:cm:1011384808003338250>: CM Chambers\n"
                "<:hmt:1011384615438647316>: HM Theatre\n"
                "🪦 Tombs of Amascut\n"
                "<:nex:1011386572240855100>: Nex\n"
                "<:CA:1011386555346210876>: Combat Achievement Tasks\n"
                "<:zalcano:1011386613550555157>: Zalcano\n"
                "<:BA:1011385814254633130>: Barbarian Assault\n"
                "🌋 Volcanic Mine\n"
                "🌀 Tempoross\n"
                "<:other:1011386588397305946>: Other Minigames\n\n"
                ":notifications: **How will I get notified?**\n"
                "Once you react to this post, you will be added to that group. You will also gain access to the looking-for-group channel. You will receive pings from this channel whenever a team is actively looking to form a group.\n\n"
                ":killtheping: **How do I ping others in my group?**\n"
                "While in the looking-for-group channel, you can @role others who have reacted to this post. Simply tag your group whenever you are looking to form a party. EX) @role +2 for cox!\n\n"
                ":sob: **What if I no longer want to receive pings from a group?**\n"
                "Simply un-react from whichever group(s) you no longer wish to be a part of!"
            ),
            color=discord.Color.blue()
        )
        message = await channel.send(embed=embed)
        save_message_id_to_db(message.id)
        for emoji in ROLE_REACTIONS:
            await message.add_reaction(emoji)
        print(f"New reaction role message created with ID: {message.id}")

async def handle_reaction_add(reaction, user, bot):
    if user == bot.user:
        return

    message_id = get_message_id_from_db()
    print(f"Reacted message ID: {reaction.message.id}, Stored message ID: {message_id}") # Check if IDs match
    if reaction.message.id == message_id and reaction.message.embeds:
        role_id = ROLE_REACTIONS.get(str(reaction.emoji))
        if role_id:
            role = discord.utils.get(reaction.message.guild.roles, id=role_id)
            if role:
                print(f"Role retrieved: {role.name}") # Check role retrieval
                member = reaction.message.guild.get_member(user.id)
                if member:
                    try:
                        await member.add_roles(role)
                        print(f"Assigned {role.name} to {user.name}")
                    except discord.Forbidden:
                        print(f"Error: Bot lacks permissions to assign {role.name}.")
                    except Exception as e:
                        print(f"An unexpected error occured: {e}")
            else:
                print("Role not found.")
        else:
            print("Role ID not found in ROLE_REACTIONS or invalid message.")
    else:
        print("Message ID mismatch or message has no embed.") #check if message ID is mismatch

async def handle_reaction_remove(reaction, user, bot):
    if user == bot.user:
        return

    message_id = get_message_id_from_db()
    if reaction.message.id == message_id and reaction.message.embeds:
        role_id = ROLE_REACTIONS.get(str(reaction.emoji))
        if role_id:
            role = discord.utils.get(reaction.message.guild.roles, id=role_id)
            if role:
                member = reaction.message.guild.get_member(user.id)
                if member:
                    await member.remove_roles(role)
                    print(f"Removed {role.name} from {user.name}")