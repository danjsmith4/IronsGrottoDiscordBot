# Irons Grotto Discord Bot

Python 3.12 Discord bot, hosted in Docker on Unraid.

## Code Map

| File | Responsibility |
| --- | --- |
| `main.py` | Startup, command registration, shutdown |
| `config.py` | Environment settings, channel IDs, boss aliases and images |
| `cogs/community.py` | Welcomes, applications, community information |
| `cogs/moderation.py` | Event bans, submission review, message cleanup |
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

See [DEPLOYMENT.md](DEPLOYMENT.md) for Unraid setup. A push to `main` builds and
tests the container. Publishing requires approval of the GitHub `production`
environment. Unraid pulls the approved image, backs up data, and restarts the bot.
Credentials and persistent data remain mounted separately from the image.
