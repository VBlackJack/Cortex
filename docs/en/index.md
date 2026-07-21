# Cortex documentation

[Francais](../fr/index.md) | **English**

Cortex is an MCP (Model Context Protocol) server that exposes semantic search
over a local knowledge base. It lets Claude, Codex and Gemini query internal
documentation without wasting their context window.

## Mental model

Cortex is the librarian of your knowledge base: it has read everything and
retrieves the right passages even when the question is phrased differently from
the source text. Search is semantic (by meaning, not keyword), in French and in
English, thanks to the multilingual ONNX model
`paraphrase-multilingual-MiniLM-L12-v2`.

Everything is local: the vector index (ChromaDB) lives on your machine, and no
content from the knowledge base ever leaves it.

## Table of contents

- [Setup](setup.md): prerequisites, `install.bat`, connecting MCP clients
  (Claude, Codex, Gemini).
- [Windows installation](windows-install.md): Python-free wizard, corpus
  selection, shortcuts, and silent deployment.
- [Standalone distribution](distribution.md): one-file executables, local
  PyInstaller builds and release artifacts.
- [User guide](user-guide.md): indexing and sync, search, the four MCP tools,
  the doctor, logs.
- [Configuration](configuration.md): `config.toml`, environment variables,
  sections, data home, index migration.
- [Reproducible install](reproducible-install.md): `requirements.lock`,
  `pip install --require-hashes`, regenerating the lock.
- [Architecture](architecture.md): end-to-end behavior and technical choices.
- [Security](security.md): no outbound traffic, telemetry disabled, bounded
  logs, single-writer writes.

## At a glance

| Item | Value |
|---|---|
| Type | Local MCP server (FastMCP) |
| Search | Semantic, FR and EN |
| Index | ChromaDB in `%LOCALAPPDATA%\Cortex\chroma_db` |
| Runtime | Standalone binary, or Python 3.10+ |
| Clients | Claude Desktop/Code, Codex, Gemini, Antigravity, LM Studio, Cursor, Windsurf, VS Code |
| License | Apache 2.0 |
