# Cortex - RAG MCP pour base de connaissance

**Français** | [English](README.md)

Cortex est un serveur MCP (Model Context Protocol) qui expose une recherche
sémantique sur une base de connaissance locale. Il permet à Claude, Codex et
Gemini de retrouver le bon passage dans vos documents sans consommer inutilement
leur fenêtre de contexte. La recherche est sémantique (par sens, pas par
mot-clé), en français comme en anglais. Cortex traite et indexe la base en local
sans envoyer son contenu ; le client MCP peut toutefois transmettre au modèle
les passages qu'il a demandés, selon sa propre politique.
Le writer Confluence optionnel ne télécharge que les espaces explicitement
autorisés ; le Markdown généré, l'index vectoriel et l'index lexical restent
locaux.

Depuis 2026.0906.01, Companion propose un accueil guidé, un historique et l'ajout Confluence par un seul lien de page ou d'espace. La connexion et le choix du nombre de pages restent dans le parcours ; la collecte réussie est suivie de l'indexation. Utiliser l'installeur combiné pour garder Cortex et Companion compatibles.

Avec la version associée 2026.0909.02, les mises à jour Confluence conservent la génération servie si un sous-arbre ne peut pas être énuméré et réappliquent les changements de cible/classification lors de la reprise. La recherche utilise le vectoriel multilingue par défaut ; les clients CLI et MCP peuvent choisir explicitement les modes hybride ou rerank. La première collecte réussie après mise à jour régénère les anciennes révisions, puis la synchronisation retire les entrées obsolètes de l’index.

## Mise à jour documentaire guidée (2026.0909.00)

Companion réunit les documents locaux et Confluence dans **Mes sources**, avec une action **Mettre à jour mes documents**. L’aperçu de recherche est redimensionnable, les grands arbres réalisent les lignes visibles et l’annulation de la préparation conserve le brouillon. La disponibilité suit désormais le dossier et la configuration enregistrés, y compris après redémarrage. Lancer une mise à jour documentaire après la mise à niveau pour établir cette preuve sur les anciens index. Voir les [notes de version](docs/fr/notes-de-version.md).

## Périmètre mesuré sans énumérer l'espace (2026.0907.00)

L'ajout d'une source Confluence mesure les périmètres page, sous-arbre et espace
entier avec un comptage indexé chacun, au lieu de parcourir l'espace page par
page. Sur un espace de 5916 pages, cette mesure prenait 3 min 19 s, au-delà du
délai de tout appelant graphique, et Companion n'affichait rien du tout. Elle
répond désormais en une seconde environ, à contrat inchangé.

Deux nombres de l'espace entier varient de un : la page résolue n'est plus
ajoutée au total de l'espace, et un espace sans page visible affiche zéro au lieu
de un. Un déploiement dont la recherche ne renvoie pas de total ne peut pas
mesurer un périmètre et le signale comme un échec permanent, non comme un échec
à réessayer. Voir [les contrats](docs/fr/writer-confluence.md).

Le Companion apparié 2026.0907.00 rétablit le contraste de la fenêtre de
périmètre, dont les options s'affichaient dans la couleur de texte du système, et
cesse de présenter un délai dépassé comme une panne de connexion ou de conseiller
une augmentation qui revient en arrière sans le dire.

## Gestion des sources dans Companion (2026.0906.02)

Ce parcours inclut recherche, arborescence distante, aperçu des changements,
états vérifiés, enregistrement avec mise à jour, annulation du dernier retrait
et actions de récupération. Voir [les contrats](docs/fr/writer-confluence.md).


La version appariée 2026.0906.02 propose **Mes sources**, un éditeur pré-rempli,
le retrait confirmé de pages ou d'espaces et l'ouverture des originaux dans
Confluence. Les retraits modifient uniquement le suivi Cortex et prennent effet
dans la recherche après une collecte et une indexation réussies.

Le retrait de la dernière source écrit explicitement `spaces = []` dans une
configuration schema v2 ou v3. Cette liste volontairement vide autorise une
publication vide avec les tombstones des anciens documents. Une clé `spaces`
absente reste une configuration incomplète et la collecte est refusée.
Les validations de connexion, de credentials et les protections de publication
restent applicables. Cette capacité requiert Cortex et Companion 2026.0906.02 ou ultérieurs ;
elle n'est pas disponible dans la release installée 2026.0906.01.


## Installation

### Windows, sans Python (recommandé)

La voie la plus simple : un seul installeur pour Cortex, Cortex Companion, le
convertisseur Confluence console et les modèles hors ligne. Aucun Python ni
runtime .NET n'est à installer séparément.

1. Télécharger `Cortex-Setup.exe` et `SHA256SUMS` depuis la
   [dernière release](https://github.com/VBlackJack/Cortex/releases/latest).
2. Avant de lancer l'installeur non signé, calculer son empreinte avec
   `Get-FileHash .\Cortex-Setup.exe -Algorithm SHA256` dans PowerShell et
   vérifier qu'elle correspond exactement à la ligne `Cortex-Setup.exe` de
   `SHA256SUMS`.
3. Double-cliquer seulement après cette vérification. Si SmartScreen affiche
   encore un avertissement, choisir `Informations complémentaires`, puis
   `Exécuter quand même`.
4. Choisir le dossier de vos documents, laisser `Tout indexer dans ce dossier`
   et terminer. Cortex Companion s'ouvre à la fin de l'installation.
   L’indexation ne démarre que lorsque vous lancez la synchronisation dans Companion.
5. Dans Companion, ouvrir `Réglages` pour vérifier le dossier de la base de
   connaissances. L'exécutable Cortex installé avec Companion est détecté
   automatiquement.
6. Déposer vos documents dans ce dossier, ouvrir `Base locale`, puis choisir
   `Synchroniser les documents locaux`.
7. Redémarrer votre application IA : Cortex y apparaît comme serveur MCP.

Companion permet ensuite de synchroniser, planifier, diagnostiquer et configurer
Cortex sans terminal. Détails, mode silencieux et réinstallation :
[Installation Windows](docs/fr/installation-windows.md).

### Archives autonomes (Windows x64, macOS Apple Silicon, Linux x64)

Chaque release fournit aussi une archive ZIP par plateforme. Elle contient le
binaire unique `cortex` ou `cortex.exe` (serveur MCP + CLI, sans Python) et les
licences de toutes les dépendances embarquées. Voir
[Distribution autonome](docs/fr/distribution.md).

### Depuis PyPI (Python, avancé)

```powershell
py -m pip install --upgrade cortex-local-rag
cortex setup
```

Cette voie installe la CLI et le serveur MCP, mais pas Cortex Companion. Le
modèle est téléchargé lors de sa première utilisation si son cache est vide.

### Depuis les sources (Python, avancé)

```bat
:: Depuis le dossier ou vous avez clone Cortex
install.bat
```

`install.bat` initialise la configuration, installe les dépendances, propose
d'enregistrer Cortex dans les clients MCP détectés et valide l'installation.
Détails : [Installation](docs/fr/setup.md).

## Fonctionnement en bref

```
Dossier de documents (.md, .pdf)   Writer Confluence optionnel (REST)
      |                                      |
      |                              generation Markdown courante
      +------------------+-------------------+
                         |
                         v
  cortex sync           <- Decoupe, hash, vectorise, met a jour FTS5
                         |
                         v
  %LOCALAPPDATA%\Cortex\  <- ChromaDB + lexical.db
      |
      v
  cortex serve          <- Serveur MCP (FastMCP)
      |
      v
  Clients MCP           <- Claude / Codex / Gemini / Antigravity / LM Studio / Cursor / Windsurf / VS Code
```

Le modèle d'embedding est le multilingue ONNX
`paraphrase-multilingual-MiniLM-L12-v2`. L'installeur Windows l'embarque ; une
installation depuis les sources ou un binaire autonome le télécharge si son
cache local est vide.

## Deux modes d'indexation

- **Tout le dossier** (défaut) : tout ce que vous placez dans le dossier
  choisi, à la racine ou dans n'importe quel sous-dossier, devient cherchable.
  Rien à configurer.
- **Sections** (avancé) : limite l'indexation à des sous-dossiers nommés que
  vous pouvez chercher séparément (défauts `knowledge`, `projects`, `notes`).

Ces modes gouvernent le dossier de documents choisi par l'utilisateur. Les
documents d'ingestion générés sont indexés séparément depuis la génération
publiée courante avec `source_kind=doc` et la section `sources`.

Détails : [Configuration](docs/fr/configuration.md).

## Commande `cortex`

Le paquet installé expose une commande unique :

| Sous-commande | Rôle |
|---|---|
| `cortex setup` | Config + index + enregistrement des clients en une fois (`--kb-path`, `--yes`, `--no-index`, `--reset`). |
| `cortex serve` | Lance le serveur MCP (utilisé par les clients). |
| `cortex sync` | Synchronisation incrémentale de l'index. |
| `cortex search` | Recherche dans l'index depuis la console (aide au débogage). |
| `cortex ingestion` | Affiche la santé d'une source et indique si un rattrapage est dû. |
| `cortex confluence` | Stocke le PAT interactivement ou lance le writer sur liste blanche. |
| `cortex config` | Lit ou modifie la configuration via un contrat JSON atomique, notamment pour Companion. |
| `cortex bundle` | Décrit ou vérifie une archive portable chiffrée. |
| `cortex doctor` | Diagnostic de l'installation (lecture seule). |
| `cortex register` / `cortex unregister` | Ajoute ou retire Cortex des clients MCP. |
| `cortex init` | Crée la seule configuration par utilisateur. |
| `cortex check` | Vérifie l'installation. |

`cortex --help` décrit chaque sous-commande et `cortex <commande> --help` décrit
ses options. Une installation sans invite se scripte ainsi :

```powershell
cortex setup --yes --kb-path "D:\Documents\Connaissances"
```

## Outils MCP exposés

| Outil | Description |
|---|---|
| `cortex_search` | Recherche vectorielle multilingue par défaut ; `retrieval_mode` facultatif (`vector`, `hybrid`, `rerank`). Paramètres : `query`, `section`, `top_k` (1-10), filtres source/auteur et plages de dates de création/mise à jour. |
| `cortex_sync` | Déclenche un sync incrémental du dossier choisi et, sur un sync complet, de la génération documentaire courante. |
| `cortex_list_sections` | Liste les sections incluses et les dossiers "out of policy". |
| `cortex_freshness` | Résumé en lecture seule de la fraîcheur du vault et de l'ingestion. Paramètres : `section` (optionnel), `include_entries` (`false` par défaut). |

## Documentation

- [Sommaire](docs/fr/index.md)
- [Installation Windows](docs/fr/installation-windows.md) : installateur unique
  Cortex + Companion + convertisseur Confluence + modèles, choix du corpus,
  mode silencieux, réinstallation.
- [Distribution autonome](docs/fr/distribution.md) : archives par plateforme et builds reproductibles.
- [Installation depuis les sources](docs/fr/setup.md) : prérequis, clients MCP.
- [Guide d'utilisation](docs/fr/user-guide.md) : sync, recherche, outils,
  doctor, logs.
- [FAQ](docs/fr/faq.md) : installation, données locales, sync et diagnostic.
- [Notes de version](docs/fr/notes-de-version.md) : changements visibles par
  version et avis sur l'historique publié.
- [Journal technique](CHANGELOG.md) : détail complet des changements par version.
- [Configuration](docs/fr/configuration.md) : `config.toml`, modes d'indexation,
  sections, data home, migration.
- [Planification de l'ingestion](docs/fr/ingestion-scheduling.md) : santé des
  sources, rattrapage, reprises et Planificateur de tâches.
- [Migration metadata v2](docs/fr/metadata-v2-migration.md) : métadonnées de
  recherche structurées, sauvegarde, migration et restauration.
- [Writer Confluence](docs/fr/writer-confluence.md) : ingestion REST sur liste
  blanche, Windows Credential Manager, conversion et générations atomiques.
- [Installation reproductible](docs/fr/install-reproductible.md) :
  `requirements.lock`, `--require-hashes`, régénération du verrou.
- [Spécification publique](docs/fr/spec.md) : surface MCP, contrats de l'index,
  données, distribution et limites.
- [Architecture](docs/fr/architecture.md) : bout en bout et choix techniques.
- [Sécurité](docs/fr/security.md) : runtime local, télémétrie off,
  single-writer.

## Prérequis

| Voie | Prérequis |
|---|---|
| Installeur Windows | Aucun Python ni runtime .NET séparé. ~500 Mo d'espace minimum (applications, modèle + index). |
| Archive autonome | Aucun Python. ~500 Mo d'espace (modèle + index). |
| Depuis les sources | Python 3.10+. ~500 Mo d'espace. |
| Client | Claude Desktop/Code, Codex, Gemini, Antigravity, LM Studio, Cursor, Windsurf ou VS Code (support MCP). |

## Licence

Apache 2.0. Voir [LICENSE](LICENSE).

## Validation de la recherche

Le contrat `cortex search --json`, le corpus FR/EN, les mesures de performance et la validation des deux SHA sont décrits dans [le guide de validation](docs/fr/validation-recherche.md).
