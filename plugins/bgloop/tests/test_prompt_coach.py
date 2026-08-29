"""Tests for the Claude Luna prompt coach.

Every test here mutates the thing under test and requires the assertion to
fail, in both directions where the rule has two sides. A test that only
consults the implementation is not a test.

Nothing touches the real ledger: PROMPT_COACH_STATE_DIR is redirected before
the module is imported. The live ledger is the instrument every threshold is
tuned from, and a suite that spends its budget skews the next measurement.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATE = Path(tempfile.mkdtemp(prefix="coach-test-state-"))
os.environ["PROMPT_COACH_STATE_DIR"] = str(STATE)
os.environ["PROMPT_COACH_ENABLED"] = "1"
# The spinner seam is a real settings file on this machine. Redirected before
# import for the same reason as the ledger: delivery tests below call deliver(),
# and an unredirected suite would leave test advice on Piotr's spinner.
SEAM = STATE / "settings.json"
SEAM.write_text("{}")
os.environ["TIP_SETTINGS_FILE"] = str(SEAM)
# The suite must not be able to address a live tmux pane. mark_pane_session
# writes @prompt_coach_session, and once the stable pane id became its first
# choice a test that cleared only TMUX_PANE wrote its fixture value onto the
# real pane this session runs in, which took the live board off its session.
# Both halves matter: no pane variable to aim with, and a tmux tmpdir with no
# server in it, so even a call that slips through cannot reach the real one.
for _pane_var in ("CLAUDE_PANE_ID", "CLAUDE_TMUX_PANE", "TMUX_PANE", "TMUX"):
    os.environ.pop(_pane_var, None)
(STATE / "tmux").mkdir(exist_ok=True)
os.environ["TMUX_TMPDIR"] = str(STATE / "tmux")

COACH_PATH = Path(__file__).resolve().parents[1] / "observers" / "prompt_coach.py"
_spec = importlib.util.spec_from_file_location("claude_prompt_coach", COACH_PATH)
coach = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coach)


# ------------------------------------------------------------------- helpers


def fresh_state(tmp_path):
    root = Path(tmp_path)
    (root / "jobs").mkdir(parents=True, exist_ok=True)
    return root


def write_ledger(root, rows):
    path = Path(root) / "ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    return path


def complete_row(session, tip, ts=1000.0, purpose="claude:recap+coach", job_id="job-1"):
    return {
        "ts": ts,
        "event": "complete",
        "decision": "fired",
        "job_id": job_id,
        "session_id": session,
        "purpose": purpose,
        "tip": tip,
        "capability_id": "",
        "reason": "line one\nline two",
    }


def write_transcript(config_root, session, rows):
    project = Path(config_root) / "projects" / "-home-decoder-dev-x"
    project.mkdir(parents=True, exist_ok=True)
    path = project / ("%s.jsonl" % session)
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    return path


def queue_row(text, timestamp="2026-08-23T12:00:00.000Z", operation="enqueue"):
    """How a channel event is recorded when it lands in a BUSY session."""
    return {
        "type": "queue-operation",
        "operation": operation,
        "timestamp": timestamp,
        "content": text,
    }


def user_row(text, kind="human", timestamp="2026-08-23T12:00:00.000Z"):
    origin = None if kind is None else {"kind": kind}
    return {
        "type": "user",
        "origin": origin,
        "timestamp": timestamp,
        "message": {"role": "user", "content": text},
    }


# -------------------------------------------------------- capability rendering


def test_invocable_row_renders_with_claude_prefix():
    row = {
        "capability_id": "skill:repo-vector-map",
        "kind": "skill",
        "invocable": True,
        "invocation_name": "repo-vector-map",
        "summary": "vector map",
    }
    assert coach.registry_capability(row)["invocation"] == "/repo-vector-map"

    # Mutation: a bare name must not survive as a bare name. If the renderer
    # stopped adding the prefix, Piotr would be told to type something that
    # does nothing in Claude Code.
    assert coach.registry_capability(row)["invocation"] != "repo-vector-map"


def test_setting_row_is_actionable_without_being_invocable():
    row = {
        "capability_id": "setting:outputStyle",
        "kind": "setting",
        "invocable": False,
        "invocation_name": None,
        "summary": "response style",
    }
    rendered = coach.registry_capability(row)
    assert rendered is not None, "settings must not be dropped by an invocable-only filter"
    assert "outputStyle" in rendered["invocation"]
    assert not rendered["invocation"].startswith("/"), "a setting is edited, not typed as a command"


def test_non_invocable_non_setting_row_is_dropped():
    row = {
        "capability_id": "tool:Read",
        "kind": "tool",
        "invocable": False,
        "invocation_name": None,
        "summary": "read a file",
    }
    assert coach.registry_capability(row) is None


def test_live_library_is_claude_shaped_and_has_no_codex_actions():
    rows = coach.load_capabilities()
    assert rows, "the live registry produced no capabilities"
    kinds = {row["surface"] for row in rows}
    assert any(kind.startswith("claude-") for kind in kinds)
    for row in rows:
        invocation = row.get("invocation", "")
        assert not invocation.startswith("codex "), "codex-only action leaked into the Claude library: %s" % row
        assert not invocation.startswith("$"), "codex skill prefix leaked: %s" % row


def test_live_library_carries_settings_advice():
    # Canary: settings are the one capability class with no invocation, so an
    # invocable-only regression removes them silently.
    rows = coach.load_capabilities()
    settings = [row for row in rows if row["surface"] == "claude-setting"]
    assert settings, "no settings reached the coach library"


# ------------------------------------------------------------- feedback loops


def test_channel_origin_is_never_treated_as_a_user_prompt():
    human = user_row("do the thing", kind="human")
    channel = user_row('<channel source="agents" kind="dm">tip</channel>', kind="channel")
    assert coach.is_human_prompt(human) is True
    assert coach.is_human_prompt(channel) is False

    # Mutation: the guard must key on origin, not on the text. A channel row
    # whose body looks like an ordinary sentence is still not a prompt.
    disguised = user_row("do the thing", kind="channel")
    assert coach.is_human_prompt(disguised) is False


def test_synthetic_prefixes_are_skipped():
    assert coach.synthetic("<coach> advice") is True
    assert coach.synthetic('<channel source="agents">x</channel>') is True
    assert coach.synthetic("<command-message>norm-agent</command-message>") is True
    assert coach.synthetic("please fix the hook") is False


def test_recent_prompts_exclude_injected_rows(tmp_path):
    config = Path(tmp_path) / "config"
    session = "sess-recent"
    write_transcript(
        config,
        session,
        [
            user_row("first real prompt"),
            user_row('<channel source="agents" kind="dm">coach tip</channel>', kind="channel"),
            user_row("second real prompt"),
        ],
    )
    os.environ["CLAUDE_CONFIG_DIR"] = str(config)
    try:
        values = coach.recent_prompts(session)
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
    assert values == ["first real prompt", "second real prompt"]


# ------------------------------------------------------------------ turn gate


def test_turn_marker_tracks_the_live_turn(tmp_path):
    root = fresh_state(tmp_path)
    session = "sess-turn"
    assert coach.turn_active(root, session) is False
    coach.turn_start(root, session)
    assert coach.turn_active(root, session) is True
    coach.turn_end(root, session)
    assert coach.turn_active(root, session) is False


def test_stale_turn_marker_counts_as_idle(tmp_path):
    root = fresh_state(tmp_path)
    session = "sess-stale"
    coach.turn_start(root, session)
    marker = coach.turn_marker(root, session)
    marker.write_text("%d\n" % int(time.time() - 7200))
    assert coach.turn_active(root, session) is False, "a session killed mid-turn must not look busy forever"


# ------------------------------------------------------------------- delivery


def pin_for(tmp_path, monkeypatch, session_id, name="testsess"):
    """Pin `session_id` as the owner of this pane's bus identity."""
    monkeypatch.setenv("PROMPT_COACH_PIN_DIR", str(tmp_path))
    monkeypatch.setenv("PROMPT_COACH_TMUX_SESSION", name)
    if session_id is not None:
        (Path(tmp_path) / ("claude_mainsid_%s.pin" % name)).write_text(session_id)


def test_publish_success_does_not_consume_the_tip(tmp_path, monkeypatch):
    """snd exit 0 means published, never delivered.

    An earlier draft advanced the relay cursor here, which destroyed every tip
    aimed at a session that was not bound.
    """
    root = fresh_state(tmp_path)
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "bound_agents", lambda: {"klod"})
    monkeypatch.setattr(coach, "channel_push", lambda agent, tip: True)
    pin_for(tmp_path, monkeypatch, "sess-push")
    coach.turn_start(root, "sess-push")
    record = complete_row("sess-push", "use /repo-vector-map before grepping")
    coach.CORE.append_event(root, record)

    coach.deliver({"agent": "klod"}, record)

    rows = coach.CORE.read_jsonl(root / "ledger.jsonl")
    attempts = [row for row in rows if row.get("event") == "channel-attempt"]
    assert len(attempts) == 1
    assert attempts[0].get("through_ts") is None, "a publish must not move the relay cursor"
    assert not [row for row in rows if row.get("event") == "relayed"]


def test_unbound_agent_is_never_published_to(tmp_path, monkeypatch):
    root = fresh_state(tmp_path)
    calls = []
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "bound_agents", lambda: set())
    monkeypatch.setattr(coach, "channel_push", lambda agent, tip: calls.append(agent) or True)
    pin_for(tmp_path, monkeypatch, "sess-unbound")
    record = complete_row("sess-unbound", "a tip")
    coach.deliver({"agent": "ghost"}, record)
    assert calls == [], "publishing at an unregistered name cannot reach anyone"


def test_idle_push_is_counted_as_an_extra_call(tmp_path, monkeypatch):
    root = fresh_state(tmp_path)
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "bound_agents", lambda: {"klod"})
    monkeypatch.setattr(coach, "channel_push", lambda agent, tip: True)
    pin_for(tmp_path, monkeypatch, "sess-idle")
    record = complete_row("sess-idle", "a tip")
    coach.deliver({"agent": "klod"}, record)  # no turn marker written: idle
    attempt = [row for row in coach.CORE.read_jsonl(root / "ledger.jsonl") if row.get("event") == "channel-attempt"][0]
    assert attempt["delivery"] == "agents-channel-idle"
    assert attempt["extra_model_calls"] == 1, "waking an idle session costs a turn and must be visible"


# ---------------------------------------------------------------------- relay


def test_pending_tip_reaches_the_next_prompt(tmp_path):
    root = fresh_state(tmp_path)
    session = "sess-relay"
    write_ledger(root, [complete_row(session, "run /code-review before pushing")])
    relay = coach.claim_pending_relay(root, session)
    assert relay is not None
    context = relay["hookSpecificOutput"]["additionalContext"]
    assert "run /code-review before pushing" in context
    assert relay["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_relay_never_repeats_itself(tmp_path):
    root = fresh_state(tmp_path)
    session = "sess-once"
    write_ledger(root, [complete_row(session, "a tip worth one showing")])
    assert coach.claim_pending_relay(root, session) is not None
    assert coach.claim_pending_relay(root, session) is None, "the cursor did not advance"


def test_trace_never_travels_with_the_tip(tmp_path):
    root = fresh_state(tmp_path)
    session = "sess-trace"
    row = complete_row(session, "short tip")
    row["reason"] = "TRACE-LINE-ONE\nTRACE-LINE-TWO"
    write_ledger(root, [row])
    context = coach.claim_pending_relay(root, session)["hookSpecificOutput"]["additionalContext"]
    assert "TRACE-LINE-ONE" not in context, "the Luna trace belongs in ctips, not in the session"


def test_tip_never_crosses_sessions(tmp_path):
    root = fresh_state(tmp_path)
    write_ledger(root, [complete_row("sess-a", "tip for a")])
    assert coach.claim_pending_relay(root, "sess-b") is None


def test_tip_never_crosses_providers(tmp_path):
    """One ledger holds Claude personal, Claude work and Codex rows."""
    root = fresh_state(tmp_path)
    session = "sess-shared-id"
    write_ledger(root, [complete_row(session, "codex only tip", purpose="recap+coach")])
    assert coach.claim_pending_relay(root, session) is None, "a Codex tip surfaced in a Claude session"

    # And the same row, tagged for this provider, must relay. Without this the
    # test above would pass on a filter that blocks everything.
    write_ledger(root, [complete_row(session, "claude tip", purpose="claude:recap+coach")])
    assert coach.claim_pending_relay(root, session) is not None


def test_confirmed_channel_delivery_suppresses_the_fallback_exactly_once(tmp_path):
    root = fresh_state(tmp_path)
    config = Path(tmp_path) / "config"
    session = "sess-ack"
    tip = "use /repo-vector-map before a broad grep"
    write_ledger(root, [complete_row(session, tip, ts=1000.0)])
    write_transcript(
        config,
        session,
        [user_row("<coach> ... apply it only if it fits his request: %s" % tip,
                  kind="channel", timestamp="2026-08-23T12:00:00.000Z")],
    )
    os.environ["CLAUDE_CONFIG_DIR"] = str(config)
    try:
        assert coach.claim_pending_relay(root, session) is None, "the tip was already on screen"
        rows = coach.CORE.read_jsonl(root / "ledger.jsonl")
        confirmed = [row for row in rows if row.get("delivery") == "already-delivered"]
        assert len(confirmed) == 1
        assert confirmed[0]["through_ts"] == 1000.0, "a confirmed delivery must move the cursor"
        assert coach.claim_pending_relay(root, session) is None
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)


def test_missing_transcript_row_keeps_the_tip_pending(tmp_path):
    """The mutation of the test above: publish happened, nothing arrived."""
    root = fresh_state(tmp_path)
    config = Path(tmp_path) / "config"
    session = "sess-noack"
    tip = "use /code-review on this branch"
    write_ledger(root, [complete_row(session, tip, ts=1000.0)])
    write_transcript(config, session, [user_row("unrelated typing", kind="human")])
    os.environ["CLAUDE_CONFIG_DIR"] = str(config)
    try:
        relay = coach.claim_pending_relay(root, session)
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
    assert relay is not None, "a published-but-undelivered tip must fall back, not vanish"
    assert tip in relay["hookSpecificOutput"]["additionalContext"]


def test_receipt_from_another_session_does_not_count(tmp_path):
    root = fresh_state(tmp_path)
    config = Path(tmp_path) / "config"
    tip = "a tip delivered somewhere else"
    write_ledger(root, [complete_row("sess-mine", tip, ts=1000.0)])
    write_transcript(config, "sess-other", [user_row("<coach> %s" % tip, kind="channel")])
    write_transcript(config, "sess-mine", [user_row("hello", kind="human")])
    os.environ["CLAUDE_CONFIG_DIR"] = str(config)
    try:
        relay = coach.claim_pending_relay(root, "sess-mine")
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
    assert relay is not None, "another session's receipt was accepted for this one"


def test_receipt_older_than_the_tip_does_not_count(tmp_path):
    root = fresh_state(tmp_path)
    config = Path(tmp_path) / "config"
    session = "sess-old"
    tip = "a tip that repeats"
    now = time.time()
    write_ledger(root, [complete_row(session, tip, ts=now)])
    write_transcript(
        config,
        session,
        [user_row("<coach> %s" % tip, kind="channel", timestamp="2020-01-01T00:00:00.000Z")],
    )
    os.environ["CLAUDE_CONFIG_DIR"] = str(config)
    try:
        relay = coach.claim_pending_relay(root, session)
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
    assert relay is not None, "an older identical tip was mistaken for this delivery"


# ------------------------------------------------------------------- enqueue


def test_enqueue_returns_without_calling_the_model(tmp_path, monkeypatch):
    root = fresh_state(tmp_path)
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "pane_agent", lambda: "")
    monkeypatch.setattr(coach, "mark_pane_session", lambda session: True)
    spawned = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            spawned.append(args)

    monkeypatch.setattr(coach.subprocess, "Popen", FakePopen)
    started = time.time()
    coach.enqueue({"session_id": "sess-enqueue", "prompt": "help me ship this"})
    elapsed = time.time() - started

    assert elapsed < 1.0, "UserPromptSubmit must not wait on the model or a capability scan"
    assert spawned, "the worker was never detached"
    jobs = list((root / "jobs").glob("*.json"))
    assert len(jobs) == 1
    job = json.loads(jobs[0].read_text())
    assert job["purpose"].startswith("claude:")
    assert job["client"] == "claude"
    assert job["session_id"] == "sess-enqueue"


def _worker_env(tmp_path, monkeypatch, session="sess-env"):
    """Build the detached worker's environment through the real enqueue path."""
    root = fresh_state(tmp_path)
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "pane_agent", lambda: "")
    monkeypatch.setattr(coach, "mark_pane_session", lambda session_id: True)
    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured.update(kwargs.get("env") or {})

    monkeypatch.setattr(coach.subprocess, "Popen", FakePopen)
    coach.enqueue({"session_id": session, "prompt": "ship the thing"})
    return captured


def test_the_worker_is_never_handed_an_api_key(tmp_path, monkeypatch):
    """Luna is paid for by subscription, so no key may reach the worker.

    Asserted on the environment the real enqueue path builds, not on the
    source text: putting OPENAI_API_KEY back in the allowlist has to fail
    here. The secret is also searched for by VALUE, so smuggling it under
    another name fails the same test.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-canary-must-not-propagate")
    env = _worker_env(tmp_path, monkeypatch)

    assert "OPENAI_API_KEY" not in env
    assert not [key for key, value in env.items() if "sk-canary-must-not-propagate" in str(value)]


def test_the_worker_inherits_the_codex_login(tmp_path, monkeypatch):
    """The transport shells out to `codex exec`, which reads CODEX_HOME."""
    monkeypatch.setenv("CODEX_HOME", "/home/decoder/.codex")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert _worker_env(tmp_path, monkeypatch)["CODEX_HOME"] == "/home/decoder/.codex"


def test_work_and_personal_bill_separate_codex_accounts(tmp_path, monkeypatch):
    """Two roots, no copying.

    A work Claude session billing Luna to the personal ChatGPT account is
    invisible in the ledger and wrong on the invoice, so the pairing is
    asserted in both directions rather than assumed from the shell export.
    """
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude-work"))
    work = _worker_env(tmp_path, monkeypatch, session="sess-work")
    assert work["CODEX_HOME"] == str(Path.home() / ".codex-work")

    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    personal = _worker_env(tmp_path, monkeypatch, session="sess-personal")
    assert personal.get("CODEX_HOME", "") == "", "personal sessions leave codex on its own default"


def test_the_claude_lane_makes_no_direct_api_call(tmp_path, monkeypatch):
    """The Claude lane owns no transport of its own.

    It hands the job to the shared core and inherits whatever that core posts
    with. If the core is ever pointed back at a keyed HTTP endpoint, this
    fails here rather than at the next invoice.
    """
    import inspect

    assert inspect.signature(coach.CORE.process_job).parameters["post"].default is coach.CORE.subscription_post
    source = inspect.getsource(coach.run_job)
    assert "post=" not in source, "the Claude lane must not pin its own transport"


def test_enqueue_ignores_its_own_output(tmp_path, monkeypatch):
    root = fresh_state(tmp_path)
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "pane_agent", lambda: "")
    monkeypatch.setattr(coach, "mark_pane_session", lambda session: True)
    monkeypatch.setattr(coach.subprocess, "Popen", lambda *a, **k: None)
    coach.enqueue({"session_id": "sess-loop", "prompt": "<coach> a tip from the coach"})
    assert not list((root / "jobs").glob("*.json")), "the coach coached itself"


def test_turn_marker_is_written_even_for_a_skipped_prompt(tmp_path, monkeypatch):
    root = fresh_state(tmp_path)
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "pane_agent", lambda: "")
    monkeypatch.setattr(coach, "mark_pane_session", lambda session: True)
    monkeypatch.setattr(coach.subprocess, "Popen", lambda *a, **k: None)
    coach.enqueue({"session_id": "sess-marker", "prompt": "<coach> skipped"})
    assert coach.turn_active(root, "sess-marker") is True


# --------------------------------------------------------------- shared caps


def test_budget_caps_are_the_shared_ones():
    """One budget, not two.

    The numbers are not asserted here. Piotr moves the caps through
    `--budget`, and 0 means unlimited, so a literal in this file would only
    record when it was last written. What must hold is that every cap Claude
    meters against is read from the shared config, never from a Claude-only
    default.
    """
    live_root = Path.home() / ".local" / "state" / "prompt-coach"
    for scope in ("session", "daily", "output"):
        assert scope in coach.CORE.BUDGET_SETTINGS

    if (live_root / "config.json").is_file():
        live = json.loads((live_root / "config.json").read_text())
        for scope, (key, _env, _default) in coach.CORE.BUDGET_SETTINGS.items():
            if key in live:
                assert coach.CORE.setting_int(scope, live_root) == live[key], scope
        assert coach.CORE.setting_int("output", live_root) > 0

    # The structural half: the Claude coach must meter against the SAME root
    # the Codex coach uses. A private state dir would give Claude its own
    # budget on top of Codex's, doubling one that is meant to be shared.
    os.environ.pop("PROMPT_COACH_STATE_DIR", None)
    try:
        assert coach.CORE.state_dir() == live_root
    finally:
        os.environ["PROMPT_COACH_STATE_DIR"] = str(STATE)


def test_receipt_for_a_busy_turn_is_the_queue_row(tmp_path):
    """The common case: the push folded into a turn already running.

    A busy session never writes a user row for a channel event, so a receipt
    check that only looks for user rows reports "not delivered" for every tip
    the coach actually landed, and the fallback shows it a second time.
    """
    root = fresh_state(tmp_path)
    config = Path(tmp_path) / "config"
    session = "sess-busy"
    tip = "use /repo-vector-map before a broad grep"
    write_ledger(root, [complete_row(session, tip, ts=1000.0)])
    write_transcript(
        config,
        session,
        [
            user_row("some earlier prompt", kind="human"),
            queue_row("<coach> ... apply it only if it fits his request: %s" % tip),
        ],
    )
    os.environ["CLAUDE_CONFIG_DIR"] = str(config)
    try:
        assert coach.claim_pending_relay(root, session) is None, "the tip was already folded into the live turn"
        confirmed = [
            row
            for row in coach.CORE.read_jsonl(root / "ledger.jsonl")
            if row.get("delivery") == "already-delivered"
        ]
        assert len(confirmed) == 1
        assert confirmed[0]["through_ts"] == 1000.0
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)


def test_queue_receipt_from_another_session_does_not_count(tmp_path):
    root = fresh_state(tmp_path)
    config = Path(tmp_path) / "config"
    tip = "a tip delivered somewhere else"
    write_ledger(root, [complete_row("sess-q-mine", tip, ts=1000.0)])
    write_transcript(config, "sess-q-other", [queue_row("<coach> %s" % tip)])
    write_transcript(config, "sess-q-mine", [user_row("hello", kind="human")])
    os.environ["CLAUDE_CONFIG_DIR"] = str(config)
    try:
        assert coach.claim_pending_relay(root, "sess-q-mine") is not None
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)


def test_enqueue_scopes_ctips_to_this_session(tmp_path, monkeypatch):
    """ctips reads the pane, not the ledger, to decide whose session it shows.

    Without this the viewer in a Claude pane reports a Codex session's budget
    and decisions, which reads as the coach having done nothing here.
    """
    root = fresh_state(tmp_path)
    marked = []
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "pane_agent", lambda: "")
    monkeypatch.setattr(coach, "mark_pane_session", lambda session: marked.append(session) or True)
    monkeypatch.setattr(coach.subprocess, "Popen", lambda *a, **k: None)
    coach.enqueue({"session_id": "sess-ctips", "prompt": "ship it"})
    assert marked == ["sess-ctips"]


def test_pane_session_marker_survives_a_missing_pane(monkeypatch):
    # All three, since the stable pane id is now the first choice: leaving it
    # set meant this test passed only because the suite happened to run outside
    # a monitored session.
    monkeypatch.delenv("CLAUDE_PANE_ID", raising=False)
    monkeypatch.delenv("CLAUDE_TMUX_PANE", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert coach.mark_pane_session("sess-nopane") is False


# ------------------------------------------------------- pane identity is not
# ------------------------------------------------------- session identity


def delivery_probe(tmp_path, monkeypatch, pinned, job_session):
    """Run deliver() with a chosen pin and report what it did."""
    root = fresh_state(tmp_path)
    pushes = []
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "bound_agents", lambda: {"klod"})
    monkeypatch.setattr(coach, "channel_push", lambda agent, tip: pushes.append(agent) or True)
    pin_for(tmp_path, monkeypatch, pinned)
    coach.turn_start(root, job_session)
    record = complete_row(job_session, "a tip that belongs to one session")
    coach.CORE.append_event(root, record)
    coach.deliver({"agent": "klod"}, record)
    attempts = [row for row in coach.CORE.read_jsonl(root / "ledger.jsonl") if row.get("event") == "channel-attempt"]
    return pushes, attempts, root


def test_publish_only_when_the_pin_names_this_exact_session(tmp_path, monkeypatch):
    pushes, attempts, _ = delivery_probe(tmp_path, monkeypatch, pinned="sess-owner", job_session="sess-owner")
    assert pushes == ["klod"]
    assert len(attempts) == 1


def test_a_session_sharing_the_pane_never_publishes(tmp_path, monkeypatch):
    """The live failure: a headless `claude -p` inherits the pane and the
    registered session's @agent_name, and published its tip into that other
    session."""
    pushes, attempts, root = delivery_probe(tmp_path, monkeypatch, pinned="sess-owner", job_session="sess-guest")
    assert pushes == [], "a tip was published at another session's bus name"
    assert attempts == [], "a refused publish must not leave an attempt row"
    relay = coach.claim_pending_relay(root, "sess-guest")
    assert relay is not None, "the refused tip must stay pending for its own session"


def test_missing_pin_refuses_to_publish(tmp_path, monkeypatch):
    pushes, attempts, _ = delivery_probe(tmp_path, monkeypatch, pinned=None, job_session="sess-nopin")
    assert pushes == []
    assert attempts == []


def test_blank_pin_refuses_to_publish(tmp_path, monkeypatch):
    pushes, attempts, _ = delivery_probe(tmp_path, monkeypatch, pinned="   \n", job_session="sess-blank")
    assert pushes == []
    assert attempts == []


def test_a_prefix_of_the_session_id_is_not_a_match(tmp_path, monkeypatch):
    """Full id or nothing. Session ids share prefixes often enough that a
    startswith would reintroduce the leak on a narrower path."""
    pushes, _, _ = delivery_probe(tmp_path, monkeypatch, pinned="sess-owner", job_session="sess-owner-2")
    assert pushes == []


# ------------------------------------------------- one worker per real prompt


def enqueue_probe(root, monkeypatch, session, prompt):
    spawned = []
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "pane_agent", lambda: "")
    monkeypatch.setattr(coach, "mark_pane_session", lambda value: True)
    monkeypatch.setattr(coach.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    coach.enqueue({"session_id": session, "prompt": prompt})
    return spawned


def test_two_rapid_distinct_prompts_both_get_a_worker(tmp_path, monkeypatch):
    """Two questions in the same second are two questions.

    The stamp is keyed on the prompt, so neither job can evict the other. A
    session-keyed stamp would have silently dropped the first.
    """
    root = fresh_state(tmp_path)
    enqueue_probe(root, monkeypatch, "sess-rapid", "how do I trace this commit")
    enqueue_probe(root, monkeypatch, "sess-rapid", "and where is the config read")

    jobs = [json.loads(path.read_text()) for path in (root / "jobs").glob("*.json")]
    assert len(jobs) == 2, "a distinct prompt lost its worker"
    assert {job["prompt"] for job in jobs} == {
        "how do I trace this commit",
        "and where is the config read",
    }
    stamps = list((root / "sessions").glob("*.latest"))
    assert len(stamps) == 2, "two prompts must own two stamps"
    for job in jobs:
        stamp = coach.CORE.dedupe_stamp(root, "sess-rapid", job["prompt"])
        assert stamp.read_text().strip() == job["job_id"], "a job does not own its own stamp"


def test_the_same_payload_twice_dedupes_to_one_worker(tmp_path, monkeypatch):
    """The only thing that coalesces: one hook payload delivered twice."""
    root = fresh_state(tmp_path)
    prompt = "identical prompt text"
    enqueue_probe(root, monkeypatch, "sess-dupe", prompt)
    enqueue_probe(root, monkeypatch, "sess-dupe", prompt)

    stamps = list((root / "sessions").glob("*.latest"))
    assert len(stamps) == 1, "an exact duplicate payload created a second stamp"
    jobs = sorted(
        (json.loads(path.read_text()) for path in (root / "jobs").glob("*.json")),
        key=lambda job: job["created_at"],
    )
    owner = coach.CORE.dedupe_stamp(root, "sess-dupe", prompt).read_text().strip()
    assert owner == jobs[-1]["job_id"], "the later duplicate must own the stamp"
    assert owner != jobs[0]["job_id"], "the earlier duplicate must lose it and coalesce"


# ------------------------------------------------------------ fallback bundle


def test_fallback_bundles_tips_in_order(tmp_path):
    root = fresh_state(tmp_path)
    session = "sess-bundle"
    write_ledger(
        root,
        [
            complete_row(session, "first tip", ts=1000.0, job_id="j1"),
            complete_row(session, "second tip", ts=1001.0, job_id="j2"),
            complete_row(session, "third tip", ts=1002.0, job_id="j3"),
        ],
    )
    context = coach.claim_pending_relay(root, session)["hookSpecificOutput"]["additionalContext"]
    assert context.count("<coach>") == 1, "tips must arrive as one block, not one block each"
    body = context.splitlines()[1:]
    assert body == ["- first tip", "- second tip", "- third tip"], body

    row = coach.CORE.read_jsonl(root / "ledger.jsonl")[-1]
    assert row["through_ts"] == 1002.0
    assert row["tip_count"] == 3
    assert coach.claim_pending_relay(root, session) is None


def test_identical_advice_is_shown_once(tmp_path):
    root = fresh_state(tmp_path)
    session = "sess-samesame"
    write_ledger(
        root,
        [
            complete_row(session, "run /code-review before pushing", ts=1000.0, job_id="j1"),
            complete_row(session, "Run /code-review before pushing", ts=1001.0, job_id="j2"),
            complete_row(session, "something else entirely", ts=1002.0, job_id="j3"),
        ],
    )
    context = coach.claim_pending_relay(root, session)["hookSpecificOutput"]["additionalContext"]
    assert context.lower().count("/code-review") == 1, "the same advice was shown twice"
    assert "something else entirely" in context


def test_an_oversized_queue_splits_and_keeps_the_rest_owed(tmp_path, monkeypatch):
    """The cursor moves through the last INCLUDED tip, never past it."""
    root = fresh_state(tmp_path)
    session = "sess-bounded"
    tips = ["tip number %d %s" % (i, "x" * 60) for i in range(6)]
    write_ledger(
        root,
        [complete_row(session, tip, ts=1000.0 + i, job_id="j%d" % i) for i, tip in enumerate(tips)],
    )
    monkeypatch.setenv("PROMPT_COACH_RELAY_MAX_BYTES", "400")

    first = coach.claim_pending_relay(root, session)["hookSpecificOutput"]["additionalContext"]
    assert len(first.encode()) <= 400, "the injected block blew its byte budget"
    included = [line[2:] for line in first.splitlines()[1:]]
    assert 0 < len(included) < len(tips), "the split did not happen"
    assert included == tips[: len(included)], "order was not preserved across the split"

    row = coach.CORE.read_jsonl(root / "ledger.jsonl")[-1]
    assert row["through_ts"] == 1000.0 + len(included) - 1, "cursor moved past a tip that was never shown"

    second = coach.claim_pending_relay(root, session)["hookSpecificOutput"]["additionalContext"]
    rest = [line[2:] for line in second.splitlines()[1:]]
    assert rest[0] == tips[len(included)], "the first unshown tip was skipped"
    assert not set(included) & set(rest), "a tip was shown in both batches"


def test_one_giant_tip_still_goes_rather_than_blocking_the_queue(tmp_path, monkeypatch):
    root = fresh_state(tmp_path)
    session = "sess-giant"
    write_ledger(root, [complete_row(session, "z" * 140, ts=1000.0, job_id="j1"),
                        complete_row(session, "the one behind it", ts=1001.0, job_id="j2")])
    monkeypatch.setenv("PROMPT_COACH_RELAY_MAX_BYTES", "10")
    context = coach.claim_pending_relay(root, session)["hookSpecificOutput"]["additionalContext"]
    assert "z" * 140 in context, "a tip larger than the budget would stall the queue forever"
    assert "the one behind it" not in context
    assert coach.claim_pending_relay(root, session) is not None, "the remainder must still be owed"


def test_bundle_never_mixes_sessions_or_providers(tmp_path):
    root = fresh_state(tmp_path)
    session = "sess-mine"
    write_ledger(
        root,
        [
            complete_row(session, "mine one", ts=1000.0, job_id="j1"),
            complete_row("sess-theirs", "another session's tip", ts=1000.5, job_id="j2"),
            complete_row(session, "codex tip", ts=1001.0, purpose="recap+coach", job_id="j3"),
            complete_row(session, "mine two", ts=1002.0, job_id="j4"),
        ],
    )
    context = coach.claim_pending_relay(root, session)["hookSpecificOutput"]["additionalContext"]
    assert "mine one" in context and "mine two" in context
    assert "another session" not in context, "a tip crossed sessions"
    assert "codex tip" not in context, "a tip crossed providers"


def test_the_worker_coaches_the_prompt_it_was_queued_for(tmp_path, monkeypatch):
    """A worker wakes after the user has typed again. It still answers its own
    question: coaching the newest prompt under an older job's identity answers
    something nobody asked."""
    root = fresh_state(tmp_path)
    seen = {}
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "recent_prompts", lambda session, limit=4: ["older one", "my prompt", "typed since"])
    monkeypatch.setattr(coach, "load_capabilities", lambda: [])
    monkeypatch.setattr(coach.CORE, "process_job", lambda job, deliver=None: seen.update(job))

    job = {
        "job_id": "j-keep",
        "session_id": "sess-keep",
        "prompt": "my prompt",
        "not_before": 0,
        "purpose": "claude:recap+coach",
    }
    job_path = root / "jobs" / "j-keep.json"
    coach.CORE.atomic_json(job_path, job)
    stamp = coach.CORE.dedupe_stamp(root, "sess-keep", "my prompt")
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("j-keep")

    coach.run_job(job_path)

    assert seen["prompt"] == "my prompt", "the worker was retargeted at a newer prompt"
    assert "my prompt" not in seen["recent_user_prompts"], "the prompt must not also appear as its own context"
    assert "typed since" in seen["recent_user_prompts"], "later prompts are still bounded context"
    assert not stamp.exists(), "a finished job must clean up the stamp it owned"


# ------------------------------------------------------------- spinner seam


def seam_tips(path):
    """The tips currently queued on a settings file's spinner seam."""
    if not Path(path).exists():
        return []
    return json.loads(Path(path).read_text()).get("spinnerTipsOverride", {}).get("tips", [])


def test_a_fired_tip_reaches_piotr_not_only_the_agent(tmp_path, monkeypatch):
    """The seam is the human's copy of the same tip.

    Before this, a tip Piotr paid for was visible to the model in context and
    to him only through a status page in another pane.
    """
    root = fresh_state(tmp_path)
    seam = Path(tmp_path) / "settings.json"
    seam.write_text("{}")
    monkeypatch.setenv("TIP_SETTINGS_FILE", str(seam))
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "bound_agents", lambda: set())

    coach.deliver({"agent": ""}, complete_row("sess-seam", "use /statusline"))

    assert seam_tips(seam) == ["use /statusline"]


def test_the_seam_queues_tips_instead_of_overwriting_them(tmp_path, monkeypatch):
    root = fresh_state(tmp_path)
    seam = Path(tmp_path) / "settings.json"
    seam.write_text("{}")
    monkeypatch.setenv("TIP_SETTINGS_FILE", str(seam))
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "bound_agents", lambda: set())

    coach.deliver({"agent": ""}, complete_row("sess-seam", "first tip"))
    coach.deliver({"agent": ""}, complete_row("sess-seam", "second tip"))

    assert seam_tips(seam) == ["second tip", "first tip"], "tips arrive one by one and must queue"


def test_a_job_with_no_tip_leaves_the_seam_alone(tmp_path, monkeypatch):
    root = fresh_state(tmp_path)
    seam = Path(tmp_path) / "settings.json"
    seam.write_text("{}")
    monkeypatch.setenv("TIP_SETTINGS_FILE", str(seam))
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "bound_agents", lambda: set())

    coach.deliver({"agent": ""}, complete_row("sess-seam", ""))

    assert seam_tips(seam) == [], "a no-tip decision has nothing to show anyone"


def test_the_relay_takes_the_tip_back_off_the_seam(tmp_path, monkeypatch):
    """One queue, two readers. What the agent has been handed is spent."""
    root = fresh_state(tmp_path)
    seam = Path(tmp_path) / "settings.json"
    seam.write_text("{}")
    monkeypatch.setenv("TIP_SETTINGS_FILE", str(seam))
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "bound_agents", lambda: set())
    monkeypatch.setattr(coach, "channel_delivered", lambda *a, **k: False)

    kept = complete_row("sess-other", "another session's tip", ts=1000.0, job_id="job-other")
    spent = complete_row("sess-relay", "the relayed tip", ts=1001.0, job_id="job-relay")
    coach.deliver({"agent": ""}, kept)
    coach.deliver({"agent": ""}, spent)
    write_ledger(root, [kept, spent])

    assert coach.claim_pending_relay(root, "sess-relay") is not None
    assert seam_tips(seam) == ["another session's tip"], "only the injected tip is spent"


def test_seam_failure_never_breaks_delivery(tmp_path, monkeypatch):
    """The display is a nicety. The ledger and the relay are the system."""
    root = fresh_state(tmp_path)
    monkeypatch.setenv("TIP_SETTINGS_FILE", "/proc/definitely/not/writable/settings.json")
    monkeypatch.setattr(coach.CORE, "state_dir", lambda: root)
    monkeypatch.setattr(coach, "bound_agents", lambda: {"klod"})
    monkeypatch.setattr(coach, "channel_push", lambda agent, tip: True)
    pin_for(tmp_path, monkeypatch, "sess-unwritable")
    record = complete_row("sess-unwritable", "a tip")

    coach.deliver({"agent": "klod"}, record)

    rows = coach.CORE.read_jsonl(root / "ledger.jsonl")
    assert [row for row in rows if row.get("event") == "channel-attempt"], "delivery must still be attempted"


# --------------------------------------------------------------- pane marker


def marked_pane(monkeypatch, env):
    """The tmux target mark_pane_session actually writes to, under this env."""
    seen = {}

    class Result:
        returncode = 0

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return Result()

    for name in ("CLAUDE_PANE_ID", "TMUX_PANE", "CLAUDE_TMUX_PANE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(coach.subprocess, "run", fake_run)
    coach.mark_pane_session("sess-mark")
    cmd = seen.get("cmd", [])
    return cmd[cmd.index("-t") + 1] if "-t" in cmd else None


def test_the_pane_marker_uses_the_stable_pane_id(monkeypatch):
    """A launch-time session:window.index string names another pane later.

    Verified live: this session launched as poke:1.3, moved to poke:1.2, and
    poke:1.3 resolved to a Codex pane by then. Writing there took ctips in that
    pane off its own session.
    """
    target = marked_pane(monkeypatch, {"CLAUDE_PANE_ID": "%41", "CLAUDE_TMUX_PANE": "poke:1.3"})
    assert target == "%41", "the index form must never win over the stable id"


def test_tmux_pane_is_preferred_over_the_index_form(monkeypatch):
    target = marked_pane(monkeypatch, {"TMUX_PANE": "%41", "CLAUDE_TMUX_PANE": "poke:1.3"})
    assert target == "%41"


def test_the_index_form_is_still_used_when_it_is_all_there_is(monkeypatch):
    target = marked_pane(monkeypatch, {"CLAUDE_TMUX_PANE": "poke:1.3"})
    assert target == "poke:1.3", "a caller with nothing better must still mark its pane"

