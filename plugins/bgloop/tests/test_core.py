#!/usr/bin/env python3

import asyncio
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "core" / "coach.py"


def load_coach():
    spec = importlib.util.spec_from_file_location("prompt_coach", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PromptCoachTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.capabilities = self.root / "capabilities.json"
        self.capabilities.write_text(
            json.dumps(
                [
                    {
                        "id": "daily-rss",
                        "surface": "codex-skill",
                        "invocation": "$daily-rss",
                        "description": "Open the latest RSS brief and discuss the news.",
                    },
                    {
                        "id": "claim-auditor",
                        "surface": "codex-skill",
                        "invocation": "$claim-auditor",
                        "description": "Audit a report and label claims as ran, read, or inferred.",
                    },
                ]
            )
        )
        self.old_env = os.environ.copy()
        os.environ.update(
            {
                "PROMPT_COACH_STATE_DIR": str(self.state),
                "PROMPT_COACH_CAPABILITIES_FILE": str(self.capabilities),
                "PROMPT_COACH_SESSION_TOKEN_CAP": "6000",
                "PROMPT_COACH_DAILY_TOKEN_CAP": "20000",
                "PROMPT_COACH_MAX_OUTPUT_TOKENS": "400",
                "NO_COLOR": "1",
            }
        )
        self.coach = load_coach()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.temp.cleanup()

    def job(self, **overrides):
        job = {
            "job_id": "job-1",
            "session_id": "session-1",
            "pane": "%9",
            "prompt": "I have a daily RSS brief and want to discuss the important news.",
            "recent_user_prompts": [],
            "created_at": 1_800_000_000,
            "purpose": "coach",
        }
        job.update(overrides)
        return job

    @staticmethod
    def response(tip="Use $daily-rss to open the latest brief and discuss it.", capability="daily-rss"):
        value = {
            "kind": "capability",
            "tip": tip,
            "capability_id": capability,
            "reason": "The installed skill matches the task.",
        }
        return {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(value)}],
                }
            ],
            "usage": {
                "input_tokens": 700,
                "output_tokens": 120,
                "total_tokens": 820,
                "input_tokens_details": {"cached_tokens": 100},
                "output_tokens_details": {"reasoning_tokens": 40},
            },
        }

    def test_counts_first_then_records_exact_usage_and_tip(self):
        calls = []

        def post(path, payload):
            calls.append((path, payload))
            if path.endswith("/input_tokens"):
                return {"object": "response.input_tokens", "input_tokens": 700}
            return self.response()

        delivered = []
        result = self.coach.process_job(
            self.job(), post=post, deliver=lambda pane, record: delivered.append((pane, record)), now=lambda: 1_800_000_010
        )

        self.assertEqual([c[0] for c in calls], ["/v1/responses/input_tokens", "/v1/responses"])
        self.assertEqual(calls[1][1]["model"], "gpt-5.6-luna")
        self.assertEqual(calls[1][1]["max_output_tokens"], 400)
        self.assertEqual(calls[1][1]["reasoning"], {"effort": "low"})
        self.assertEqual(result["decision"], "fired")
        self.assertEqual(result["usage"]["input_tokens"], 700)
        self.assertEqual(result["usage"]["cached_input_tokens"], 100)
        self.assertEqual(result["usage"]["output_tokens"], 120)
        self.assertEqual(result["usage"]["reasoning_tokens"], 40)
        self.assertEqual(result["usage"]["total_tokens"], 820)
        self.assertEqual(delivered[0][0], "%9")
        self.assertEqual(delivered[0][1]["capability_id"], "daily-rss")

        status = self.coach.status_data(self.state, now=1_800_000_010, session_id="session-1")
        self.assertEqual(status["tokens"]["today"], 820)
        self.assertEqual(status["tokens"]["session"], 820)
        self.assertEqual(status["calls"]["session"], 1)
        self.assertEqual(status["latest"]["tip"], "Use $daily-rss to open the latest brief and discuss it.")
        self.assertEqual(status["pipeline"]["state"], "waiting-relay")
        self.assertEqual(
            [row["event"] for row in status["activity"]],
            ["started", "request", "reserved", "complete"],
        )
        self.assertEqual(status["activity"][1]["decision"], "budget-estimate")

    def test_process_job_uses_subscription_transport_without_an_api_key(self):
        os.environ.pop("OPENAI_API_KEY", None)
        calls = []

        def post(path, payload):
            calls.append(path)
            return {"input_tokens": 700} if path.endswith("/input_tokens") else self.response()

        result = self.coach.process_job(self.job(), post=post, deliver=lambda *_: None, now=lambda: 1_800_000_010)

        self.assertEqual(result["decision"], "fired")
        self.assertEqual(calls, ["/v1/responses/input_tokens", "/v1/responses"])

    def test_subscription_transport_is_ephemeral_and_maps_exact_usage(self):
        payload = self.coach.response_payload(self.job(), [], [])
        stdout = "\n".join(
            [
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"kind": "none"})}}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 18000, "cached_input_tokens": 9000, "output_tokens": 20, "reasoning_output_tokens": 4}}),
            ]
        )

        with mock.patch.object(self.coach.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=stdout, stderr="")) as run:
            response = self.coach.subscription_post("/v1/responses", payload)

        command = run.call_args.args[0]
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        config_index = command.index("--config")
        self.assertEqual(command[config_index + 1], 'model_reasoning_effort="low"')
        self.assertIn("Keep the whole response within 400 output tokens.", command[-1])
        self.assertNotIn("OPENAI_API_KEY", run.call_args.kwargs["env"])
        self.assertEqual(response["usage"]["input_tokens"], 18000)
        self.assertEqual(response["billing"], "subscription")
        self.assertEqual(self.coach.usage_cost(self.coach.usage_from_response(response)), 0.0)

    def test_internal_capability_id_is_rendered_as_native_invocation(self):
        def post(path, payload):
            if path.endswith("/input_tokens"):
                return {"input_tokens": 100}
            return self.response(tip="Use codex-skill:daily-rss to open the brief.", capability="daily-rss")

        result = self.coach.process_job(self.job(), post=post, deliver=lambda *_: None, now=lambda: 1_800_000_010)

        self.assertEqual(result["tip"], "Use $daily-rss to open the brief.")
        self.assertNotIn("codex-skill:", result["tip"])

    def test_hard_budget_blocks_before_generation(self):
        os.environ["PROMPT_COACH_SESSION_TOKEN_CAP"] = "1000"
        calls = []

        def post(path, payload):
            calls.append(path)
            return {"object": "response.input_tokens", "input_tokens": 700}

        result = self.coach.process_job(self.job(), post=post, deliver=lambda *_: None, now=lambda: 1_800_000_010)

        self.assertEqual(calls, ["/v1/responses/input_tokens"])
        self.assertEqual(result["decision"], "session-token-cap")
        self.assertEqual(result["reserved_tokens"], 1100)

    def test_zero_session_and_daily_budgets_are_unlimited(self):
        os.environ["PROMPT_COACH_SESSION_TOKEN_CAP"] = "0"
        os.environ["PROMPT_COACH_DAILY_TOKEN_CAP"] = "0"

        def post(path, *_):
            if path.endswith("/input_tokens"):
                return {"input_tokens": 700}
            return self.response()

        result = self.coach.process_job(self.job(), post=post, deliver=lambda *_: None, now=lambda: 1_800_000_010)

        self.assertEqual(result["decision"], "fired")

    def test_completed_none_calls_do_not_disable_later_coaching(self):
        self.state.mkdir(parents=True)
        ledger = self.state / "ledger.jsonl"
        rows = []
        for n in range(3):
            rows.append(
                {
                    "ts": 1_800_000_000 + n,
                    "event": "complete",
                    "decision": "none",
                    "job_id": f"old-{n}",
                    "session_id": "session-1",
                    "usage": {"total_tokens": 10},
                }
            )
        ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))

        calls = []

        def post(path, *_):
            calls.append(path)
            if path.endswith("/input_tokens"):
                return {"input_tokens": 700}
            return self.response()

        result = self.coach.process_job(self.job(), post=post, deliver=lambda *_: None, now=lambda: 1_800_000_010)

        self.assertEqual(result["decision"], "fired")
        self.assertEqual(calls, ["/v1/responses/input_tokens", "/v1/responses"])

    def test_a_recent_completed_call_does_not_back_off_the_next_prompt(self):
        self.state.mkdir(parents=True)
        (self.state / "ledger.jsonl").write_text(
            json.dumps(
                {
                    "ts": 1_800_000_005,
                    "event": "complete",
                    "decision": "fired",
                    "job_id": "old",
                    "session_id": "session-1",
                    "purpose": "recap+coach",
                    "usage": {"total_tokens": 10},
                }
            )
            + "\n"
        )
        calls = []

        def post(path, *_):
            calls.append(path)
            if path.endswith("/input_tokens"):
                return {"input_tokens": 700}
            return self.response()

        result = self.coach.process_job(
            self.job(purpose="recap+coach"),
            post=post,
            deliver=lambda *_: None,
            now=lambda: 1_800_000_010,
        )

        self.assertEqual(result["decision"], "fired")
        self.assertEqual(calls, ["/v1/responses/input_tokens", "/v1/responses"])

    def test_uninstalled_capability_is_refused_but_usage_is_still_counted(self):
        def post(path, payload):
            if path.endswith("/input_tokens"):
                return {"object": "response.input_tokens", "input_tokens": 500}
            return self.response(capability="invented-skill")

        result = self.coach.process_job(self.job(), post=post, deliver=lambda *_: self.fail("must not deliver"), now=lambda: 1_800_000_010)

        self.assertEqual(result["decision"], "invalid-capability")
        self.assertEqual(result["usage"]["total_tokens"], 820)

    def test_marking_a_capability_learned_suppresses_later_variants_without_ai(self):
        learned = self.coach.mark_learned(
            self.state,
            "Use $daily-rss to open the latest brief and discuss it.",
            now=1_800_000_000,
            capability_id="daily-rss",
        )
        self.assertEqual(learned["capability_id"], "daily-rss")

        def post(path, payload):
            if path.endswith("/input_tokens"):
                return {"object": "response.input_tokens", "input_tokens": 500}
            return self.response(tip="Use $daily-rss for the current RSS brief.")

        result = self.coach.process_job(self.job(), post=post, deliver=lambda *_: self.fail("must not deliver"), now=lambda: 1_800_000_010)

        self.assertEqual(result["decision"], "learned")
        self.assertEqual(self.coach.status_data(self.state, now=1_800_000_010)["learned_count"], 1)

    def test_restore_removes_the_latest_learned_rule(self):
        first = self.coach.mark_learned(self.state, "First lesson", now=1_800_000_000)
        second = self.coach.mark_learned(self.state, "Second lesson", now=1_800_000_001)

        restored = self.coach.restore_learned(self.state)

        self.assertEqual(restored["id"], second["id"])
        remaining = self.coach.load_learned(self.state)
        self.assertEqual([row["id"] for row in remaining], [first["id"]])

    def test_disabled_system_never_calls_the_subscription_transport(self):
        self.state.mkdir(parents=True)
        (self.state / "disabled").write_text("disabled\n")

        result = self.coach.process_job(
            self.job(), post=lambda *_: self.fail("transport must not run"), deliver=lambda *_: None, now=lambda: 1_800_000_010
        )

        self.assertEqual(result["decision"], "disabled")

    def test_enqueue_detaches_a_worker_without_calling_luna(self):
        payload = {"session_id": "session-1", "prompt": "Help me use the native daily RSS workflow."}
        os.environ["CODEX_APP_SERVER_SOCKET"] = "/tmp/prompt-coach.sock"

        with (
            mock.patch.object(self.coach.time, "time", return_value=1_800_000_000),
            mock.patch.object(self.coach.subprocess, "run") as run,
            mock.patch.object(self.coach.subprocess, "Popen") as popen,
        ):
            self.coach.enqueue(payload)

        popen.assert_called_once()
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.kwargs["stdin"], self.coach.subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs["env"]["CODEX_APP_SERVER_SOCKET"], "/tmp/prompt-coach.sock")
        self.assertNotIn("OPENAI_API_KEY", popen.call_args.kwargs["env"])
        queued = [row for row in self.coach.read_jsonl(self.state / "ledger.jsonl") if row["event"] == "queued"]
        self.assertEqual(len(queued), 1)
        job = json.loads(next((self.state / "jobs").glob("*.json")).read_text())
        self.assertEqual(job["not_before"], 1_800_000_001)
        options = [call.args[0][5] for call in run.call_args_list if call.args[0][:4] == ["tmux", "set-option", "-p", "-t"]]
        self.assertNotIn("@claude_goal", options)
        self.assertNotIn("@claude_goal_src", options)

    def test_enqueue_ignores_a_synthetic_coach_steer(self):
        payload = {
            "session_id": "session-1",
            "prompt": "<coach> Automated prompt-coach advice: use codex review.",
        }

        with mock.patch.object(self.coach.subprocess, "Popen") as popen:
            result = self.coach.enqueue(payload)

        self.assertEqual(result, 0)
        popen.assert_not_called()
        self.assertEqual(self.coach.read_jsonl(self.state / "ledger.jsonl"), [])

    def test_dedupe_stamp_matches_only_the_exact_same_prompt(self):
        first = self.coach.dedupe_stamp(self.state, "session-1", "first prompt")
        duplicate = self.coach.dedupe_stamp(self.state, "session-1", "first prompt")
        distinct = self.coach.dedupe_stamp(self.state, "session-1", "second prompt")

        self.assertEqual(first, duplicate)
        self.assertNotEqual(first, distinct)

    def test_session_budget_does_not_reset_at_midnight(self):
        self.state.mkdir(parents=True)
        yesterday = 1_799_913_610
        today = 1_800_000_010
        (self.state / "ledger.jsonl").write_text(
            json.dumps(
                {
                    "ts": yesterday,
                    "event": "complete",
                    "decision": "none",
                    "job_id": "old",
                    "session_id": "session-1",
                    "usage": {"total_tokens": 5000},
                }
            )
            + "\n"
        )

        status = self.coach.status_data(self.state, now=today, session_id="session-1")

        self.assertEqual(status["tokens"]["today"], 0)
        self.assertEqual(status["tokens"]["session"], 5000)

    def test_status_scopes_tip_call_and_decision_to_requested_session(self):
        self.state.mkdir(parents=True)
        rows = [
            {"ts": 0.5, "event": "queued", "decision": "queued", "purpose": "recap+coach", "job_id": "a", "session_id": "session-1"},
            {"ts": 1, "event": "complete", "decision": "fired", "job_id": "a", "session_id": "session-1", "tip": "Session one", "usage": {"total_tokens": 1}, "cost_usd": 0.1},
            {"ts": 1.5, "event": "queued", "decision": "queued", "purpose": "recap+coach", "job_id": "b", "session_id": "session-2"},
            {"ts": 2, "event": "complete", "decision": "fired", "job_id": "b", "session_id": "session-2", "tip": "Session two", "usage": {"total_tokens": 1}, "cost_usd": 0.2},
            {"ts": 2.5, "event": "relayed", "decision": "relayed", "purpose": "relay", "job_id": "relay-a", "source_job_id": "a", "through_ts": 1, "session_id": "session-1"},
            {"ts": 3, "event": "blocked", "decision": "spacing", "purpose": "recap+coach", "session_id": "session-1"},
            {"ts": 4, "event": "blocked", "decision": "session-call-cap", "purpose": "recap+coach", "session_id": "session-2"},
        ]
        (self.state / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

        status = self.coach.status_data(self.state, now=10, session_id="session-1")

        self.assertEqual(status["latest"]["tip"], "Session one")
        self.assertEqual(status["latest_call"]["session_id"], "session-1")
        self.assertEqual(status["last_decision"]["decision"], "spacing")
        self.assertEqual({row["session_id"] for row in status["activity"]}, {"session-1"})
        self.assertEqual(status["pipeline"], {"state": "idle", "reason": "spacing"})
        self.assertAlmostEqual(status["cost_usd_today"], 0.3)
        self.assertEqual(
            status["billing"],
            {"subscription_calls_today": 0, "historical_api_calls_today": 2},
        )

    def test_status_counts_mixed_daily_billing_without_using_the_latest_call(self):
        self.state.mkdir(parents=True)
        rows = [
            {
                "ts": 1,
                "event": "complete",
                "decision": "fired",
                "job_id": "legacy",
                "session_id": "session-1",
                "usage": {"total_tokens": 1, "billing": "api"},
                "cost_usd": 0.2,
            },
            {
                "ts": 2,
                "event": "complete",
                "decision": "none",
                "job_id": "subscription",
                "session_id": "session-1",
                "usage": {"total_tokens": 1, "billing": "subscription"},
                "cost_usd": 0,
            },
        ]
        (self.state / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

        status = self.coach.status_data(self.state, now=10)

        self.assertEqual(
            status["billing"],
            {"subscription_calls_today": 1, "historical_api_calls_today": 1},
        )
        self.assertAlmostEqual(status["cost_usd_today"], 0.2)

    def test_status_exposes_the_current_background_stage(self):
        self.state.mkdir(parents=True)
        rows = [
            {"ts": 8, "event": "queued", "decision": "queued", "purpose": "recap+coach", "job_id": "active", "session_id": "session-1"},
            {"ts": 9, "event": "request", "decision": "token-count", "purpose": "recap+coach", "job_id": "active", "session_id": "session-1"},
        ]
        (self.state / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

        status = self.coach.status_data(self.state, now=10, session_id="session-1")

        self.assertEqual(
            status["pipeline"],
            {"state": "running", "stage": "token-count", "job_id": "active", "since_ts": 9},
        )

    def test_simulator_records_a_visible_zero_token_tip(self):
        delivered = []

        record = self.coach.simulate(
            "Help me use the daily RSS workflow.",
            pane="%9",
            session_id="session-1",
            deliver=lambda pane, value: delivered.append((pane, value)),
            now=1_800_000_010,
        )

        self.assertEqual(record["event"], "simulated")
        self.assertEqual(record["usage"]["total_tokens"], 0)
        self.assertEqual(delivered[0][0], "%9")
        self.assertIn("daily-rss", record["tip"])
        status = self.coach.status_data(self.state, now=1_800_000_010, session_id="session-1")
        self.assertEqual(status["tokens"]["today"], 0)
        self.assertEqual(status["latest"]["event"], "simulated")

    def test_delivery_does_not_interrupt_tmux_with_a_popup(self):
        record = {"goal": "Inspect the tip system", "tip": "Use $prompt-coach."}

        with mock.patch.object(self.coach.subprocess, "run") as run:
            self.coach.deliver_tip("%9", record)

        display = [call.args[0] for call in run.call_args_list if call.args[0][1] == "display-message"]
        self.assertEqual(display, [])

    def test_delivery_keeps_the_persisted_tip_free_of_display_prefixes(self):
        record = {"tip": "Use $prompt-coach."}

        with mock.patch.object(self.coach.subprocess, "run") as run:
            self.coach.deliver_tip("%9", record)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["tmux", "set-option", "-p", "-t", "%9", "@prompt_coach_tip", "Use $prompt-coach."], commands)
        self.assertNotIn("Codex tip:", record["tip"])

    def test_delivery_never_overwrites_the_task_goal(self):
        record = {"goal": "The latest user message", "tip": "Use $prompt-coach."}

        with mock.patch.object(self.coach.subprocess, "run") as run:
            self.coach.deliver_tip("%9", record)

        options = [call.args[0][5] for call in run.call_args_list if call.args[0][:5] == ["tmux", "set-option", "-p", "-t", "%9"]]
        self.assertNotIn("@claude_goal", options)
        self.assertNotIn("@claude_goal_src", options)

    def test_pending_relay_bundles_ordered_unique_tips_once(self):
        self.state.mkdir(parents=True)
        rows = [
            {
                "ts": 1_800_000_000 + n,
                "event": "complete",
                "decision": "fired",
                "job_id": f"tip-{n}",
                "session_id": "session-1",
                "purpose": "recap+coach",
                "tip": tip,
                "capability_id": "daily-rss",
                "reason": f"Reason {n}",
                "usage": {"total_tokens": 10},
            }
            for n, tip in enumerate(("First tip", "First tip", "Second tip"))
        ]
        (self.state / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

        relay = self.coach.claim_pending_relay(self.state, "session-1", now=1_800_000_010)

        context = relay["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Codex tips:\n- First tip\n- Second tip", context)
        self.assertNotIn("Luna decision trace", context)
        self.assertNotIn("Reason 2", context)
        self.assertIsNone(self.coach.claim_pending_relay(self.state, "session-1", now=1_800_000_011))
        event = self.coach.read_jsonl(self.state / "ledger.jsonl")[-1]
        self.assertEqual(event["event"], "relayed")
        self.assertEqual(event["delivery"], "next-prompt-hook")
        self.assertEqual(event["extra_model_calls"], 0)
        self.assertEqual(event["injected_bytes"], len(context.encode()))
        status = self.coach.status_data(self.state, now=1_800_000_010, session_id="session-1")
        self.assertEqual(status["latest_relay"]["tip"], "2 tips bundled")
        self.assertEqual(status["latest_relay"]["tips"], ["First tip", "Second tip"])
        self.assertEqual(status["latest_relay"]["injected_bytes"], len(context.encode()))

    def test_pending_relay_buffer_is_bounded_without_dropping_the_remainder(self):
        self.state.mkdir(parents=True)
        rows = [
            {
                "ts": 1_800_000_000 + n,
                "event": "complete",
                "decision": "fired",
                "job_id": f"tip-{n}",
                "session_id": "session-1",
                "purpose": "recap+coach",
                "tip": f"Tip {n}",
                "usage": {"total_tokens": 10},
            }
            for n in range(3)
        ]
        (self.state / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        os.environ["PROMPT_COACH_RELAY_MAX_TIPS"] = "2"

        first = self.coach.claim_pending_relay(self.state, "session-1", now=1_800_000_010)
        second = self.coach.claim_pending_relay(self.state, "session-1", now=1_800_000_011)

        self.assertIn("Tip 0", first["hookSpecificOutput"]["additionalContext"])
        self.assertIn("Tip 1", first["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("Tip 2", first["hookSpecificOutput"]["additionalContext"])
        self.assertIn("Codex tip: Tip 2", second["hookSpecificOutput"]["additionalContext"])

    def test_replay_makes_latest_tip_pending_for_another_session_without_model_usage(self):
        self.state.mkdir(parents=True)
        (self.state / "ledger.jsonl").write_text(
            json.dumps(
                {
                    "ts": 1_800_000_000,
                    "event": "complete",
                    "decision": "fired",
                    "job_id": "source",
                    "session_id": "probe",
                    "tip": "Use $daily-rss.",
                    "reason": "It matches the current task.",
                    "usage": {"total_tokens": 700},
                }
            )
            + "\n"
        )

        replay = self.coach.replay_latest(self.state, "session-1", now=1_800_000_010)
        relay = self.coach.claim_pending_relay(self.state, "session-1", now=1_800_000_011)

        self.assertEqual(replay["event"], "replayed")
        self.assertNotIn("usage", replay)
        self.assertIn("Codex tip: Use $daily-rss.", relay["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("Luna decision trace", relay["hookSpecificOutput"]["additionalContext"])

    def test_active_turn_receives_tip_by_steer_without_a_new_turn(self):
        calls = []

        async def request(method, params):
            calls.append((method, params))
            if method == "thread/read":
                return {"thread": {"status": {"type": "active"}, "turns": [{"id": "turn-1", "status": "inProgress"}]}}
            return {"turnId": "turn-1"}

        result = asyncio.run(self.coach.steer_active_turn(request, "thread-1", "Use codex resume.", "private trace"))

        self.assertEqual(result, "steered")
        self.assertEqual([method for method, _ in calls], ["thread/read", "turn/steer"])
        steer = calls[-1][1]
        self.assertEqual(steer["expectedTurnId"], "turn-1")
        self.assertIn("Use codex resume.", steer["input"][0]["text"])
        self.assertNotIn("private trace", steer["input"][0]["text"])

    def test_idle_turn_keeps_tip_pending_without_starting_a_turn(self):
        calls = []

        async def request(method, params):
            calls.append((method, params))
            return {"thread": {"status": {"type": "idle"}, "turns": []}}

        result = asyncio.run(self.coach.steer_active_turn(request, "thread-1", "Use codex resume.", "private trace"))

        self.assertEqual(result, "pending")
        self.assertEqual([method for method, _ in calls], ["thread/read"])

    def test_successful_steer_records_immediate_zero_call_delivery(self):
        os.environ["CODEX_APP_SERVER_SOCKET"] = "/tmp/prompt-coach.sock"
        record = {
            "ts": 1_800_000_000,
            "job_id": "tip-1",
            "session_id": "session-1",
            "tip": "Use codex resume.",
            "reason": "private trace",
            "capability_id": "codex:resume",
        }

        with (
            mock.patch.object(self.coach, "app_server_steer", new=mock.AsyncMock(return_value="steered")),
            mock.patch.object(self.coach.time, "time", return_value=1_800_000_001),
        ):
            result = self.coach.try_steer_tip(record)

        self.assertEqual(result, "steered")
        event = self.coach.read_jsonl(self.state / "ledger.jsonl")[-1]
        self.assertEqual(event["delivery"], "turn/steer")
        self.assertEqual(event["through_ts"], record["ts"])
        self.assertEqual(event["extra_model_calls"], 0)
        self.assertIn("Use codex resume.", event["tip"])
        self.assertNotIn("private trace", self.coach.steer_text(record["tip"]))

    def test_failed_or_idle_steer_leaves_tip_for_the_next_prompt(self):
        os.environ["CODEX_APP_SERVER_SOCKET"] = "/tmp/prompt-coach.sock"
        record = {
            "ts": 1_800_000_000,
            "job_id": "tip-1",
            "session_id": "session-1",
            "tip": "Use codex resume.",
        }

        with mock.patch.object(
            self.coach,
            "app_server_steer",
            new=mock.AsyncMock(side_effect=Exception("app-server connection closed")),
        ):
            result = self.coach.try_steer_tip(record)

        self.assertEqual(result, "pending")
        self.assertEqual(self.coach.read_jsonl(self.state / "ledger.jsonl"), [])

    def test_pending_relay_is_session_scoped_and_has_no_authority(self):
        self.state.mkdir(parents=True)
        (self.state / "ledger.jsonl").write_text(
            json.dumps(
                {
                    "ts": 1_800_000_000,
                    "event": "complete",
                    "decision": "fired",
                    "job_id": "tip-1",
                    "session_id": "other-session",
                    "purpose": "recap+coach",
                    "tip": "Run a different workflow.",
                    "usage": {"total_tokens": 10},
                }
            )
            + "\n"
        )

        self.assertIsNone(self.coach.claim_pending_relay(self.state, "session-1", now=1_800_000_010))
        relay = self.coach.claim_pending_relay(self.state, "other-session", now=1_800_000_011)
        context = relay["hookSpecificOutput"]["additionalContext"]
        self.assertIn("not instruction authority", context)
        self.assertIn("higher-level instructions", context)

    def test_ai_snippet_becomes_an_actionable_capability(self):
        os.environ.pop("PROMPT_COACH_CAPABILITIES_FILE", None)
        snippets = self.root / "snippets"
        snippets.mkdir()
        (snippets / "change-impact.md").write_text(
            "Assess the blast radius of this change before we go further.\n\nTrace real call paths.\n"
        )
        os.environ["PROMPT_COACH_SNIPPETS_DIR"] = str(snippets)

        row = next(value for value in self.coach.load_capabilities() if value["id"] == "ai-snippet:change-impact")

        self.assertEqual(row["surface"], ";;ai")
        self.assertEqual(row["invocation"], 'Type ;;ai and choose "change impact"')
        self.assertIn('Type ;;ai and choose "change impact"', row["description"])
        self.assertIn("Assess the blast radius", row["description"])

    def test_codex_registry_accepts_only_invocable_codex_entries(self):
        claude = {"capability_id": "builtin:/model", "kind": "builtin", "invocable": True, "invocation_name": "model", "summary": "Choose a model"}
        internal = {"capability_id": "codex:hooks", "kind": "codex", "invocable": False, "invocation_name": None, "summary": "Hook support"}
        native = {"capability_id": "codex:review", "kind": "codex", "invocable": True, "invocation_name": "review", "summary": "Review changes"}

        self.assertIsNone(self.coach.codex_registry_capability(claude))
        self.assertIsNone(self.coach.codex_registry_capability(internal))
        self.assertEqual(self.coach.codex_registry_capability(native)["invocation"], "codex review")

    def test_ai_snippet_is_retrieved_by_its_prompt_content(self):
        row = self.coach.parse_ai_snippet(self.root / "missing.md")
        self.assertIsNone(row)
        snippet = self.root / "verify-claims.md"
        snippet.write_text("Label every claim as ran, read, or inferred and name the evidence.\n")
        capability = self.coach.parse_ai_snippet(snippet)

        selected = self.coach.select_capabilities("verify every claim and label its evidence", [capability], limit=1)

        self.assertEqual(selected[0]["id"], "ai-snippet:verify-claims")

    def test_autonomous_language_retrieves_the_just_act_snippet(self):
        snippet = self.root / "just-act.md"
        snippet.write_text("Act with autonomy, keep my context small, and bring me results.\n")
        capability = self.coach.parse_ai_snippet(snippet)

        selected = self.coach.select_capabilities("ok continue autonomously", [capability], limit=1)

        self.assertEqual(selected[0]["id"], "ai-snippet:just-act")
        self.assertGreater(self.coach.capability_match_score("ok continue autonomously", selected[0]), 0)

    def test_luna_is_told_to_render_snippets_through_the_real_picker(self):
        snippet = {
            "id": "ai-snippet:just-act",
            "surface": ";;ai",
            "invocation": 'Type ;;ai and choose "just act"',
            "description": 'Type ;;ai and choose "just act" to paste this prompt.',
        }

        request = self.coach.response_payload(self.job(), [snippet], [])

        installed = json.loads(request["input"])["installed_capabilities"]
        self.assertIn('invoke=Type ;;ai and choose "just act"', installed[0])
        self.assertIn("never expose that raw id", request["instructions"])
        self.assertIn("12 to 15 short lines", request["instructions"])

    def test_luna_must_preserve_explicit_method_constraints(self):
        request = self.coach.response_payload(self.job(), [], [])

        self.assertIn("explicit method", request["instructions"])
        self.assertIn("later cross-check", request["instructions"])
        self.assertIn("return kind none", request["instructions"])

    def test_luna_is_scoped_to_the_agent_harness_not_the_task_domain(self):
        request = self.coach.response_payload(self.job(), [], [])

        self.assertIn("Your specialty is agent workflow", request["instructions"])
        self.assertIn("Do not solve or advise on the repository, shell, infrastructure, application", request["instructions"])
        self.assertIn("If no harness-level improvement exists, return kind none", request["instructions"])
        self.assertNotIn("goal", request["text"]["format"]["schema"]["properties"])

    def test_persistent_budget_is_visible_and_blocks_generation(self):
        os.environ.pop("PROMPT_COACH_SESSION_TOKEN_CAP", None)
        configured = self.coach.set_budget(self.state, "session", 900)
        self.assertEqual(configured["session_token_cap"], 900)

        calls = []

        def post(path, payload):
            calls.append(path)
            return {"object": "response.input_tokens", "input_tokens": 600}

        result = self.coach.process_job(self.job(), post=post, deliver=lambda *_: None, now=lambda: 1_800_000_010)

        self.assertEqual(result["decision"], "session-token-cap")
        self.assertEqual(calls, ["/v1/responses/input_tokens"])
        status = self.coach.status_data(self.state, now=1_800_000_010, session_id="session-1")
        self.assertEqual(status["tokens"]["session_cap"], 900)


if __name__ == "__main__":
    unittest.main()
