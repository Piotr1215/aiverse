# bgloop

An AI loop that runs in the background of a coding session.

One shape, whatever the observer is for:

```text
observable event
  -> detached one-shot observer
  -> bounded decision
  -> session-addressed action
  -> acknowledgment and ledger
```

A hook fires on a session event, spawns a detached worker, and returns immediately. The worker makes one bounded decision, emits one typed action or nothing at all, records exact usage and cost, and exits. Nothing about the originating turn waits for it.

Design and open questions: [Piotr1215/claude#175](https://github.com/Piotr1215/claude/issues/175).

## What ships today

One observer, the Luna prompt coach. It reads a submitted prompt, retrieves the machine capabilities that prompt could have used, asks a specialist model whether one of them is worth naming, and delivers at most one line back to the session that asked.

| Path | What it is |
| --- | --- |
| `core/coach.py` | The decision core. Ledger, reservation accounting, session and daily token caps, learned-tip rules, the model call. No Claude-specific imports. |
| `observers/prompt_coach.py` | The Claude shell. Capability rendering, transcript reading, delivery, the hook entry points. |
| `hooks/hooks.json` | `UserPromptSubmit` enqueues a job, `Stop` clears the turn marker. |
| `scripts/tip_write.sh` | Writes the spinner seam, the surface a human reads the tip on. |
| `tests/` | 94 tests. `uvx pytest tests/ -q` from the plugin root. |

## State

The ledger, the learned-tip file, and the job queue live under `~/.local/state/prompt-coach/`, not under `${CLAUDE_PLUGIN_DATA}`.

That is deliberate and it is the one place this plugin declines the platform's answer. `${CLAUDE_PLUGIN_DATA}` is scoped per plugin id per config home, so `~/.claude` and `~/.claude-work` would get separate directories. One budget would silently become two, and the ledger is the instrument every threshold is tuned from. Override with `PROMPT_COACH_STATE_DIR`.

`${CLAUDE_PLUGIN_ROOT}` changes on every update and the old directory is ephemeral, so nothing writes there.

## Dependencies

Python is stdlib only. Outside it:

- `codex` CLI, which is how the model call is made. Identity travels as `CODEX_HOME`, so a work session and a personal session reach different accounts.
- `node` and `snd.js` from agents-mcp-server, for pushing a tip at a live session over the bus. Override the path with `PROMPT_COACH_SND_BIN`.
- `jq` and `flock`, for the spinner seam.
- `__agents_presence.sh` on `PATH`, for the bus roster. Without it the bus roster reads empty and every tip takes the relay instead.

Each one degrades to a quieter coach rather than a broken session. Every path in the hook exits 0.

## Delivery

Two paths, and the second is the one that always works.

A session bound to the agents bus gets the tip pushed at it live. Only sessions that called `agent_register` are bound, and a hook cannot call an MCP tool, so most sessions are not.

Everything else takes the relay: the tip is handed to the next `UserPromptSubmit` as `additionalContext`. Zero extra model calls, and it reaches the model the same way any hook context does.

A turn marker written on `UserPromptSubmit` and removed on `Stop` separates a push into a busy session, which folds into the turn already running, from a push into an idle one, which starts a whole turn nobody asked for. The idle case is allowed and logged with `extra_model_calls=1`, so the cost stays visible instead of being assumed away.

## Installing

The plugin ships disabled, because `~/.claude/settings.json` still wires the same two hooks to the pre-plugin copies of these files. Enabling before removing them runs the coach twice per prompt against one budget.

```bash
/plugin install bgloop@aiverse
# remove the UserPromptSubmit and Stop entries for __claude_prompt_coach.py
# from ~/.claude/settings.json, then:
claude plugin enable bgloop
```

## Not here yet

The Codex adapter. A Claude plugin is invisible to Codex, so this is Claude only. The core carries no Claude imports and the env override `PROMPT_COACH_CORE` still wins, which is the seam Codex joins through later.

The synchronous guard lane, and a plugin-declared channel for delivery.
