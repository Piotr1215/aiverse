#!/usr/bin/env bash
# Set the line Claude Code shows on its spinner "Tip:" seam.
#
# WHY THIS EXISTS: Claude Code ships 16 hardcoded tips plus two contextual ones
# (/clear past 30min, /btw until first use). Those two prove the surface is the
# right place for a nudge, and they are the only two that will ever exist,
# because the registry is compiled into the binary. `spinnerTipsOverride` is the
# documented way in: custom tips are built with `cooldownSessions: 0` and
# `isRelevant: () => true`, so whatever sits in the array is always eligible.
# Rewrite the array, change the nudge.
#
# WHY settings.json AND NOT settings.local.json: the gitignored local file was
# the first choice, to keep a per-turn writer out of every commit. It showed no
# tip in a fresh session. The binary describes at least one setting as "read
# from user, flag, and managed settings only", and carries "legacy
# settings.local.json" error strings, so a user-level local file is not a
# settings source we can rely on. settings.json is the file every hook and the
# statusline already load from, so it is the one that is known to be read. The
# git noise is the price and it is one key.
#
# Setting an override suppresses Claude Code's own two contextual tips. Any
# caller taking this seam owns replacing them.
#
# WHO CALLS THIS NOW: the Luna coach, from its Claude-side delivery path, so a
# tip Luna writes for a Claude session lands on the spinner the moment it fires
# rather than being visible only to the agent that receives the relay. Codex
# tips never reach here; that path has its own client and its own surface.
#
# The key is user-level, not per session, so with two Claude sessions coaching
# at once the newest tip is the one on the seam. That is the honest reading of
# a single-slot surface, and the ledger stays the per-session record.
#
# A QUEUE, NOT A SLOT. Luna fires tips one at a time and the relay hands them
# to the agent one at a time, so overwriting the seam on every fire would show
# Piotr only whichever tip happened to be newest when he glanced up. Tips are
# pushed as they fire and dropped as the relay consumes them, which makes the
# seam the same queue the agent is reading, rendered for the human.
#
# When the queue empties the key is deleted rather than left holding an empty
# array, so Claude Code's own tips come back. Luna owns the seam only while it
# actually has something to say.
#
# Usage:
#   __tip_write.sh --push "Context at 74% - /subtask this sweep"
#   __tip_write.sh --drop "Context at 74% - /subtask this sweep"
#   __tip_write.sh --clear          # hand the seam back to the built-ins
#   __tip_write.sh --show           # print the queued tips, one per line
#
# Never fails a caller. A missing jq, an unwritable file, or a malformed
# settings file leaves the tip alone and exits 0: a hint is a nicety, and
# nothing upstream should ever break because the nicety did.

set -eo pipefail

SETTINGS_FILE="${TIP_SETTINGS_FILE:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json}"
LOCK_FILE="${TMPDIR:-/tmp}/claude-tip-write.lock"

# Longer than this and the spinner truncates it out of the terminal.
TIP_MAX_CHARS="${TIP_MAX_CHARS:-140}"

bail() { exit 0; }

command -v jq >/dev/null 2>&1 || bail

# More than this on the seam and the oldest advice is competing with the newest
# for a one-line surface. Five is a queue you can work through, not a backlog.
TIP_MAX_QUEUE="${TIP_MAX_QUEUE:-5}"

case "${1:-}" in
    --show)
        [[ -r "$SETTINGS_FILE" ]] || bail
        jq -r '.spinnerTipsOverride.tips[]? // empty' "$SETTINGS_FILE" 2>/dev/null || true
        exit 0
        ;;
    --clear)        action="clear"; tip="" ;;
    --push|--drop)  action="${1#--}"; tip="${2:-}"; [[ -n "$tip" ]] || bail ;;
    *)              bail ;;
esac

# Collapse newlines: the seam is one line, and a literal \n renders as garbage.
tip="$(printf '%s' "$tip" | tr '\n\r\t' '   ')"
(( ${#tip} > TIP_MAX_CHARS )) && tip="${tip:0:$((TIP_MAX_CHARS - 1))}…"

# Serialize writers. Two hooks finishing at once would otherwise race on
# read-modify-write and one would silently lose its hint.
exec 9>"$LOCK_FILE" 2>/dev/null || bail
flock -w 2 9 2>/dev/null || bail

[[ -f "$SETTINGS_FILE" ]] || echo '{}' > "$SETTINGS_FILE" 2>/dev/null || bail
jq -e . "$SETTINGS_FILE" >/dev/null 2>&1 || bail

tmp="${SETTINGS_FILE}.tip.$$"
case "$action" in
    clear)
        jq 'del(.spinnerTipsOverride)' "$SETTINGS_FILE" > "$tmp" 2>/dev/null || { rm -f "$tmp"; bail; }
        ;;
    push)
        # Newest first, deduplicated: Luna repeats itself while a lesson is
        # unlearned, and the same sentence twice on a one-line seam wastes half
        # the queue saying one thing.
        jq --arg t "$tip" --argjson cap "$TIP_MAX_QUEUE" \
           '.spinnerTipsOverride = {
                excludeDefault: true,
                tips: ([$t] + ((.spinnerTipsOverride.tips? // []) - [$t]))[0:$cap]
            }' "$SETTINGS_FILE" > "$tmp" 2>/dev/null || { rm -f "$tmp"; bail; }
        ;;
    drop)
        jq --arg t "$tip" \
           'if ((.spinnerTipsOverride.tips? // []) - [$t]) == [] then
                del(.spinnerTipsOverride)
            else
                .spinnerTipsOverride = {
                    excludeDefault: true,
                    tips: ((.spinnerTipsOverride.tips? // []) - [$t])
                }
            end' "$SETTINGS_FILE" > "$tmp" 2>/dev/null || { rm -f "$tmp"; bail; }
        ;;
esac

# Verify before swapping. A truncated write here corrupts the settings file that
# every later session reads, which is a far worse failure than a missing tip.
jq -e . "$tmp" >/dev/null 2>&1 || { rm -f "$tmp"; bail; }
mv -f "$tmp" "$SETTINGS_FILE" 2>/dev/null || { rm -f "$tmp"; bail; }

exit 0
