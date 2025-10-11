# aiverse

> A universe of AI-augmented utilities - what GNU coreutils are to Unix, aiverse is to AI-assisted development

## Philosophy

Unix coreutils (`ls`, `grep`, `sed`) operate on text streams through standard interfaces. Aiverse utilities leverage Claude's capabilities through slash commands, agents, hooks, and MCP servers.

### The Evolution

```
Traditional:  User → Unix Tools (ls, grep, sed)
AI-Enhanced:  User → Claude → Unix Tools + AI Capabilities
```

Claude sits between user and tools, leveraging both traditional Unix utilities and AI-specific operations. Not replacing, augmenting.

### The Parallel

| Unix System | Description | Claude Code System | Description |
|-------------|-------------|-----------|-------------|
| **Coreutils** (`ls`, `grep`) | Small C programs<br>Operate on text | **Slash Commands** (`/ai-extract`, `/ai-summarize`) | Prompts guiding Claude's tool use<br>Predictable text operations |
| **Shell/Pipes** (`bash`, `\|`) | Composition layer<br>Chain operations | **Hooks** (PostToolUse, SessionStart) | Event-driven automation<br>Orchestrate Claude's actions |
| **Daemons** (`sshd`, `httpd`) | Single-purpose services<br>Always available | **Agents** (doc-writer, test-generator) | Focused Claude instances<br>Specialized tasks |
| **System Services** (`systemd`, `cron`) | Complex coordination<br>Inter-process comm | **MCP Servers** (Model Context Protocol) | External tool integration<br>State & communication |

### Common Interface

Unix: stdin/stdout (text streams)
Claude Code: tool calls/results + conversation context

## Examples

Just as you pipe Unix commands:
```bash
cat file.md | grep "TODO" | wc -l
```

Claude Code utilities compose through hooks and tool use:
```
Edit event → hook triggers → Claude uses tools → notifies user
```

## Installation

```bash
/plugin marketplace add Piotr1215/aiverse
/plugin install dev-essentials@aiverse
```

## Components

### Slash Commands
Prompts that guide Claude to perform specific operations with consistent output format. Claude uses its tool capabilities under the hood. Examples: extract structured data, summarize in bullet format, semantic comparison.

### Agents
Pre-configured Claude instances with focused behavior and limited scope. Each agent has specific system prompts and tool access. Examples: documentation writer, test generator, security reviewer.

### Hooks
Bash/Python scripts triggered by Claude Code lifecycle events (SessionStart, PostToolUse, Stop). Orchestrate workflows, call external systems, automate responses to Claude's actions.

### MCP Servers
Model Context Protocol servers that extend Claude's capabilities. Provide custom tools, maintain state, enable communication between instances, integrate external systems.

## Available Plugins

- **dev-essentials** - Core commands, hooks, and agents for AI-assisted development

## Design Principles

1. **Do one thing well** - Each component has singular focus
2. **Composable** - Chain operations through standard interfaces
3. **Generic** - Not tied to specific projects or workflows
4. **Predictable** - Consistent input/output formats
5. **Stateless** - Where possible (commands), stateful where needed (agents, servers)

## Contributing

Contributions must follow the philosophy: small, focused, generic, composable utilities that enhance Claude Code workflows.

## License

MIT
