# Linear Project Binding

Optional but recommended pattern: mirror a design-kit plan to a Linear project so the team sees the same source of truth and agents can pull plan / task context from Linear when working off an issue.

## Mental model

- **Global spec storage**: `~/.claude/specs/<slug>/` — one directory per project, machine-wide. Holds PLAN.md, tasks/, proofs/, and `linear.yaml`.
- **Per-repo pointer**: `<repo>/.claude/current-project` — plain text file, single line: the project slug. Repos opt-in to a project by dropping this pointer.
- **Linear** is the visible mirror. The team sees progress, assigns issues, comments, and reviews. Agents working from a Linear issue link can pull the plan and component instructions without local-machine access.
- All three stay in sync through the `/design-kit:*` commands.

This is *not* a replacement for the local toolchain — `/design-kit:dd-research-tasks` and `/design-kit:dd-integration-tasks` still need local files to read PLAN.md and write task files. Linear is an additional source/target for the same information.

## Why global-spec + per-repo pointer

A project usually spans multiple repos (e.g. `vcluster-docs`, `vcluster`, `loft-enterprise`) and many branches (one per Linear issue). Storing the spec inside any one repo at any one branch is wrong:

- The spec gets duplicated across repos and drifts
- Branch switches lose context
- A worker on `loft-enterprise/devops-846/...` and a worker on `vcluster-docs/devops-867/...` can't see the same plan

Global slug-keyed storage solves this. Each repo just carries a small pointer file naming the project.

## Sidecar: `~/.claude/specs/<slug>/linear.yaml`

Created by `/design-kit:dd-plan`, read by `/design-kit:dd-research-tasks` and `/design-kit:dd-integration-tasks`.

```yaml
project_id: bc719c01-6c79-4e01-8e5a-4ec947bfb176
project_url: https://linear.app/loft/project/docs-config-automation-improvements-fe494b55707f
plan_doc_id: 4c96f469-bd0d-4d41-8687-2ca66be0291c
plan_doc_url: https://linear.app/loft/document/implementation-plan-docs-config-automation-29a24d5d4b48
team: DEVOPS
milestones:
  M1: d6c4fc90-59d5-4590-bc6f-c449e4354117  # Architectural foundation
  M2: d722ce07-9455-4b57-aebe-31ff8e87ab0c  # Pipeline parity
  M3: e2a48a14-9a83-4b2d-849a-50b614609f85  # Unification & auto-approve
research_milestone: M1     # /design-kit:dd-research-tasks issues land here
integrate_milestone: M3    # /design-kit:dd-integration-tasks issues land here
issue_map:
  TASK-P1-A1: DEVOPS-867   # populated by /design-kit:dd-research-tasks
  TASK-P1-A2: DEVOPS-868
  TASK-P2-C: DEVOPS-870    # populated by /design-kit:dd-integration-tasks
```

The `issue_map` is what makes resyncs idempotent — each command checks the map before creating, and updates in place if the entry exists.

## Slug derivation

The slug is the machine-wide project identifier and the directory name under `~/.claude/specs/`.

- **From Linear project name**: kebab-case the project name. `"docs config automation improvements"` → `docs-config-automation-improvements`.
- **From CLI arg**: `/design-kit:dd-plan --slug <name>` overrides.
- **From prompt**: if neither, `/design-kit:dd-plan` asks the user.

Slugs allow `[a-zA-Z0-9._-]`. Validation in `auto-connect-design.sh --init`.

## Lifecycle

| Command | Linear actions |
|---|---|
| `/design-kit:dd-plan` | Determine slug, run `auto-connect-design.sh --init <slug>` (creates `~/.claude/specs/<slug>/` and writes `<repo>/.claude/current-project`), write PLAN.md, create or update Linear document, capture milestone IDs into `linear.yaml`. |
| `/design-kit:dd-research-tasks` | Resolve `<slug>` from pointer, read PLAN.md, write `TASK-P1-*.md` to `<spec-dir>/tasks/`. For each task, create or update a Linear issue in `research_milestone`. Issue body links to plan doc and tells the agent to pull from there. |
| `/design-kit:dd-integration-tasks` | Same pattern, target milestone is `integrate_milestone`. Issue body points to Phase 1 CONTRACT.md / TESTING.md (in the global spec dir) and the plan doc. Refuses to run unless `.phase-1.5-complete` marker is present and fresh (mtime newer than PLAN.md/SCHEMA.md/FEEDBACK.md). |

## What goes inside a Linear issue

Every issue created by the toolchain has a standard header so any agent that picks it up can navigate back to the plan and the local files:

```markdown
## Source artifacts

- **Master plan**: [<doc-title>](<plan_doc_url>)
- **Local task file** (on any machine that has the project bound): `~/.claude/specs/<slug>/tasks/<TASK-FILE>.md`

## How to use this issue

1. Pull the master plan from the Linear document above
2. Read this issue body for component-specific instructions
3. Local scratch space: `~/.claude/specs/<slug>/proofs/<component>/`
4. When done, comment with summary + PR link(s), then mark Done
```

The component-specific body (goal, testing strategy, deliverables) follows.

## Binding additional repos to an existing project

A worker on a different repo (e.g. `loft-enterprise`) needs the same project context. They run:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/auto-connect-design.sh" --init docs-config-automation-improvements
```

This drops a pointer in their current repo and ensures the global spec dir exists. They can now run `/design-kit:dd-research-tasks`, `/design-kit:dd-integration-tasks`, etc. from that repo and resolve to the same plan.

## MCP dependency

The kit uses `mcp__linear-server__*` tools. If the MCP server is unreachable:
- Commands print a clear error and exit non-zero
- Local files are still written (so work isn't blocked)
- User can re-run when MCP is healthy, or pass `LINEAR_SKIP=1` to bypass

There is no GraphQL/CLI fallback. Keeping the surface area small — one tool family.

## Skipping the binding

To work fully local (no Linear involvement on a particular plan): pass `LINEAR_SKIP=1` when running `/design-kit:dd-plan`. The command still creates `~/.claude/specs/<slug>/` and the per-repo pointer; it just doesn't create `linear.yaml` or call any Linear MCP tools. Downstream commands skip Linear sync entirely.

## Conventions on milestone mapping

Default mapping in the sidecar:

- `research_milestone: M1` — Phase 1 proof tasks are foundational research; first milestone usually represents the design / foundation work.
- `integrate_milestone: M3` — Phase 2 integration is the final unification before delivery.

These defaults are project-conventional, not hardcoded. Override in `linear.yaml` if the project's milestones don't follow the M1/M2/M3 pattern.

## Why this pattern

- **Distributed teams**: not everyone has the local checkout; Linear is universally readable.
- **Cross-repo work**: one project, many repos — global storage avoids drift.
- **Cross-branch work**: switching branches doesn't lose context; the pointer is per-repo, not per-branch.
- **Agent portability**: an agent spawned from a Linear issue link can pull the plan from Linear, run locally, push results back to Linear.
- **Auditability**: Linear keeps a comment trail; local files don't.
- **Mirror not master**: local stays authoritative for the toolchain; Linear stays authoritative for the team. Both sides update via the same commands so drift is bounded.
