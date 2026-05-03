---
name: dd-status
description: "Read-only state inspection: current project, all projects, task list, or task details. Suggests the next command."
---

State-machine entry point for design-kit. Inspects the current project (or all projects in `~/.claude/specs/`), prints where things stand, and recommends the next command.

**Read-only.** Never mutate anything. Inspections use `ls`, `find`, `stat`, `cat` — no edits, no Linear writes.

## Dispatch

Parse `{ARGS}` to pick a mode. Free-form natural language, no flags required:

| Args contain… | Mode | What it shows |
|---------------|------|---------------|
| (empty) or "current" / "this" / "here" | **single-project** | State block for the project bound to this repo |
| "all" / "all projects" / "everything" | **multi-project** | One row per spec under `~/.claude/specs/` |
| "tasks" / "list tasks" / "what tasks" | **task-list** | Every TASK file in the bound project's `tasks/` dir |
| Anything matching a task ID (e.g. "A", "P1-A", "task A1", "TASK-P2-C") | **task-view** | The full task file content |

If args are ambiguous, default to **single-project** and tell the user other modes exist.

## Setup

```bash
# Resolve global spec dir via the per-repo pointer (does not error if unbound — we report the unbound state too)
output=$("${CLAUDE_PLUGIN_ROOT}/scripts/auto-connect-design.sh")
SPEC_DIR=$(echo "$output" | awk '/^SpecDir:/ {print $2}')
SLUG=$(echo "$output" | awk '/^Slug:/ {print $2}')
GLOBAL_SPECS="$HOME/.claude/specs"
```

## Mode: single-project

State detection — figure out where the project stands:

| State | Detected by | Next command |
|-------|-------------|--------------|
| **unbound** | No `<repo>/.claude/current-project` pointer | `/design-kit:dd-plan "<idea>"` |
| **bound, no plan** | Pointer exists, no `$SPEC_DIR/PLAN.md` | `/design-kit:dd-plan` |
| **plan, no tasks** | `PLAN.md` exists, `$SPEC_DIR/tasks/` empty | `/design-kit:dd-research-tasks` |
| **tasks, no proofs** | TASK-P1-* files exist, `$SPEC_DIR/proofs/` empty or no CONTRACT.md | execute Phase 1 (run agents on `TASK-P1-*` files) |
| **phase 1 in flight** | Some proofs have CONTRACT.md, some don't | finish remaining Phase 1 proofs |
| **phase 1 done, replan needed** | All proofs have CONTRACT.md+TESTING.md, no `.phase-1.5-complete` marker | `/design-kit:dd-replan-after-research` |
| **phase 1.5 stale** | Marker exists but a `FEEDBACK.md`, `PLAN.md`, or `SCHEMA.md` is newer | `/design-kit:dd-replan-after-research` (re-synthesize) |
| **phase 1.5 done, no P2 tasks** | Marker fresh, no `TASK-P2-*` files | `/design-kit:dd-integration-tasks` |
| **phase 2 in flight** | TASK-P2-* files exist | execute Phase 2 |
| **phase 2 done** | All P2 tasks have integration evidence (subjective — surface counts, let user decide) | wrap up / new project |

### Output (single-project)

Print one block. Keep it scannable.

```
Project: <slug> (or "no project bound")
Spec dir: <SPEC_DIR>
Linear:   <yes — link / no>
Lineage:  <root | parent=<slug> from-task=<TASK-P1-X-...>>

State: <state name>
  - PLAN.md:       <yes/no> [mtime: <ISO>]
  - SCHEMA.md:     <yes/no/n.a.>
  - Tasks:         <P1: N done / M total> | <P2: N done / M total>
  - Proofs:        <component: ✓ ✓ ✓ — CONTRACT TESTING FEEDBACK> per row
  - Phase 1.5:     <not run | done <ISO> | STALE — newer files: ...>
  - Refinements:   <none | N active: TASK-P1-X-REFINEMENT-foo, ...>

Next: <one-line recommended command, with example args>

Why: <one sentence rationale based on what's missing>
```

**Lineage** is read from PLAN.md frontmatter (`parent_spec`, `derived_from_task`).
If frontmatter is absent (legacy plans pre-0.1.5) or both fields are null, show `root`.

**Refinements** are `TASK-P1-*-REFINEMENT-*.md` files in `$SPEC_DIR/tasks/`. They
indicate Phase 2 surfaced a contract gap and the spec is iterating Phase 1 work
again. Surface them prominently so the open loop is visible — refinements are
expected and normal, but invisible refinements rot.

Per-proof row symbols:
- `✓` = file present
- `·` = file missing
- check `CONTRACT.md` `TESTING.md` `FEEDBACK.md` in that order

If unbound, skip every project-specific row and just print the unbound block + suggestion.

### Counts

- P1 done = proofs with both `CONTRACT.md` and `TESTING.md`
- P1 total = TASK-P1-*.md count under `$SPEC_DIR/tasks/`
- P2 done = TASK-P2-* files with associated PR/branch markers (best-effort; surface counts only)

### Stale detection

Mirror the `/design-kit:dd-integration-tasks` gate: marker missing, or any `FEEDBACK.md` / `PLAN.md` / `SCHEMA.md` newer than the marker.

## Mode: multi-project

When the user wants the bird's-eye view across every spec.

```bash
ls -1 "$GLOBAL_SPECS" 2>/dev/null
```

For each slug, detect a coarse phase using the same rules as single-project mode (no need for full state-block detail). Print one row per spec:

```
SPECS UNDER ~/.claude/specs/

slug                              phase                    last-touched         linear
─────────────────────────────────────────────────────────────────────────────────────
ci-aop-briefer                    phase 1.5 done           2026-05-03 14:35     yes
docs-config-automation            phase 2 in flight        2026-05-01 09:12     no
some-old-thing                    phase 1 in flight        2026-04-12 18:44     yes (stale?)

Bound to this repo: <slug or "—">

Tip: To bind this repo to one of the projects above, write the slug to its pointer file:

     mkdir -p .claude && echo "<slug>" > .claude/current-project

Or run `/design-kit:dd-plan "<idea>"` to create a new project from scratch.
```

`last-touched` = newest mtime among PLAN.md, marker, any TASK file. Best-effort.

## Mode: task-list

User wants every TASK file in the bound project. This was the old `/norm-tasks` behavior.

```bash
[[ -z "$SPEC_DIR" ]] && { echo "No project bound. Run /design-kit:dd-plan first."; exit 0; }
find "$SPEC_DIR/tasks" -maxdepth 1 -name 'TASK-*.md' | sort
```

Output:

```
Tasks in <slug>:

Phase 1 (research)
  TASK-P1-A-component-x.md         <state: done | in-progress | todo>
  TASK-P1-B-component-y.md         <state>

Phase 2 (integration)
  TASK-P2-C-x-integration.md       <state>

Refinement
  TASK-P1-A-REFINEMENT-foo.md      <state>
```

State heuristic: P1 task is "done" if its component has CONTRACT.md+TESTING.md; "in-progress" if proof dir exists but missing files; "todo" otherwise. P2 tasks fall back to "todo" unless evidence in code suggests otherwise — keep this conservative.

## Mode: task-view

User wants the full content of one task file. Was `/norm-task <ID>`.

Match `{ARGS}` against task IDs:
- "A" → match `TASK-P1-A-*.md` (default Phase 1 if ambiguous)
- "P1-A" / "p1 a" → `TASK-P1-A-*.md`
- "P2-C" / "p2 c" → `TASK-P2-C-*.md`
- "TASK-P1-A1" → exact filename match

If multiple files match, list them and ask the user to disambiguate.
If zero match, print the task list (mode = task-list output) and tell the user to pick one.

Then read the file and print:
- Full content (use Read tool)
- Status block: which proofs/contracts exist for this task, current state
- Next-step hint based on state

## Anti-Patterns

❌ Running the recommended command automatically — this is a guidance command, not an executor
❌ Editing files (this includes "fixing" a stale marker — that's `/design-kit:dd-replan-after-research`'s job)
❌ Hiding partial state behind a single status word — list per-proof rows so the user sees what's actually missing
❌ Inventing tasks that don't exist on disk in task-list / task-view modes

## Verification

After running:
- ✅ Nothing on disk changed
- ✅ User can read the recommended next command and run it as-is
- ✅ Stale Phase 1.5 surfaced even when the marker exists
- ✅ In multi-project mode, every directory under `~/.claude/specs/` is listed
- ✅ Lineage row reflects PLAN.md frontmatter (or `root` when frontmatter absent)
- ✅ Active refinements surfaced when present, omitted when none
