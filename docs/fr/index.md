# Documentation Cortex

**Francais** | [English](../en/index.md)

Cortex est un serveur MCP (Model Context Protocol) qui expose une recherche
semantique sur une base de connaissance locale. Il permet a Claude, Codex et
Gemini d'interroger la documentation interne sans consommer inutilement leur
fenetre de contexte.

## Modele mental

Cortex est le bibliothecaire de ta base de connaissance : il a tout lu et
retrouve les bons passages meme quand la question est formulee autrement que
dans le texte d'origine. La recherche est semantique (par sens, pas par
mot-cle), en francais comme en anglais, grace au modele ONNX multilingue
`paraphrase-multilingual-MiniLM-L12-v2`.

Tout est local : l'index vectoriel (ChromaDB) vit sur ton poste, aucun contenu
de la base ne quitte la machine.

## Sommaire

- [Installation](setup.md) : prerequis, `install.bat`, connexion des clients
  MCP (Claude, Codex, Gemini).
- [Installation Windows](installation-windows.md) : assistant sans Python,
  choix du corpus, raccourcis et deploiement silencieux.
- [Distribution autonome](distribution.md) : executables one-file, builds
  PyInstaller locaux et artefacts de release.
- [Guide d'utilisation](user-guide.md) : indexation et sync, recherche, les
  quatre outils MCP, le doctor, les logs.
- [Configuration](configuration.md) : `config.toml`, variables
  d'environnement, sections, data home, migration de l'index.
- [Installation reproductible](install-reproductible.md) : `requirements.lock`,
  `pip install --require-hashes`, regeneration du verrou.
- [Architecture](architecture.md) : fonctionnement de bout en bout et choix
  techniques.
- [Securite](security.md) : absence de flux sortant, telemetrie desactivee,
  logs bornes, ecriture single-writer.

## En un coup d'oeil

| Element | Valeur |
|---|---|
| Type | Serveur MCP local (FastMCP) |
| Recherche | Semantique, FR et EN |
| Index | ChromaDB dans `%LOCALAPPDATA%\Cortex\chroma_db` |
| Runtime | Binaire autonome, ou Python 3.10+ |
| Clients | Claude Desktop/Code, Codex, Gemini, Antigravity, LM Studio, Cursor, Windsurf, VS Code |
| Licence | Apache 2.0 |
