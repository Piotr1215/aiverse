---
name: dd-replan-after-research
description: "Phase 1.5 — synthesize FEEDBACK across proofs, propose plan/schema deltas, write the marker that gates integration"
---

Run the Phase 1.5 feedback loop: read every `FEEDBACK.md` from completed proofs, propose deltas to `PLAN.md` and (if present) `SCHEMA.md`, get user confirmation, write a `.phase-1.5-complete` marker so `/design-kit:dd-integration-tasks` will run.

**Phase 1.5 is a peer phase**, not an afterthought. Skipping it is the most common failure mode of this kit: integration tasks get generated against an outdated plan, surprises from research never propagate, and contract gaps that should have been reconciled show up as integration churn instead.

## Setup

```bash
# Resolve global spec dir via the per-repo pointer
output=$("${CLAUDE_PLUGIN_ROOT}/scripts/auto-connect-design.sh")
SPEC_DIR=$(echo "$output" | awk '/^SpecDir:/ {print $2}')
SLUG=$(echo "$output" | awk '/^Slug:/ {print $2}')

if [[ -z "$SPEC_DIR" ]]; then
    echo "❌ ERROR: No project bound to this repo. Run /design-kit:dd-plan first to bind."
    exit 1
fi

PLAN_FILE="$SPEC_DIR/PLAN.md"
SCHEMA_FILE="$SPEC_DIR/SCHEMA.md"   # optional — only some projects freeze a contract
PROOFS_DIR="$SPEC_DIR/proofs"
MARKER_FILE="$SPEC_DIR/.phase-1.5-complete"

if [[ ! -f "$PLAN_FILE" ]]; then
    echo "❌ ERROR: PLAN.md not found at $PLAN_FILE. Run /design-kit:dd-plan first."
    exit 1
fi

# Phase 1 must be complete — every proof needs CONTRACT.md + TESTING.md + FEEDBACK.md
INCOMPLETE=()
MISSING_FEEDBACK=()
for proof_dir in "$PROOFS_DIR"/*/ ; do
    name=$(basename "$proof_dir")
    if [[ ! -f "$proof_dir/CONTRACT.md" ]] || [[ ! -f "$proof_dir/TESTING.md" ]]; then
        INCOMPLETE+=("$name")
    fi
    if [[ ! -f "$proof_dir/FEEDBACK.md" ]]; then
        MISSING_FEEDBACK+=("$name")
    fi
done

if [[ ${#INCOMPLETE[@]} -gt 0 ]]; then
    echo "❌ Phase 1 incomplete — these proofs are missing CONTRACT.md or TESTING.md:"
    printf '  - %s\n' "${INCOMPLETE[@]}"
    echo "Finish Phase 1 first."
    exit 1
fi

if [[ ${#MISSING_FEEDBACK[@]} -gt 0 ]]; then
    echo "⚠ These proofs have no FEEDBACK.md (will be skipped from synthesis):"
    printf '  - %s\n' "${MISSING_FEEDBACK[@]}"
fi
```

> **Why missing FEEDBACK.md is a warning, not an error:** task templates list `FEEDBACK.md` as a required deliverable, but proofs that genuinely had nothing surprising to feed back are real. Hard-erroring would push agents to write empty FEEDBACK.md files just to satisfy the gate. The intentional choice: proceed with whatever feedback exists; surface the gap so the user can verify the proof author meant to leave it empty.

## Task Description

You are running Phase 1.5. Your job is **synthesis and reconciliation**, not new task generation.

## Workflow

### 1. Read everything

- `PLAN.md` (current source of truth — preserve YAML frontmatter `slug` / `parent_spec` / `derived_from_task` verbatim across edits; lineage is not synthesis material)
- `SCHEMA.md` (if present — frozen contract; gaps surface here)
- Every `proofs/*/FEEDBACK.md`
- Every `proofs/*/CONTRACT.md` (so you can spot drift between what the plan promised and what proofs delivered)

### 2. Synthesize a deltas digest

Group findings into these categories, lifted from FEEDBACK.md content:

- **Schema gaps** — fields proofs found missing or under-specified in `SCHEMA.md`
- **Plan corrections** — components whose scope, approach, or split changed during research
- **New risks** — failure modes / edge cases discovered that aren't reflected in PLAN.md
- **Cross-component contract drift** — places where two proofs assumed different shapes for the same boundary
- **Decisions worth pinning** — A1-vs-A2-style verdicts (or any picked-one-of-many decisions) that should be locked into PLAN.md so Phase 2 doesn't re-litigate them
- **Out-of-scope / deferred** — anything proofs flagged that should NOT be acted on now (record so it doesn't get lost)

For each item, cite the proof (e.g. "[from `proofs/observer-workflow/FEEDBACK.md`]") so the user can trust-but-verify.

### 3. Propose concrete edits

Show the user a unified summary:

```
PROPOSED DELTAS
===============

PLAN.md edits
-------------
1. <one-line description> — <why> — [from <component>]
2. ...

SCHEMA.md edits (if present)
----------------------------
1. <field / shape change> — <why> — [from <component>]
2. ...

Decisions to pin
----------------
1. <decision> — [from <component>]
2. ...

Deferred / out of scope
-----------------------
1. <item> — [from <component>]
```

### 4. Confirm with the user

Ask: "Apply these deltas to PLAN.md (and SCHEMA.md if present)? [yes / let me edit / skip]"

- **yes** → apply edits in place, then continue to step 5
- **let me edit** → write the proposed deltas to `$SPEC_DIR/REPLAN-PROPOSAL.md` and stop. The user edits, then re-runs `/design-kit:dd-replan-after-research` to apply
- **skip** → write the marker anyway with `decision: skip` (user explicitly said the plan is fine as-is); continue to step 5

### 5. Write the marker

Write `$SPEC_DIR/.phase-1.5-complete` with this content:

```markdown
# Phase 1.5 marker — generated by /design-kit:dd-replan-after-research

generated_at: <ISO 8601 timestamp>
slug: <slug>

# Proofs that contributed feedback
contributors:
  - <component-1>
  - <component-2>

# Summary of applied deltas (or "no deltas" if user skipped)
deltas_applied:
  plan: <count or "none">
  schema: <count or "none" or "n/a — no SCHEMA.md">

# Full digest below — useful as audit trail for /design-kit:dd-integration-tasks
---

## Plan changes applied
<bulleted list>

## Schema changes applied
<bulleted list>

## Decisions pinned
<bulleted list>

## Deferred
<bulleted list>
```

The marker is the gate `/design-kit:dd-integration-tasks` will check. Re-running this command overwrites it.

### 6. Linear sync (if linear.yaml exists)

If `$SPEC_DIR/linear.yaml` is present:
- Update the Linear plan document with the new `PLAN.md` content (`mcp__linear-server__save_document` with `id` from `linear.yaml.plan_doc_id`)
- Post a comment on each contributing Phase 1 issue: "Phase 1.5 complete — see updated plan: <plan_doc_url>" (only if the issue isn't already in a Done state)
- Do **not** change Linear issue states automatically — that's the user's call

If MCP is unreachable, print a warning but still write the marker (local-only mode is supported).

## Anti-Patterns

❌ Generating new TASK-P1-* files — that's `/design-kit:dd-research-tasks`'s job, and only after the user explicitly asks for refinement
❌ Editing proof contents (CONTRACT.md, TESTING.md inside `proofs/<x>/`) — those are owned by the proof author
❌ Auto-applying deltas without showing the user — synthesis is fast, blind edits are not
❌ Skipping the marker write — without it, `/design-kit:dd-integration-tasks` will refuse to run
❌ Treating FEEDBACK.md as advisory only — every entry is a real signal; "no change" is a valid response but must be a deliberate one

## When to Re-Run

- After any Phase 1 task is updated (refinement loop) — re-run to re-synthesize
- After `PLAN.md` is edited manually — re-run to refresh the marker so the gate stays valid
- Before `/design-kit:dd-integration-tasks` if it's been more than a few days since the last replan

## Verification

After running:
- ✅ `.phase-1.5-complete` exists at `$SPEC_DIR/`
- ✅ Every proof's FEEDBACK.md was read and is reflected in the digest (or explicitly excluded)
- ✅ User saw the proposed deltas before they were applied
- ✅ Linear plan doc updated if linear.yaml exists

## Next Steps

- Run `/design-kit:dd-integration-tasks` to generate Phase 2 tasks (the gate will now pass)
- Or run `/design-kit:dd-status` for a state-machine view of where the project stands
