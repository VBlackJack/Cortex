# Setup

[Francais](../fr/setup.md) | **English**

[Back to table of contents](index.md)

## Prerequisites

| Tool | Minimum version |
|---|---|
| Runtime | Standalone Cortex binary, or Python 3.10+ |
| Client | Claude Desktop/Code, Codex or Gemini with MCP support |
| Disk space | ~500 MB (model + index) |

For a target machine without Python, use a released standalone binary and see
[Standalone distribution](distribution.md). The clone-based `install.bat` and
pip paths below remain the development and source-install options.

## One-click install

```bat
:: From the folder where you cloned Cortex
install.bat
```

The script is portable: it works regardless of the clone location (internal
`%~dp0`). It runs automatically:

1. Detect Python 3 on the PATH.
2. Initialize `%APPDATA%\Cortex\config.toml` without overwriting an existing
   configuration.
3. Install or update the pip dependencies.
4. Offer to register Cortex in the detected MCP clients.
5. Offer to clear the vector store (useful if the model changes).
6. Validate the installation.

After installation: restart the registered clients.

## Install as a user tool

To install Cortex as a package, without depending on the clone folder:

```powershell
python -m pip install -e .
cortex doctor
```

The `.bat` scripts remain fully supported and `install.bat` does not require the
Cortex package to be installed. For a hash-locked install (byte-for-byte
identical dependency chains), see
[Reproducible install](reproducible-install.md).

### One-command setup

Once the package is installed, `cortex setup` chains the three steps in a single
call: initialize the config, build the index, then register the MCP clients.

```powershell
# Config + index + registration of every detected client
cortex setup

# Non-interactive (no prompts; requires CORTEX_KB_PATH to create the config)
cortex setup --yes

# Skip building the index (useful on a RAM-constrained machine)
cortex setup --no-index

# Target specific clients
cortex setup --clients claude-desktop,codex
```

`--clients` accepts `all` (default), `none`, or a list. The index is built in a
single process (higher RAM peak than section-by-section `sync.bat`); `--no-index`
lets you run `sync.bat` separately afterwards. A client registration failure is
reported as a warning without interrupting the rest.

When this command runs from the standalone executable, it registers that
executable with `serve` as the MCP argument. When it runs from a pip or source
installation, it preserves the Python plus `server.py` entry.

## Connect Claude, Codex and Gemini

`setup_config.py` detects installed clients, prints a summary, then registers
the `cortex` MCP server. Invalid JSON or TOML makes the operation fail before
any write. Each modified file gets a timestamped backup and is replaced
atomically; other settings and MCP servers are preserved.

| Client | User configuration | Cortex entry |
|---|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` | `mcpServers.cortex` |
| Claude Code | Managed by `claude mcp add --scope user` | never written directly by Cortex |
| Codex CLI and IDE extension | `~/.codex/config.toml` | `[mcp_servers.cortex]` |
| Gemini CLI and Gemini Code Assist (VS Code agent mode) | `~/.gemini/settings.json` | `mcpServers.cortex` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json` | `mcpServers.cortex` |
| Windsurf | `%USERPROFILE%\.codeium\windsurf\mcp_config.json` | `mcpServers.cortex` |
| VS Code | `%APPDATA%\Code\User\mcp.json` | `servers.cortex` (with `type: stdio`) |

Registration is done at user scope for all seven clients. Cursor and Windsurf
use the same `mcpServers` key as Claude; VS Code uses the `servers` key with a
`type: stdio` field (VS Code's native MCP format).

These locations and formats follow the official documentation for
[Claude Code](https://docs.anthropic.com/en/docs/claude-code/mcp),
[Codex](https://developers.openai.com/codex/mcp/),
[Gemini CLI](https://google-gemini.github.io/gemini-cli/docs/tools/mcp-server.html)
and [Gemini Code Assist](https://docs.cloud.google.com/gemini/docs/codeassist/use-agentic-chat-pair-programmer).

```powershell
# All detected clients (default behavior)
python setup_config.py

# All known targets; missing clients are reported as SKIP
python setup_config.py --clients all

# Explicit selection
python setup_config.py --clients claude-desktop,codex,gemini

# Validation without writing: entry, server command and arguments
python setup_config.py --check --clients all

# Non-interactive (no prompts): register detected clients
python setup_config.py --yes --clients all
```

The `--yes` mode asks no questions: it never prompts for a path (`--init --yes`
then requires `CORTEX_KB_PATH`) and never moves an existing index (migration
stays explicit via `--migrate-data`).

Each client launches its own server process: `cortex serve` for a standalone
installation, or `python server.py` for a source/pip installation. Concurrent
reads are safe. All writes to the index are serialized across processes by the
Cortex write lock, already tested under multi-process conditions (see
[Security](security.md)).

## Post-install validation

```powershell
python setup_config.py --check
```

Checks: runtime dependencies, user configuration, single index location or
migration required, `cortex` entry presence for each selected client, and stored
server command/arguments. The output is qualified per client with `[OK]`,
`[SKIP not installed]` or `[FAIL]`.

For a full support diagnostic, then run the
[doctor](user-guide.md#cortex-doctor).
