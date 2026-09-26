# Agent tooling conventions: Claude Code, Cursor, Codex CLI

Researched 25 Sep 2026. Latest versions at that date: Claude Code v2.1.282 (24 Sep), Codex CLI
rust-v0.157.0 (25 Sep), Cursor docs as published (CLI release 26 Aug), `skills` CLI v1.7.0 (17 Sep).

Source labels: **Doc** = official docs. **Source** = the vendor's own GitHub repo. **Forum** = a
Cursor staff reply on forum.cursor.com. Everything else is marked as inference.

## Summary

- Claude Code reads `AGENTS.md` natively since v2.1.277. It still ignores `.agents/` entirely, so
  it only finds skills through `.claude/skills/`.
- Cursor and Codex both read `.agents/skills/` natively. The `.cursor/skills/` links aren't needed.
- Codex has loaded a repo-local `.codex/config.toml`, MCP servers included, for **trusted**
  projects since v0.78 (Jan 2026). The claim that Codex doesn't load repo-local config is out of
  date, so `install-codex` is optional.
- A `CLAUDE.md` that contains `@AGENTS.md` never makes Claude Code load AGENTS.md twice. A
  *symlinked* `CLAUDE.md` does double-load in Cursor.
- Each tool resolves relative stdio paths differently. The fix for each tool is in section 5.3.

---

## 1. Claude Code (code.claude.com/docs)

### 1.1 Does it read AGENTS.md? Would `@AGENTS.md` double-load?
- **Yes, natively, since v2.1.277 (18 Sep 2026).** v2.1.281 (23 Sep) extended it to Bedrock,
  Vertex, Foundry, LLM gateways and telemetry-off sessions. The feature is a built-in plugin,
  `agents-md@builtin`. (Doc: memory#agents-md; changelog)
- Default mode `claude-md-or-agents-md`: Claude reads AGENTS.md **only if** there is no
  `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` in the working directory or any parent.
  If one exists, Claude reads the CLAUDE.md files only. `~/.claude/CLAUDE.md` and
  `.claude/rules/` don't count toward that check.
- **No double-load.** The docs say a `CLAUDE.md` containing `@AGENTS.md` can stay: the import
  never causes a second read in any mode. In `claude-md-and-agents-md` mode, Claude skips an
  AGENTS.md it has already loaded through an import or a symlink.
- When Claude reads AGENTS.md natively:
  - At session start it loads every `AGENTS.md` and `.claude/AGENTS.md` from the working
    directory up.
  - It loads a subdirectory's AGENTS.md the first time it reads a file there, if that directory
    has no CLAUDE.md.
  - It expands `@path` imports.
  - It never reads `AGENTS.local.md`, `AGENTS.override.md`, or anything under `.agents/`. That
    means `.agents/AGENTS.md` is invisible to Claude Code.
- Pitfalls:
  - Adding a `CLAUDE.local.md` silently turns native AGENTS.md reading off.
  - The mode can only be set in user or managed settings
    (`pluginConfigs."agents-md@builtin".options.instructionFiles`). Project settings are ignored.
  - Some sessions read CLAUDE.md only: versions before 2.1.277, sessions with the plugin
    disabled, and sometimes the first session after upgrading from 2.1.276 or earlier.
  - `InstructionsLoaded` hooks don't fire for an AGENTS.md read natively.
  - With a root CLAUDE.md present, the default mode also skips **nested** AGENTS.md files.
- A symlinked `CLAUDE.md` pointing to `AGENTS.md` also works (read once). But the Edit and Write
  tools refuse to write through it, and Windows clones without `core.symlinks` get a one-line
  text file instead.
- Sources: https://code.claude.com/docs/en/memory#agents-md ,
  https://code.claude.com/docs/en/changelog

### 1.2 Skill discovery and symlinks
- Locations:
  - `~/.claude/skills/`
  - project `.claude/skills/`, in the start directory **and every parent up to the repo root**
  - nested `<subdir>/.claude/skills/`, loaded the first time Claude reads or edits a file there
  - `--add-dir` directories, plugins (`<plugin>/skills/`) and managed settings
  - **`.agents/skills/` is not a location.**
- Symlinks: a `<skill-name>` entry in the personal, project or enterprise location may be a
  symlink to a directory elsewhere. Claude reads `SKILL.md` from the target and loads the skill
  once even when several entries point at the same target.
  - The docs describe per-skill links.
  - Changelog v2.1.178 fixed the Linux sandbox failing to start when `.claude/skills` itself is a
    symlink.
- The command name comes from the directory name; frontmatter `name` only sets the display label.
- Portable frontmatter is the six spec fields. claude.ai uploads and the Skills API reject any
  other key.
- Source: https://code.claude.com/docs/en/skills (section "Choose where skills load")

### 1.3 Status of anthropics/claude-code#31005
- Title: "Support for AGENTS.md and .agents/skills/, the community has been asking since August
  2025". kvnwolf opened it on 5 Mar 2026.
- **Closed on 18 Sep 2026 by its author** (state_reason `completed`; labels `duplicate`,
  `enhancement`, `area:core`, `memory`), minutes after a commenter posted the v2.1.277 AGENTS.md
  release note. It has 29 comments and none from Anthropic staff.
- Only the AGENTS.md half shipped. Commenters on 19–22 Sep asked to reopen it for
  `.agents/skills/`.
  - The open tracker is **#16345**, a feature request for the standard `.agents/skills/`
    directory (opened 5 Jan 2026, 28 comments).
  - #70247 was closed as a duplicate.
  - Related: #6235 (AGENTS.md, about 6.7k reactions) was closed on 17 Aug 2026 by bcherny, who
    pointed to the `@AGENTS.md` import.
- **Native `.agents/` scanning has not shipped.**
- Sources: https://github.com/anthropics/claude-code/issues/31005 ,
  https://github.com/anthropics/claude-code/issues/16345

### 1.4 `.mcp.json`
- The file lives at the project root as `{"mcpServers": {"<name>": {...}}}`. Interactive sessions
  ask for a one-time approval of project servers; `-p` and SDK sessions load them without asking.
- **stdio:** `command`, `args`, `env`, plus optional `"type": "stdio"`. An entry with no `type`
  is treated as stdio.
- **http:** `"type": "http"` (alias `streamable-http`; `sse` and `ws` also exist), `url`,
  optional `headers`, `headersHelper` and `oauth`. A `url` with no `type` is an error.
- **Expansion:** `${VAR}` and `${VAR:-default}` work in `command`, `args`, `env`, `url` and
  `headers`.
  - An unset variable with no default still loads, with a warning, and passes the literal text.
  - Credential variables such as `ANTHROPIC_API_KEY` read as empty in a remote `url` or
    `headers`.
- **Working directory:** there is no `cwd` key. Relative paths in `command` and `args` resolve
  against **the directory you launched `claude` from**, not the location of `.mcp.json`.
- **Project-dir variable:** since v2.1.139, Claude Code exports `CLAUDE_PROJECT_DIR` (the project
  root where the session started) into every stdio server's environment.
  - It is *not* in Claude Code's own environment, so `${CLAUDE_PROJECT_DIR}` in a project
    `.mcp.json` doesn't expand.
  - The docs suggest `${CLAUDE_PROJECT_DIR:-.}`, which normally just falls back to `.`.
  - Plugin MCP configs substitute the variable directly.
  - Use it inside the server (`os.environ["CLAUDE_PROJECT_DIR"]`) or in a shell wrapper.
- Sources: https://code.claude.com/docs/en/mcp ,
  https://code.claude.com/docs/en/debug-your-config#check-mcp-servers ,
  https://code.claude.com/docs/en/hooks#reference-scripts-by-path

## 2. Cursor (cursor.com/docs)

### 2.1 AGENTS.md
- **Yes**, at the project root and in any subdirectory.
  - A nested file applies when Agent works on files in that directory. It is combined with its
    parents, and the most specific file wins.
  - The CLI reads the root `AGENTS.md` **and `CLAUDE.md`** as rules.
- Cursor also reads **`CLAUDE.md`** the same way, **always applied**, as a "third-party" config.
  - IDE opt-out: Settings → Rules, Skills and Subagents → "Include third-party Plugins, Skills,
    and other configs".
  - The CLI has no opt-out as of Jul 2026 (Forum 166558).
- Known bug (Forum 164295, open; staff replies from Jun and Aug 2026):
  - Always-on rules are de-duplicated **by filename, not inode**. A `CLAUDE.md` symlinked to
    `AGENTS.md` is therefore injected twice.
  - Staff suggest a `CLAUDE.md` containing just `@AGENTS.md` as the workaround.
- Sources: https://cursor.com/docs/rules#agentsmd , https://cursor.com/help/customization/rules ,
  https://cursor.com/docs/cli/using , https://forum.cursor.com/t/164295 ,
  https://forum.cursor.com/t/166558

### 2.2 Skill directories and symlinks
- Directories scanned:

  | Scope | Directories |
  | :--- | :--- |
  | Project | **`.agents/skills/`**, `.cursor/skills/` |
  | User | `~/.agents/skills/`, `~/.cursor/skills/` |
  | Compatibility (third-party) | `.claude/skills/`, `.codex/skills/`, `~/.claude/skills/`, `~/.codex/skills/` |

  - Scans are recursive, so category folders work.
  - A `.agents/skills/` or `.cursor/skills/` folder anywhere in the repo is picked up and scoped
    to its subtree.
- Frontmatter: `name` is required (lowercase letters, digits and hyphens; must match the folder).
  `description` is required. Optional: `paths`, `disable-model-invocation`, `icon`, `color`,
  `metadata`.
- Symlinks aren't mentioned in the docs.
  - Forum 149693: staff said symlinked skills were fixed in Cursor 2.5 (Feb 2026), and the
    reporter confirmed.
  - CLI changelog, 22 Jun 2026: skill discovery follows symlinked directories.
  - Cloud Agents still don't follow symlinked skills (Forum 153603, open).
- Duplicates: the same skill in two scanned locations is listed twice (Forum 169575). The docs
  don't say whether two symlinks to one target are collapsed.
- Sources: https://cursor.com/docs/skills , https://cursor.com/help/customization/skills ,
  https://cursor.com/docs/cli/changelog , https://forum.cursor.com/t/149693 ,
  https://forum.cursor.com/t/169575

### 2.3 `.cursor/mcp.json`
- The project `.cursor/mcp.json` and the global `~/.cursor/mcp.json` are merged. The project
  wins on a name clash.
- **stdio:**
  - `type: "stdio"`: the field table marks it **required**, yet every JSON example omits it.
  - `command`: must be on PATH or a full path.
  - `args`, `env`, and `envFile` (stdio only).
- **Remote** (Streamable HTTP or SSE): `url`, `headers`, and optional `auth`
  (`CLIENT_ID`, `CLIENT_SECRET`, `scopes`).
  - The examples carry no `type`; Cursor infers the transport.
  - The Cloud Agents API accepts `type` as `http`, `sse` or `stdio`, defaulting from
    `url`/`command`.
- Sources: https://cursor.com/docs/mcp , https://cursor.com/help/customization/mcp ,
  https://cursor.com/docs/cloud-agent/api/endpoints

### 2.4 Interpolation and working directory
- Variables:
  - `${env:NAME}`
  - `${userHome}`
  - `${workspaceFolder}`: the folder that contains `.cursor/mcp.json`
  - `${workspaceFolderBasename}`
  - `${pathSeparator}` or `${/}`
- They resolve in `command`, `args`, `env`, `url` and `headers`, plus `auth`.
- **The stdio working directory isn't documented, and no `cwd` key is documented.** Put
  `${workspaceFolder}` in front of anything project-relative.
- Source: https://cursor.com/docs/mcp#config-interpolation

## 3. Codex CLI

The pages at developers.openai.com/codex/* now redirect to learn.chatgpt.com/docs/*.
github.com/openai/codex `docs/config.md` is a stub that links to them, and there is no
`docs/config-reference` in the repo.

### 3.1 Project-local `.codex/config.toml`
- **Yes, for trusted projects.** Since rust-v0.78.0 (6 Jan 2026), Codex loads every
  `.codex/config.toml` from the project root down to the working directory; the closest file wins.
  - In an untrusted project it skips every project `.codex/` layer: config, hooks and rules.
  - The MCP page explicitly allows MCP servers in the project file.
  - Keys ignored in project files: `openai_base_url`, `chatgpt_base_url`,
    `apps_mcp_product_sku`, `model_provider(s)`, `notify`, `profile(s)`,
    `experimental_realtime_ws_base_url`, `otel`.
- Trust:
  - Set it at the onboarding prompt or with `/permissions`.
  - It is stored as `[projects."/abs/path"] trust_level = "trusted"` in `~/.codex/config.toml`.
  - The user config directory is `$CODEX_HOME`, default `~/.codex`.
- Precedence: CLI flags > project > profile > user > cloud-managed > `/etc/codex/config.toml` >
  built-in defaults.
- The project root is the nearest directory with `.git` (`project_root_markers` changes this).
- Sources: https://developers.openai.com/codex/config-basic ,
  https://developers.openai.com/codex/config-advanced (section "Project config files"),
  https://github.com/openai/codex/releases/tag/rust-v0.78.0

### 3.2 `[mcp_servers.<name>]` fields
- **stdio:**
  - `command` (required), `args`, `env` (a map)
  - `env_vars`: names, or `{ name, source = "local" | "remote" }`; forwarded from Codex's
    environment
  - `cwd`
  - `experimental_environment = "remote"`
- **Streamable HTTP:**
  - `url` (required)
  - `bearer_token_env_var`
  - `http_headers` (static values)
  - `env_http_headers` (header name to env var name)
  - `http_headers_helper` (a command that prints the headers as JSON)
  - `auth`: `oauth` (default) or `chatgpt`
  - `[mcp_servers.<name>.oauth]` with `client_id`, `callback_url`, `callback_port`
  - `scopes`, `oauth_resource`
- **Common:**
  - `startup_timeout_sec` (default 10) and `tool_timeout_sec` (default 60)
  - `enabled`, `required`
  - `enabled_tools`, `disabled_tools`
  - `default_tools_approval_mode`: `auto`, `prompt`, `writes` or `approve`
  - `tools.<tool>.approval_mode`, `tools.<tool>.output_token_limit`
- There is **no `type` key**: the transport follows `command` versus `url`. There is also no
  `${VAR}` or workspace-variable interpolation.
- Source-level behaviour (openai/codex main):
  - With no `cwd`, the server starts in Codex's runtime working directory, so relative commands
    resolve from where Codex runs.
  - The server's environment is cleared except for an allowlist (HOME, LOGNAME, PATH, SHELL,
    USER, …), plus `env` and `env_vars`.
  - The docs resolve relative paths in a project config against its `.codex/` folder for keys
    like `model_instructions_file`. `cwd` is a plain string and isn't covered, so don't rely on
    `cwd = ".."`.
- Sources: https://developers.openai.com/codex/mcp ,
  https://developers.openai.com/codex/config-reference ,
  https://github.com/openai/codex/blob/main/codex-rs/rmcp-client/src/stdio_server_launcher.rs ,
  https://github.com/openai/codex/blob/main/codex-rs/rmcp-client/src/utils.rs

### 3.3 Skill discovery
- Doc locations:
  - **`.agents/skills` in every directory from the working directory up to the repo root**
    (REPO scope)
  - `~/.agents/skills` (USER)
  - `/etc/codex/skills` (ADMIN)
  - bundled skills (SYSTEM)
- Symlinked skill folders are followed. Skills with the same `name` aren't merged; both are
  listed.
- Disable a skill with `[[skills.config]] path = …, enabled = false`. UI and policy extras go in
  `agents/openai.yaml`.
- The source code still scans two locations the docs don't list:
  - the deprecated `$CODEX_HOME/skills` (`~/.codex/skills`), kept for backward compatibility
  - `.codex/skills` inside trusted project layers
- Sources: https://developers.openai.com/codex/skills ,
  https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs

### 3.4 AGENTS.md, including nested files
- Global: `$CODEX_HOME/AGENTS.override.md`, otherwise `AGENTS.md` (the first non-empty one).
- Project:
  - Codex walks **from the project root down to the working directory**.
  - In each directory it takes the first of `AGENTS.override.md`, `AGENTS.md`, or a name from
    `project_doc_fallback_filenames`, so at most one file per directory.
  - It concatenates them root first, so deeper files override earlier ones.
  - Empty files are skipped, and it stops at `project_doc_max_bytes` (32 KiB).
- Codex builds this list once per run. **Files below the working directory are not loaded.**
- CLAUDE.md is ignored unless you add it as a fallback filename, and fallbacks only apply where a
  directory has no AGENTS.md.
- Since rust-v0.150.0 (26 Aug 2026), untrusted projects contribute no project AGENTS.md.
- Sources: https://developers.openai.com/codex/guides/agents-md ,
  https://github.com/openai/codex/releases/tag/rust-v0.150.0

## 4. Also

### 4.1 agentskills.io spec
- **Required:**
  - `name`: 1–64 chars; lowercase `a-z`, `0-9` and `-` only; no leading or trailing hyphen; no
    `--`; **must equal the parent directory name**.
  - `description`: 1–1024 chars; says what the skill does and when to use it.
- **Optional:**
  - `license`
  - `compatibility` (at most 500 chars)
  - `metadata` (a map from strings to strings)
  - `allowed-tools` (space-separated; experimental)
- The body is free-form.
  - Keep `SKILL.md` under 500 lines.
  - Put detail in `references/`, `scripts/` and `assets/`, referenced by relative paths one
    level deep.
  - Validate with `skills-ref validate ./<skill>`.
- Source: https://agentskills.io/specification

### 4.2 Does `npx skills add` use `.agents/skills/` and link `.claude/skills/`?
- **Yes.** In the default symlink mode (v1.7.0), a project install:
  - copies each skill to `.agents/skills/<name>/`
  - creates a relative symlink for each agent that has its own directory. For Claude Code that is
    `.claude/skills/<name>`, created even if `.claude/` doesn't exist yet.
- Codex and Cursor are "universal" agents (they read `.agents/skills`), so no link is made for
  them.
- A global install uses `~/.agents/skills/`.
- If a symlink fails, the tool copies instead. `--copy` forces copies.
- Source: https://github.com/vercel-labs/skills (README; `src/installer.ts`, `src/agents.ts`)

---

## 5. Recommendation

### 5.1 Symlink targets that are actually needed
- **Needed:** `.claude/skills/<name>` → `../../.agents/skills/<name>`. Claude Code only reads
  `.claude/skills/` (#16345 is still open).
  - Use per-skill links. They are the documented form and what `npx skills` creates.
  - Commit the links.
  - Windows clones need `core.symlinks=true` or Developer Mode.
- **Drop:** `.cursor/skills/*`. Cursor reads `.agents/skills/` natively, and it also reads
  `.claude/skills/` for compatibility. A third copy only adds duplicate listings.
  - In `link-skills.sh`, set `TARGETS=(".claude/skills")`.
- **None for Codex.** It reads `.agents/skills/` natively. Don't create `.codex/skills/`, which
  Codex still scans and would duplicate.
- **Private skills:** `.agents/skills-local/` isn't scanned by any of the three tools. Link each
  private skill as both:
  - `.agents/skills/<name>` → `../skills-local/<name>` (excluded through `.git/info/exclude`),
    which covers Cursor and Codex
  - `.claude/skills/<name>`, which covers Claude Code
- **Duplicate listing in Cursor:** Cursor may list a skill twice (from `.agents/skills` and from
  the `.claude/skills` link). Check Customize → Skills. IDE users can turn off "Include
  third-party Plugins, Skills, and other configs". Cursor then keeps `AGENTS.md` and
  `.agents/skills`, and drops `CLAUDE.md` and `.claude/skills`. The CLI has no such switch.

### 5.2 Should CLAUDE.md import AGENTS.md?
**Yes. Keep `CLAUDE.md` as the import, not a symlink, and cut it down to the single line
`@AGENTS.md`.** Move its "reusable agent assets live in `.agents/`" sentence into AGENTS.md.
- It never double-loads in Claude Code, per the docs.
- It works on every Claude Code version and session, including the ones that can't read
  AGENTS.md.
- It protects against the `CLAUDE.local.md` trap.
- Cursor loads it as a one-line extra rule. Cursor staff recommend this form; a symlink would
  inject AGENTS.md twice. Confirm it in Cursor's Context Explorer.
- Codex ignores `CLAUDE.md`.
- When to revisit:
  - If you add nested `AGENTS.md` files, Claude Code's default mode skips them while a root
    CLAUDE.md exists. Either add a `CLAUDE.md` with `@AGENTS.md` beside each nested file, or
    delete the root CLAUDE.md once everyone is on v2.1.281 or later.
  - `.agents/AGENTS.md` is never read by Claude Code, and Codex only reads it when launched
    inside `.agents/`.

### 5.3 MCP config formats, using `sekisho` as the example
Canonical entry: `command .venv/bin/python`, `args ["mcp/server.py"]`,
`env {"SEKISHO_URL": "http://localhost:8000"}`.

**Claude Code: `.mcp.json`**
```json
{
  "mcpServers": {
    "sekisho": {
      "type": "stdio",
      "command": ".venv/bin/python",
      "args": ["mcp/server.py"],
      "env": { "SEKISHO_URL": "http://localhost:8000" }
    }
  }
}
```
- Caveat: relative paths resolve against the directory `claude` was **launched** from, and there
  is no `cwd` key. The file above works only when you launch from the repo root.
- Fix, independent of the launch directory:
  `"command": "/bin/sh", "args": ["-c", "cd \"$CLAUDE_PROJECT_DIR\" && exec .venv/bin/python mcp/server.py"]`.
  - Write it as bare `$CLAUDE_PROJECT_DIR` with no braces, so Claude Code's `${…}` expansion
    leaves it for the shell. It needs v2.1.139 or later.
  - If you sometimes launch from a subdirectory, use the `git rev-parse` form shown under Codex
    instead; it works in Claude Code as well.

**Cursor: `.cursor/mcp.json`**
```json
{
  "mcpServers": {
    "sekisho": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["${workspaceFolder}/mcp/server.py"],
      "env": { "SEKISHO_URL": "http://localhost:8000" }
    }
  }
}
```
- Caveat: the stdio working directory is undocumented, there is no `cwd` key, and `command` must
  be on PATH or a full path.
- Fix: `${workspaceFolder}` (the folder containing `.cursor/mcp.json`).
- Keep `"type": "stdio"`, because the field table marks it required. `sync-mcp.sh`'s
  `render_cursor` currently deletes it and would emit bare relative paths.

**Codex: `.codex/config.toml` (trusted project), or a user-level block**
```toml
[mcp_servers.sekisho]
command = ".venv/bin/python"
args = ["mcp/server.py"]
env = { SEKISHO_URL = "http://localhost:8000" }
```
- Caveat: there is no workspace variable. With no `cwd`, relative paths resolve from the directory
  Codex runs in, so you must launch from the repo root or pass `codex --cd <repo>`.
- Fix, portable enough to commit:
  `command = "/bin/sh"`, `args = ["-c", "cd \"$(git rev-parse --show-toplevel)\" && exec .venv/bin/python mcp/server.py"]`.
  PATH is in Codex's environment allowlist.
- For a per-machine user-level block, write absolute `command` and `args` plus
  `cwd = "/Users/…/wallet-audit-trail"`.
- To take `SEKISHO_URL` from the shell instead of hard-coding it, use `env_vars = ["SEKISHO_URL"]`;
  Codex doesn't inherit the shell environment.

**HTTP servers, for completeness:**

| Tool | Fields |
| :--- | :--- |
| Claude Code | `type: "http"`, `url`, `headers` |
| Cursor | `url`, `headers` (no `type` in the docs) |
| Codex | `url`, then `http_headers` (static), `env_http_headers`, or `bearer_token_env_var` for secrets |

**In all three tools:** have `mcp/server.py` resolve its own files from `Path(__file__)` rather
than the working directory. The POSIX `sh -c` wrappers are fine on macOS, but they won't work on
native Windows.

### 5.4 Other changes to this repo's setup
- `install-codex` is no longer needed once developers trust the project. That happens once, at
  Codex's trust prompt.
  - If you keep it, make it opt-in.
  - A user-level `sekisho` block starts in **every** Codex session on the machine.
  - Defining the server in both layers is redundant, because the project layer wins key by key.
  - Update the Codex paragraph in `.agents/AGENTS.md`, which says the opposite.
- `sync-mcp.sh` currently rejects `${…}` in `servers.json`, which is fine. The renderer then has
  to rewrite repo-relative `command` and path arguments for each tool:
  - Cursor: `${workspaceFolder}/…`
  - Claude Code and Codex: the `sh -c` wrapper, or plain relative paths plus the rule "launch from
    the repo root"
