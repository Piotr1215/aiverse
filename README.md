# aiverse

> A universe of AI-augmented utilities — what GNU coreutils are to Unix, aiverse is to AI-assisted development.

## Philosophy

Unix coreutils (`ls`, `grep`, `sed`) operate on text streams through standard interfaces. Aiverse utilities leverage Claude Code's capabilities through slash commands, agents, hooks, and MCP/LSP servers.

### The parallel

| Unix system | Description | Claude Code system | Description |
| --- | --- | --- | --- |
| Coreutils (`ls`, `grep`) | Small programs operating on text | Slash commands | Prompts guiding Claude's tool use |
| Shell/pipes (`bash`, `\|`) | Composition layer chaining operations | Hooks (PostToolUse, SessionStart) | Event-driven automation |
| Daemons (`sshd`, `httpd`) | Single-purpose services | Agents | Focused Claude instances for specialized tasks |
| System services (systemd, cron) | Complex coordination | MCP/LSP servers | External tool and language integration |

### Common interface

- Unix: stdin/stdout text streams.
- Claude Code: tool calls/results plus conversation context.

## Installation

```bash
/plugin marketplace add Piotr1215/aiverse
/plugin install <plugin-name>@aiverse
```

## Available plugins

| Plugin | Description | Source |
| --- | --- | --- |
| `ai-coreutils` | Essential AI-augmented dev utilities (commands, agents, hooks) | [Piotr1215/ai-coreutils](https://github.com/Piotr1215/ai-coreutils) |
| `vale-lsp` | Vale prose linter LSP for markdown and MDX | local (`./plugins/vale-lsp`) |
| `design-kit` | Test-driven, parallel-execution framework for building complex systems | [Piotr1215/design-kit](https://github.com/Piotr1215/design-kit) |

## Design principles

1. Do one thing well — singular focus per component.
2. Composable — chain operations through standard interfaces.
3. Generic — not tied to specific projects.
4. Predictable — consistent input/output formats.
5. Stateless where possible (commands), stateful where needed (agents, servers).

## Contributing

New plugins must follow the philosophy: small, focused, generic, composable.

Each plugin entry in `.claude-plugin/marketplace.json` is validated against `schema/marketplace.schema.json` on every PR. Run validation locally:

```bash
npm install
npm run validate
npm run lint:md
```

## License

MIT
