---
name: dd-plan
description: "Create a master implementation plan: components, three-phase breakdown, optional Linear binding"
---

Create a master implementation plan following the design-kit philosophy: test-driven, parallel execution, contract-based integration.

## Setup

```bash
# 1. Determine slug for this project. Order:
#    a) If args contain a Linear project URL, derive slug from project name (kebab-case)
#    b) Else if --slug <name> passed in args, use that
#    c) Else prompt user: "Project slug (kebab-case, e.g. docs-config-automation)?"
SLUG="<derived-or-prompted>"

# 2. Bind this repo to the project (creates global spec dir + local pointer)
"${CLAUDE_PLUGIN_ROOT}/scripts/auto-connect-design.sh" --init "$SLUG"

# 3. Compute paths
SPEC_DIR="$HOME/.claude/specs/$SLUG"
PLAN_FILE="$SPEC_DIR/PLAN.md"

# 4. Check if PLAN.md already exists
if [[ -f "$PLAN_FILE" ]]; then
    echo "❌ ERROR: PLAN.md already exists at $PLAN_FILE"
    echo "   The project '$SLUG' already has a plan."
    echo "   To recreate: rm $PLAN_FILE"
    echo "   To bind THIS repo to that existing project without recreating: just keep going — the pointer was set."
    exit 1
fi
```

**Path model**: plans are stored globally at `~/.claude/specs/<slug>/`, not per-branch in the current repo. Each repo that participates in the project drops a pointer file `<repo>/.claude/current-project` containing the slug. Multiple repos and multiple branches can share one plan — Phase 1 proofs and Phase 2 task files all live in the global location.

## Task Description

Given project requirements: `{ARGS}`

## FIRST: Detect Current Phase

**Before creating PLAN.md, determine project state:**

1. Check `$SPEC_DIR/proofs/` - any proofs exist?
2. Check `$SPEC_DIR/tasks/` - any tasks exist?
3. Determine appropriate action based on findings

## SECOND: Search the Corpus

**Before decomposing into components, mine prior research.** Every spec under
`~/.claude/specs/` is a record of work the team has already done — proofs
written, contracts hardened, surprises documented. New plans should stand on
those shoulders, not start cold.

After you've drafted the rough component list (in your head, not yet on disk),
search the corpus for adjacent prior work:

```bash
# Find candidate prior proofs by keyword. Run for each component you intend to propose.
grep -lri --include='CONTRACT.md' --include='FEEDBACK.md' \
    -e '<keyword-1>' -e '<keyword-2>' \
    "$HOME/.claude/specs/" 2>/dev/null | grep -v "^$SPEC_DIR/"
```

For each hit, read the `CONTRACT.md` (interface already proven) and the
sibling `FEEDBACK.md` (gotchas already discovered). Decide:

- **Reuse**: prior contract is sufficient → reference it in the new PLAN.md, don't re-prove
- **Refine**: prior contract is close but needs extension → call out the delta, prove only the delta in Phase 1
- **Independent**: no usable overlap → proceed normally

Surface findings to the user before writing PLAN.md:

```
Corpus search for components: [token-validator, rate-limiter]

Prior work found:
  ~/.claude/specs/auth-rewrite/proofs/oauth-jwt/        — CONTRACT.md covers JWT validation (reusable)
  ~/.claude/specs/api-hardening/proofs/redis-rate-limit/ — CONTRACT.md + FEEDBACK.md (gotcha: clock skew at boundaries)

Reusing: oauth-jwt contract for token-validator (no Phase 1 task needed)
New work: rate-limiter (extending redis-rate-limit pattern; new TASK-P1 will reference it)
```

If no prior work matches, say so explicitly: `Corpus search: no prior proofs match.` Don't be silent.

The corpus is the system's compounding asset. Every spec written makes the
next one cheaper. **Skipping this step wastes the team's accumulated knowledge.**

## Core Philosophy

1. **Incremental Testing**: Start with happy path, add tests one-by-one, run ALL tests every time (catch regressions early)
2. **Test-Driven**: Sufficient diverse test runs to validate requirements BEFORE writing documentation
3. **Parallel Execution**: ALL Phase 1 tasks must be 100% independent (zero dependencies)
4. **Contract-Based**: Phase 2 uses ONLY CONTRACT.md + TESTING.md (never internals)
5. **Proof-First**: Validate approaches in isolation BEFORE integration
6. **Iterative Integration**: Integration may uncover issues → refine Phase 1 proof → re-integrate (this is NORMAL)
7. **Requirement-Driven Testing**: Test coverage based on what can go wrong, not arbitrary numbers

## Create PLAN.md Structure

### Lineage frontmatter

PLAN.md begins with YAML frontmatter capturing where this spec came from. For
**root specs**, both lineage fields are `null`. For **leaves** (a child spec
spawned from a research task in a parent spec), they record the genealogy.

How to detect lineage:

1. Args contain `--parent <slug> --from-task <task-id>` → use directly
2. Args contain a parent slug + task reference in prose → infer
3. `pwd` is inside `~/.claude/specs/<some-slug>/` → propose `<some-slug>` as parent and ask the user which task spawned this child
4. Otherwise → root spec, both `null`

The leaves pattern is core to the system: a single research task can grow
its own three-phase pipeline. Capturing parent + originating task is what
makes those branches walkable later.

### Template

Write to `$SPEC_DIR/PLAN.md`:

```markdown
---
slug: <slug>
parent_spec: <parent-slug-or-null>
derived_from_task: <TASK-P1-X-...-or-null>
---

# Project: [Name]

## Overview
[What are we building? Why?]

## Prior work referenced (from corpus search)
[List of paths to reused/extended CONTRACT.md files, or "none — fresh ground"]

## Components (Phase 1 - Parallel Proofs)

Each component must be:
- 100% independent (can run in parallel)
- Test-driven (sufficient tests to validate requirements before docs)
- Contract-ready (produces CONTRACT.md + TESTING.md)

### Component List
1. [Component A] - [What needs to be proven?]
2. [Component B] - [What needs to be proven?]
3. [Component C] - [What needs to be proven?]

## Three-Phase Approach

### Phase 1: Research (Parallel)
- All tasks run simultaneously
- Each proves ONE component works in isolation
- Uses generic/sample test data (NOT real system data)
- Deliverables: CONTRACT.md, TESTING.md, test runs sufficient to validate requirements

### Phase 1.5: Feedback Loop
- Review all FEEDBACK.md files from proofs
- Update this PLAN.md based on discoveries
- Adjust Phase 2 if needed

### Phase 2: Integration (Sequential if needed, ITERATIVE by nature)
- Connect proven components to actual system
- Use ONLY contracts from Phase 1 (black-box)
- Re-run Phase 1 test harness with REAL data
- **EXPECT iteration**: Integration often uncovers issues not found in isolation
- When issues found → create TASK-P1-X-REFINEMENT.md → refine proof → re-integrate
- **This back-and-forth is NORMAL and EXPECTED in real engineering**

## Testing Emphasis

**CRITICAL**: Testing is the PRIMARY deliverable, not documentation.

For each component:
- Design EFFECTIVE testing strategy first (what can go wrong in YOUR use case?)
- **CHECK MEMORY MCP** for proven test harness setups (e.g., `Playwright_Quick_Setup_Guide`)
- Implement test harness (run.sh)
- **Develop tests INCREMENTALLY:**
  - Start with ONE happy-path test
  - Add one test at a time (edge case, failure mode, invariant)
  - Run ALL tests after each addition (catch regressions immediately)
  - Build confidence iteratively until reliability requirements met
- Collect results (pass/fail logs, metrics)
- THEN write docs based on empirical evidence
- **ADD TO MEMORY** if you created a novel test harness (save future agents hours of setup)

**Focus on test design quality and incremental development over arbitrary test counts.**

## Success Criteria

Phase 1 complete when:
- [ ] All components have CONTRACT.md + TESTING.md
- [ ] All test harnesses achieve acceptable pass rate (documented in TESTING.md with rationale)
- [ ] All FEEDBACK.md files reviewed

Phase 2 complete when:
- [ ] Integration with real system data works
- [ ] Phase 1 harness re-run passes with real data
- [ ] No regressions in existing functionality
```

## Key Principles

1. **NO implementation code in PLAN.md** - just high-level component breakdown
2. **Short and focused** - agent gets creative freedom in approach
3. **Clear success boundaries** - "done when reliability requirements are validated"
4. **Test strategy must be automatable** - no manual validation
5. **Requirement-driven testing** - test coverage based on what can fail, not arbitrary numbers

## Linear Project Binding (after PLAN.md is written)

The kit can mirror the plan to a Linear project so the team sees the same source of truth. Local files remain the working artifacts (`/design-kit:dd-research-tasks`, `/design-kit:dd-integration-tasks` read from disk); Linear is the visible mirror that agents can also pull from when working off a Linear issue.

### Detection (in order)

1. **Existing sidecar**: `$SPEC_DIR/linear.yaml` — already bound, update the doc
2. **Args**: parse a `linear.app/.../project/<slug>` URL from `{ARGS}`
3. **Env var**: `LINEAR_PROJECT_ID` set
4. **Prompt user**: "Linear project to bind (name, URL, ID, or 'skip')?"

### When bound — after writing PLAN.md

1. Create or update Linear document attached to project:
   - Title: `Implementation plan — <project name>`
   - Content: full PLAN.md (no local-machine paths, no dates)
   - Tool: `mcp__linear-server__save_document` (project=<id>, title=..., content=...)
2. Read project milestones: `mcp__linear-server__get_project(includeMilestones: true)` and capture each milestone ID by name (M1, M2, M3 conventionally)
3. Write `$SPEC_DIR/linear.yaml`:
   ```yaml
   project_id: <uuid>
   project_url: https://linear.app/<workspace>/project/<slug>
   plan_doc_id: <uuid>
   plan_doc_url: https://linear.app/<workspace>/document/<slug>
   team: <TEAM-KEY>            # e.g. DEVOPS
   milestones:
     M1: <uuid>                # name → id mapping
     M2: <uuid>
     M3: <uuid>
   research_milestone: M1      # /design-kit:dd-research-tasks issues land here
   integrate_milestone: M3     # /design-kit:dd-integration-tasks issues land here
   issue_map: {}               # filled in by /design-kit:dd-research-tasks and /design-kit:dd-integration-tasks
   ```
4. Echo: `Plan synced to Linear: <plan_doc_url>`

### MCP requirement

Requires `mcp__linear-server__*` tools. If MCP is unreachable, **DO NOT silently skip** — print:

```
❌ Linear MCP not reachable. Either:
   - fix the MCP server, OR
   - run with LINEAR_SKIP=1 to bypass and work local-only
```

Exit non-zero so the user notices.

### Skipping

If user passes `LINEAR_SKIP=1` or answers "skip": work local-only. PLAN.md still written. No sidecar created.

### What gets put inside a Linear issue (referenced from `/design-kit:dd-research-tasks` and `/design-kit:dd-integration-tasks`)

Every Linear issue created by the toolchain must include this header:

```markdown
## Source artifacts

- **Master plan**: [Implementation plan — <project>](<plan_doc_url>)
- **Local task file** (for tools, when working from a checkout): `~/.claude/specs/<slug>/tasks/<task-file>.md`

## How to use this issue

1. Pull the master plan from the Linear document above (link is the source of truth)
2. Read this issue body for component-specific instructions
3. Local scratch space (any machine that has the project bound): `~/.claude/specs/<slug>/proofs/<component>/`
4. When done, comment on this issue with summary + PR link, then mark Done
```

## Next Steps

After PLAN.md is created and (optionally) Linear-bound:
- Run `/design-kit:dd-research-tasks` to generate Phase 1 parallel proof tasks
- Complete all Phase 1 tasks independently
- Run `/design-kit:dd-replan-after-research` to fold FEEDBACK into PLAN
- Run `/design-kit:dd-integration-tasks` to generate Phase 2 integration tasks
