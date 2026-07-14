# Cortex - RAG MCP pour base de connaissance

**Francais** | [English](README.en.md)

Cortex est un serveur MCP (Model Context Protocol) qui expose une recherche
semantique sur une base de connaissance locale. Il permet a Claude, Codex et
Gemini d'interroger la documentation interne sans consommer inutilement leur
fenetre de contexte. La recherche est semantique (par sens, pas par mot-cle), en
francais comme en anglais, et tout reste local : aucun contenu de la base ne
quitte le poste.

## Fonctionnement en bref

```
kb_path (TOML/env)      <- Export Confluence (fichiers .md)
      |
      v
  indexer.py            <- Decoupe, hash, vectorise
      |
      v
  %LOCALAPPDATA%\Cortex\chroma_db\  <- Base vectorielle locale (ChromaDB)
      |
      v
  server.py             <- Serveur MCP (FastMCP)
      |
      v
  Clients MCP           <- Claude / Codex / Gemini
```

Le modele d'embedding est le multilingue ONNX
`paraphrase-multilingual-MiniLM-L12-v2`.

## Demarrage rapide

```bat
:: Depuis le dossier ou vous avez clone Cortex
install.bat
```

`install.bat` initialise la configuration, installe les dependances, propose
d'enregistrer Cortex dans les clients MCP detectes et valide l'installation.
Apres l'installation, redemarrer les clients enregistres. Details :
[Installation](docs/fr/setup.md).

## Outils MCP exposes

| Outil | Description |
|---|---|
| `cortex_search` | Recherche semantique. Parametres : `query`, `section` (optionnel), `top_k` (1-10). |
| `cortex_sync` | Declenche un sync incremental. Parametre : `section` (optionnel). |
| `cortex_list_sections` | Liste les sections incluses et les dossiers "out of policy". |
| `cortex_freshness` | Resume de fraicheur. Parametres : `section` (optionnel), `include_entries` (`false` par defaut). |

## Documentation

- [Sommaire](docs/fr/index.md)
- [Installation](docs/fr/setup.md) : prerequis, clients MCP.
- [Guide d'utilisation](docs/fr/user-guide.md) : sync, recherche, outils,
  doctor, logs.
- [Configuration](docs/fr/configuration.md) : `config.toml`, sections, data
  home, migration.
- [Installation reproductible](docs/fr/install-reproductible.md) :
  `requirements.lock`, `--require-hashes`, regeneration du verrou.
- [Architecture](docs/fr/architecture.md) : bout en bout et choix techniques.
- [Securite](docs/fr/security.md) : zero flux sortant, telemetrie off,
  single-writer.

## Prerequis

| Outil | Version minimale |
|---|---|
| Python | 3.10+ |
| Client | Claude Desktop/Code, Codex, Gemini, Cursor, Windsurf ou VS Code (support MCP) |
| Espace disque | ~500 Mo (modele + index) |

## Licence

Apache 2.0. Voir [LICENSE](LICENSE).
