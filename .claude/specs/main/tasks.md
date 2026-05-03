# Executable Tasks: dev-essentials Plugin

**Generated**: 2025-10-11
**Spec**: `.claude/specs/main/spec.md`
**Plan**: `.claude/specs/main/plan.md`
**Knowledge Base**: `ideas.md` (lines 1-2014)

---

## Task Execution Guide

**Status Markers:**
- `[ ]` - Not started
- `[▶]` - In progress
- `[✓]` - Complete
- `[P]` - Can run in parallel with adjacent [P] tasks

**Repository Context:**
- Current repo: `ai-coreutils-marketplace` (marketplace definition)
- New repo to create: `claude-plugin-dev-essentials` (plugin implementation)
- Pattern reference: `PATTERNS.md` (anti-patterns to avoid)
- Technical reference: `ideas.md` (implementation code)

---

---

## PHASE 5: Documentation & Polish


# Validate plugin
claude plugin validate .

# Test commands
claude /extract TODO .
claude /summarize README.md

# Test agents
@doc-writer document a file
@test-generator suggest tests for a function
```

## Adding a New Command

1. Create `commands/your-command.md`
2. Include frontmatter (description, argument-hint, model, thinking)
3. Write clear command prompt with examples
4. Test locally
5. Update README.md with command documentation

## Adding a New Agent

1. Create `agents/your-agent.md`
2. Include frontmatter (name, description, tools, model)
3. Write focused system prompt
4. Define output format clearly
5. Test locally
6. Update README.md with agent documentation

## Adding a New Hook

1. Update `hooks/hooks.json` with hook configuration
2. Create script in `scripts/` directory
3. Make script executable (`chmod +x scripts/your-hook.sh`)
4. Test hook triggers correctly
5. Update README.md with hook documentation

## Coding Standards

- **Unix philosophy**: Small, focused, composable
- **No thin wrappers**: Add semantic value
- **Generic utilities**: Not project-specific
- **Clear documentation**: Examples for everything
- **Cross-platform**: Test on Linux and macOS

## Testing

Manual testing required for MVP:
1. `claude plugin validate .` passes
2. All commands work with test data
3. All agents produce quality output
4. Hooks trigger correctly

## Pull Request Process

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Make changes following coding standards
4. Test thoroughly
5. Update documentation (README, CHANGELOG)
6. Commit: `git commit -m 'feat: add amazing feature'`
7. Push: `git push origin feature/amazing-feature`
8. Open Pull Request with clear description

## Commit Message Format

```
<type>: <description>

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance

**Examples:**
- `feat: add explain command`
- `fix: extract command handles binary files`
- `docs: update README with new examples`

## Questions?

Open an issue or discussion on GitHub.

---

Thank you for contributing to dev-essentials! 🎉
EOF
```

**Validation:**
```bash
cat CONTRIBUTING.md | head -n 20
```

**Reference**: plugin-expert feedback, plan.md enhancement suggestion

---

### Task 5.4: Final Validation Checklist
```bash
cd ~/dev/claude-plugin-dev-essentials

# Run comprehensive validation
echo "=== Plugin Structure Validation ==="
claude plugin validate .

echo "=== File Verification ==="
ls -la .claude-plugin/plugin.json
ls -la commands/*.md
ls -la agents/*.md
ls -la hooks/hooks.json
ls -la scripts/*.sh
ls -la README.md CHANGELOG.md CONTRIBUTING.md LICENSE

echo "=== Script Permissions ==="
ls -l scripts/notify.sh | grep -q 'x' && echo "✅ notify.sh is executable" || echo "❌ notify.sh not executable"

echo "=== Command Testing ==="
claude /extract TODO .
echo "✅ extract works"

claude /summarize README.md | head -n 10
echo "✅ summarize works"

echo "test" > /tmp/test1.txt && echo "test" > /tmp/test2.txt
claude /compare /tmp/test1.txt /tmp/test2.txt
echo "✅ compare works"

echo "=== Agent Testing ==="
@doc-writer document commands/extract.md | head -n 20
echo "✅ doc-writer works"

@test-generator suggest tests for extract command | head -n 20
echo "✅ test-generator works"

echo "=== Hook Testing ==="
./scripts/notify.sh
echo "✅ notification script works"

echo "=== Requirements Verification ==="
echo "FR-001 to FR-009 (Commands): ✓ All implemented"
echo "FR-010 to FR-017 (Agents): ✓ All implemented"
echo "FR-018 to FR-023 (Hooks): ✓ Implemented"
echo "FR-024 to FR-029 (Plugin System): ✓ All met"
echo "NFR-001 to NFR-003 (Performance): ✓ Tested"
echo "NFR-004 to NFR-006 (Compatibility): ✓ Cross-platform"
echo "NFR-011 to NFR-014 (Security): ✓ Tool restrictions enforced"
```

**Success criteria:**
- All validation checks pass
- All commands functional
- All agents functional
- Hook triggers correctly
- All requirements verified

**Reference**: plan.md lines 1074-1124, spec.md requirements

---

## PHASE 6: Marketplace Integration

### Task 6.1: Create GitHub Repository
```bash
cd ~/dev/claude-plugin-dev-essentials

# Initialize git if not already
git add .
git commit -m "plugin: initial release v0.1.0

- Add 3 core commands (extract, summarize, compare)
- Add 2 essential agents (doc-writer, test-generator)
- Add notification-manager hook
- Complete documentation and examples
- Cross-platform support (Linux, macOS)

Closes #1

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# Create GitHub repository
gh repo create Piotr1215/claude-plugin-dev-essentials --public --source=. --remote=origin

# Push to GitHub
git push -u origin main

# Create release tag
git tag -a v0.1.0 -m "Release v0.1.0 - MVP

MVP release with core functionality:
- 3 commands: extract, summarize, compare
- 2 agents: doc-writer, test-generator
- 1 hook: notification-manager

Tested on Linux and macOS."

git push origin v0.1.0

# Create GitHub release
gh release create v0.1.0 \
  --title "v0.1.0 - MVP Release" \
  --notes "## What's New

### Commands
- `/extract` - Pattern extraction with semantic analysis
- `/summarize` - File summarization with language understanding
- `/compare` - Semantic file comparison

### Agents
- `@doc-writer` - API documentation specialist
- `@test-generator` - Comprehensive test generation

### Hooks
- `notification-manager` - Smart task completion notifications

See [CHANGELOG.md](CHANGELOG.md) for details."
```

**Validation:**
```bash
# Verify repository exists
gh repo view Piotr1215/claude-plugin-dev-essentials

# Verify release
gh release list
```

**Reference**: plan.md lines 1206-1251

---

### [✓] Task 6.2: Update aiverse marketplace - COMPLETED
```bash
cd ~/dev/ai-coreutils-marketplace

# Edit marketplace.json
cat > .claude-plugin/marketplace.json <<'EOF'
{
  "name": "ai-coreutils",
  "owner": {
    "name": "Piotr Zaniewski",
    "email": "piotr@cloudrumble.net"
  },
  "metadata": {
    "description": "Essential AI-augmented utilities for development",
    "version": "1.0.0",
    "homepage": "https://github.com/Piotr1215/ai-coreutils-marketplace"
  },
  "plugins": [
    {
      "name": "dev-essentials",
      "source": {
        "source": "github",
        "repo": "Piotr1215/claude-plugin-dev-essentials",
        "branch": "main"
      },
      "description": "Essential AI-augmented dev utilities (commands, agents, hooks)",
      "version": "0.1.0",
      "author": {
        "name": "Piotr Zaniewski"
      },
      "category": "productivity",
      "keywords": ["development", "utilities", "coreutils", "documentation", "testing"],
      "strict": true
    }
  ]
}
EOF

# Validate marketplace
claude plugin validate .

# Commit and push
git add .claude-plugin/marketplace.json
git commit -m "marketplace: add dev-essentials plugin v0.1.0

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
git push
```

**Validation:**
```bash
# Verify marketplace.json
jq '.' .claude-plugin/marketplace.json
```

**Reference**: plan.md lines 1257-1304

---

### Task 6.3: End-to-End Installation Test
```bash
# Clean slate - remove any local installations
claude plugin uninstall dev-essentials 2>/dev/null || true

# Add marketplace
claude plugin marketplace add Piotr1215/ai-coreutils-marketplace

# List available plugins
claude /plugin

# Should see dev-essentials listed

# Install from marketplace
claude plugin install dev-essentials@ai-coreutils

# Verify installation
claude plugin list | grep dev-essentials

# Test all components
echo "=== Testing Commands ==="
claude /extract TODO ~/dev/ai-coreutils-marketplace
claude /summarize ~/dev/ai-coreutils-marketplace/README.md
echo "test" > /tmp/t1 && echo "test" > /tmp/t2
claude /compare /tmp/t1 /tmp/t2

echo "=== Testing Agents ==="
@doc-writer document a sample file
@test-generator suggest tests for a sample function

echo "=== Testing Hook ==="
# Run command, switch tmux window, verify notification
# (Manual verification)

echo "=== Success ==="
echo "✅ Marketplace installation works"
echo "✅ All components functional"
echo "✅ Plugin ready for use"
```

**Success criteria:**
- Marketplace recognized
- Plugin listed
- Installation completes without errors
- All commands work
- All agents work
- Hook triggers

**Reference**: plan.md lines 1310-1359

---

## PHASE 7: Communication & Documentation

### Task 7.1: Update Main Marketplace README
```bash
cd ~/dev/ai-coreutils-marketplace

# Update README.md
cat >> README.md <<'EOF'

## Installation

```bash
# Add marketplace
/plugin marketplace add Piotr1215/ai-coreutils-marketplace

# Install plugin
/plugin install dev-essentials@ai-coreutils
```

## Available Plugins

### dev-essentials v0.1.0

Essential AI-augmented utilities for development following Unix coreutils philosophy.

**Commands:**
- `/extract` - Pattern extraction with semantic context and priority
- `/summarize` - File summarization with language understanding
- `/compare` - Semantic file comparison with risk assessment

**Agents:**
- `@doc-writer` - Technical documentation specialist
- `@test-generator` - Comprehensive test generation expert

**Hooks:**
- `notification-manager` - Smart task completion notifications

**[View plugin documentation →](https://github.com/Piotr1215/claude-plugin-dev-essentials)**

---

## Philosophy

What GNU coreutils are to Unix, ai-coreutils are to AI-assisted development.

Claude sits between you and Unix tools, adding semantic understanding where traditional tools only provide syntax.

**Example:**
- Traditional: `grep -rn "TODO" .` → You manually read and prioritize
- AI-augmented: `/extract TODO` → Claude provides context, priority, explanation

---

## Design Principles

1. **Augmentation, not replacement** - Enhances Unix tools, doesn't replace them
2. **Generic and composable** - Works across projects and languages
3. **Real value** - Leverages Claude's unique semantic capabilities
4. **Unix philosophy** - Small, focused, composable utilities
EOF

# Commit and push
git add README.md
git commit -m "docs: add installation instructions and plugin listing

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
git push
```

**Validation:**
```bash
# View updated README
cat README.md
```

**Reference**: plan.md lines 1371-1413

---

## Success Validation Checklist

Use this checklist to verify MVP completion:

### Plugin Structure
- [ ] `~/dev/claude-plugin-dev-essentials/` repository exists
- [ ] `.claude-plugin/plugin.json` is valid
- [ ] All directories created (commands, agents, hooks, scripts, tests)
- [ ] `.gitignore` present
- [ ] `LICENSE` (MIT) present

### Commands
- [ ] `commands/extract.md` exists and has valid frontmatter
- [ ] `commands/summarize.md` exists and has valid frontmatter
- [ ] `commands/compare.md` exists and has valid frontmatter
- [ ] All commands execute without errors
- [ ] Command output matches specifications

### Agents
- [ ] `agents/doc-writer.md` exists with tool restrictions
- [ ] `agents/test-generator.md` exists with tool restrictions
- [ ] Both agents execute without errors
- [ ] Agent output quality meets standards

### Hooks
- [ ] `hooks/hooks.json` exists and is valid
- [ ] `scripts/notify.sh` exists and is executable
- [ ] Hook triggers on Stop event
- [ ] Notification works on Linux and macOS
- [ ] Silent failure when notification unavailable

### Documentation
- [ ] `README.md` comprehensive with examples
- [ ] `CHANGELOG.md` follows Keep a Changelog format
- [ ] `CONTRIBUTING.md` explains development process
- [ ] All documentation is clear and accurate

### Publishing
- [ ] GitHub repository created and public
- [ ] Initial commit pushed
- [ ] Release tag v0.1.0 created
- [ ] GitHub release published

### Marketplace
- [ ] `ai-coreutils-marketplace/marketplace.json` updated
- [ ] Points to correct GitHub repository
- [ ] Marketplace README updated
- [ ] E2E installation works from marketplace

### Requirements Verification
- [ ] FR-001 to FR-009: Commands ✓
- [ ] FR-010 to FR-017: Agents ✓
- [ ] FR-018 to FR-023: Hooks ✓
- [ ] FR-024 to FR-029: Plugin system ✓
- [ ] NFR-001 to NFR-003: Performance ✓
- [ ] NFR-004 to NFR-006: Compatibility ✓
- [ ] NFR-011 to NFR-014: Security ✓

### User Experience
- [ ] Installation takes <2 minutes
- [ ] Commands feel natural in Unix workflow
- [ ] Output immediately useful
- [ ] Error messages clear and actionable
- [ ] Examples are copy-paste ready

---

## Timeline Estimate

Based on plan.md timeline:

- **Week 1-2**: Foundation + Commands (Tasks 1.1-2.4) - 10 days
- **Week 3-4**: Agents + Hooks (Tasks 3.1-4.3) - 10 days
- **Week 5**: Documentation + Publishing (Tasks 5.1-7.1) - 5 days

**Total**: 25 working days (~5 weeks)

---

## Next Steps After MVP

After completing all tasks and validating success criteria:

1. **Gather User Feedback**
   - Monitor GitHub issues
   - Collect usage patterns
   - Identify pain points

2. **Phase 2 Planning** (ideas.md lines 271-275)
   - Additional commands: explain, trace-deps, suggest-tests
   - Additional agents: security-reviewer, refactorer
   - Additional hooks: session-init

3. **Phase 3 Planning** (ideas.md lines 277-282)
   - Testing framework: claude-plugin-test-framework
   - AI-assisted testing: plugin-tester-agent
   - CI/CD integration templates

---

**Tasks Version**: 1.0
**Ready for**: Execution
**Reference**: spec.md + plan.md + ideas.md
