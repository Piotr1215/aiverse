#!/usr/bin/env bash
# Tests for tip_write.sh: the queue behind Claude Code's spinner Tip: seam.
#
# Every case runs against a scratch settings file. The live one drives every
# session on this machine, and a test that writes it would put stale advice in
# front of Piotr for the rest of the day.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRITE="${TIP_WRITE_SCRIPT:-${SCRIPT_DIR}/../scripts/tip_write.sh}"

passed=0
failed=0
pass() { printf '  PASS: %s\n' "$1"; passed=$((passed + 1)); }
fail() { printf '  FAIL: %s\n' "$1" >&2; failed=$((failed + 1)); }

check_eq() {
    if [[ "$2" == "$3" ]]; then pass "$1"; else fail "$1 (want ${2@Q}, got ${3@Q})"; fi
}

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
SETTINGS="$T/settings.json"
export TIP_SETTINGS_FILE="$SETTINGS"

tips()    { "$WRITE" --show; }
key()     { jq -r 'has("spinnerTipsOverride")' "$SETTINGS"; }
exclude() { jq -r '.spinnerTipsOverride.excludeDefault' "$SETTINGS"; }

echo '{"model": "opus"}' > "$SETTINGS"

echo "Test: a pushed tip lands on the seam and owns it"
"$WRITE" --push "use /statusline"
check_eq "the tip is queued"          "use /statusline" "$(tips)"
check_eq "Luna owns the pool"         "true"            "$(exclude)"
check_eq "unrelated settings survive" "opus"            "$(jq -r .model "$SETTINGS")"

echo "Test: tips queue newest first instead of replacing each other"
"$WRITE" --push "use ;;ai explain"
check_eq "both tips are queued, newest first" $'use ;;ai explain\nuse /statusline' "$(tips)"

echo "Test: the same tip twice does not take two slots"
"$WRITE" --push "use /statusline"
check_eq "the repeat moves to the front, once" $'use /statusline\nuse ;;ai explain' "$(tips)"

echo "Test: the queue is capped"
: > "$SETTINGS"; echo '{}' > "$SETTINGS"
for n in 1 2 3 4 5 6 7; do "$WRITE" --push "tip $n"; done
check_eq "the cap holds"        "5"     "$(jq '.spinnerTipsOverride.tips | length' "$SETTINGS")"
check_eq "the oldest fell off"  "false" "$(jq '.spinnerTipsOverride.tips | index("tip 1") != null' "$SETTINGS")"
check_eq "the newest is first"  "tip 7" "$(jq -r '.spinnerTipsOverride.tips[0]' "$SETTINGS")"

echo "Test: a relayed tip is dropped, and the rest stay"
echo '{}' > "$SETTINGS"
"$WRITE" --push "first"
"$WRITE" --push "second"
"$WRITE" --drop "second"
check_eq "only the spent tip left" "first" "$(tips)"

echo "Test: draining the queue hands the seam back to the built-ins"
"$WRITE" --drop "first"
check_eq "the key is gone, not an empty array" "false" "$(key)"

echo "Test: dropping a tip that was never queued changes nothing"
echo '{}' > "$SETTINGS"
"$WRITE" --push "kept"
"$WRITE" --drop "never queued"
check_eq "the queue is untouched" "kept" "$(tips)"

echo "Test: --clear takes the whole queue down"
"$WRITE" --push "another"
"$WRITE" --clear
check_eq "nothing is queued" "false" "$(key)"

echo "Test: a tip too long for one line is truncated"
echo '{}' > "$SETTINGS"
"$WRITE" --push "$(printf 'x%.0s' {1..300})"
check_eq "cut to the seam width" "140" "$(jq -r '.spinnerTipsOverride.tips[0] | length' "$SETTINGS")"

echo "Test: newlines are collapsed, because the seam is one line"
echo '{}' > "$SETTINGS"
"$WRITE" --push "$(printf 'first\nsecond')"
check_eq "rendered as one line" "first second" "$(tips)"

echo "Test: a malformed settings file is never rewritten"
printf 'not json at all' > "$SETTINGS"
"$WRITE" --push "should not land"
check_eq "the file is left exactly as found" "not json at all" "$(cat "$SETTINGS")"

echo "Test: a caller that passes no tip is a no-op, not a wipe"
echo '{}' > "$SETTINGS"
"$WRITE" --push "kept"
"$WRITE" --push
"$WRITE" --drop
check_eq "the queue survives an empty call" "kept" "$(tips)"

printf '\n%d passed, %d failed\n' "$passed" "$failed"
[[ $failed -eq 0 ]]
