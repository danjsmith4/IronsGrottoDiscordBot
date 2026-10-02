"""Environment settings and shared server configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'))


def channel_id(name, default=None):
    try:
        value = int(os.environ.get(name, default))
        if value <= 0:
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise ValueError(f'{name} must contain a valid Discord channel ID') from None


def bot_token():
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        raise RuntimeError('DISCORD_BOT_TOKEN is not configured')
    return token


def guild_id():
    return channel_id('GUILD_ID') if os.getenv('GUILD_ID') else None


def force_clear():
    return os.getenv('FORCE_CLEAR') == '1'


EVENT_BANNED_ROLE_NAME = os.getenv('EVENT_BANNED_ROLE_NAME', 'Event Banned')
EVENTBAN_LOG_CHANNEL_ID = int(os.getenv('EVENTBAN_LOG_CHANNEL_ID', '0'))
EVENTBAN_DB_PATH = os.getenv('EVENTBAN_DB_PATH', 'event_bans.sqlite3')
APPLY_ROLE_BY_DEFAULT = os.getenv('EVENTBAN_APPLY_ROLE_DEFAULT', 'true').lower() == 'true'
LEADERBOARD_DB_PATH = 'leaderboards.db'
MSG_IDS_PATH = 'leaderboard_messages.json'
HASHES_PATH = 'leaderboard_hashes.json'
LEADERBOARD_CHANNEL_ID = channel_id('LEADERBOARD_CHANNEL_ID', 1357210920882798763)
SUBMISSION_CHANNEL_ID = channel_id('SUBMISSION_CHANNEL_ID', 1357560551219396628)
SUBMISSION_GUIDELINES_CHANNEL_ID = channel_id('SUBMISSION_GUIDELINES_CHANNEL_ID', 1357560608635097229)
RANK_APPLICATION_CHANNEL_ID = channel_id('RANK_APPLICATION_CHANNEL_ID', 1135112081205633105)
DIARY_CHANNEL_ID = channel_id('DIARY_CHANNEL_ID', 1386920119619289210)
BINGO_DROPS_CHANNEL_ID = channel_id('BINGO_DROPS_CHANNEL_ID', 1399077840523104326)
STAFF_ROLE_ID = channel_id('STAFF_ROLE_ID', 829386451624001539)
BUMP_CHANNEL_ID = channel_id('BUMP_CHANNEL_ID', 697877519730213010)
BUMP_POST_URL = 'https://discord.com/channels/324132423636090880/1254535748502421564'
BUMP_INTERVAL_SECONDS = 4 * 60 * 60
OWNER_ROLE = os.getenv('OWNER_ROLE', 'Owner')
STAFF_ROLES = (OWNER_ROLE, os.getenv('DEPUTY_ROLE', 'Deputy Owner'))
WAVE_BOSSES = {'Doom of Mokhaiotl'}
INVITE_LINK = 'https://discord.gg/HPuwhhXnD5'
TEMPLE_LINK = 'https://templeosrs.com/groups/overview.php?id=241'
RANK_CALCULATOR_LINK = 'https://ironsgrotto.xyz'

BOSS_IMAGES = {'Alchemical Hydra': 'https://i.imgur.com/ABJ2QsO.png',
 'Amoxliatl': 'https://i.imgur.com/paHwkUF.png',
 'Araxxor': 'https://i.imgur.com/vFEON5R.png',
 'Chambers of Xeric CM 5-Man': 'https://i.imgur.com/nbAhM3s.png',
 'Chambers of Xeric CM Solo': 'https://i.imgur.com/FRr4gyR.png',
 'Chambers of Xeric CM Trio': 'https://i.imgur.com/5K1z9eb.png',
 'Chambers of Xeric Duo': 'https://tinypic.host/images/2025/04/04/duo-olm.png',
 'Chambers of Xeric Solo': 'https://i.imgur.com/JyhvZaS.png',
 'Chambers of Xeric Trio': 'https://tinypic.host/images/2025/04/04/olm-trio.png',
 'Corrupted Gauntlet': 'https://i.imgur.com/joKX3Pm.png',
 'Duke': 'https://i.imgur.com/lSI3PLw.png',
 'Doom of Mokhaiotl': 'https://i.imgur.com/dyqGBrK.png',
 'Fight Caves': 'https://i.imgur.com/E4tRuPx.png',
 'Fortis Colosseum': 'https://i.imgur.com/j72p8V5.png',
 'Grotesque Guardians': 'https://i.imgur.com/Peh7PuU.png',
 'Hallowed Sepulchre': 'https://i.imgur.com/ynD3Exh.png',
 'Hard Mode ToB 4-Man': 'https://i.imgur.com/7NKkNNF.png',
 'Hard Mode ToB 5-Man': 'https://i.imgur.com/abuq8ZO.png',
 'Hard Mode ToB Trio': 'https://i.imgur.com/hYfqlVa.png',
 'Hespori': 'https://i.imgur.com/bFvQ5O2.png',
 'Inferno': 'https://i.imgur.com/HpQOARB.png',
 'Leviathan': 'https://i.imgur.com/ZmzZVt1.png',
 'Phantom Muspah': 'https://i.imgur.com/zg468rf.png',
 "Phosani's Nightmare": 'https://i.imgur.com/iZ8lyZE.png',
 'Regular Gauntlet': 'https://i.imgur.com/9J34UrO.png',
 'Royal Titans': 'https://i.imgur.com/owZjOoq.png',
 'Theater of Blood 4-Man': 'https://i.imgur.com/wErk9ne.png',
 'Theater of Blood 5-Man': 'https://i.imgur.com/5jKMQ5W.png',
 'Theater of Blood Duo': 'https://i.imgur.com/9ONRE2u.png',
 'Theater of Blood Solo': 'https://i.imgur.com/P5UBxSn.png',
 'Theater of Blood Trio': 'https://i.imgur.com/ksWmzR1.png',
 "Tomb's of Amascut": 'https://i.imgur.com/dfW2MgK.png',
 "Tomb's of Amascut Expert": 'https://i.imgur.com/rcS4UBT.png',
 'Vardorvis': 'https://i.imgur.com/q3WbSIQ.png',
 'Vorkath': 'https://i.imgur.com/0JZJxD8.png',
 'Whisperer': 'https://i.imgur.com/EaIZEKi.png',
 'Zulrah': 'https://i.imgur.com/XhAQFSb.png',
 'Yama': 'https://i.imgur.com/4GGXfVi.gif'}

BOSS_ALIASES = {'Araxxor': ['araxxor'],
 'Zulrah': ['zulrah'],
 'Grotesque Guardians': ['grotesque guardians', 'gg'],
 'Vorkath': ['vorkath'],
 'Chambers of Xeric Solo': ['chambers of xeric solo', 'cox solo', 'cox 1'],
 'Chambers of Xeric Duo': ['chambers of xeric duo', 'cox duo', 'cox 2'],
 'Chambers of Xeric Trio': ['chambers of xeric trio', 'cox trio', 'cox 3'],
 'Chambers of Xeric CM Solo': ['chambers of xeric cm solo', 'cox cm solo', 'cox cm 1'],
 'Chambers of Xeric CM Trio': ['chambers of xeric cm trio', 'cox cm trio', 'cox cm 3'],
 'Chambers of Xeric CM 5-Man': ['chambers of xeric cm 5-man', 'cox cm 5-man', 'cox cm 5'],
 'Doom of Mokhaiotl': ['dom', 'doom', 'doom of mokhaiotl', 'doom of mok'],
 'Theater of Blood Solo': ['tob solo', 'theater of blood solo'],
 'Theater of Blood Duo': ['tob duo', 'theater of blood duo', 'tob 2'],
 'Theater of Blood Trio': ['tob trio', 'theater of blood trio', 'tob 3'],
 'Theater of Blood 4-Man': ['tob 4-man', 'theater of blood 4-man', 'tob 4'],
 'Theater of Blood 5-Man': ['tob 5-man', 'theater of blood 5-man', 'tob 5'],
 'Hard Mode ToB Trio': ['hard mode tob trio', 'hard mode theater of blood trio', 'hmt 3'],
 'Hard Mode ToB 4-Man': ['hard mode tob 4-man', 'hard mode theater of blood 4-man', 'hmt 4'],
 'Hard Mode ToB 5-Man': ['hard mode tob 5-man', 'hard mode theater of blood 5-man', 'hmt 5'],
 "Tomb's of Amascut": ["tomb's of amascut", 'tombs of amascut', 'toa'],
 "Tomb's of Amascut Expert": ["tomb's of amascut expert", 'tombs of amascut expert', 'toa expert'],
 "Phosani's Nightmare": ["phosani's nightmare", 'pnm'],
 'Phantom Muspah': ['phantom muspah', 'muspah'],
 'Royal Titans': ['royal titans'],
 'Alchemical Hydra': ['alchemical hydra', 'hydra'],
 'Amoxliatl': ['amoxliatl'],
 'Vardorvis': ['vardorvis'],
 'Leviathan': ['leviathan', 'levi'],
 'Duke': ['duke'],
 'Whisperer': ['whisperer'],
 'Regular Gauntlet': ['regular gauntlet', 'gauntlet'],
 'Corrupted Gauntlet': ['corrupted gauntlet', 'cg'],
 'Hespori': ['hespori'],
 'Inferno': ['inferno'],
 'Fight Caves': ['fight caves'],
 'Fortis Colosseum': ['fortis colosseum', 'colo', 'sol'],
 'Hallowed Sepulchre': ['hallowed sepulchre'],
 'Yama': ['yama']}
