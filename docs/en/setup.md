# Setup

[Francais](../fr/setup.md) | **English**

[Back to table of contents](index.md)

## Prerequisites

| Tool | Minimum version |
|---|---|
| Python | 3.10+ |
| Client | Claude Desktop/Code, Codex or Gemini with MCP support |
| Disk space | ~500 MB (model + index) |

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

# Validation without writing: entry, Python executable and server.py
python setup_config.py --check --clients all
```

Each client launches its own `server.py` process, about 150 MB of RAM per
active client. Concurrent reads are safe. All writes to the index are
serialized across processes by the Cortex write lock, already tested under
multi-process conditions (see [Security](security.md)).

## Post-install validation

```powershell
python setup_config.py --check
```

Checks: Python reachable, packages importable, user configuration valid, single
index location or migration required, `cortex` entry present for each selected
client, Python executable and `server.py` reachable. The output is qualified per
client with `[OK]`, `[SKIP not installed]` or `[FAIL]`.

For a full support diagnostic, then run the
[doctor](user-guide.md#cortex-doctor).
