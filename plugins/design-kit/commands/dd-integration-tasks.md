---
name: dd-integration-tasks
description: "Phase 2 — generate integration tasks against the actual system. Gated on the Phase 1.5 marker."
---

Generate Phase 2 integration tasks that connect proven components to the actual system.

**CRITICAL**: Integration is ITERATIVE. It often uncovers issues not found in isolation.
Going back to Phase 1 for refinement is NORMAL and EXPECTED in real engineering.

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
PROOFS_DIR="$SPEC_DIR/proofs"
TASKS_DIR="$SPEC_DIR/tasks"
LINEAR_FILE="$SPEC_DIR/linear.yaml"
MARKER_FILE="$SPEC_DIR/.phase-1.5-complete"

if [[ ! -f "$PLAN_FILE" ]]; then
    echo "❌ ERROR: PLAN.md not found at $PLAN_FILE. Run /design-kit:dd-plan first."
    exit 1
fi

# Check Phase 1 complete - all proofs must have CONTRACT.md + TESTING.md
INCOMPLETE=()
for proof_dir in "$PROOFS_DIR"/*/ ; do
    if [[ ! -f "$proof_dir/CONTRACT.md" ]] || [[ ! -f "$proof_dir/TESTING.md" ]]; then
        INCOMPLETE+=("$(basename "$proof_dir")")
    fi
done

if [[ ${#INCOMPLETE[@]} -gt 0 ]]; then
    echo "❌ ERROR: Phase 1 incomplete. Missing CONTRACT.md or TESTING.md for:"
    printf '  - %s\n' "${INCOMPLETE[@]}"
    exit 1
fi

# Phase 1.5 gate — Phase 2 must not be planned against an unsynthesized plan.
# The marker is written by /design-kit:dd-replan-after-research after FEEDBACK is reconciled into PLAN.md.
if [[ ! -f "$MARKER_FILE" ]]; then
    echo "❌ ERROR: Phase 1.5 has not been run yet."
    echo ""
    echo "  Phase 1 produced FEEDBACK.md files. Before generating Phase 2 tasks,"
    echo "  those discoveries need to be folded back into PLAN.md (and SCHEMA.md if present)"
    echo "  so integration is planned against the latest understanding, not the original draft."
    echo ""
    echo "  Run: /design-kit:dd-replan-after-research"
    echo ""
    echo "  This will synthesize FEEDBACK.md across all proofs, propose plan deltas,"
    echo "  and write $MARKER_FILE on confirmation."
    exit 1
fi

# If FEEDBACK.md is newer than the marker, replan is stale.
STALE_FEEDBACK=$(find "$PROOFS_DIR" -name FEEDBACK.md -newer "$MARKER_FILE" 2>/dev/null)
if [[ -n "$STALE_FEEDBACK" ]]; then
    echo "❌ ERROR: Phase 1.5 marker is stale — these FEEDBACK.md files are newer:"
    echo "$STALE_FEEDBACK" | sed 's|^|  - |'
    echo ""
    echo "  Re-run /design-kit:dd-replan-after-research to fold the new feedback into PLAN.md before integrating."
    exit 1
fi

# If PLAN.md was edited after the marker, the synthesis on record is stale too.
if [[ "$PLAN_FILE" -nt "$MARKER_FILE" ]]; then
    echo "❌ ERROR: PLAN.md is newer than the Phase 1.5 marker."
    echo "  Run /design-kit:dd-replan-after-research to refresh the synthesis and the marker."
    exit 1
fi

# If SCHEMA.md exists and was edited after the marker, also stale (frozen contract drifted).
SCHEMA_FILE="$SPEC_DIR/SCHEMA.md"
if [[ -f "$SCHEMA_FILE" ]] && [[ "$SCHEMA_FILE" -nt "$MARKER_FILE" ]]; then
    echo "❌ ERROR: SCHEMA.md is newer than the Phase 1.5 marker."
    echo "  The frozen contract changed after the last replan. Run /design-kit:dd-replan-after-research to re-synthesize."
    exit 1
fi

# Read PLAN.md and proof contracts for context
# Write TASK-P2-*.md files to $TASKS_DIR/
# If $LINEAR_FILE exists, mirror each task as a Linear issue (see "Linear Sync" below)
```

## Context

**Load these sources:**
1. Read `$SPEC_DIR/PLAN.md` - integration requirements
2. Read all `$SPEC_DIR/proofs/*/CONTRACT.md` - proven component interfaces
3. Read all `$SPEC_DIR/proofs/*/TESTING.md` - validation strategies
4. Read all `$SPEC_DIR/proofs/*/FEEDBACK.md` - discoveries and gotchas
5. Check CLAUDE.md in the current repo for repo conventions
6. Scan actual codebase to understand current implementation
7. **CHECK MEMORY MCP** for proven test harness patterns to reuse Phase 1 harness

## Task Generation Rules

### Phase 1.5 — already enforced by the gate above

Phase 1.5 is no longer something this command does inline. It is a **separate command (`/design-kit:dd-replan-after-research`)** and is **enforced** by the marker check in the Setup block — if the marker is missing or stale, this command refuses to run and tells the user to run it.

By the time you reach this section, you can trust:
- All FEEDBACK.md files have been synthesized
- Plan deltas have been reviewed by the user
- PLAN.md (and SCHEMA.md if applicable) reflect the current understanding

You should still **read** the marker (`$SPEC_DIR/.phase-1.5-complete`) for the digest of what was decided in Phase 1.5 — it tells you which decisions are pinned and which items are explicitly deferred, both of which shape Phase 2 task generation.

### Integration Task Structure

Each integration task connects ONE proven component to the actual system.

### Naming Convention

Use: `TASK-P2-C-[Feature]-Integration.md`, `TASK-P2-D-[Feature]-Integration.md`, etc.

Example:
- `TASK-P2-C-pdf-generation-integration.md`
- `TASK-P2-D-auth-middleware-integration.md`

### Parallelism Check for Phase 2

**Unlike Phase 1, Phase 2 tasks may need to be sequential:**
- If tasks modify DIFFERENT files → Parallel ✅
- If tasks modify SAME files → Sequential ❌ (mark dependencies)

### Task Template

```markdown
# TASK-P2-[X]-[Feature]-Integration (Phase 2)

## Goal
Integrate proven [component] from Phase 1 into [target system].

## Prerequisites
- TASK-P1-[X] completed with CONTRACT.md at `$SPEC_DIR/proofs/[component]/CONTRACT.md`
- [If sequential] TASK-P2-[Y] completed (modifies same files: [list files])

## Current Implementation Analysis

**Existing Code**:
- [File:LineNumbers] - Current implementation
- Problems: [what's broken/missing]
- Constraints: [deployment, infrastructure limitations]

**Proven Solution** (per CONTRACT.md):
- Approach/library from Phase 1
- Benefits: [what it fixes]
- Requirements: [dependencies, infrastructure needs]

## Integration Constraints

**Critical limitations to consider:**
- Static site? Server infrastructure available?
- Build process? Deployment pipeline?
- Browser compatibility? Mobile support?
- Performance requirements? Scale?

## What to Implement

**Must Reference**: `$SPEC_DIR/proofs/[component]/CONTRACT.md` ONLY (never internal implementation)

**Replace**:
- [File:LineNumbers to be replaced]

**Preserve**:
- [Existing functionality that must not break]

**Add**:
- [New functionality]

## Integration Points

**Existing Functions to Connect**:
- `existingFunction()` - [file:line] ([how it connects])

**New Functions Needed**:
- `newFunction()` - [purpose]

## Deliverable

- Updated [files modified]
- New [dependencies, config files]
- Integration test results with REAL system data
- **Regression test report**: Re-ran Phase 1 harness with real data
  - Copy Phase 1 test harness to project root
  - Update to target REAL system endpoints (not mocks)
  - If Memory MCP has setup guide for this tech, follow it for quick setup
- README.md section: [documentation updates]
- INTEGRATION-ISSUES.md (if contract gaps found)

## Done When

- [ ] Read CONTRACT.md + TESTING.md thoroughly
- [ ] Implemented integration per contract
- [ ] Removed old dependencies/code
- [ ] Feature works with actual system data
- [ ] **Re-ran Phase 1 test harness with real data** (regression check)
- [ ] No regressions in existing functionality
- [ ] Error handling for edge cases
- [ ] Integration-level automated tests created
- [ ] Manual testing: [specific test count/scenarios]
- [ ] Updated documentation

## If Contract is Insufficient

**If integration reveals contract gaps, DO NOT work around them:**

1. Document issues in `INTEGRATION-ISSUES.md`:
   ```markdown
   # Integration Issues Found

   ## Issue 1: [Description]
   - What's missing from CONTRACT.md
   - Impact on integration
   - Required refinement
   ```

2. Create `TASK-P1-[X]-REFINEMENT-[Issue].md` in tasks/ directory
3. Agent must return to Phase 1, refine proof, update CONTRACT + TESTING
4. Re-run validation harness
5. Return to Phase 2 integration after refinement complete

**Do NOT throw away Phase 1 work. Refine it.**
```

## Your Task

For each component that needs integration:
1. Analyze existing codebase implementation
2. Read corresponding proof CONTRACT.md + TESTING.md
3. Create one TASK-P2-*.md file in `$SPEC_DIR/tasks/`
4. Specify file-level integration points
5. Mark sequential dependencies if tasks modify same files
6. Include regression testing requirements

## Sequential Dependencies Example

If multiple tasks modify the same files:

```markdown
## Prerequisites
- TASK-P1-A completed with CONTRACT.md + TESTING.md
- **TASK-P2-C completed** (modifies same files: api/server.go, api/handlers.go)
```

## Anti-Patterns to Avoid

❌ Working around insufficient contracts (go back to Phase 1!)
❌ Ignoring Phase 1 FEEDBACK.md discoveries
❌ Referencing proof implementation internals (use CONTRACT.md only)
❌ Skipping Phase 1 harness re-run with real data
❌ Forgetting to check for file conflicts (parallel vs sequential)

## Verification

- ✅ All tasks reference CONTRACT.md + TESTING.md (black-box)
- ✅ Sequential dependencies marked where files conflict
- ✅ Regression testing included (re-run Phase 1 harness)
- ✅ Refinement path clear if contracts insufficient

## Linear Sync (if linear.yaml exists)

Mirror each TASK-P2-*.md as a Linear issue in the `integrate_milestone`. Same mechanism as `/design-kit:dd-research-tasks` but the target milestone is read from `linear.yaml` `integrate_milestone` (default M3).

### Detection, MCP requirement, idempotency

Identical to `/design-kit:dd-research-tasks` — see that command for details. Quick recap:

- Detect: `$SPEC_DIR/linear.yaml` present
- MCP unreachable → flag clearly, do not silently skip
- Use `issue_map` to avoid duplicates; update existing issues via `save_issue(id=...)`

### Issue body template

```markdown
## Source artifacts

- **Master plan**: [<doc-title>](<plan_doc_url>)
- **Phase 1 contracts** (read these, NOT proof internals):
  - `~/.claude/specs/<slug>/proofs/<component>/CONTRACT.md`
  - `~/.claude/specs/<slug>/proofs/<component>/TESTING.md`
- **Local task file**: `~/.claude/specs/<slug>/tasks/<TASK-FILE>.md`

## How to use this issue

1. Pull the master plan from the Linear document above
2. Read the relevant Phase 1 CONTRACT.md + TESTING.md ONLY (never the proof's implementation)
3. This issue body lists the integration scope
4. When done, comment with summary + PR link(s), then mark Done

## Goal

<copy from local TASK file>

## Prerequisites

<copy from local TASK file>

## What to implement

<copy from local TASK file>

## Done when

<copy from local TASK file>

## If contract is insufficient

If integration reveals contract gaps, do NOT work around them. Create a REFINEMENT issue (file `TASK-P1-X-REFINEMENT-*.md` locally and a Linear sub-issue under the original Phase 1 issue), refine the proof, update CONTRACT.md, then return here.
```

## Next Steps

After Phase 2 tasks are generated:
- Agent(s) execute integration tasks (locally and/or pulling Linear issues)
- Re-run Phase 1 harnesses with real system data
- If contract gaps found → create REFINEMENT tasks
- Verify no regressions in existing functionality
- Update documentation (and re-sync the Linear plan doc if PLAN.md changed)
