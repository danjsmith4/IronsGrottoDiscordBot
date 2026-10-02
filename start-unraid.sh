#!/bin/sh
set -eu

image=${1:-irons-grotto-bot:migration}
base=/mnt/user/appdata/irons-grotto-bot

docker run -d \
  --name irons-grotto-bot \
  --restart unless-stopped \
  --user 99:100 \
  --network bridge \
  --read-only \
  --tmpfs /tmp \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  --env HOME=/data \
  --env FORCE_CLEAR=0 \
  --mount "type=bind,src=$base/data,dst=/data" \
  --mount "type=bind,src=$base/secrets/bot.env,dst=/app/.env,readonly" \
  "$image"
