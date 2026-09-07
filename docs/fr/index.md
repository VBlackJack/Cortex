# Documentation Cortex

**Français** | [English](../en/index.md)

Cortex est un serveur MCP (Model Context Protocol) qui expose une recherche
hybride sur une base de connaissance locale et les générations documentaires
courantes. Il permet à Claude, Codex et Gemini d'interroger la documentation
interne sans consommer inutilement leur fenêtre de contexte.

## Modèle mental

Cortex est le bibliothécaire de ta base de connaissance : il a tout lu et
retrouve les bons passages même quand la question est formulée autrement que
dans le texte d'origine. La recherche est sémantique (par sens, pas par
mot-clé), en français comme en anglais, grâce au modèle ONNX multilingue
`paraphrase-multilingual-MiniLM-L12-v2`.

L'index vectoriel (ChromaDB), l'index lexical (SQLite FTS5) et le traitement
Cortex restent sur ton poste. Le writer Confluence optionnel ne télécharge que
les espaces explicitement autorisés. Cortex n'envoie pas le contenu de la base ;
le client MCP peut toutefois transmettre au modèle les passages qu'il a
demandés, selon sa propre politique.

## Sommaire

- [Installation](setup.md) : prérequis, `install.bat`, connexion des clients
  MCP (Claude, Codex, Gemini).
- [Installation Windows](installation-windows.md) : installateur unique sans
  Python pour Cortex, Companion et les modèles, puis déploiement silencieux.
- [Distribution autonome](distribution.md) : exécutables one-file, builds
  PyInstaller locaux et artefacts de release.
- [Guide d'utilisation](user-guide.md) : indexation et sync, recherche, les
  quatre outils MCP, le doctor, les logs.
- [FAQ](faq.md) : installation, données locales, sync, diagnostic et sécurité.
- [Notes de version](notes-de-version.md) : changements visibles par version et
  avis sur l'historique publié.
- [Configuration](configuration.md) : `config.toml`, variables
  d'environnement, sections, data home, migration de l'index.
- [Planification de l'ingestion](ingestion-scheduling.md) : santé des sources,
  rattrapage, reprises et Planificateur de tâches Windows.
- [Migration metadata v2](metadata-v2-migration.md) : contrat de stockage,
  rechunk en une passe, sauvegarde et restauration mesurées.
- [Installation reproductible](install-reproductible.md) : `requirements.lock`,
  `pip install --require-hashes`, régénération du verrou.
- [Spécification publique](spec.md) : surface MCP, contrats de l'index,
  données, distribution et limites.
- [Architecture](architecture.md) : fonctionnement de bout en bout et choix
  techniques.
- [Sécurité](security.md) : runtime local, télémétrie désactivée,
  logs bornés, écriture single-writer.
- [Writer Confluence](writer-confluence.md) : ingestion REST sur liste blanche,
  stockage interactif du PAT, conversion et planification.

- [Validation de la recherche](validation-recherche.md) : contrat JSON, mesures
  isolées de pertinence et de performance, vérification des deux SHA.

## En un coup d'oeil

| Élément | Valeur |
|---|---|
| Type | Serveur MCP local (FastMCP) |
| Recherche | Hybride vectorielle + lexicale, FR et EN |
| Index | ChromaDB + SQLite FTS5 dans `%LOCALAPPDATA%\Cortex` |
| Runtime | Binaire autonome, ou Python 3.10+ |
| Clients | Claude Desktop/Code, Codex, Gemini, Antigravity, LM Studio, Cursor, Windsurf, VS Code |
| Licence | Apache 2.0 |
