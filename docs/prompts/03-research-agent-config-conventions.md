# Research agent config conventions

Subagent prompt written by the lead agent (Claude Code, Claude Opus 5.5) on 2026-09-25 13:00 UTC.
Local paths are shortened to `<repo>` and `<scratchpad>`; the text is otherwise verbatim.

---

Research the current conventions (today is 25 Sep 2026) of three AI coding tools. This finalises an "agent-agnostic repo" setup with these parts:
- AGENTS.md at the repo root, and CLAUDE.md as an `@AGENTS.md` pointer.
- Shared skills in `.agents/skills/<name>/SKILL.md`, symlinked into `.claude/skills/` and `.cursor/skills/`.
- Canonical MCP servers in `.agents/mcp/servers.json`, rendered by a script into `.mcp.json` (Claude Code), `.cursor/mcp.json` (Cursor) and `.codex/config.toml` (Codex). An `install-codex` command merges a managed block into `~/.codex/config.toml`, because Codex supposedly doesn't load repo-local config.

Use official docs and cite them. Questions:

**Claude Code** (code.claude.com/docs):
1. Does it read AGENTS.md natively now? If so, a CLAUDE.md with `@AGENTS.md` would double-load it.
2. Where does it discover project skills: only `.claude/skills/`, or also `.agents/skills/`? Does it follow symlinked skill directories?
3. What is the status of github.com/anthropics/claude-code/issues/31005 (native `.agents/` scanning)?
4. The `.mcp.json` format: stdio (`command`, `args`, `env`, `type: "stdio"`), http (`type: "http"`, `url`, `headers`), and env-var expansion syntax (`${VAR}`, `${VAR:-default}`). Which working directory are stdio servers spawned in? Is there a variable for the project dir usable inside `.mcp.json`?

**Cursor** (cursor.com/docs):
1. Does it read AGENTS.md?
2. Which skills directories does it scan (`.cursor/skills`, `.agents/skills`?), and does it support symlinks?
3. The `.cursor/mcp.json` format for stdio and remote servers. Is `type` accepted or required?
4. The interpolation syntax (`${env:NAME}`, `${workspaceFolder}`), and the working directory for stdio servers.

**Codex CLI** (developers.openai.com/codex and github.com/openai/codex docs/config.md or docs/config-reference):
1. Does Codex now load a project-local `.codex/config.toml` (for trusted projects?), or only `~/.codex/config.toml` / `$CODEX_HOME`?
2. The `[mcp_servers.<name>]` fields for stdio (command, args, env, cwd, env_vars?) and for streamable HTTP (url, bearer_token_env_var, http_headers, env_http_headers).
3. Where does Codex discover skills (`.agents/skills`, `.codex/skills`, `~/.codex/skills`)?
4. How does it treat AGENTS.md, including nested files?

**Also**:
1. The agentskills.io spec: required SKILL.md frontmatter fields and naming rules.
2. Does `npx skills add` (vercel-labs/skills) install into `.agents/skills/` and create `.claude/skills/` symlinks?

Output: write concise findings with source URLs to `<scratchpad>/research/agent-tooling.md`. End it with a recommendation section:
- Which symlink targets are actually needed.
- Whether CLAUDE.md should import AGENTS.md.
- The exact file formats for the three MCP configs, using one stdio server as the example: name `sekisho`, command `.venv/bin/python`, args `["mcp/server.py"]`, env `{"SEKISHO_URL": "http://localhost:8000"}`. Show how each tool would express it, and note any working-directory or relative-path caveats, with the fix (e.g. a `cwd` field or a workspace variable).

Your final message: a summary of at most 12 lines.
