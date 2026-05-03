# Design-Driven Development

A test-driven, parallel-execution framework for building complex systems.

## Core Philosophy

Traditional development follows a linear path:
```
Plan → Build → Test → Integrate → Debug → Fix → Repeat
```

Design-Driven Development inverts this:
```
Plan → Prove (parallel) → Integrate (with contracts)
```

**Key insight**: Validate components work independently BEFORE integration.

## The Three Phases

### Phase 1: Research (Parallel)

**Goal**: Prove each component works in isolation

**Characteristics**:
- All tasks run simultaneously (zero dependencies)
- Uses generic/sample test data (NOT real system)
- Each component must be testable independently
- Produces contracts for integration

**Deliverables per component**:
- `run.sh` - Automated test harness
- `CONTRACT.md` - Interface/API specification
- `TESTING.md` - Validation strategy (≤50 lines)
- `FEEDBACK.md` - Discoveries and surprises (≤30 lines)
- `results/` - 100+ test runs with pass/fail data

**Testing is PRIMARY**:
- NOT: Write 1000-line testing philosophy → Run 3 tests
- CORRECT: Design minimal test strategy → Run 100+ diverse tests → Document from evidence

**Example**: Building a REST API with OAuth2 + PDF generation

Phase 1 tasks (run in parallel):
```
TASK-P1-A: Prove OAuth2 token validation works
TASK-P1-B: Prove PDF generation with margins works
TASK-P1-C: Prove rate limiting middleware works
```

Each uses generic test data:
- OAuth2: Sample tokens, not real user database
- PDF: Test HTML files, not production content
- Rate limiter: Simulated requests, not live traffic

### Phase 1.5: Feedback Loop

**Goal**: Incorporate discoveries before integration

**Activities**:
1. Review all `FEEDBACK.md` files
2. Identify surprises or changed assumptions
3. Update `PLAN.md` if needed
4. Adjust Phase 2 approach based on learnings

**Example discoveries**:
- "OAuth2 library X has better error messages than Y"
- "PDF page breaks require manual tweaking for tables"
- "Rate limiter needs Redis, not in-memory cache"

### Phase 2: Integration

**Goal**: Connect proven components to actual system

**Characteristics**:
- References ONLY `CONTRACT.md` + `TESTING.md` (black-box)
- Re-runs Phase 1 test harness with REAL system data
- May be sequential if tasks modify same files
- Creates REFINEMENT tasks if contracts insufficient

**Critical rule**: Never reference proof implementation internals

**Example**: Continuing REST API

Phase 2 tasks (may be sequential):
```
TASK-P2-C: Integrate OAuth2 validation into auth middleware
TASK-P2-D: Integrate PDF generation into report endpoint
TASK-P2-E: Integrate rate limiter into API gateway
```

Each:
- Reads `CONTRACT.md` for interface
- Preserves existing functionality
- Re-runs Phase 1 harness with production data
- Reports if contract gaps found

## The Contract System

### What is a Contract?

A `CONTRACT.md` specifies the interface between components without revealing implementation:

```markdown
# Component: OAuth2 Token Validator

## Interface

Function: `validateToken(token: string) -> Result<UserId, Error>`

## Inputs
- `token`: JWT string, format: `Bearer xxx.yyy.zzz`
- Must contain claims: `sub`, `exp`, `aud`

## Outputs
- Success: `UserId` (integer, 1-2147483647)
- Error: `InvalidToken | ExpiredToken | MalformedToken`

## Guarantees
- Validates signature against public key
- Checks expiration (current time < exp)
- Verifies audience matches API identifier
- Response time: <50ms for valid tokens

## Gotchas
- Clock skew: Allows 60s leeway for exp
- Large tokens (>8KB): Reject immediately
- Missing claims: Return MalformedToken, not crash
```

### Why Contracts?

**Benefits**:
- Phase 2 doesn't care HOW validation works
- Can swap implementations without touching Phase 2
- Clear boundaries prevent coupling
- Easy to verify completeness

**Anti-pattern**: Reading proof implementation files in Phase 2

## Test Harness Contract

Every Phase 1 proof must implement a standard test harness:

### Exit Codes
```bash
exit 0  # All tests passed
exit 1  # Any test failed
```

### results/summary.json
```json
{
  "timestamp": "20251014_103045",
  "generator": "jest",
  "test_filter": "all",
  "total": 127,
  "passed": 125,
  "failed": 2,
  "pass_rate": 0.98,
  "failures": ["oauth-timeout-edge-case", "pdf-unicode-emoji"]
}
```

### results/logs/
Individual test details in JSON format:
```
results/logs/
├── oauth_jest_001_20251014_103045.json
├── oauth_jest_002_20251014_103046.json
└── pdf_puppeteer_001_20251014_103047.json
```

**Why this matters**:
- Automated verification of "Phase 1 complete"
- Reproducible test runs
- Clear failure tracking
- Enables orchestration tooling

## Parallelism Rules

### Phase 1: Must Be 100% Parallel

**Valid decomposition**:
```
✅ Task A: Prove Helm chart templating works (sample values)
✅ Task B: Prove rate limiter works (test requests)
✅ Task C: Prove i18n loading works (sample locales)
```

All can run simultaneously.

**Invalid decomposition**:
```
❌ Task 1: Analyze API authentication issues
❌ Task 2: Fix authentication (requires Task 1)
❌ Task 3: Test fix (requires Task 2)
```

This is sequential, not parallel!

### Phase 2: May Be Sequential

If tasks modify different files → Parallel ✅
If tasks modify same files → Sequential ❌

**Mark dependencies explicitly**:
```markdown
## Prerequisites
- TASK-P1-A completed with CONTRACT.md + TESTING.md
- **TASK-P2-C completed** (modifies same files: api/server.go, api/handlers.go)
```

## Testing Philosophy

### Testing is the Primary Deliverable

Code without tests is incomplete. But tests must come BEFORE documentation.

**Data-Driven Workflow**:
1. Research approaches (2-3 options)
2. Design MINIMAL testing strategy
3. Implement test harness (run.sh)
4. Implement solution
5. **RUN DIVERSE TESTS** (100+ runs, edge cases)
6. **COLLECT DATA** (pass/fail logs, metrics)
7. **ANALYZE PATTERNS** (what works? what breaks?)
8. **THEN DOCUMENT** (write CONTRACT.md from evidence)

### Edge Cases for YOUR Use Case

Generic tests are worthless. Test YOUR specific scenario:

**API endpoint?**
- Large payloads (1MB+)
- Timeouts and retries
- Malformed JSON
- Unicode in fields
- Concurrent requests

**React component?**
- Async validation
- Rapid user input
- Browser autofill
- Keyboard navigation
- Mobile viewports

**K8s operator?**
- Multiple replicas
- Network partition
- OOM conditions
- Node drain
- Pod restarts

**NOT** just happy-path tests!

### Test Coverage Target

**Minimum**: 100+ test runs across diverse scenarios

**Pass rate requirement**: ≥98% over last 50 consecutive runs

**What "diverse" means**:
- Edge cases (empty input, max input, null, undefined)
- Stress tests (concurrent, rapid, large scale)
- Failure modes (timeouts, errors, crashes)
- Performance (latency, memory, CPU)
- Integration points (APIs, databases, files)

## Iterative Refinement

Phase 2 integration may reveal contract gaps:

### When This Happens

**DO NOT work around insufficient contracts!**

Instead:
1. Document issues in `INTEGRATION-ISSUES.md`
2. Create `TASK-P1-X-REFINEMENT-[Issue].md`
3. Return to Phase 1, refine proof
4. Update CONTRACT.md + TESTING.md
5. Re-run validation harness
6. Return to Phase 2 with improved contract

**Example**:
```markdown
# INTEGRATION-ISSUES.md

## Issue: OAuth2 Token Refresh Not Covered

**What's missing**: CONTRACT.md only covers token validation,
not refresh token handling.

**Impact**: Cannot implement session extension feature.

**Required refinement**: Add refresh token validation to proof,
update CONTRACT.md with refresh interface.
```

### Why This Matters

- Preserves Phase 1 proof quality
- Improves contracts for future use
- Prevents technical debt
- Maintains black-box integration

## Slug-Based Workflow

Each project gets a global, slug-keyed workspace under `~/.claude/specs/`. A project usually spans multiple repos (e.g. backend + frontend + docs) and many branches (one per ticket). Tying the workspace to a single repo's current branch is wrong: branches change, repos diverge, and the plan loses its home.

```
~/.claude/specs/
├── docs-config-automation-improvements/
│   ├── PLAN.md
│   ├── linear.yaml          # optional: Linear binding metadata
│   ├── proofs/
│   │   ├── token-validator/
│   │   └── rate-limiter/
│   └── tasks/
│       ├── TASK-P1-A-token-validator.md
│       └── TASK-P2-C-auth-integration.md
└── another-project/
    └── ...
```

Each repo that participates in a project drops a pointer so the kit can resolve the right global workspace:

```
<repo>/.claude/current-project    # plain text, single line: the slug
```

Switching branches in any repo doesn't change the workspace — the pointer stays the same. Multiple repos can point at the same project, enabling cross-repo coordination through one shared plan.

## Commands

### /design-kit:dd-plan

Creates master plan with component breakdown:
```bash
/design-kit:dd-plan "Build REST API with OAuth2 authentication and rate limiting"
```

Produces: `~/.claude/specs/{slug}/PLAN.md`

### /design-kit:dd-research-tasks

Generates Phase 1 parallel proof tasks:
```bash
/design-kit:dd-research-tasks
```

Creates: `~/.claude/specs/{slug}/tasks/TASK-P1-*.md` files

### /design-kit:dd-integration-tasks

Generates Phase 2 integration tasks:
```bash
/design-kit:dd-integration-tasks
```

Creates: `~/.claude/specs/{slug}/tasks/TASK-P2-*.md` files

## Benefits

### Parallel Execution Saves Time

Traditional: 3 components × 2 days each = 6 days sequential
Design-Driven: 3 components × 2 days = 2 days parallel

### Test Failures Isolated

Traditional: "Something broke!" (where?)
Design-Driven: "PDF component failing at margins test" (specific)

### Contract-Based Reduces Coupling

Traditional: Phase 2 depends on Phase 1 implementation details
Design-Driven: Phase 2 depends only on CONTRACT.md interface

### Feedback Loop Prevents Surprises

Traditional: Discover library X is wrong at integration time
Design-Driven: Discover library X is wrong in Phase 1, pivot early

### Empirical Evidence Drives Docs

Traditional: Write specs, hope they're correct
Design-Driven: Run 100+ tests, document what actually works

## Anti-Patterns

### ❌ Creating Phase 1 Dependencies

**Wrong**:
```
TASK-P1-A: Design database schema
TASK-P1-B: Implement ORM models (requires A)
TASK-P1-C: Write migrations (requires B)
```

**Right**:
```
TASK-P1-A: Prove database query patterns work (sample DB)
TASK-P1-B: Prove API validation works (sample requests)
TASK-P1-C: Prove caching strategy works (sample data)
```

### ❌ Writing Docs Before Tests

**Wrong**:
1. Write 50-page TESTING.md philosophy
2. Run 3 basic tests
3. Call it done

**Right**:
1. Design minimal test strategy (1 page)
2. Run 100+ diverse tests
3. Collect data
4. Write TESTING.md from evidence (≤50 lines)

### ❌ Using Real System Data in Phase 1

**Wrong**:
```
TASK-P1-A: Test OAuth2 with production user database
```

**Right**:
```
TASK-P1-A: Test OAuth2 with sample tokens (no database)
```

Phase 1 proves the component works. Phase 2 integrates with real data.

### ❌ Phase 2 Referencing Proof Internals

**Wrong**:
```
# TASK-P2-C-integration.md
Read the implementation in proofs/oauth/src/validator.ts
and copy the validation logic into api/auth.ts
```

**Right**:
```
# TASK-P2-C-integration.md
Read CONTRACT.md at proofs/oauth/CONTRACT.md
and implement the interface in api/auth.ts
```

### ❌ Manual Validation

**Wrong**:
```
TESTING.md: "Manually test by running server and hitting API"
```

**Right**:
```
TESTING.md: "Run ./run.sh - automated harness validates 127 test cases"
```

## When to Use Design-Driven

**Good fit**:
- Complex systems with multiple components
- Uncertain technical approaches (need to explore)
- High quality/reliability requirements
- Teams working in parallel

**Poor fit**:
- Single-file changes
- Well-understood problems
- Prototypes/experiments
- Time-sensitive hotfixes

## Optional: Linear Project Binding

The kit can mirror plans, proof tasks, and integration tasks to a Linear project. Local files remain the toolchain's source — `/design-kit:dd-research-tasks` and `/design-kit:dd-integration-tasks` still read and write the local `~/.claude/specs/<slug>/` tree. Linear is an additional source/target for the same information so distributed teams can see and assign work without local-machine access.

A `~/.claude/specs/<slug>/linear.yaml` sidecar captures project / document / milestone IDs after `/design-kit:dd-plan` runs with binding enabled. Each subsequent command checks for the sidecar and mirrors writes to Linear if present.

See `templates/linear-binding.md` for the schema, lifecycle, and issue body templates.

## Further Reading

- `README.md` - Installation and usage
- `templates/linear-binding.md` - Linear binding pattern (optional)
- `~/.claude/specs/{slug}/PLAN.md` - Your project's plan
- `~/.claude/specs/{slug}/proofs/*/CONTRACT.md` - Component interfaces
- `~/.claude/specs/{slug}/proofs/*/TESTING.md` - Validation strategies

---

**Design-Driven Development**: Prove it works in isolation, then integrate with confidence.
