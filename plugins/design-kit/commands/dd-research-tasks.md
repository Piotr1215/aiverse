---
name: dd-research-tasks
description: "Generate Phase 1 parallel proof-of-concept tasks (one per component, 100% independent, test-driven)"
---

Generate Phase 1 proof-of-concept tasks. Each task must be 100% independent and test-driven.

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
TASKS_DIR="$SPEC_DIR/tasks"
LINEAR_FILE="$SPEC_DIR/linear.yaml"

if [[ ! -f "$PLAN_FILE" ]]; then
    echo "❌ ERROR: PLAN.md not found at $PLAN_FILE. Run /design-kit:dd-plan first."
    exit 1
fi

# Read PLAN.md for context
# Write TASK-P1-*.md files to $TASKS_DIR/
# If $LINEAR_FILE exists, also mirror each task as a Linear issue (see "Linear Sync" section below)
```

## Context

**Load these sources:**
1. Read `$SPEC_DIR/PLAN.md` - component breakdown
2. Check CLAUDE.md in the current repo for repo conventions
3. Scan codebase for existing patterns

## Task Generation Rules

### CRITICAL: Parallelism Check

**Each task MUST be 100% independent:**
- ✅ Can run simultaneously with all other Phase 1 tasks
- ✅ Uses generic/sample test data (NOT real system data)
- ✅ Proves ONE component works in isolation
- ❌ NO dependencies on other tasks
- ❌ NO integration with actual system (that's Phase 2)

### Naming Convention

Use this pattern: `TASK-P1-A-[Component].md`, `TASK-P1-B-[Component].md`, etc.

Example:
- `TASK-P1-A-pdf-generation.md`
- `TASK-P1-B-auth-middleware.md`
- `TASK-P1-C-graphql-parser.md`

### Task Template (Keep concise and focused)

```markdown
# TASK-P1-[X]-[Component]

## Goal
Prove [component X] works reliably in isolation with automated validation.

## PRIMARY OBJECTIVE: Design EFFECTIVE Testing Strategy

**BEFORE implementing, design tests that will actually stress YOUR system:**

**1. Understand What Can Go Wrong:**
- What invariants MUST hold true? (e.g., auth token never leaks, data never corrupts)
- What are failure modes specific to THIS component? (timeouts, race conditions, memory leaks)
- What edge cases are unique to YOUR use case? (not generic happy-path scenarios)

**2. Design Tests That Reveal Problems:**
- How will we detect violations of invariants? (automated assertions, monitoring)
- What conditions expose failure modes? (concurrent requests, slow networks, large data)
- Pick ONE validation tool/library that can verify these conditions

**3. Determine "Done" Criteria:**
- What pass rate indicates reliability for YOUR requirements? (critical system = higher bar)
- How many test runs validate consistency? (based on how random/timing-sensitive the component is)
- Document your rationale in TESTING.md (not arbitrary numbers)

**CRITICAL**: A great testing approach is more valuable than running arbitrary test counts.
**If you cannot design meaningful tests that stress the system, STOP and report to user immediately.**

## What to Explore

- Try at least 2 approaches: Library A vs Library B, or Technique X vs Y
- Test with: [describe generic test data]
- Compare tradeoffs: size, performance, complexity, testability

## Research Starting Points

- [Library/tool name 1]
- [Library/tool name 2]
- [Testing framework for validation]

## CRITICAL: Check Memory for Proven Test Harness Patterns

**BEFORE setting up a new test harness, check if Memory MCP has proven patterns:**

**If Memory MCP available:**
1. Search for: `[tech-stack] quick setup guide` or `[tech-stack] test harness`
2. Example queries: "Playwright quick setup", "Jest configuration", "Pytest harness", "Cypress setup"
3. Follow proven steps from memory to avoid common pitfalls

**If you create a NOVEL test harness (not in memory): YOU MUST add your setup steps to memory.**

Create memory entity with pattern: `[Tech]_Quick_Setup_Guide`. Use generic, copy-paste-ready commands. Skip project-specific details.

## Deliverable

Working proof in `$SPEC_DIR/proofs/[component-name]/` with:

**CRITICAL: Incremental Test Development (NOT batch testing):**

1. **Start Simple - Happy Path First:**
   - [ ] Set up test harness (run.sh exits 0/1, generates results/summary.json, results/logs/*.json)
   - [ ] Write ONE basic happy-path test
   - [ ] Make it pass
   - [ ] Verify test harness works end-to-end

2. **Build Iteratively - Add One Test at a Time:**
   - [ ] Identify next most important scenario (edge case, failure mode, invariant check)
   - [ ] Write ONE new test
   - [ ] Run ALL tests (catch regressions immediately)
   - [ ] Make new test pass
   - [ ] REPEAT until confidence achieved

3. **Research Multiple Approaches:**
   - [ ] Test at least 2 different approaches/libraries using same iterative method
   - [ ] Compare tradeoffs based on empirical test results
   - [ ] Pick ONE winner with documented rationale

4. **Validate Reliability:**
   - [ ] Run full test suite multiple times to validate consistency
   - [ ] Document acceptable pass rate in TESTING.md (based on requirements, not arbitrary)
   - [ ] Achieve target reliability for YOUR use case

5. **THEN Document from Empirical Evidence:**
   - [ ] TESTING.md (how to run, what's validated, pass criteria from test data)
   - [ ] CONTRACT.md (API/interface + gotchas discovered during testing)
   - [ ] FEEDBACK.md (design choices + surprises learned from test results)
   - [ ] README.md (quick start, dependencies)

**Anti-Pattern**: Writing 100+ tests then running them all at once (no regression detection)
**Correct**: Write 1 test → run ALL tests → repeat (catch regressions early)

## Edge Cases for YOUR Use Case

Think: "What breaks in MY specific scenario?"
- API endpoint? → Large payloads, timeouts, retries, malformed JSON, Unicode
- React form? → Async validation, rapid input, browser autofill, keyboard nav
- K8s controller? → Multiple replicas, network partition, OOM, node drain
- NOT generic happy-path tests!

## Done When

All checkboxes above are complete with empirical evidence.
```

## Your Task

For each component in PLAN.md:
1. Create one TASK-P1-*.md file in `$SPEC_DIR/tasks/`
2. Keep each task concise and focused
3. Emphasize testing strategy upfront
4. Ensure 100% parallelism (no cross-task dependencies)
5. Focus on WHAT to prove, not HOW to code it

## Anti-Patterns to Avoid

❌ Creating dependencies between tasks
❌ Including implementation code in task files
❌ Making tasks unnecessarily verbose
❌ Allowing manual validation (must be automated)
❌ Forgetting the Test Harness Contract (summary.json + logs/)
❌ Specifying arbitrary test counts ("100+ tests") - let requirements drive coverage

## Verification

- ✅ Can all tasks start simultaneously?
- ✅ Does each task use generic test data?
- ✅ Is testing strategy clearly defined?
- ✅ Are tasks concise and focused?
- ✅ Are test coverage targets based on requirements, not arbitrary numbers?

## Linear Sync (if linear.yaml exists)

After writing local TASK-P1-*.md files, mirror each as a Linear issue.

### Detection

```bash
[[ -f "$LINEAR_FILE" ]] || skip Linear sync
```

If `linear.yaml` is absent, skip Linear sync entirely (local-only mode).

### MCP requirement

Requires `mcp__linear-server__*`. If unreachable:
```
❌ Linear MCP not reachable. Local tasks were written, but Linear issues were NOT created.
   Fix MCP and re-run /design-kit:dd-research-tasks.
```
Do not silently continue.

### For each TASK-P1-*.md

1. Compute task ID from filename (e.g. `TASK-P1-A1` → `A1`)
2. Skip if `linear.yaml`'s `issue_map` already has this task ID (idempotent)
3. Create Linear issue:
   - **team**: from `linear.yaml` `team`
   - **project**: from `linear.yaml` `project_id`
   - **milestone**: from `linear.yaml` `research_milestone`
   - **title**: `<component>: <one-line goal>` (lowercase, no period)
   - **description**: see template below
   - **state**: `Todo`
4. Append to `linear.yaml` `issue_map`: `<task-id>: <issue-identifier>` (e.g. `A1: DEVOPS-867`)
5. Echo: `Created <issue-identifier> for <task-id>`

### Issue body template

```markdown
## Source artifacts

- **Master plan**: [<doc-title>](<plan_doc_url>)
- **Local task file**: `~/.claude/specs/<slug>/tasks/<TASK-FILE>.md`

## How to use this issue

1. Pull the master plan from the Linear document above (source of truth)
2. Read this issue body for the component-specific instructions
3. Local proof scratch space: `~/.claude/specs/<slug>/proofs/<component>/`
4. When done, comment with summary + PR link(s), then mark Done

## Goal

<task goal — copy from local TASK file>

## Testing strategy

<copy from local TASK file>

## Research starting points

<copy from local TASK file>

## Deliverables

In `~/.claude/specs/<slug>/proofs/<component>/`:
- run.sh (exits 0 / 1)
- CONTRACT.md
- TESTING.md
- FEEDBACK.md
- results/

## Done when

<copy from local TASK file>
```

### Idempotency

Re-running `/design-kit:dd-research-tasks` on an already-bound plan must not create duplicate Linear issues. Use `issue_map` to detect existing issues and update them in place via `save_issue` with `id`.

## Next Steps

After tasks are generated:
- Agent(s) execute Phase 1 tasks independently (locally and/or pulling Linear issues)
- Each produces CONTRACT.md + TESTING.md + sufficient test runs to validate requirements
- Run `/design-kit:dd-replan-after-research` to fold FEEDBACK into PLAN
- Then run `/design-kit:dd-integration-tasks` for Phase 2
