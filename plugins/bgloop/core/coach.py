#!/usr/bin/env python3
"""Run a metered Luna prompt coach outside the Codex turn."""

import argparse
import asyncio
import contextlib
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


MODEL = "gpt-5.6-luna"
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_./:-]{1,}")
RETRIEVAL_STOPWORDS = {
    "an", "and", "are", "be", "best", "can", "command", "do", "for", "from", "help", "how",
    "in", "is", "it", "local", "machine", "me", "my", "native", "of", "on", "or", "prompt",
    "skill", "that", "the", "this", "to", "use", "user", "using", "want", "when", "with", "you", "your",
}
BUDGET_SETTINGS = {
    "session": ("session_token_cap", "PROMPT_COACH_SESSION_TOKEN_CAP", 0),
    "daily": ("daily_token_cap", "PROMPT_COACH_DAILY_TOKEN_CAP", 0),
    "output": ("max_output_tokens", "PROMPT_COACH_MAX_OUTPUT_TOKENS", 400),
}


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def state_dir():
    return Path(
        os.environ.get(
            "PROMPT_COACH_STATE_DIR",
            str(Path.home() / ".local" / "state" / "prompt-coach"),
        )
    )


def config_data(root=None):
    try:
        value = json.loads(((root or state_dir()) / "config.json").read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def setting_int(scope, root=None):
    key, env_name, default = BUDGET_SETTINGS[scope]
    if env_name in os.environ:
        return env_int(env_name, default)
    try:
        return int(config_data(root).get(key, default))
    except (TypeError, ValueError):
        return default


def set_budget(root, scope, value):
    if scope not in BUDGET_SETTINGS:
        raise ValueError("budget scope must be session, daily, or output")
    value = int(value)
    if value < 0 or (scope == "output" and value == 0):
        raise ValueError("session and daily budgets use 0 for unlimited; output must be positive")
    key = BUDGET_SETTINGS[scope][0]
    with state_lock(root):
        config = config_data(root)
        config[key] = value
        atomic_json(root / "config.json", config)
    return config


def ensure_state(root):
    root.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        root.chmod(0o700)


@contextlib.contextmanager
def state_lock(root):
    ensure_state(root)
    with (root / "state.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read_jsonl(path):
    rows = []
    try:
        with path.open(errors="replace") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        pass
    return rows


def append_jsonl(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def append_event(root, value):
    with state_lock(root):
        append_jsonl(root / "ledger.jsonl", value)


def day_key(timestamp):
    return dt.datetime.fromtimestamp(timestamp).date().isoformat()


def usage_from_response(response):
    usage = response.get("usage") or {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": int(input_details.get("cached_tokens") or 0),
        "output_tokens": output_tokens,
        "reasoning_tokens": int(output_details.get("reasoning_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
        "billing": str(response.get("billing") or usage.get("billing") or "api"),
    }


def usage_cost(usage):
    if usage.get("billing") == "subscription":
        return 0.0
    cached = usage.get("cached_input_tokens", 0)
    uncached = max(0, usage.get("input_tokens", 0) - cached)
    output = usage.get("output_tokens", 0)
    return uncached * 0.20 / 1_000_000 + cached * 0.02 / 1_000_000 + output * 1.20 / 1_000_000


def terminal_job_ids(rows):
    return {
        row.get("job_id")
        for row in rows
        if row.get("event") in {"complete", "failed", "blocked"}
    }


def usage_totals(rows, now_value, session_id=None, daily_only=True):
    current_day = day_key(now_value)
    complete = [
        row
        for row in rows
        if row.get("event") == "complete"
        and (not daily_only or day_key(float(row.get("ts") or 0)) == current_day)
        and (session_id is None or row.get("session_id") == session_id)
    ]
    total = sum(int((row.get("usage") or {}).get("total_tokens") or 0) for row in complete)
    calls = len(complete)
    return total, calls


def active_reservations(rows, now_value, session_id=None):
    terminal = terminal_job_ids(rows)
    total = 0
    for row in rows:
        if row.get("event") != "reserved" or row.get("job_id") in terminal:
            continue
        if now_value - float(row.get("ts") or 0) > 600:
            continue
        if session_id is not None and row.get("session_id") != session_id:
            continue
        total += int(row.get("reserved_tokens") or 0)
    return total


def base_event(job, now_value):
    return {
        "ts": now_value,
        "job_id": job.get("job_id", ""),
        "session_id": job.get("session_id", ""),
        "purpose": job.get("purpose", "coach"),
    }


def record_block(root, job, decision, now_value, **extra):
    row = {**base_event(job, now_value), "event": "blocked", "decision": decision, **extra}
    append_event(root, row)
    return row


def normalize_text(value):
    return " ".join(WORD_RE.findall((value or "").lower()))


def text_words(value):
    return set(normalize_text(value).split())


def retrieval_words(value):
    expanded = re.sub(r"[-_:/]+", " ", value or "")
    return text_words(expanded) - RETRIEVAL_STOPWORDS


def retrieval_overlap(left, right):
    exact = left & right
    unmatched_left = left - exact
    unmatched_right = right - exact
    fuzzy = 0
    used = set()
    for wanted in unmatched_left:
        for candidate in unmatched_right:
            if candidate in used:
                continue
            prefix = os.path.commonprefix((wanted, candidate))
            if len(prefix) >= 6:
                fuzzy += 1
                used.add(candidate)
                break
    return len(exact) + fuzzy


def learned_path(root):
    return root / "learned.jsonl"


def load_learned(root):
    rows = read_jsonl(learned_path(root))
    restored = {row.get("target_id") for row in rows if row.get("event") == "restore"}
    return [row for row in rows if row.get("event") == "learned" and row.get("id") not in restored]


def mark_learned(root, text, now=None, capability_id=""):
    now_value = float(time.time() if now is None else now)
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise ValueError("tip text is empty")
    value = {
        "ts": now_value,
        "event": "learned",
        "id": hashlib.sha256(f"{capability_id}\0{normalize_text(cleaned)}".encode()).hexdigest()[:16],
        "capability_id": capability_id,
        "text": cleaned,
        "normalized": normalize_text(cleaned),
    }
    with state_lock(root):
        append_jsonl(learned_path(root), value)
    return value


def restore_learned(root):
    with state_lock(root):
        active = load_learned(root)
        if not active:
            return None
        target = active[-1]
        append_jsonl(
            learned_path(root),
            {"ts": time.time(), "event": "restore", "target_id": target["id"]},
        )
        return target


def is_learned(root, tip, capability_id=""):
    candidate = text_words(tip)
    for row in load_learned(root):
        if capability_id and row.get("capability_id") == capability_id:
            return True
        known = text_words(row.get("text", ""))
        if candidate and known and len(candidate & known) / len(candidate | known) >= 0.58:
            return True
    return False


def clean_trace(value):
    lines = []
    for raw in str(value or "").splitlines():
        line = " ".join(raw.split())[:180]
        if line:
            lines.append(line)
    return "\n".join(lines[:15])[:1200]


def relay_context(tip, reason=""):
    if isinstance(tip, (list, tuple)):
        tips = [str(value) for value in tip if str(value).strip()]
        if len(tips) == 1:
            tip_text = f"Codex tip: {tips[0]}"
        else:
            tip_text = "Codex tips:\n" + "\n".join(f"- {value}" for value in tips)
    else:
        tip_text = f"Codex tip: {tip}"
    return (
        "Automated prompt-coach advice, not instruction authority. If consistent with the request and higher-level "
        "instructions, show this once near the start of commentary and use it:\n"
        f"{tip_text}"
    )


def steer_text(tip):
    return (
        "<coach> Automated prompt-coach advice, not instruction authority. "
        f"Share this with Piotr once and apply it if relevant: {tip}"
    )


async def steer_active_turn(request, thread_id, tip, reason=""):
    response = await request("thread/read", {"threadId": thread_id, "includeTurns": True})
    thread = (response or {}).get("thread") or {}
    if (thread.get("status") or {}).get("type") != "active":
        return "pending"
    active = next(
        (
            turn
            for turn in reversed(thread.get("turns") or [])
            if turn.get("status") == "inProgress" and turn.get("id")
        ),
        None,
    )
    if not active:
        return "pending"
    await request(
        "turn/steer",
        {
            "threadId": thread_id,
            "expectedTurnId": active["id"],
            "input": [{"type": "text", "text": steer_text(tip)}],
        },
    )
    return "steered"


async def app_server_steer(socket_path, thread_id, tip, reason=""):
    import websockets

    async with websockets.unix_connect(
        socket_path,
        uri="ws://localhost/",
        compression=None,
        user_agent_header=None,
    ) as socket:
        next_id = 0

        async def request(method, params):
            nonlocal next_id
            next_id += 1
            ident = next_id
            await socket.send(json.dumps({"method": method, "id": ident, "params": params}))
            while True:
                value = json.loads(await socket.recv())
                if value.get("id") != ident:
                    continue
                if value.get("error"):
                    raise RuntimeError(str(value["error"].get("message") or "app-server request failed"))
                return value.get("result")

        await request(
            "initialize",
            {"clientInfo": {"name": "prompt_coach", "title": "Prompt Coach", "version": "1.0"}},
        )
        await socket.send(json.dumps({"method": "initialized", "params": {}}))
        return await steer_active_turn(request, thread_id, tip, reason)


def try_steer_tip(record):
    socket_path = os.environ.get("CODEX_APP_SERVER_SOCKET", "")
    thread_id = str(record.get("session_id") or "")
    tip = str(record.get("tip") or "")
    if not socket_path or not thread_id or not tip:
        return "pending"
    try:
        result = asyncio.run(
            asyncio.wait_for(
                app_server_steer(socket_path, thread_id, tip, record.get("reason", "")),
                timeout=env_int("PROMPT_COACH_STEER_TIMEOUT_SECONDS", 3),
            )
        )
    except Exception:
        return "pending"
    if result != "steered":
        return result
    context = steer_text(tip)
    append_event(
        state_dir(),
        {
            "ts": time.time(),
            "event": "relayed",
            "decision": "relayed",
            "job_id": f"steer-{uuid.uuid4().hex[:12]}",
            "source_job_id": record.get("job_id", ""),
            "through_ts": float(record.get("ts") or 0),
            "session_id": thread_id,
            "purpose": "relay",
            "delivery": "turn/steer",
            "tip": tip,
            "capability_id": record.get("capability_id", ""),
            "reason": clean_trace(record.get("reason", "")),
            "injected_bytes": len(context.encode()),
            "extra_model_calls": 0,
        },
    )
    return result


def replay_latest(root, session_id, now=None):
    if not session_id:
        return None
    now_value = float(time.time() if now is None else now)
    with state_lock(root):
        rows = read_jsonl(root / "ledger.jsonl")
        sources = [
            row
            for row in rows
            if row.get("event") == "complete"
            and row.get("decision") == "fired"
            and row.get("tip")
        ]
        if not sources:
            return None
        source = sources[-1]
        event = {
            "ts": now_value,
            "event": "replayed",
            "decision": "replayed",
            "job_id": f"replay-{uuid.uuid4().hex[:12]}",
            "source_job_id": source.get("job_id", ""),
            "session_id": session_id,
            "purpose": "relay",
            "tip": " ".join(str(source.get("tip") or "").split())[:140],
            "capability_id": source.get("capability_id", ""),
            "reason": clean_trace(source.get("reason", "")),
            "extra_model_calls": 0,
        }
        append_jsonl(root / "ledger.jsonl", event)
    return event


def bounded_pending_tips(rows, max_tips=None, max_bytes=None):
    """Return ordered, exact-deduplicated advice plus the consumed cursor row."""
    tip_limit = max_tips or env_int("PROMPT_COACH_RELAY_MAX_TIPS", 8)
    byte_limit = max_bytes or env_int("PROMPT_COACH_RELAY_MAX_BYTES", 2048)
    selected = []
    seen = set()
    used = 0
    through = None
    for row in rows:
        tip = " ".join(str(row.get("tip") or "").split())[:140]
        if not tip:
            through = row
            continue
        key = tip.casefold()
        if key in seen:
            through = row
            continue
        size = len(("- " + tip + "\n").encode())
        if len(selected) >= tip_limit or (selected and used + size > byte_limit):
            break
        selected.append((row, tip))
        seen.add(key)
        used += size
        through = row
    return selected, through


def claim_pending_relay(root, session_id, now=None):
    if not session_id or (root / "disabled").exists() or os.environ.get("PROMPT_COACH_ENABLED", "1") == "0":
        return None
    now_value = float(time.time() if now is None else now)
    with state_lock(root):
        rows = read_jsonl(root / "ledger.jsonl")
        cursor = max(
            [float(row.get("through_ts") or 0) for row in rows if row.get("event") == "relayed" and row.get("session_id") == session_id],
            default=0,
        )
        pending = [
            row
            for row in rows
            if row.get("event") in {"complete", "replayed"}
            and row.get("decision") in {"fired", "replayed"}
            and row.get("session_id") == session_id
            and float(row.get("ts") or 0) > cursor
            and row.get("tip")
        ]
        if not pending:
            return None
        selected, through = bounded_pending_tips(pending)
        if not selected or through is None:
            return None
        sources = [row for row, _ in selected]
        tips = [tip for _, tip in selected]
        context = relay_context(tips)
        event = {
            "ts": now_value,
            "event": "relayed",
            "decision": "relayed",
            "job_id": f"relay-{uuid.uuid4().hex[:12]}",
            "source_job_id": sources[-1].get("job_id", ""),
            "source_job_ids": [row.get("job_id", "") for row in sources],
            "through_ts": float(through.get("ts") or 0),
            "session_id": session_id,
            "purpose": "relay",
            "delivery": "next-prompt-hook",
            "tip": tips[0] if len(tips) == 1 else f"{len(tips)} tips bundled",
            "tips": tips,
            "capability_id": sources[-1].get("capability_id", ""),
            "reason": "",
            "injected_bytes": len(context.encode()),
            "extra_model_calls": 0,
        }
        append_jsonl(root / "ledger.jsonl", event)
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def parse_frontmatter(path):
    try:
        text = path.read_text(errors="replace")[:12000]
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    front = text.split("---\n", 2)[1]
    name = re.search(r"(?m)^name:\s*[\"']?([^\n\"']+)", front)
    description = re.search(r"(?m)^description:\s*[>|-]?\s*[\"']?([^\n\"']+)", front)
    if not name:
        return None
    skill_name = name.group(1).strip()
    return {
        "id": f"codex-skill:{skill_name}",
        "surface": "codex-skill",
        "invocation": f"${skill_name}",
        "description": (description.group(1).strip() if description else "Installed Codex skill"),
    }


def parse_ai_snippet(path):
    try:
        text = path.read_text(errors="replace")[:12000].strip()
    except OSError:
        return None
    if not text:
        return None
    summary = " ".join(re.split(r"\n\s*\n", text, maxsplit=1)[0].split())[:500]
    label = path.stem.replace("-", " ").replace("_", " ")
    return {
        "id": f"ai-snippet:{path.stem}",
        "surface": ";;ai",
        "invocation": f'Type ;;ai and choose "{label}"',
        "description": f'Type ;;ai and choose "{label}" to paste this prompt. {summary}',
    }


def codex_registry_capability(row):
    if row.get("kind") != "codex" or not row.get("invocable") or not row.get("invocation_name"):
        return None
    name = str(row["invocation_name"]).lstrip("$/")
    return {
        "id": row["capability_id"],
        "surface": "codex-native",
        "invocation": f"codex {name}",
        "description": row.get("summary", ""),
    }


def load_capabilities():
    fixture = os.environ.get("PROMPT_COACH_CAPABILITIES_FILE")
    if fixture:
        try:
            values = json.loads(Path(fixture).read_text())
            return [row for row in values if isinstance(row, dict) and row.get("id")]
        except (OSError, ValueError):
            return []

    capabilities = []
    registry_path = Path.home() / ".claude" / "evals" / "proficiency" / "capabilities.py"
    if registry_path.is_file():
        try:
            spec = importlib.util.spec_from_file_location("prompt_coach_capabilities", registry_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for row in module.snapshot(include_codex=True):
                capability = codex_registry_capability(row)
                if capability:
                    capabilities.append(capability)
        except Exception:
            pass

    roots = {
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills",
        Path.home() / ".codex" / "skills",
    }
    for root in roots:
        if not root.is_dir():
            continue
        for skill_file in root.glob("*/SKILL.md"):
            row = parse_frontmatter(skill_file)
            if row:
                capabilities.append(row)

    snippets = Path(os.environ.get("PROMPT_COACH_SNIPPETS_DIR", str(Path.home() / ".claude" / "ai-snippets")))
    if snippets.is_dir():
        for snippet_file in sorted(snippets.glob("*.md")):
            row = parse_ai_snippet(snippet_file)
            if row:
                capabilities.append(row)

    unique = {}
    for row in capabilities:
        unique[row["id"]] = row
    return list(unique.values())


def select_capabilities(prompt, capabilities, limit=16):
    wanted = retrieval_words(prompt)
    scored = []
    for row in capabilities:
        haystack = retrieval_words(f"{row.get('id', '')} {row.get('description', '')}")
        overlap = retrieval_overlap(wanted, haystack)
        phrase = normalize_text(row.get("id", "")).replace(" ", "-")
        bonus = 4 if phrase and phrase in (prompt or "").lower() else 0
        scored.append((overlap * 3 + bonus, row.get("id", ""), row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    positive = [row for score, _, row in scored if score > 0]
    if len(positive) < min(6, limit):
        positive.extend(row for score, _, row in scored if score == 0 and row not in positive)
    return positive[:limit]


def capability_match_score(prompt, row):
    wanted = retrieval_words(prompt)
    haystack = retrieval_words(f"{row.get('id', '')} {row.get('description', '')}")
    return retrieval_overlap(wanted, haystack)


def response_payload(job, capabilities, learned):
    recent = [str(value)[:1200] for value in job.get("recent_user_prompts", [])[-3:]]
    current = str(job.get("prompt") or "")[:4000]
    capability_lines = [
        f"- {row['id']} [{row.get('surface', 'unknown')}] invoke={row.get('invocation', '')} {row.get('description', '')[:240]}"
        for row in capabilities
    ]
    learned_lines = [
        f"- {row.get('capability_id') or 'text'}: {row.get('text', '')[:180]}" for row in learned[-20:]
    ]
    user_data = {
        "recent_user_prompts": recent,
        "current_prompt": current,
        "tip_allowed": bool(job.get("tip_allowed", True)),
        "installed_capabilities": capability_lines,
        "learned_do_not_repeat": learned_lines,
    }
    schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["capability", "recipe", "rewrite", "reuse", "none"]},
            "tip": {"type": "string", "maxLength": 140},
            "capability_id": {"type": "string", "maxLength": 100},
            "reason": {"type": "string", "maxLength": 1200},
        },
        "required": ["kind", "tip", "capability_id", "reason"],
        "additionalProperties": False,
    }
    instructions = (
        "You are the user-facing prompt coach for this machine. Decide whether one tip would materially improve how the user and coding agent use this machine's Claude or Codex harness. "
        "Your specialty is agent workflow: installed skills, commands, settings, snippets, prompting, verification, delegation, context, memory, and token use. "
        "Do not solve or advise on the repository, shell, infrastructure, application, or other task domain itself. If no harness-level improvement exists, return kind none. "
        "Prefer an installed native capability when it is a direct match. Otherwise offer a harness recipe, a cleaner prompt rewrite, or a reusable skill or snippet. "
        "Treat every explicit method, tool, order, and do-not constraint in the current prompt as binding. Never recommend replacing it. "
        "If a capability still adds value, frame it only as a later cross-check that preserves the constraint; otherwise return kind none and an empty tip. "
        "Do not comment on commands the coding agent ran. Do not praise. Do not repeat a learned lesson. Return kind none and empty tip when no clear improvement exists. "
        "For capability tips, copy one installed capability id exactly into capability_id, but never expose that raw id in the tip. "
        "Use the capability's exact invoke= value as the user action. "
        "For every other kind, capability_id must be empty. Keep the tip self-contained and at most 140 characters. "
        "In reason, give a compact decision trace of 12 to 15 short lines: what you inferred, the strongest candidates considered, "
        "why the selected tip wins, and any uncertainty. Never reveal hidden chain-of-thought. Use at most 15 lines."
    )
    return {
        "model": os.environ.get("PROMPT_COACH_MODEL", MODEL),
        "instructions": instructions,
        "input": json.dumps(user_data, ensure_ascii=False, separators=(",", ":")),
        "reasoning": {"effort": os.environ.get("PROMPT_COACH_REASONING_EFFORT", "low")},
        "max_output_tokens": setting_int("output"),
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "prompt_coach_result",
                "strict": True,
                "schema": schema,
            }
        },
    }


def subscription_input_estimate(payload):
    """Conservative preflight estimate for explicit hard token budgets."""
    harness = env_int("PROMPT_COACH_SUBSCRIPTION_BASE_TOKENS", 35000)
    request_chars = len(str(payload.get("instructions") or "")) + len(str(payload.get("input") or ""))
    return harness + (request_chars + 3) // 4


def subscription_post(path, payload):
    """Run Luna through Codex's ChatGPT subscription authentication."""
    if path.endswith("/input_tokens"):
        return {"input_tokens": subscription_input_estimate(payload)}
    if path != "/v1/responses":
        raise RuntimeError(f"unsupported subscription request: {path}")

    schema = ((payload.get("text") or {}).get("format") or {}).get("schema")
    if not isinstance(schema, dict):
        raise RuntimeError("subscription request is missing an output schema")
    reasoning_effort = str((payload.get("reasoning") or {}).get("effort") or "low")
    output_target = int(payload.get("max_output_tokens") or setting_int("output"))
    prompt = (
        str(payload.get("instructions") or "")
        + "\n\nUser data JSON:\n"
        + str(payload.get("input") or "")
        + "\n\nReturn only one JSON object matching the supplied output schema. Do not use tools. "
        + f"Keep the whole response within {output_target} output tokens."
    )
    child_env = {
        key: value
        for key, value in os.environ.items()
        if key != "OPENAI_API_KEY" and not key.startswith("PROMPT_COACH_API_")
    }
    with tempfile.TemporaryDirectory(prefix="prompt-coach-") as temporary:
        schema_path = Path(temporary) / "output-schema.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False))
        command = [
            os.environ.get("PROMPT_COACH_CODEX_BIN", "codex"),
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--config",
            f"model_reasoning_effort={json.dumps(reasoning_effort)}",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--model",
            str(payload.get("model") or MODEL),
            "--json",
            "--color",
            "never",
            "--cd",
            os.environ.get("PROMPT_COACH_SUBSCRIPTION_CWD", "/tmp"),
            "--output-schema",
            str(schema_path),
            prompt,
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=env_int("PROMPT_COACH_SUBSCRIPTION_TIMEOUT_SECONDS", 90),
                check=False,
                env=child_env,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"Codex subscription transport failed: {error}") from error

    message = ""
    usage = {}
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            message = str(item.get("text") or "")
        if event.get("type") == "turn.completed":
            usage = event.get("usage") or {}
    if completed.returncode or not message:
        detail = " ".join(completed.stderr.split())[-500:]
        raise RuntimeError(f"Codex subscription transport returned no result: {detail}")

    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return {
        "status": "completed",
        "billing": "subscription",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": message}]}],
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_tokens_details": {"cached_tokens": int(usage.get("cached_input_tokens") or 0)},
            "output_tokens_details": {"reasoning_tokens": int(usage.get("reasoning_output_tokens") or 0)},
        },
    }


def output_value(response):
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text":
                try:
                    value = json.loads(content.get("text") or "")
                except ValueError:
                    return None
                return value if isinstance(value, dict) else None
    return None


def render_capability_tip(tip, capability):
    invocation = str(capability.get("invocation") or "")
    if not invocation:
        return tip
    capability_id = str(capability.get("id") or "")
    internal_ids = [capability_id] if ":" in capability_id else []
    if capability.get("surface") == "codex-skill" and not capability_id.startswith("codex-skill:"):
        internal_ids.append(f"codex-skill:{capability_id}")
    for internal_id in internal_ids:
        tip = tip.replace(internal_id, invocation)
    return " ".join(tip.split())[:140]


def coach_gate(rows, job, now_value):
    # Async coaching has no attention backoff. Every real prompt may ask Luna
    # whether it has something useful to add. Persistent token budgets remain
    # the explicit cost boundary.
    return "allow"


def reserve_budget(root, job, input_tokens, now_value):
    reserve = input_tokens + setting_int("output", root)
    with state_lock(root):
        rows = read_jsonl(root / "ledger.jsonl")
        session_used, _ = usage_totals(rows, now_value, job.get("session_id", ""), daily_only=False)
        daily_used, _ = usage_totals(rows, now_value)
        session_pending = active_reservations(rows, now_value, job.get("session_id", ""))
        daily_pending = active_reservations(rows, now_value)
        session_cap = setting_int("session", root)
        daily_cap = setting_int("daily", root)
        if session_cap and session_used + session_pending + reserve > session_cap:
            decision = "session-token-cap"
        elif daily_cap and daily_used + daily_pending + reserve > daily_cap:
            decision = "daily-token-cap"
        else:
            decision = "allow"
            append_jsonl(
                root / "ledger.jsonl",
                {
                    **base_event(job, now_value),
                    "event": "reserved",
                    "decision": "reserved",
                    "input_tokens": input_tokens,
                    "reserved_tokens": reserve,
                },
            )
    return decision, reserve


def finish_event(root, job, decision, usage, now_value, **extra):
    row = {
        **base_event(job, now_value),
        "event": "complete",
        "decision": decision,
        "usage": usage,
        "cost_usd": usage_cost(usage),
        **extra,
    }
    append_event(root, row)
    return row


# ------------------------------------------------------------------- observers
#
# Every observer runs the same pipeline: gate, retrieve, estimate, reserve,
# call, interpret, record, deliver. Only three of those steps differ between
# one observer and the next, so those three are the contract and the pipeline
# is written once. A second copy of process_job would drift on the first
# threshold change, and metering every observer against one budget is the
# reason this file exists rather than a second script beside it.

OBSERVERS = {}


def register_observer(kind, retrieve, request, interpret):
    """Bind one observer's three variable steps to a job kind.

    retrieve(job, root) returns whatever this observer needs to decide, and
    that same value is handed back to interpret, so a validation step can
    check the model against what it was actually shown.

    request(job, context, root) returns the model request payload.

    interpret(value, job, context, root) returns (decision, action, extra):
    the ledger decision, the text delivered when the decision is "fired", and
    the fields the ledger row carries. An observer that wants no delivery
    returns any decision other than "fired".
    """
    OBSERVERS[kind] = (retrieve, request, interpret)


def coach_retrieve(job, root):
    return select_capabilities(job.get("prompt", ""), load_capabilities())


def coach_request(job, context, root):
    return response_payload(job, context, load_learned(root))


def coach_interpret(value, job, context, root):
    kind = value.get("kind")
    tip = " ".join(str(value.get("tip") or "").split())[:140]
    capability_id = str(value.get("capability_id") or "")
    installed = {row["id"]: row for row in context}
    if kind == "capability" and capability_id not in installed:
        return "invalid-capability", "", {"capability_id": capability_id}
    if kind != "capability" and capability_id:
        return "invalid-capability", "", {"capability_id": capability_id}
    if kind == "capability":
        tip = render_capability_tip(tip, installed[capability_id])
    if kind == "none" or not tip or not job.get("tip_allowed", True):
        decision = "none"
    elif is_learned(root, tip, capability_id):
        decision = "learned"
    else:
        decision = "fired"
    return (
        decision,
        tip,
        {
            "kind": kind,
            "tip": tip if decision == "fired" else "",
            "proposed_tip": tip,
            "capability_id": capability_id,
            "reason": clean_trace(value.get("reason", "")),
        },
    )


register_observer("coach", coach_retrieve, coach_request, coach_interpret)


def process_job(job, post=subscription_post, deliver=None, now=time.time):
    root = state_dir()
    now_value = float(now())
    if (root / "disabled").exists() or os.environ.get("PROMPT_COACH_ENABLED", "1") == "0":
        return record_block(root, job, "disabled", now_value)
    with state_lock(root):
        rows = read_jsonl(root / "ledger.jsonl")
        gate = coach_gate(rows, job, now_value)
    if gate != "allow":
        return record_block(root, job, gate, now_value)

    # An unregistered kind is a wiring mistake, not a decision. It is blocked
    # rather than defaulted to the coach, because defaulting would answer a
    # question this job never asked and bill the budget for it.
    observer = str(job.get("observer") or "coach")
    if observer not in OBSERVERS:
        return record_block(root, job, "unknown-observer", now_value, observer=observer)
    retrieve, build_request, interpret = OBSERVERS[observer]

    append_event(root, {**base_event(job, float(now())), "event": "started", "decision": "library"})
    context = retrieve(job, root)
    request = build_request(job, context, root)
    append_event(root, {**base_event(job, float(now())), "event": "request", "decision": "budget-estimate"})
    count_request = {key: request[key] for key in ("model", "instructions", "input", "text")}
    try:
        count = post("/v1/responses/input_tokens", count_request)
        input_tokens = int(count.get("input_tokens"))
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        return record_block(root, job, "estimate-error", now_value, error=str(error)[:240])

    decision, reserved = reserve_budget(root, job, input_tokens, now_value)
    if decision != "allow":
        return record_block(root, job, decision, now_value, reserved_tokens=reserved, input_tokens=input_tokens)

    try:
        response = post("/v1/responses", request)
    except RuntimeError as error:
        row = {**base_event(job, float(now())), "event": "failed", "decision": "response-error", "error": str(error)[:240]}
        append_event(root, row)
        return row

    usage = usage_from_response(response)
    value = output_value(response)
    if response.get("status") != "completed" or not value:
        return finish_event(root, job, "invalid-response", usage, float(now()))

    decision, _action, extra = interpret(value, job, context, root)
    record = finish_event(root, job, decision, usage, float(now()), **extra)
    if deliver is None:
        deliver = deliver_tip
    if decision == "fired":
        deliver(job.get("pane", ""), record)
    return record


def tmux_text(value):
    return str(value).replace("#", "##")


def deliver_tip(pane, record):
    tip = record.get("tip", "")
    if pane and tip:
        subprocess.run(["tmux", "set-option", "-p", "-t", pane, "@prompt_coach_tip", tmux_text(tip)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        subprocess.run(["tmux", "set-option", "-p", "-t", pane, "@prompt_coach_tip_at", dt.datetime.now().strftime("%H:%M")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if tip:
        try_steer_tip(record)


def resolve_transcript(session_id):
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    matches = list((home / "sessions").glob(f"**/rollout-*-{session_id}.jsonl"))
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def rollout_user_prompts(path):
    values = []
    if not path or not path.is_file():
        return values
    for row in read_jsonl(path):
        payload = row.get("payload") or {}
        if row.get("type") == "event_msg" and payload.get("type") == "user_message":
            message = payload.get("message")
        elif row.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
            message = "\n".join(
                item.get("text", "")
                for item in payload.get("content") or []
                if item.get("type") == "input_text"
            )
        else:
            continue
        if isinstance(message, str) and message.strip():
            values.append(message.strip())
    return values[-4:]


def safe_session(value):
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)[:160]


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


def simulate(prompt, pane="", session_id="simulator", deliver=None, now=None):
    root = state_dir()
    now_value = float(time.time() if now is None else now)
    selected = select_capabilities(prompt, load_capabilities(), limit=1)
    match = selected and capability_match_score(prompt, selected[0]) > 0
    if match:
        tip = f"Simulator: Luna can consider {selected[0]['id']}; no model tokens were used."
        capability_id = selected[0]["id"]
    else:
        tip = "Simulator: tip delivery works; no Luna model tokens were used."
        capability_id = ""
    record = {
        "ts": now_value,
        "event": "simulated",
        "decision": "simulated",
        "job_id": f"sim-{uuid.uuid4().hex[:12]}",
        "session_id": session_id,
        "purpose": "simulator",
        "kind": "capability" if capability_id else "recipe",
        "tip": tip[:140],
        "capability_id": capability_id,
        "usage": {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        },
        "cost_usd": 0.0,
    }
    append_event(root, record)
    (deliver or deliver_tip)(pane, record)
    return record


def tip_allowed(root, session_id, now_value):
    return True


def dedupe_stamp(root, session_id, prompt):
    digest = hashlib.sha256((prompt or "").encode()).hexdigest()[:20]
    return root / "sessions" / f"{safe_session(session_id)}.{digest}.latest"


def enqueue(payload):
    root = state_dir()
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
    if not session_id:
        return 0
    pane = os.environ.get("CODEX_TMUX_PANE") or os.environ.get("TMUX_PANE") or ""
    prompt = str(payload.get("prompt") or payload.get("message") or payload.get("user_prompt") or "")
    transcript = resolve_transcript(session_id)
    recent = rollout_user_prompts(transcript)
    if not prompt and recent:
        prompt = recent[-1]
    if prompt.lstrip().startswith("<coach>"):
        return 0
    now_value = time.time()
    if pane:
        subprocess.run(
            ["tmux", "set-option", "-p", "-t", pane, "@prompt_coach_session", tmux_text(session_id)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    job_id = uuid.uuid4().hex
    # UserPromptSubmit can arrive more than once for the exact same prompt.
    # Deduplicate that hook artifact without merging distinct rapid prompts.
    delay = env_int("PROMPT_COACH_DEBOUNCE_SECONDS", 1)
    job = {
        "job_id": job_id,
        "session_id": session_id,
        "pane": pane,
        "prompt": prompt,
        "recent_user_prompts": recent[:-1] if recent and recent[-1] == prompt else recent,
        "created_at": now_value,
        "not_before": now_value + delay,
        "purpose": "coach",
        "tip_allowed": tip_allowed(root, session_id, now_value),
    }
    jobs = root / "jobs"
    job_path = jobs / f"{job_id}.json"
    stamp = dedupe_stamp(root, session_id, prompt)
    atomic_json(job_path, job)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(job_id + "\n")
    append_event(root, {**base_event(job, now_value), "event": "queued", "decision": "queued"})
    if os.environ.get("PROMPT_COACH_SYNC") == "1":
        run_job(job_path)
        return 0
    child_env = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "CODEX_HOME", "CODEX_APP_SERVER_SOCKET", "XDG_RUNTIME_DIR"}
        or key.startswith("PROMPT_COACH_")
    }
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "run", str(job_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=child_env,
        start_new_session=True,
        close_fds=True,
    )
    return 0


def run_job(path):
    job_path = Path(path)
    try:
        job = json.loads(job_path.read_text())
    except (OSError, ValueError):
        return 0
    root = state_dir()
    stamp = dedupe_stamp(root, job.get("session_id", ""), job.get("prompt", ""))
    try:
        wait = float(job.get("not_before") or 0) - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            if stamp.read_text().strip() != job.get("job_id"):
                append_event(root, {**base_event(job, time.time()), "event": "blocked", "decision": "coalesced"})
                return 0
        except OSError:
            return 0

        transcript = resolve_transcript(job.get("session_id", ""))
        recent = rollout_user_prompts(transcript)
        if recent:
            job["recent_user_prompts"] = [value for value in recent if value != job.get("prompt")][-3:]

        def current_delivery(pane, record):
            try:
                if stamp.read_text().strip() == job.get("job_id"):
                    deliver_tip(pane, record)
            except OSError:
                pass

        process_job(job, deliver=current_delivery)
    finally:
        with contextlib.suppress(OSError):
            job_path.unlink()
        try:
            if stamp.read_text().strip() == job.get("job_id"):
                stamp.unlink()
        except OSError:
            pass
    return 0


def status_data(root=None, now=None, session_id=None):
    root = root or state_dir()
    now_value = float(time.time() if now is None else now)
    rows = read_jsonl(root / "ledger.jsonl")
    today_tokens, today_calls = usage_totals(rows, now_value)
    session_tokens, session_calls = usage_totals(rows, now_value, session_id, daily_only=False) if session_id else (0, 0)
    in_scope = lambda row: session_id is None or row.get("session_id") == session_id
    all_complete = [row for row in rows if row.get("event") == "complete"]
    complete = [row for row in all_complete if in_scope(row)]
    tips = [row for row in complete if row.get("decision") == "fired" and row.get("tip")]
    simulations = [row for row in rows if row.get("event") == "simulated" and in_scope(row)]
    relays = [
        row
        for row in rows
        if row.get("event") == "relayed" and (session_id is None or row.get("session_id") == session_id)
    ]
    live_decisions = [
        row
        for row in rows
        if row.get("purpose") in {"coach", "recap+coach"}
        and row.get("event") in {"queued", "blocked", "failed", "complete"}
        and in_scope(row)
    ]
    activity = [
        row
        for row in rows
        if row.get("event") in {"queued", "started", "request", "reserved", "blocked", "failed", "complete", "relayed", "replayed"}
        and row.get("purpose") in {"coach", "recap+coach", "relay"}
        and in_scope(row)
    ][-12:]
    terminal = terminal_job_ids(rows)
    active = [
        row
        for row in rows
        if row.get("event") in {"queued", "started", "request", "reserved"}
        and row.get("job_id") not in terminal
        and now_value - float(row.get("ts") or 0) <= 600
        and in_scope(row)
    ]
    latest = tips[-1] if tips else (complete[-1] if complete else (simulations[-1] if simulations else None))
    relay_cutoff = max([float(row.get("through_ts") or 0) for row in relays], default=0)
    if active:
        current = active[-1]
        pipeline = {
            "state": "running",
            "stage": current.get("decision", current.get("event", "unknown")),
            "job_id": current.get("job_id", ""),
            "since_ts": current.get("ts", 0),
        }
    elif tips and float(tips[-1].get("ts") or 0) > relay_cutoff:
        pipeline = {
            "state": "waiting-relay",
            "job_id": tips[-1].get("job_id", ""),
            "since_ts": tips[-1].get("ts", 0),
        }
    else:
        pipeline = {
            "state": "idle",
            "reason": live_decisions[-1].get("decision", "no-work") if live_decisions else "no-work",
        }
    today_complete = [
        row for row in all_complete if day_key(float(row.get("ts") or 0)) == day_key(now_value)
    ]
    costs = sum(float(row.get("cost_usd") or 0) for row in today_complete)
    subscription_calls = sum(
        (row.get("usage") or {}).get("billing") == "subscription" for row in today_complete
    )
    historical_api_calls = len(today_complete) - subscription_calls
    capabilities = load_capabilities()
    return {
        "enabled": not (root / "disabled").exists(),
        "session_id": session_id,
        "model": os.environ.get("PROMPT_COACH_MODEL", MODEL),
        "tokens": {
            "today": today_tokens,
            "daily_cap": setting_int("daily", root),
            "session": session_tokens,
            "session_cap": setting_int("session", root),
            "output_cap": setting_int("output", root),
        },
        "calls": {
            "today": today_calls,
            "session": session_calls,
        },
        "cost_usd_today": costs,
        "billing": {
            "subscription_calls_today": subscription_calls,
            "historical_api_calls_today": historical_api_calls,
        },
        "latest": latest,
        "latest_call": complete[-1] if complete else None,
        "latest_simulation": simulations[-1] if simulations else None,
        "latest_relay": relays[-1] if relays else None,
        "library": {
            "total": len(capabilities),
            "snippets": sum(row.get("surface") == ";;ai" for row in capabilities),
        },
        "last_decision": live_decisions[-1] if live_decisions else None,
        "activity": activity,
        "pipeline": pipeline,
        "learned_count": len(load_learned(root)),
    }


def resolve_session_prefix(root, value):
    if not value:
        return None
    session_ids = [str(row.get("session_id") or "") for row in read_jsonl(root / "ledger.jsonl")]
    for session_id in reversed(session_ids):
        if session_id == value:
            return session_id
    for session_id in reversed(session_ids):
        if session_id.startswith(value):
            return session_id
    return value


def print_status(value):
    state = "enabled" if value["enabled"] else "disabled"
    print(f"Luna coach: {state}, {value['model']}")
    print(
        f"Today: {value['tokens']['today']:,}/{value['tokens']['daily_cap']:,} tokens in "
        f"{value['calls']['today']} calls, ${value['cost_usd_today']:.4f}"
    )
    latest = value.get("latest") or {}
    if latest.get("tip"):
        print(f"Latest tip: {latest['tip']}")
    elif value.get("last_decision"):
        print(f"Latest decision: {value['last_decision'].get('decision', 'unknown')}")
    print(f"Learned: {value['learned_count']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Metered Luna prompt coach")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("enqueue")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("job")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--json", action="store_true")
    status_parser.add_argument("--session")
    library_parser = sub.add_parser("library")
    library_parser.add_argument("query", nargs="?", default="")
    simulate_parser = sub.add_parser("simulate")
    simulate_parser.add_argument("prompt", nargs="?", default="Show me how a prompt coaching tip will look.")
    simulate_parser.add_argument("--session", default="simulator")
    simulate_parser.add_argument("--pane", default="")
    relay_parser = sub.add_parser("relay")
    relay_parser.add_argument("--session", required=True)
    replay_parser = sub.add_parser("replay")
    replay_parser.add_argument("--session", required=True)
    budget_parser = sub.add_parser("budget")
    budget_parser.add_argument("scope", nargs="?", choices=sorted(BUDGET_SETTINGS))
    budget_parser.add_argument("value", nargs="?", type=int)
    learned_parser = sub.add_parser("learned")
    learned_parser.add_argument("text")
    learned_parser.add_argument("--capability", default="")
    sub.add_parser("restore")
    sub.add_parser("enable")
    sub.add_parser("disable")
    sub.add_parser("latest")
    args = parser.parse_args(argv)
    root = state_dir()
    if args.command == "enqueue":
        try:
            payload = json.load(sys.stdin)
        except (TypeError, ValueError):
            return 0
        return enqueue(payload if isinstance(payload, dict) else {})
    if args.command == "run":
        return run_job(args.job)
    if args.command == "status":
        value = status_data(root, session_id=resolve_session_prefix(root, args.session))
        print(json.dumps(value, ensure_ascii=False) if args.json else "", end="") if args.json else print_status(value)
        return 0
    if args.command == "library":
        query = args.query.casefold()
        for row in sorted(load_capabilities(), key=lambda value: value["id"]):
            searchable = f"{row.get('id', '')} {row.get('surface', '')} {row.get('description', '')}".casefold()
            if not query or query in searchable:
                print(f"{row['id']}\t[{row.get('surface', 'unknown')}] {row.get('description', '')}")
        return 0
    if args.command == "simulate":
        pane = args.pane or os.environ.get("CODEX_TMUX_PANE") or os.environ.get("TMUX_PANE") or ""
        print(json.dumps(simulate(args.prompt, pane=pane, session_id=args.session), ensure_ascii=False))
        return 0
    if args.command == "relay":
        relay = claim_pending_relay(root, args.session)
        if relay:
            print(json.dumps(relay, ensure_ascii=False))
        return 0
    if args.command == "replay":
        replay = replay_latest(root, args.session)
        print(json.dumps(replay, ensure_ascii=False) if replay else "nothing to replay")
        return 0
    if args.command == "budget":
        if (args.scope is None) != (args.value is None):
            parser.error("budget requires both scope and value")
        if args.scope is not None:
            try:
                set_budget(root, args.scope, args.value)
            except ValueError as error:
                parser.error(str(error))
        print(
            json.dumps(
                {
                    "session": setting_int("session", root),
                    "daily": setting_int("daily", root),
                    "output": setting_int("output", root),
                }
            )
        )
        return 0
    if args.command == "learned":
        latest = status_data(root).get("latest") or {}
        capability = args.capability
        if not capability and args.text in {latest.get("tip"), latest.get("proposed_tip")}:
            capability = latest.get("capability_id", "")
        print(json.dumps(mark_learned(root, args.text, capability_id=capability), ensure_ascii=False))
        return 0
    if args.command == "restore":
        restored = restore_learned(root)
        print(json.dumps(restored, ensure_ascii=False) if restored else "nothing to restore")
        return 0
    if args.command == "enable":
        with contextlib.suppress(OSError):
            (root / "disabled").unlink()
        print("Luna coach enabled")
        return 0
    if args.command == "disable":
        ensure_state(root)
        (root / "disabled").write_text("disabled\n")
        print("Luna coach disabled")
        return 0
    if args.command == "latest":
        latest = status_data(root).get("latest") or {}
        print(latest.get("tip") or latest.get("proposed_tip") or "")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
