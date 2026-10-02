#!/bin/bash
set -eu
source_dir=$(cd "$(dirname "$0")/.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
mkdir -p "$test_root/bin"
cp "$source_dir/tests/mock-docker.sh" "$test_root/bin/docker"
ln -s /bin/true "$test_root/bin/sleep"
ln -s /bin/true "$test_root/bin/logger"
chmod +x "$test_root/bin/docker"
export PATH="$test_root/bin:$PATH"

for mode in success unchanged startup-failure pull-failure; do
  export TEST_MODE=$mode TEST_DIR="$test_root/$mode"
  mkdir -p "$TEST_DIR/data"
  cp "$source_dir/start-unraid.sh" "$TEST_DIR/start-unraid.sh"
  sed -e "s|base=/mnt/user/appdata/irons-grotto-bot|base=$TEST_DIR|" \
      -e "s|/var/run/irons-grotto-bot-update.lock|$TEST_DIR/update.lock|" \
      "$source_dir/update-unraid.sh" > "$TEST_DIR/update.sh"
  echo true > "$TEST_DIR/irons-grotto-bot.running"
  old=sha256:old
  [[ "$mode" != unchanged ]] || old=sha256:new
  echo "$old" > "$TEST_DIR/irons-grotto-bot.image"
  result=0
  bash "$TEST_DIR/update.sh" || result=$?
  [[ $(cat "$TEST_DIR/irons-grotto-bot.running") == true ]]
  case "$mode" in
    success)
      [[ "$result" == 0 ]]
      [[ $(cat "$TEST_DIR/irons-grotto-bot.image") == sha256:new ]]
      compgen -G "$TEST_DIR/backups/data-*.tar.gz" >/dev/null;;
    unchanged)
      [[ "$result" == 0 && ! -d "$TEST_DIR/backups" ]];;
    startup-failure)
      [[ "$result" != 0 ]]
      [[ $(cat "$TEST_DIR/irons-grotto-bot.image") == sha256:old ]]
      [[ $(cat "$TEST_DIR/failed-image") == sha256:new ]];;
    pull-failure)
      [[ "$result" != 0 && ! -d "$TEST_DIR/backups" ]]
      [[ $(cat "$TEST_DIR/irons-grotto-bot.image") == sha256:old ]];;
  esac
  echo "PASS: $mode"
done
