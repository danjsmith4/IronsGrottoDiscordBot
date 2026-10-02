#!/bin/bash
set -eu
case "$1" in
  pull) [[ "$TEST_MODE" != pull-failure ]];;
  image) echo sha256:new;;
  inspect)
    name=${@: -1}
    case "$3" in
      '{{.State.Running}}') cat "$TEST_DIR/$name.running";;
      '{{.Image}}') cat "$TEST_DIR/$name.image";;
      '{{.RestartCount}}') echo 0;;
    esac;;
  stop) echo false > "$TEST_DIR/${@: -1}.running";;
  rename)
    mv "$TEST_DIR/$2.running" "$TEST_DIR/$3.running"
    mv "$TEST_DIR/$2.image" "$TEST_DIR/$3.image";;
  run)
    echo true > "$TEST_DIR/irons-grotto-bot.running"
    echo sha256:new > "$TEST_DIR/irons-grotto-bot.image";;
  logs) [[ "$TEST_MODE" == startup-failure ]] || echo 'Logged in as Test Bot'; exit 0;;
  rm) rm -f "$TEST_DIR/${@: -1}.running" "$TEST_DIR/${@: -1}.image";;
  start) echo true > "$TEST_DIR/$2.running";;
  *) echo "Unexpected docker call: $*" >&2; exit 2;;
esac
