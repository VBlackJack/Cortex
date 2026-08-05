# Documentation Cortex

**Francais** | [English](../en/index.md)

Cortex est un serveur MCP (Model Context Protocol) qui expose une recherche
hybride sur une base de connaissance locale et les generations documentaires
courantes. Il permet a Claude, Codex et Gemini d'interroger la documentation
interne sans consommer inutilement leur fenetre de contexte.

## Modele mental

Cortex est le bibliothecaire de ta base de connaissance : il a tout lu et
retrouve les bons passages meme quand la question est formulee autrement que
dans le texte d'origine. La recherche est semantique (par sens, pas par
mot-cle), en francais comme en anglais, grace au modele ONNX multilingue
`paraphrase-multilingual-MiniLM-L12-v2`.

L'index vectoriel (ChromaDB), l'index lexical (SQLite FTS5) et le traitement
Cortex restent sur ton poste. Le writer Confluence optionnel ne telecharge que
les espaces explicitement autorises. Cortex n'envoie pas le contenu de la base ;
le client MCP peut toutefois transmettre au modele les passages qu'il a
demandes, selon sa propre politique.

## Sommaire

- [Installation](setup.md) : prerequis, `install.bat`, connexion des clients
  MCP (Claude, Codex, Gemini).
- [Installation Windows](installation-windows.md) : assistant sans Python,
  choix du corpus, raccourcis et deploiement silencieux.
- [Distribution autonome](distribution.md) : executables one-file, builds
  PyInstaller locaux et artefacts de release.
- [Guide d'utilisation](user-guide.md) : indexation et sync, recherche, les
  quatre outils MCP, le doctor, les logs.
- [FAQ](faq.md) : installation, donnees locales, sync, diagnostic et securite.
- [Configuration](configuration.md) : `config.toml`, variables
  d'environnement, sections, data home, migration de l'index.
- [Planification de l'ingestion](ingestion-scheduling.md) : sante des sources,
  rattrapage, reprises et Planificateur de taches Windows.
- [Migration metadata v2](metadata-v2-migration.md) : contrat de stockage,
  rechunk en une passe, sauvegarde et restauration mesurees.
- [Installation reproductible](install-reproductible.md) : `requirements.lock`,
  `pip install --require-hashes`, regeneration du verrou.
- [Specification publique](spec.md) : surface MCP, contrats de l'index,
  donnees, distribution et limites.
- [Architecture](architecture.md) : fonctionnement de bout en bout et choix
  techniques.
- [Securite](security.md) : runtime local, telemetrie desactivee,
  logs bornes, ecriture single-writer.
- [Writer Confluence](writer-confluence.md) : ingestion REST sur liste blanche,
  stockage interactif du PAT, conversion et planification.

## En un coup d'oeil

| Element | Valeur |
|---|---|
| Type | Serveur MCP local (FastMCP) |
| Recherche | Hybride vectorielle + lexicale, FR et EN |
| Index | ChromaDB + SQLite FTS5 dans `%LOCALAPPDATA%\Cortex` |
| Runtime | Binaire autonome, ou Python 3.10+ |
| Clients | Claude Desktop/Code, Codex, Gemini, Antigravity, LM Studio, Cursor, Windsurf, VS Code |
| Licence | Apache 2.0 |
