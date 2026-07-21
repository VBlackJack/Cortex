# Cortex - RAG MCP pour base de connaissance

**Francais** | [English](README.en.md)

Cortex est un serveur MCP (Model Context Protocol) qui expose une recherche
semantique sur une base de connaissance locale. Il permet a Claude, Codex et
Gemini de retrouver le bon passage dans vos documents sans consommer inutilement
leur fenetre de contexte. La recherche est semantique (par sens, pas par
mot-cle), en francais comme en anglais, et tout reste local : aucun contenu de la
base ne quitte le poste.

## Installation

### Windows, sans Python (recommande)

La voie la plus simple : un installeur autonome, aucun Python a installer.

1. Telecharger `Cortex-Setup.exe` depuis la
   [derniere release](https://github.com/VBlackJack/Cortex/releases/latest).
2. Double-cliquer. L'installeur n'etant pas encore signe, SmartScreen peut
   afficher un avertissement : `Informations complementaires`, puis
   `Executer quand meme`.
3. Choisir le dossier de vos documents, laisser `Tout indexer dans ce dossier`,
   terminer.
4. Redemarrer votre application IA : Cortex y apparait comme serveur MCP.

Deposez ensuite vos documents dans le dossier et lancez le raccourci
`Cortex Sync`. Details, mode silencieux et reinstallation :
[Installation Windows](docs/fr/installation-windows.md).

### Binaire autonome (macOS Apple Silicon, Linux x64)

Chaque release fournit aussi un binaire unique `cortex` pour macOS Apple
Silicon (arm64) et Linux x64 (serveur MCP + CLI, sans Python). Voir
[Distribution autonome](docs/fr/distribution.md).

### Depuis les sources (Python, avance)

```bat
:: Depuis le dossier ou vous avez clone Cortex
install.bat
```

`install.bat` initialise la configuration, installe les dependances, propose
d'enregistrer Cortex dans les clients MCP detectes et valide l'installation.
Details : [Installation](docs/fr/setup.md).

## Fonctionnement en bref

```
Dossier de documents (.md, .pdf)   <- vos fichiers
      |
      v
  cortex sync           <- Decoupe, hash, vectorise
      |
      v
  %LOCALAPPDATA%\Cortex\chroma_db\  <- Base vectorielle locale (ChromaDB)
      |
      v
  cortex serve          <- Serveur MCP (FastMCP)
      |
      v
  Clients MCP           <- Claude / Codex / Gemini / Antigravity / LM Studio / Cursor / Windsurf / VS Code
```

Le modele d'embedding est le multilingue ONNX
`paraphrase-multilingual-MiniLM-L12-v2`, telecharge au premier usage.

## Deux modes d'indexation

- **Tout le dossier** (defaut) : tout ce que vous placez dans le dossier
  choisi, a la racine ou dans n'importe quel sous-dossier, devient cherchable.
  Rien a configurer.
- **Sections** (avance) : limite l'indexation a des sous-dossiers nommes que
  vous pouvez chercher separement (defauts `knowledge`, `projects`, `notes`).

Details : [Configuration](docs/fr/configuration.md).

## Commande `cortex`

Le paquet installe expose une commande unique :

| Sous-commande | Role |
|---|---|
| `cortex setup` | Config + index + enregistrement des clients en une fois (`--yes`, `--no-index`, `--reset`). |
| `cortex serve` | Lance le serveur MCP (utilise par les clients). |
| `cortex sync` | Synchronisation incrementale de l'index. |
| `cortex doctor` | Diagnostic de l'installation (lecture seule). |
| `cortex register` / `cortex unregister` | Ajoute ou retire Cortex des clients MCP. |
| `cortex check` | Verifie l'installation. |

## Outils MCP exposes

| Outil | Description |
|---|---|
| `cortex_search` | Recherche semantique. Parametres : `query`, `section` (optionnel), `top_k` (1-10). |
| `cortex_sync` | Declenche un sync incremental. Parametre : `section` (optionnel). |
| `cortex_list_sections` | Liste les sections incluses et les dossiers "out of policy". |
| `cortex_freshness` | Resume de fraicheur. Parametres : `section` (optionnel), `include_entries` (`false` par defaut). |

## Documentation

- [Sommaire](docs/fr/index.md)
- [Installation Windows](docs/fr/installation-windows.md) : assistant sans
  Python, choix du corpus, mode silencieux, reinstallation.
- [Distribution autonome](docs/fr/distribution.md) : binaires one-file et builds.
- [Installation depuis les sources](docs/fr/setup.md) : prerequis, clients MCP.
- [Guide d'utilisation](docs/fr/user-guide.md) : sync, recherche, outils,
  doctor, logs.
- [FAQ](docs/fr/faq.md) : installation, donnees locales, sync et diagnostic.
- [Configuration](docs/fr/configuration.md) : `config.toml`, modes d'indexation,
  sections, data home, migration.
- [Installation reproductible](docs/fr/install-reproductible.md) :
  `requirements.lock`, `--require-hashes`, regeneration du verrou.
- [Architecture](docs/fr/architecture.md) : bout en bout et choix techniques.
- [Securite](docs/fr/security.md) : zero flux sortant, telemetrie off,
  single-writer.

## Prerequis

| Voie | Prerequis |
|---|---|
| Installeur Windows / binaire autonome | Aucun Python. ~500 Mo d'espace (modele + index). |
| Depuis les sources | Python 3.10+. ~500 Mo d'espace. |
| Client | Claude Desktop/Code, Codex, Gemini, Antigravity, LM Studio, Cursor, Windsurf ou VS Code (support MCP). |

## Licence

Apache 2.0. Voir [LICENSE](LICENSE).
