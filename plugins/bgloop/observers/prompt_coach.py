#!/usr/bin/env python3
"""Metered Luna prompt coach for Claude Code.

WHY THIS FILE EXISTS
The coach already runs on Codex: one Luna call per prompt, gated hard, with a
shared ledger that meters tokens and remembers which tips Piotr has already
learned. Claude Code had no coach at all. It had a SPINNER tip path instead,
which wrote `spinnerTipsOverride` into settings.json and showed one line on the
spinner. That surface could never carry a Luna tip: it is a settings key rather
than an event, the model never sees it, and running it beside this coach would
put two independent gates on the same human attention budget. This file
replaces it.

WHAT IS SHARED AND WHAT IS NOT
Everything that costs money or bounds attention is SHARED with the Codex coach
by importing its module: the ledger, the reservation accounting, the session
and daily token caps, the learned-tip rules, the Luna request shape. One budget,
not two. A second copy of that logic would drift on the first threshold change
and the ledger is the instrument every threshold is tuned from.

What is NOT shared is everything provider-shaped, and it is exactly the list a
port gets wrong:
  - capabilities, which must render as `/thing` for Claude and never as
    `codex thing`, an action Piotr cannot type here;
  - the transcript, which lives in ~/.claude/projects rather than a rollout;
  - delivery, because Codex steers its active turn over an app-server socket
    and Claude Code has no equivalent call.

DELIVERY, AND WHY IT IS TWO PATHS
Claude Code's live-push seam is Channels: an MCP server emits
`notifications/claude/channel` and the text lands in the session as a
<channel source="agents"> tag. The agents bus already does this and is the path
the rest of this machine's agent framework uses, so the coach reuses it rather
than inventing a second one.

Two properties decide when it may be used. A channel event that arrives while
the session is BUSY is folded into the turn already running, which costs no
extra provider call. A channel event that arrives while the session is IDLE
makes Claude start responding, which is a whole extra turn Piotr did not ask
for. Eventual delivery outranks that saving, so an idle push is allowed, but a
turn marker (written on UserPromptSubmit, removed on Stop) separates the two
cases and the idle one is logged with extra_model_calls=1. The cost stays
visible in the ledger instead of being assumed away.

The second property is that the bus only reaches sessions that called
agent_register, because agents-mcp-server pushes to bound sessions only
(src/index.ts, pushToSessions). An ordinary session is not bound and cannot be
bound from a hook, since hooks cannot call MCP tools. Those sessions fall back
to the relay: the tip is handed to the next UserPromptSubmit as
additionalContext, which is zero extra model calls and reaches the model the
same way any hook context does.

Never fails a caller. A hook that breaks a turn to deliver a nicety is worse
than no coach, so every path here exits 0.
"""

import argparse
import contextlib
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

CORE_ENV = "PROMPT_COACH_CORE"
# The shared core ships inside this plugin. It used to be imported by absolute
# path out of ~/.codex, which made a Claude hook fail whenever the Codex repo
# was absent, moved or mid-checkout. The env override stays so a foreign core
# (a Codex checkout, a test double) can still win.
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CORE_DEFAULT = str(PLUGIN_ROOT / "core" / "coach.py")
SND_BIN = os.environ.get("PROMPT_COACH_SND_BIN", "/home/decoder/dev/agents-mcp-server/build/snd.js")
NATS_URL = os.environ.get("AGENTS_NATS_URL", "nats://nats-nats-tailscale.tail165ec.ts.net:4222")
# The bus label the tip is published under. A tip must never look like Piotr
# talking to himself, and never like another agent either.
COACH_AGENT = os.environ.get("PROMPT_COACH_AGENT_NAME", "coach")
# Every row this client writes carries the tag in `purpose`, which is the one
# field the shared core copies verbatim from the job. Claude personal, Claude
# work and Codex share one ledger, so without a provider mark a Codex tip could
# be relayed into a Claude session.
PROVIDER_TAG = "claude:"


def load_core():
    """Import the shared coach core, or None when it is not installed."""
    candidates = [os.environ.get(CORE_ENV, ""), CORE_DEFAULT]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("prompt_coach_core", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:
            return None
    return None


CORE = load_core()


def config_root():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser()


# ---------------------------------------------------------------- capabilities


def registry_capability(row):
    """One registry row as something Piotr can act on in Claude Code.

    Two shapes, not one. An invocable row becomes `/thing`: the registry
    deliberately stores bare names, because the same skill is
    `/repo-vector-map` in Claude and `$repo-vector-map` in Codex and it cannot
    see which client is reading, so adding the prefix is this renderer's job.

    A SETTING is the other shape and it is why this is not a one-line filter.
    `outputStyle` is not typable and would be dropped by an invocable-only
    rule, yet changing it is some of the most useful advice available here.
    It renders as the file and key to edit instead of a command to type.

    Codex rows never arrive: they are excluded at the source with
    include_codex=False, so `codex resume` cannot reach a Claude tip.
    """
    kind = row.get("kind", "capability")
    capability_id = row.get("capability_id", "")
    if row.get("invocable") and row.get("invocation_name"):
        name = str(row["invocation_name"]).lstrip("$/")
        if name:
            return {
                "id": capability_id,
                "surface": "claude-%s" % kind,
                "invocation": "/%s" % name,
                "description": row.get("summary", ""),
            }
    if kind == "setting" and ":" in capability_id:
        name = capability_id.split(":", 1)[1]
        if name:
            return {
                "id": capability_id,
                "surface": "claude-setting",
                "invocation": "set %s in ~/.claude/settings.json" % name,
                "description": row.get("summary", ""),
            }
    return None


def load_capabilities():
    fixture = os.environ.get("PROMPT_COACH_CAPABILITIES_FILE")
    if fixture:
        try:
            values = json.loads(Path(fixture).read_text())
            return [row for row in values if isinstance(row, dict) and row.get("id")]
        except (OSError, ValueError):
            return []

    capabilities = []
    registry_path = config_root() / "evals" / "proficiency" / "capabilities.py"
    if registry_path.is_file():
        try:
            spec = importlib.util.spec_from_file_location("prompt_coach_registry", registry_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for row in module.snapshot(root=config_root(), include_codex=False):
                capability = registry_capability(row)
                if capability:
                    capabilities.append(capability)
        except Exception:
            pass

    snippets = Path(
        os.environ.get("PROMPT_COACH_SNIPPETS_DIR", str(config_root() / "ai-snippets"))
    )
    if CORE and snippets.is_dir():
        for snippet_file in sorted(snippets.glob("*.md")):
            row = CORE.parse_ai_snippet(snippet_file)
            if row:
                capabilities.append(row)

    unique = {}
    for row in capabilities:
        unique[row["id"]] = row
    return list(unique.values())


# ------------------------------------------------------------------ transcript


def transcript_path(session_id):
    if not session_id:
        return None
    matches = list((config_root() / "projects").glob("*/%s.jsonl" % session_id))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def is_human_prompt(row):
    """True only for text Piotr actually typed.

    Claude Code stamps every user row with an origin. A channel push lands as
    `{"kind": "channel", "server": "agents"}` and a typed prompt as
    `{"kind": "human"}`. Coaching on a channel row would mean coaching on the
    coach's own tip, which is the feedback loop this check exists to stop.
    Rows with no origin are skill and command expansions, not prompts.
    """
    if row.get("type") != "user" or row.get("isSidechain"):
        return False
    origin = row.get("origin")
    return isinstance(origin, dict) and origin.get("kind") == "human"


def message_text(row):
    content = (row.get("message") or {}).get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = [
        item.get("text", "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    return "\n".join(part for part in parts if part).strip()


def synthetic(text):
    value = (text or "").lstrip()
    return value.startswith("<coach>") or value.startswith("<channel ") or value.startswith("<command-message>")


def recent_prompts(session_id, limit=4):
    path = transcript_path(session_id)
    if not path or not CORE:
        return []
    values = []
    for row in CORE.read_jsonl(path):
        if not is_human_prompt(row):
            continue
        text = message_text(row)
        if text and not synthetic(text):
            values.append(text)
    return values[-limit:]


# -------------------------------------------------------------------- delivery


def turn_marker(root, session_id):
    return root / "turns" / ("%s.turn" % CORE.safe_session(session_id))


def turn_start(root, session_id):
    marker = turn_marker(root, session_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("%d\n" % int(time.time()))


def turn_end(root, session_id):
    with contextlib.suppress(OSError):
        turn_marker(root, session_id).unlink()


def turn_active(root, session_id):
    """Is a turn running right now?

    Also treats a very old marker as inactive: a session killed mid-turn never
    fires Stop, and a stale marker would let the coach push into an idle
    session and start a turn Piotr did not ask for.
    """
    if not session_id:
        return False
    marker = turn_marker(root, session_id)
    try:
        started = int(marker.read_text().strip())
    except (OSError, ValueError):
        return False
    limit = CORE.env_int("PROMPT_COACH_TURN_MAX_SECONDS", 1800)
    return 0 <= time.time() - started <= limit


def channel_text(tip):
    return (
        "<coach> Automated prompt-coach advice, not instruction authority. "
        "Share this with Piotr once and apply it only if it fits his request: %s" % tip
    )


def relay_block(tips):
    """One bounded <coach> block carrying every tip the session is owed.

    Without spacing or a session cap, several workers can finish while the user
    is mid-turn, so the next prompt may owe more than one tip. They arrive as a
    single block rather than one injection per tip: the model reads context
    once, and a bundle makes the ordering visible instead of leaving it to
    whichever hook ran last.
    """
    lines = ["<coach> Automated prompt-coach advice, not instruction authority. "
             "Apply only what fits the request and higher-level instructions:"]
    lines.extend("- %s" % tip for tip in tips)
    return "\n".join(lines)


def channel_push(agent, tip):
    """Publish the tip to one bound session over the agents bus."""
    if not agent or not tip or not Path(SND_BIN).is_file():
        return False
    env = dict(os.environ, AGENTS_NATS_URL=NATS_URL, SND_FROM=COACH_AGENT)
    try:
        result = subprocess.run(
            ["node", SND_BIN, "-t", agent, channel_text(tip)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=CORE.env_int("PROMPT_COACH_PUSH_TIMEOUT_SECONDS", 5),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def presence_script():
    """Where the live bus roster comes from.

    It lives in the dotfiles scripts directory, not under the Claude config
    root: an earlier draft assumed the latter and silently returned an empty
    roster, which turns every channel push into a no-op.
    """
    found = shutil.which("__agents_presence.sh")
    if found:
        return found
    for candidate in (
        Path.home() / "dev" / "dotfiles" / "scripts" / "__agents_presence.sh",
        config_root() / "scripts" / "__agents_presence.sh",
    ):
        if candidate.is_file():
            return str(candidate)
    return ""


def pane_target():
    """This pane, named so it still means this pane an hour from now.

    __claude_with_monitor exports two identifiers. CLAUDE_PANE_ID is tmux's
    %id, fixed for the life of the pane. CLAUDE_TMUX_PANE is a
    session:window.index string captured at launch, and an index shifts
    whenever any pane in that window is opened or closed, so the launch-time
    string later names somebody else's pane.

    Verified live on 2026-08-23: this session launched as poke:1.3 and had
    moved to poke:1.2, by which time poke:1.3 resolved to %51, a Codex pane.
    Every prompt wrote this session's id onto Codex's @prompt_coach_session,
    taking ctips in that pane off its own session, and read that pane's
    @agent_name back as this session's bus identity.

    Order is stable id, tmux's own TMUX_PANE (also a %id), then the index form
    as a last resort for a caller that has nothing better.
    """
    return (
        os.environ.get("CLAUDE_PANE_ID")
        or os.environ.get("TMUX_PANE")
        or os.environ.get("CLAUDE_TMUX_PANE")
        or ""
    )


def tmux_session_name():
    """The tmux session this pane belongs to, or empty."""
    override = os.environ.get("PROMPT_COACH_TMUX_SESSION")
    if override is not None:
        return override
    pane = pane_target()
    if not pane:
        return ""
    if ":" in pane:
        return pane.split(":", 1)[0]
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane, "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def pinned_session():
    """Which Claude session actually owns this pane's bus identity.

    The agent registration hook pins the registering session's own id next to
    the pane. That pin is the only thing that distinguishes the session that
    holds the bus name from any other session running in the same pane: a
    nested `claude -p`, a background agent, a subagent. All of them inherit
    TMUX_PANE and therefore all of them resolve the same @agent_name.

    Empty when the pin is missing, unreadable or blank, and empty always means
    do not publish.
    """
    name = tmux_session_name()
    if not name:
        return ""
    safe = re.sub(r"[/ :]", "-", name)
    pin = Path(os.environ.get("PROMPT_COACH_PIN_DIR", "/tmp")) / ("claude_mainsid_%s.pin" % safe)
    try:
        return pin.read_text().strip()
    except OSError:
        return ""


def bound_agents():
    """Names the bus currently reports as registered.

    Registration is what binds a session, so presence is the closest thing to
    a reachability check available before publishing. It is not a delivery
    receipt and is not treated as one.
    """
    presence = presence_script()
    if not presence:
        return set()
    try:
        result = subprocess.run(
            [presence, "--agents"],
            capture_output=True,
            text=True,
            timeout=CORE.env_int("PROMPT_COACH_PRESENCE_TIMEOUT_SECONDS", 5),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def record_attempt(root, record, delivery, context_bytes):
    """Log a channel push WITHOUT consuming the tip.

    snd.js publishes to NATS and drains; it never learns whether a bound
    session received anything, so its exit 0 means "published", not
    "delivered". An earlier draft advanced the relay cursor on that exit code,
    which silently destroyed every tip aimed at a session that was not bound.
    This row therefore carries no `through_ts`: the relay cursor only moves
    when the next prompt actually carries the tip into the model's context.
    """
    CORE.append_event(
        root,
        {
            "ts": time.time(),
            "event": "channel-attempt",
            "decision": "published",
            "job_id": "%s-%s" % (delivery, uuid.uuid4().hex[:12]),
            "source_job_id": record.get("job_id", ""),
            "session_id": record.get("session_id", ""),
            "purpose": record.get("purpose", ""),
            "delivery": delivery,
            "acknowledged": False,
            "tip": record.get("tip", ""),
            "capability_id": record.get("capability_id", ""),
            "injected_bytes": context_bytes,
            "extra_model_calls": 1 if delivery == "agents-channel-idle" else 0,
        },
    )


def seam_write(*args):
    """Run the spinner-seam writer, best effort, never raising.

    A missing writer, an unwritable settings file or a slow disk loses the
    display and nothing else: the tip is already in the ledger, and the relay
    still delivers it to the agent.
    """
    writer = PLUGIN_ROOT / "scripts" / "tip_write.sh"
    if not os.access(writer, os.X_OK):
        return
    # setdefault, not an override: the test suite and any caller that has
    # already chosen a settings file must be able to keep it, or running the
    # tests would rewrite the live spinner tip on this machine.
    env = {**os.environ}
    env.setdefault("TIP_SETTINGS_FILE", str(config_root() / "settings.json"))
    with contextlib.suppress(Exception):
        subprocess.run(
            [str(writer), *args],
            env=env,
            timeout=5,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def pin_spinner_tip(tip):
    """Queue the tip on Claude Code's spinner seam, where Piotr can read it.

    This does not replace the relay, it doubles it. The relay hands the tip to
    the AGENT and still does. Until now nothing handed it to Piotr, so the
    coach he pays for was advice he could only read by opening `ctips` in
    another pane, while the model got it in context for free. The spinner
    already renders a Tip: line, `spinnerTipsOverride` fills its pool, and that
    is the one surface in front of him during the turn the tip is about.

    Pushed, not set: tips arrive one at a time and the relay consumes them one
    at a time, so the seam holds the same queue rather than only its newest
    entry. unpin_spinner_tips takes each one back off as the relay spends it.

    Claude-side only, by construction: this file IS the Claude client, so a
    Codex job never reaches it. Codex has no equivalent seam.

    The write follows the account the session belongs to, because a work
    session reads its settings from CLAUDE_CONFIG_DIR and a tip written to the
    personal file would render for nobody.

    One limit worth naming: spinnerTipsOverride is a user-level setting, not a
    per-session one. Two Claude sessions coaching at once share the seam, so
    the queue is per account and the ledger stays the per-session record.
    """
    if not tip:
        return
    seam_write("--push", tip)


def unpin_spinner_tips(tips):
    """Take tips back off the seam as the relay hands them to the agent.

    The queue Piotr reads and the queue the agent receives are the same queue.
    A tip that has been injected has been spent, and leaving it on the spinner
    would coach him with advice the session already acted on.
    """
    for tip in tips or []:
        if tip:
            seam_write("--drop", tip)


def deliver(job, record):
    """Push the tip at the live turn, and leave the relay authoritative.

    Only the tip travels. The 12 to 15 line Luna trace stays in the ledger and
    is read with `ctips`: putting it in the session would spend more of Piotr's
    context on the coach's reasoning than on his own work.

    The push is best effort by construction, so this never reports success.
    Delivery is settled by whichever path actually puts the text in front of
    the model, and only that path moves the cursor.
    """
    root = CORE.state_dir()
    tip = record.get("tip", "")
    if not tip:
        return "none"
    # Before any delivery decision. Whether the bus push lands, whether the pin
    # names this session, whether the relay is still owed: none of that changes
    # that Luna has advice for Piotr right now, and the seam is his copy.
    pin_spinner_tip(tip)
    agent = job.get("agent", "")
    session_id = record.get("session_id", "")
    if not agent:
        return "pending"
    # The bus address is a property of the PANE and this job is a property of a
    # SESSION. Verified live: a headless `claude -p` sharing this pane resolved
    # the pane's @agent_name and its tip was published into the registered
    # session instead of its own, which both leaked one session's context into
    # another and lost the tip for the session that earned it. So the pane's
    # identity counts only when the pin says this exact session owns it.
    # Anything else, including a missing or blank pin, publishes nothing and
    # writes no attempt row: the tip stays pending for this session's own relay.
    if not session_id or pinned_session() != session_id:
        return "pending"
    if agent not in bound_agents():
        return "pending"
    # An idle push wakes Claude into a turn Piotr did not ask for. It is
    # allowed, because eventual delivery outranks the saving, but it is
    # counted so the cost is visible in the ledger rather than assumed away.
    delivery = "agents-channel" if turn_active(root, session_id) else "agents-channel-idle"
    if channel_push(agent, tip):
        record_attempt(root, record, delivery, len(channel_text(tip).encode()))
    return "pending"


def row_epoch(row):
    """Transcript timestamp as epoch seconds, 0 when unreadable."""
    value = str(row.get("timestamp") or "")
    if not value:
        return 0.0
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def channel_delivered(session_id, tip, after=0.0):
    """Did the bus push actually reach THIS session, after the attempt?

    The transcript answers it, in two shapes, and reading only the obvious one
    is how this was wrong the first time.

    A channel event that arrives while the session is IDLE becomes a user row
    stamped origin {"kind": "channel"}: Claude wakes and answers it, which is a
    whole extra provider turn.

    A channel event that arrives while the session is BUSY never becomes a user
    row at all. It is written as `queue-operation` rows, enqueue then remove,
    and folded into the turn already running at no extra cost. That is the
    common case for this coach, since the push is aimed at a live turn. An
    earlier draft looked only for the user row, found nothing, and let the
    fallback deliver a tip that was already on screen.

    Both shapes carry the session id in their own file, so a receipt can never
    be borrowed from another session, and both are bounded by `after` so an
    older identical tip cannot stand in for this delivery.
    """
    path = transcript_path(session_id)
    if not path or not tip:
        return False
    needle = " ".join(tip.split())[:80]
    if not needle:
        return False
    for row in CORE.read_jsonl(path):
        kind = row.get("type")
        if kind == "queue-operation":
            body = str(row.get("content") or "")
        elif kind == "user":
            origin = row.get("origin")
            if not isinstance(origin, dict) or origin.get("kind") != "channel":
                continue
            body = message_text(row)
        else:
            continue
        if after and row_epoch(row) < after:
            continue
        if needle in " ".join(body.split()):
            return True
    return False


def claim_pending_relay(root, session_id, now=None):
    """Hand every tip this session is owed to the next prompt, once.

    Authoritative by design. A channel push logs an attempt and never consumes
    a tip, so anything the bus failed to deliver is still waiting here.

    Four rules, each earned:
      - rows are matched on session AND provider tag, because Claude personal,
        Claude work and Codex share one ledger and a tip surfacing in the wrong
        client is the failure cross-provider state exists to prevent;
      - identical advice is shown once, however many workers produced it;
      - a tip already confirmed on screen through the bus is skipped but still
        consumed, so it is never shown twice;
      - the cursor advances only through the LAST INCLUDED source, so anything
        dropped for size is still owed and arrives on the following prompt.
    """
    if not session_id or (root / "disabled").exists():
        return None
    if os.environ.get("PROMPT_COACH_ENABLED", "1") == "0":
        return None
    now_value = float(time.time() if now is None else now)
    budget = CORE.env_int("PROMPT_COACH_RELAY_MAX_BYTES", 1200)
    with CORE.state_lock(root):
        rows = CORE.read_jsonl(root / "ledger.jsonl")
        cursor = max(
            [
                float(row.get("through_ts") or 0)
                for row in rows
                if row.get("event") == "relayed" and row.get("session_id") == session_id
            ],
            default=0,
        )
        pending = sorted(
            (
                row
                for row in rows
                if row.get("event") in {"complete", "replayed"}
                and row.get("decision") in {"fired", "replayed"}
                and row.get("session_id") == session_id
                and str(row.get("purpose", "")).startswith(PROVIDER_TAG)
                and float(row.get("ts") or 0) > cursor
                and row.get("tip")
            ),
            key=lambda row: float(row.get("ts") or 0),
        )
        if not pending:
            return None

        seen = set()
        included = []
        sources = []
        through = 0.0
        used = len(relay_block([]).encode())
        for row in pending:
            tip = " ".join(str(row.get("tip") or "").split())[:140]
            row_ts = float(row.get("ts") or 0)
            if not tip:
                through = row_ts
                continue
            key = tip.casefold()
            if key in seen or any(tip.casefold() == value.casefold() for value in included):
                through = row_ts
                continue
            if channel_delivered(session_id, tip, row_ts):
                seen.add(key)
                through = row_ts
                continue
            cost = len(("- %s\n" % tip).encode())
            # The first tip always goes, whatever the budget: a tip too large
            # to ever fit would otherwise block the queue behind it forever.
            if included and used + cost > budget:
                break
            seen.add(key)
            included.append(tip)
            sources.append(row.get("job_id", ""))
            used += cost
            through = row_ts

        if not through:
            return None
        context = relay_block(included) if included else ""
        CORE.append_jsonl(
            root / "ledger.jsonl",
            {
                "ts": now_value,
                "event": "relayed",
                "decision": "relayed",
                "job_id": "relay-%s" % uuid.uuid4().hex[:12],
                "source_job_id": sources[-1] if sources else "",
                "source_job_ids": sources,
                "through_ts": through,
                "session_id": session_id,
                "purpose": "%s:relay" % PROVIDER_TAG.rstrip(":"),
                "delivery": "next-prompt-hook" if included else "already-delivered",
                "tip": included[0] if included else "",
                "tip_count": len(included),
                "injected_bytes": len(context.encode()),
                "extra_model_calls": 0,
            },
        )
    if not included:
        return None
    unpin_spinner_tips(included)
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


# ------------------------------------------------------------------- job cycle


def pane_agent():
    """This session's bus identity, or empty when it never registered.

    Must target $TMUX_PANE explicitly. A bare display-message resolves against
    the attached client's active pane, so the answer would depend on where
    Piotr's cursor happens to be sitting.
    """
    pane = pane_target()
    if not pane:
        return ""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane, "#{@agent_name}"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def mark_pane_session(session_id):
    """Tell the pane which coach session it is looking at.

    `__tip_status.sh` scopes its whole view to the session in the pane's
    @prompt_coach_session variable. Only the Codex enqueue used to set it, so
    ctips in a Claude pane reported a Codex session's budget and decisions.
    Best effort: no tmux, no pane, no problem.
    """
    pane = pane_target()
    if not pane or not session_id:
        return False
    try:
        result = subprocess.run(
            ["tmux", "set-option", "-p", "-t", pane, "@prompt_coach_session", session_id.replace("#", "##")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def codex_home():
    """Which Codex login the subscription transport should spend against.

    The shell exports CODEX_HOME alongside CLAUDE_CONFIG_DIR, so an inherited
    value is already right. It is derived only when the hook runs without that
    export: a work Claude session must never bill Luna to the personal
    ChatGPT account, and the pairing is the same one .zsh_claude enforces.
    Nothing is copied between the two roots.
    """
    explicit = os.environ.get("CODEX_HOME", "")
    if explicit:
        return explicit
    config = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if config and Path(config).name == ".claude-work":
        return str(Path.home() / ".codex-work")
    return ""


def enqueue(payload):
    root = CORE.state_dir()
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
    if not session_id:
        return 0
    prompt = str(payload.get("prompt") or "")
    turn_start(root, session_id)
    mark_pane_session(session_id)
    if not prompt or synthetic(prompt):
        return 0
    now_value = time.time()
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "session_id": session_id,
        "agent": pane_agent(),
        "prompt": prompt,
        "recent_user_prompts": [],
        "created_at": now_value,
        "not_before": now_value + CORE.env_int("PROMPT_COACH_DEBOUNCE_SECONDS", 1),
        "purpose": "%srecap+coach" % PROVIDER_TAG,
        "client": "claude",
        "config_home": str(config_root()),
    }
    job_path = root / "jobs" / ("%s.json" % job_id)
    CORE.atomic_json(job_path, job)
    # The stamp is keyed on the PROMPT, not the session. Two different prompts
    # in the same second are two questions and both deserve a worker; the only
    # thing that coalesces is the same hook payload arriving twice, which is a
    # delivery artefact rather than a second question.
    stamp = CORE.dedupe_stamp(root, session_id, prompt)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(job_id + "\n")
    CORE.append_event(root, {**CORE.base_event(job, now_value), "event": "queued", "decision": "queued"})
    if os.environ.get("PROMPT_COACH_SYNC") == "1":
        run_job(job_path)
        return 0
    spawn_worker(Path(__file__).resolve(), job_path)
    return 0


def spawn_worker(script, job_path):
    """Detach one worker for one job, with a whitelisted environment.

    Split out of enqueue so a second observer reuses the environment rules
    rather than reasoning about them again. The whitelist is the security
    boundary here, not a tidiness preference: a detached process inherits
    whatever it is given, and the two entries that matter are the two that
    were once wrong.
    """
    child_env = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "HOME",
            "PATH",
            "LANG",
            "LC_ALL",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            # No OPENAI_API_KEY. Luna runs on Piotr's ChatGPT subscription
            # through `codex exec`, so a key here would be an unused secret
            # handed to a detached process. CODEX_HOME is what the transport
            # actually needs: it selects the work or personal login, and
            # dropping it would silently coach a work session from the
            # personal account.
            "CODEX_HOME",
            "CLAUDE_CONFIG_DIR",
            "AGENTS_NATS_URL",
            "TMUX",
            "XDG_RUNTIME_DIR",
        }
        or key.startswith("PROMPT_COACH_")
    }
    resolved_home = codex_home()
    if resolved_home:
        child_env["CODEX_HOME"] = resolved_home
    subprocess.Popen(
        [sys.executable, str(script), "run", str(job_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=child_env,
        start_new_session=True,
        close_fds=True,
    )
    return 0


def capabilities_fixture(root, job_id):
    """Hand the Claude capability list to the shared core.

    The core reads PROMPT_COACH_CAPABILITIES_FILE when it is set, which is the
    one seam that lets a provider supply its own library without a second copy
    of process_job.
    """
    path = root / "jobs" / ("%s.capabilities.json" % job_id)
    CORE.atomic_json(path, load_capabilities())
    return path


def run_job(path):
    job_path = Path(path)
    try:
        job = json.loads(job_path.read_text())
    except (OSError, ValueError):
        return 0
    wait = float(job.get("not_before") or 0) - time.time()
    if wait > 0:
        time.sleep(wait)
    root = CORE.state_dir()
    stamp = CORE.dedupe_stamp(root, job.get("session_id", ""), job.get("prompt", ""))
    try:
        if stamp.read_text().strip() != job.get("job_id"):
            CORE.append_event(
                root, {**CORE.base_event(job, time.time()), "event": "blocked", "decision": "coalesced"}
            )
            return 0
    except OSError:
        return 0

    # The job's own prompt is the question. It is never replaced by whatever
    # the transcript happens to end with: by the time a worker wakes, the user
    # may have typed twice more, and coaching the newest prompt under an older
    # job's identity answers a question nobody asked in a session that already
    # moved on. Other recent prompts stay, as bounded context only.
    history = [value for value in recent_prompts(job.get("session_id", "")) if value != job.get("prompt")]
    job["recent_user_prompts"] = history[-3:]

    fixture = capabilities_fixture(root, job.get("job_id", uuid.uuid4().hex))
    os.environ["PROMPT_COACH_CAPABILITIES_FILE"] = str(fixture)

    def current_delivery(_pane, record):
        try:
            if stamp.read_text().strip() == job.get("job_id"):
                deliver(job, record)
        except OSError:
            pass

    try:
        CORE.process_job(job, deliver=current_delivery)
    finally:
        # Only this job's own stamp is removed, and only while it still names
        # this job: a later duplicate of the same prompt owns it by then.
        with contextlib.suppress(OSError):
            if stamp.read_text().strip() == job.get("job_id"):
                stamp.unlink()
        for leftover in (fixture, job_path):
            with contextlib.suppress(OSError):
                leftover.unlink()
    return 0


def hook(payload):
    """UserPromptSubmit: relay what is pending, then queue this prompt.

    Both halves in one process. Two hook entries would pay Python startup
    twice on the one event that blocks the start of every turn.
    """
    root = CORE.state_dir()
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
    relay = claim_pending_relay(root, session_id)
    if relay:
        print(json.dumps(relay, ensure_ascii=False))
    return enqueue(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Metered Luna prompt coach for Claude Code")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hook")
    sub.add_parser("enqueue")
    sub.add_parser("turn-end")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("job")
    relay_parser = sub.add_parser("relay")
    relay_parser.add_argument("--session", required=True)
    library_parser = sub.add_parser("library")
    library_parser.add_argument("query", nargs="?", default="")
    args = parser.parse_args(argv)

    if CORE is None:
        return 0
    root = CORE.state_dir()

    if args.command in {"hook", "enqueue", "turn-end"}:
        try:
            payload = json.load(sys.stdin)
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if args.command == "turn-end":
            turn_end(root, str(payload.get("session_id") or payload.get("sessionId") or ""))
            return 0
        return hook(payload) if args.command == "hook" else enqueue(payload)
    if args.command == "run":
        return run_job(args.job)
    if args.command == "relay":
        relay = claim_pending_relay(root, args.session)
        if relay:
            print(json.dumps(relay, ensure_ascii=False))
        return 0
    if args.command == "library":
        query = args.query.casefold()
        for row in sorted(load_capabilities(), key=lambda value: value["id"]):
            searchable = "%s %s %s" % (row.get("id", ""), row.get("surface", ""), row.get("description", ""))
            if not query or query in searchable.casefold():
                print("%s\t[%s] %s\t%s" % (row["id"], row.get("surface", ""), row.get("invocation", ""), row.get("description", "")))
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        # A coach that breaks a turn is worse than no coach.
        raise SystemExit(0)
