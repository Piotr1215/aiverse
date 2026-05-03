# Design-Kit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-blue.svg)](https://docs.claude.com/en/docs/claude-code)

> Test-driven, parallel-execution framework for building complex systems with confidence

Design-Kit is a Claude Code plugin that turns the "build → test → debug" cycle into a **prove-then-integrate** workflow. Components are validated in isolation against generic data first, then integrated against the real system using contracts only.

## Why Design-Kit?

Traditional development is sequential and slow:
```
Plan → Build → Test → Debug → Fix → Repeat (6-12 weeks)
```

Design-Kit enables parallel execution and reduces risk:
```
Plan → Prove (parallel) → Replan → Integrate (with contracts) → 2-4 weeks
```

### Key benefits

- **Independent proofs run in parallel**, not sequentially
- **Zero integration surprises** — approaches validated in isolation first
- **Contract-based design** via `CONTRACT.md` reduces coupling
- **Test-first** — diverse test runs precede documentation
- **Phase 1.5 gate** — discoveries fold back into the plan before integration starts

## Install

Design-Kit is distributed through the [aiverse](https://github.com/Piotr1215/aiverse) Claude Code marketplace.

```
/plugin marketplace add Piotr1215/aiverse
/plugin install design-kit@aiverse
```

That's it. No clone, no install script. Updates ship through the marketplace.

## Quick start

```
# Lost? This always tells you the next command to run.
/design-kit:dd-status

# Create a master plan (binds this repo to a project slug under ~/.claude/specs/)
/design-kit:dd-plan "Improve API authentication with OAuth2 + rate limiting"

# Generate Phase 1 parallel proof tasks (one per component)
/design-kit:dd-research-tasks

# Agents execute proofs independently — each produces CONTRACT.md + TESTING.md + FEEDBACK.md

# Phase 1.5 — synthesize FEEDBACK across proofs into PLAN deltas. NOT optional.
/design-kit:dd-replan-after-research

# Generate Phase 2 integration tasks (refuses to run without the Phase 1.5 marker)
/design-kit:dd-integration-tasks

# Agents integrate proven components with the real system
```

## Three-phase flow

### Phase 1 — research (parallel)

All tasks run **simultaneously** with zero dependencies. Each proves ONE component works in isolation against generic test data. Deliverables per proof:

- `CONTRACT.md` — black-box interface
- `TESTING.md` — validation strategy + pass criteria
- `FEEDBACK.md` — surprises and discoveries
- `run.sh` — automated harness (exits 0/1, writes `results/summary.json`)

### Phase 1.5 — feedback loop (peer phase, not optional)

`/design-kit:dd-replan-after-research` synthesizes every `FEEDBACK.md` from Phase 1, proposes deltas to `PLAN.md` (and `SCHEMA.md` if you froze a contract), gets your confirmation, and writes `.phase-1.5-complete`.

- `/design-kit:dd-integration-tasks` **refuses to run** without that marker, and refuses if `PLAN.md`, `SCHEMA.md`, or any `FEEDBACK.md` is newer than the marker.
- Most common failure mode of the kit: discoveries from research never propagate to the plan, and Phase 2 gets generated against a stale draft. The gate prevents this.
- Re-run `/design-kit:dd-replan-after-research` any time a Phase 1 proof is refined.

### Phase 2 — integration

Connect proven components to the real system using **only** `CONTRACT.md` + `TESTING.md` (never the proof's internals). Re-run the Phase 1 harness against real data. If contract gaps surface, create a refinement task instead of working around them.

## Workspace model

Plans live globally, not per-repo. Multiple repos and branches can share one project.

```
~/.claude/specs/
└── <slug>/
    ├── PLAN.md              # master plan
    ├── linear.yaml          # (optional) Linear binding metadata
    ├── .phase-1.5-complete  # gate marker, written by /design-kit:dd-replan-after-research
    ├── proofs/              # Phase 1 proof-of-concepts
    │   └── <component>/
    │       ├── run.sh
    │       ├── CONTRACT.md
    │       ├── TESTING.md
    │       ├── FEEDBACK.md
    │       └── results/
    └── tasks/               # TASK-P1-* and TASK-P2-* files
```

Each repo participating in a project drops a pointer file:

```
<repo>/.claude/current-project    # plain text, single line: the slug
```

Multiple repos can point at the same slug — that's the cross-repo coordination model. To bind a second repo to an existing project:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/auto-connect-design.sh" --init <slug>
```

To switch the active project for the current repo, re-run the same command with a different slug. The old spec dir is untouched.

### Multi-spec discovery

Run `/design-kit:dd-status all` to list every spec under `~/.claude/specs/` with phase + last-touched timestamp. Useful when you have multiple projects in flight and need to remember what's where.

## Commands

| Command | Purpose |
|---------|---------|
| `/design-kit:dd-status` | Where am I? Read-only state inspection. Accepts free-form args: empty (current project), `all` (all projects), `tasks` (list tasks), task ID (view one task). |
| `/design-kit:dd-plan` | Create master plan with component breakdown. Binds the repo to a project slug. |
| `/design-kit:dd-research-tasks` | Generate Phase 1 parallel proof tasks (`TASK-P1-*.md`). |
| `/design-kit:dd-replan-after-research` | Phase 1.5 — synthesize FEEDBACK across proofs, propose plan/schema deltas, write the marker. |
| `/design-kit:dd-integration-tasks` | Generate Phase 2 integration tasks (`TASK-P2-*.md`). Gated on the Phase 1.5 marker. |

If you forget which command to run next: `/design-kit:dd-status`. It inspects the project, prints the state, and recommends the next command.

## Core principles

1. **Testing is the primary deliverable.** Design effective tests first; documentation comes from empirical evidence, not philosophy.
2. **100% parallelism in Phase 1.** Independent components, generic test data, zero cross-task dependencies.
3. **Contract-based integration.** Phase 2 references `CONTRACT.md` and `TESTING.md` only — never proof internals.
4. **Automated validation.** Every proof's `run.sh` exits 0/1 and produces `results/summary.json` + per-test logs.
5. **Requirement-driven coverage.** Test counts come from what can fail, not arbitrary numbers.

## Linear integration (optional)

If your project lives in a Linear workspace, the kit can mirror plans and tasks to Linear so the team sees the same source of truth. Local files remain the toolchain's working artifacts; Linear is the visible mirror that agents can also pull from when working off a Linear issue.

How it works:

1. `/design-kit:dd-plan` (when bound) creates a Linear document attached to the project, captures project + milestone IDs in `~/.claude/specs/<slug>/linear.yaml`
2. `/design-kit:dd-research-tasks` mirrors each Phase 1 task as a Linear issue in `research_milestone` (default M1)
3. `/design-kit:dd-integration-tasks` mirrors each Phase 2 task in `integrate_milestone` (default M3)

Each Linear issue includes a header pointing back to the plan document and the local task file. To skip Linear sync for a particular plan, pass `LINEAR_SKIP=1` when running `/design-kit:dd-plan`.

See [linear-binding.md](templates/linear-binding.md) for the full pattern.

## Documentation

- [Design-Driven Development Philosophy](design-driven.md) — methodology deep-dive
- [Linear Project Binding](templates/linear-binding.md) — sidecar schema, lifecycle, MCP requirements
- [Contributing Guide](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## License

MIT — see [LICENSE](LICENSE).
