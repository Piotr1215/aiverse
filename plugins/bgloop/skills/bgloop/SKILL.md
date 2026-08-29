---
name: bgloop
description: This skill should be used when the user asks to "bgloop status", "coach status", "is the coach on", "enable the coach", "disable the coach", "silence the coach", "set the coach budget", "what has the coach cost today", "mark that tip as learned", "why did the coach not fire", "show the capability library", or otherwise asks to inspect, tune, silence, or replay the bgloop background observer runtime and its Luna prompt coach.
version: 0.1.0
argument-hint: [status|enable|disable|budget|learned|replay|simulate|library]
allowed-tools: Bash
---

# bgloop operator surface

Inspect and tune the background observer runtime. Every command below is read-only unless it is listed under Changing state.

## Where the CLI lives

Two entry points, both inside the plugin:

- `${CLAUDE_PLUGIN_ROOT}/core/coach.py` owns state: status, budgets, learned tips, replay, simulate, enable, disable.
- `${CLAUDE_PLUGIN_ROOT}/observers/prompt_coach.py` owns the Claude side: hook entry points, the relay, the capability library.

Run them with `python3`. Resolve `${CLAUDE_PLUGIN_ROOT}` from the environment rather than typing a cache path, because the path changes on every plugin update.

## Answering "what is the coach doing"

Run `python3 "${CLAUDE_PLUGIN_ROOT}/core/coach.py" status` and report the four lines it prints: enabled state and model, today's token use and cost, the most recent tip, and how many tips are marked learned.

Add `--session <prefix>` to scope it to one session, and `--json` when the numbers feed something else rather than a person. A session prefix is enough; it resolves against the ledger.

## Answering "why did nothing fire"

Read the ledger decision for the job in question rather than guessing. Consult `references/ledger.md` for the event and decision vocabulary and what each one rules out. The common answers, in the order worth checking:

1. `disabled`, the runtime is off. `status` says so on its first line.
2. `session-token-cap` or `daily-token-cap`, a budget refused the reservation.
3. `learned`, the tip was suppressed because it is already marked learned.
4. `none`, the model was asked and had nothing worth saying.
5. `coalesced`, a later job for the same prompt owns the work.

Distinguish "not fired" from "fired but not delivered". A fired row that never reached the session is still owed and arrives on the next prompt through the relay.

## Changing state

Confirm with the user before running any of these. They alter a shared budget or a durable suppression.

- `core/coach.py enable` and `core/coach.py disable` turn the runtime off without uninstalling it.
- `core/coach.py budget <session|daily|output> <value>` sets a cap. Session and daily take 0 for unlimited; output must be positive.
- `core/coach.py learned "<tip text>"` suppresses that advice permanently. Use it when the user says they already know something, and pass `--capability <id>` when the tip named an installed capability.
- `core/coach.py restore` lifts the most recent learned suppression.

## Inspecting without spending

- `observers/prompt_coach.py library [query]` lists the installed capabilities the coach can recommend. No model call.
- `core/coach.py replay --session <id>` re-delivers the last decision for a session. No model call.
- `core/coach.py simulate "<prompt>"` runs one real decision end to end. This one does spend tokens, so say so before running it.

## Two facts that change the answer

The ledger is shared across config homes. `~/.claude` and `~/.claude-work` write to the same `~/.local/state/prompt-coach/ledger.jsonl`, so a daily total covers both accounts. Scope with `--session` when the user means one session.

The runtime is edge triggered. Nothing runs while no session is open, so a question about what happened overnight is answered by the ledger, never by a live process.

## Additional resources

- `references/ledger.md` covers the ledger row shapes, the full event and decision vocabulary, and how to read a job's life from queued to delivered.
