# Irons Grotto Discord Bot

Python 3.12 Discord bot, hosted in Docker on Unraid.

## Code Map

| File | Responsibility |
| --- | --- |
| `main.py` | Startup, command registration, shutdown |
| `config.py` | Environment settings, channel IDs, boss aliases and images |
| `cogs/community.py` | Welcomes, applications, community information |
| `cogs/moderation.py` | Event bans, submission review, message cleanup |
| `cogs/events.py` | Staff-managed events and eight-hour announcement rotation |
| `cogs/leaderboards.py` | Leaderboard commands, forms, Discord messages |
| `storage.py` | SQLite queries, ranking, input validation, atomic JSON writes |

Keep Discord interactions in the feature modules and data operations in storage.
Prefix and slash leaderboard commands share the same storage and page builder.
Existing command names and data formats are preserved.

## Local Development

Install `requirements.txt` in a Python 3.12 virtual environment. Keep the bot token
and server settings in an untracked `.env` beside `main.py`. Run `python main.py`
from the folder containing your local test databases. Never run a development copy
using the production token while the production bot is online.

Run offline tests from the repository root:

```sh
python -m unittest discover -s tests -p 'test_bot*.py'
bash tests/test-updater.sh
```

Tests use temporary databases and mocked Discord connections.

## Deployment

### Event Announcements

Staff role `829386451624001539` can use:

- `/event add title:... description:... end:2027-01-01 start:2026-12-01`
- `/event list` to find event IDs (ongoing and future events).
- `/event remove event_id:...`

Dates use `YYYY-MM-DD` in America/New_York, including daylight saving changes.
The end date includes the entire day. Omit start for an immediately active event.
Every eight hours, one random active event is announced in `697877518513864791`.
Future and expired events are excluded. If the last announcement is still the
latest channel message, it is edited instead of posting again. No role or everyone
pings are sent. With no active events, no new announcement is posted.

The first eligible event is announced within a minute when no previous timer exists.
Events and the timer persist in `events.sqlite3` in the backed-up data folder.
The bot needs View Channel, Read Message History, Send Messages, and Embed Links.
If history cannot be read, it skips posting and logs the failure to avoid spam.

### Forum Bump Reminders

The bot reminds Staff in channel `697877519730213010` to manually bump the
configured forum post. On first startup it sends a reminder; **Bump Done** records
the staff member and schedules the next reminder four hours later (checked every
minute). There are no repeated pings while a reminder is awaiting completion.
The button remains usable after restarts. Only role `829386451624001539` can use
it, and controls must be used in the reminder channel.

`/bump status`, `/bump done`, `/bump pause`, and `/bump resume` manage the timer.
Use `/bump done` if a reminder was deleted or staff bumped ahead of schedule.
State is stored in `bump_reminder.sqlite3` in the data folder, included in existing
data backups. The bot needs View Channel, Send Messages, and permission to mention
the Staff role (or the role must be mentionable). It does not bump the post itself.

See [DEPLOYMENT.md](DEPLOYMENT.md) for Unraid setup. A push to `main` builds and
tests the container. Publishing requires approval of the GitHub `production`
environment. Unraid pulls the approved image, backs up data, and restarts the bot.
Credentials and persistent data remain mounted separately from the image.
