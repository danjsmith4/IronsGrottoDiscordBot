# Unraid deployment

## Required setup before enabling the workflow

In GitHub Settings > Environments, create `production`, add yourself as a
required reviewer, and allow deployments only from `main`. Leave prevention of
self-review off so you can approve your own commits. Disable administrator
bypass if you want the approval rule enforced for administrators too.
The workflow's environment name alone DOES NOT require approval: configure the
required reviewer before pushing this workflow.

Each push to main builds, checks Python syntax, and runs offline bot and updater tests. Publication waits for
approval, then publishes `approved` and an immutable-by-convention commit SHA
tag to GitHub Container Registry. These checks do not connect to Discord or use production data.
Package visibility is separate from repository visibility: configure public
read access to the image or authenticate Unraid with a read:packages token.

## Credentials and data

Credentials and runtime data are excluded from new commits and container
images. Only the bot environment settings are mounted from the secrets folder.

Create `/mnt/user/appdata/irons-grotto-bot/data` and a sibling `secrets` folder.
Give Unraid user 99, group 100 write access to data and read access to the secret
files. Restrict secret access and avoid exposing the secrets folder over SMB.

Copy these runtime files into data:

- bot_data.db
- event_bans.sqlite3
- leaderboards.db
- leaderboard_hashes.json
- leaderboard_messages.json

Create `secrets/bot.env` using
`.env.example` and the existing Apollo environment values. The download has no
`.env`, so recover those values from the host before cancelling it. Transfer any
additional configured EVENTBAN_* variables, preserving a path inside /data for
EVENTBAN_DB_PATH. FORCE_CLEAR should remain 0 for routine startup.

Do not copy the old .local folder. Dependencies are installed in the image.
Do not copy discord.png into data: the entrypoint provides that path separately.

## First launch and updates

The server uses Docker directly through start-unraid.sh; Compose is optional.
This workflow builds an x86-64 image on the GitHub-hosted runner.

Stop the SparkedHost bot, take a fresh final copy of its data files, then start
the Unraid bot. Do not run both copies simultaneously. Verify login, welcome
messages, commands and leaderboards before cancelling
hosting. The downloaded database copies have not been checked for consistency.

With the compose file on Unraid, pull and start using:

```sh
docker compose pull bot
docker compose up -d bot
docker compose logs --tail=100 bot
```

## Approved automatic updates

Install update-unraid.sh beside start-unraid.sh on Unraid. Install
unraid-update.cron as
`/boot/config/plugins/dynamix/irons-grotto-bot.cron`, then run `update_cron`.
The scheduler checks the approved image once a minute. It respects a manually
stopped bot and uses a lock to prevent overlapping deployments.

GitHub builds and checks the image before approval, then publishes that exact
image after approval. In the Actions run, choose Review deployments, select
production, and approve. The GHCR package must be public for anonymous pulls
from this server. No GitHub credentials are stored on Unraid.

Before installing a changed image, the updater stops the bot and backs up its
data. The new container runs by image ID, preventing a moving tag from changing
which image is installed during deployment. A successful Discord login with no
container restarts confirms startup. This does not test every bot command.

On startup failure, the old container is restored and that failed image is not
automatically retried. Clear the `failed-image` file only when intentionally
retrying it. Runtime data is not automatically rolled back. Inspect the saved
backup if a failed future version modified its database format.

Successful updates retain stopped containers named
`irons-grotto-bot-previous-TIMESTAMP` and backups in `backups/`. Review and prune
these periodically. Updater events appear in Unraid's system log under
`irons-grotto-bot` and `irons-grotto-bot-update`.

Keep backups of data while the bot is stopped before each upgrade. To roll back,
set the image tag in compose.yaml to a previously approved commit SHA and run
pull/up again. A code rollback does not reverse database changes; restore a
matching data backup if a future update changes the database format.
