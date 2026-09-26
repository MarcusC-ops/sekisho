# .agents/

Agent-agnostic configuration following the [Agent Skills](https://agentskills.io)
open standard and [AGENTS.md](https://agents.md) conventions. Portable assets live here
once; assets that need a different format per agent are generated from one source here;
agent-specific files stay where their agent expects them.

What each agent reads (checked 25 Sep 2026):

| | Instructions | Skills | MCP servers |
|---|---|---|---|
| Claude Code | `CLAUDE.md` (imports `AGENTS.md`) | `.claude/skills/` only, so shared skills are symlinked there | `.mcp.json` |
| Cursor | `AGENTS.md`, `CLAUDE.md` | `.agents/skills/` natively | `.cursor/mcp.json` |
| Codex | `AGENTS.md` | `.agents/skills/` natively | `.codex/config.toml`, once you trust the project |

## Layout

- `skills/`: shared skills (committed). Each is a directory with a `SKILL.md`.
- `skills-local/`: private skills (gitignored). No agent reads this directory, so
  `link-skills.sh` links each one into `skills/` and `.claude/skills/`, and keeps those
  links out of git through `.git/info/exclude`.
- `mcp/servers.json`: canonical MCP server config.
- `scripts/link-skills.sh`: symlinks skills into `.claude/skills/` (and private skills into
  `skills/`).
- `scripts/sync-mcp.sh`: renders `servers.json` into `.mcp.json`, `.cursor/mcp.json` and
  `.codex/config.toml`.

## Adding a skill

1. Create `.agents/skills/<name>/SKILL.md` with `name` (lowercase letters, digits and
   hyphens, same as the directory) and `description` frontmatter. Keep it under 500 lines
   and put detail in `references/`.
2. Add `references/NOTES.md` with seven sections: Overview, Scope, Key Decisions,
   Key Nuances & Limitations, Future Improvement Ideas, Open Questions, Changelog.
   Every change to the skill gets a new changelog row.
3. Run `.agents/scripts/link-skills.sh`.
4. Commit the skill directory and its `.claude/skills/<name>` symlink together.

Third-party skills: `npx skills add <repo>@<skill> -y` installs into `.agents/skills/`
and links `.claude/skills/` itself.

## Adding an MCP server

1. Edit `.agents/mcp/servers.json`. Each entry is either
   `{"type": "stdio", "command": ..., "args": [...], "env": {...}}` or
   `{"type": "http", "url": ..., "headers": {...}}`. The script rejects any other field,
   plus `${...}` and `$(...)`, because each agent expands those differently.
2. stdio servers always start in the repo root, so `command` and `args` may be
   repo-relative (e.g. `.venv/bin/python`). The generated configs wrap them in `/bin/sh`,
   which needs a POSIX shell (macOS, Linux, WSL).
3. Run `.agents/scripts/sync-mcp.sh`.
4. Commit `servers.json` and every generated file together.

## Rules

- Edit skills in `.agents/skills/`, never in `.claude/skills/`. Don't create
  `.cursor/skills/` or `.codex/skills/`: Cursor and Codex would list those skills twice.
- Edit MCP servers in `.agents/mcp/servers.json`, never in `.mcp.json`,
  `.cursor/mcp.json` or `.codex/config.toml`.
- Agent-specific files (`.claude/settings.json`, `.claude/agents/`, `.cursor/rules/*.mdc`)
  have no cross-agent equivalent: leave them in place. Knowledge that every agent needs
  goes in the root `AGENTS.md` instead.
- Pre-commit runs `link-skills.sh check` and `sync-mcp.sh check`. Enable it once per clone
  with `pre-commit install`.
