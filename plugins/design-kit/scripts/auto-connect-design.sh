#!/usr/bin/env bash
set -euo pipefail

# Resolve the design-kit spec directory for the current working context.
#
# Globally-anchored model:
#   ~/.claude/specs/<slug>/         # global spec home, one per project
#
# Each repo can opt-in to a project by dropping a pointer:
#   <repo>/.claude/current-project  # plain text, single line: <slug>
#
# Multiple repos can point at the same project (cross-repo work).
# Multiple branches in a repo all resolve to the same project (branch is
# no longer the anchor; it's just metadata for which Linear issue is in flight).
#
# Modes
# -----
#   auto-connect-design.sh                 # resolve + ensure subdirs, print status
#   auto-connect-design.sh --init <slug>   # bootstrap a new project (called by /design-kit:dd-plan)
#
# Outputs (resolve mode):
#   Slug: <slug>
#   SpecDir: <absolute path>
#
# If no pointer is found in resolve mode, prints a warning and exits 0.
# Caller decides whether that's an error or whether to bootstrap.

GLOBAL_SPECS="$HOME/.claude/specs"
LOCAL_POINTER=".claude/current-project"

cmd="${1:-}"

case "$cmd" in
  --init)
    slug="${2:-}"
    if [[ -z "$slug" ]]; then
      echo "Usage: auto-connect-design.sh --init <slug>" >&2
      exit 1
    fi

    # Validate slug — letters, digits, dot, dash, underscore only
    if [[ ! "$slug" =~ ^[a-zA-Z0-9._-]+$ ]]; then
      echo "❌ Invalid slug: '$slug'. Use [a-zA-Z0-9._-] only." >&2
      exit 1
    fi

    spec_dir="$GLOBAL_SPECS/$slug"
    mkdir -p "$spec_dir/proofs" "$spec_dir/tasks"

    mkdir -p ".claude"
    echo "$slug" > "$LOCAL_POINTER"

    # Ensure .claude/ is gitignored (per-repo pointer is local state)
    if [[ -f .gitignore ]] && ! grep -q "^\.claude/" .gitignore; then
      printf '\n# Claude design-kit pointer (local)\n.claude/\n' >> .gitignore
    fi

    echo "✓ Initialized project: $slug"
    echo "  Global spec dir: $spec_dir"
    echo "  Local pointer:   $(pwd)/$LOCAL_POINTER → $slug"
    exit 0
    ;;
  --help|-h)
    sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
esac

# Default: resolve and ensure
if [[ ! -f "$LOCAL_POINTER" ]]; then
  echo "⚠ No project bound to this repo (no $LOCAL_POINTER)."
  echo "  Run /design-kit:dd-plan to create a new project, or"
  echo "  $(basename "$0") --init <slug>   # bind this repo to an existing global project."
  exit 0
fi

slug=$(<"$LOCAL_POINTER")
# Strip whitespace
slug="${slug//[$'\t\r\n ']/}"

if [[ -z "$slug" ]]; then
  echo "❌ Pointer $LOCAL_POINTER is empty." >&2
  exit 1
fi

spec_dir="$GLOBAL_SPECS/$slug"
mkdir -p "$spec_dir/proofs" "$spec_dir/tasks"

echo "→ Project: $slug"
echo "  Spec dir: $spec_dir"

[[ -f "$spec_dir/PLAN.md" ]]      && echo "  Has PLAN.md"
[[ -f "$spec_dir/linear.yaml" ]]  && echo "  Has linear.yaml (Linear-bound)"

proof_count=$(find "$spec_dir/proofs" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
task_count=$(find "$spec_dir/tasks"  -name "TASK-*.md" 2>/dev/null | wc -l)
echo "  Has $proof_count proof(s), $task_count task(s)"

# Stable identifiers for downstream commands
echo ""
echo "Slug: $slug"
echo "SpecDir: $spec_dir"
