# Cortex - RAG MCP pour base de connaissance

**Francais** | [English](README.md)

Cortex est un serveur MCP (Model Context Protocol) qui expose une recherche
semantique sur une base de connaissance locale. Il permet a Claude, Codex et
Gemini de retrouver le bon passage dans vos documents sans consommer inutilement
leur fenetre de contexte. La recherche est semantique (par sens, pas par
mot-cle), en francais comme en anglais. Cortex traite et indexe la base en local
sans envoyer son contenu ; le client MCP peut toutefois transmettre au modele
les passages qu'il a demandes, selon sa propre politique.
Le writer Confluence optionnel ne telecharge que les espaces explicitement
autorises ; le Markdown genere, l'index vectoriel et l'index lexical restent
locaux.

Depuis 2026.0906.01, Companion propose un accueil guide, un historique et l'ajout Confluence par un seul lien de page ou d'espace. La connexion et le choix du nombre de pages restent dans le parcours ; la collecte reussie est suivie de l'indexation. Utiliser l'installeur combine pour garder Cortex et Companion compatibles.

## Perimetre mesure sans enumerer l'espace (2026.0907.00)

L'ajout d'une source Confluence mesure les perimetres page, sous-arbre et espace
entier avec un comptage indexe chacun, au lieu de parcourir l'espace page par
page. Sur un espace de 5916 pages, cette mesure prenait 3 min 19 s, au-dela du
delai de tout appelant graphique, et Companion n'affichait rien du tout. Elle
repond desormais en une seconde environ, a contrat inchange.

Deux nombres de l'espace entier varient de un : la page resolue n'est plus
ajoutee au total de l'espace, et un espace sans page visible affiche zero au lieu
de un. Un deploiement dont la recherche ne renvoie pas de total ne peut pas
mesurer un perimetre et le signale comme un echec permanent, non comme un echec
a reessayer. Voir [les contrats](docs/fr/writer-confluence.md).

Le Companion apparie 2026.0907.00 retablit le contraste de la fenetre de
perimetre, dont les options s'affichaient dans la couleur de texte du systeme, et
cesse de presenter un delai depasse comme une panne de connexion ou de conseiller
une augmentation qui revient en arriere sans le dire.

## Gestion des sources dans Companion (2026.0906.02)

Ce parcours inclut recherche, arborescence distante, apercu des changements,
etats verifies, enregistrement avec mise a jour, annulation du dernier retrait
et actions de recuperation. Voir [les contrats](docs/fr/writer-confluence.md).


La version appariee 2026.0906.02 propose **Mes sources**, un editeur pre-rempli,
le retrait confirme de pages ou d'espaces et l'ouverture des originaux dans
Confluence. Les retraits modifient uniquement le suivi Cortex et prennent effet
dans la recherche apres une collecte et une indexation reussies.

Le retrait de la derniere source ecrit explicitement `spaces = []` dans une
configuration schema v2 ou v3. Cette liste volontairement vide autorise une
publication vide avec les tombstones des anciens documents. Une cle `spaces`
absente reste une configuration incomplete et la collecte est refusee.
Les validations de connexion, de credentials et les protections de publication
restent applicables. Cette capacite requiert Cortex et Companion 2026.0906.02 ou ulterieurs ;
elle n'est pas disponible dans la release installee 2026.0906.01.


## Installation

### Windows, sans Python (recommande)

La voie la plus simple : un seul installeur pour Cortex, Cortex Companion, le
convertisseur Confluence console et les modeles hors ligne. Aucun Python ni
runtime .NET n'est a installer separement.

1. Telecharger `Cortex-Setup.exe` et `SHA256SUMS` depuis la
   [derniere release](https://github.com/VBlackJack/Cortex/releases/latest).
2. Avant de lancer l'installeur non signe, calculer son empreinte avec
   `Get-FileHash .\Cortex-Setup.exe -Algorithm SHA256` dans PowerShell et
   verifier qu'elle correspond exactement a la ligne `Cortex-Setup.exe` de
   `SHA256SUMS`.
3. Double-cliquer seulement apres cette verification. Si SmartScreen affiche
   encore un avertissement, choisir `Informations complementaires`, puis
   `Executer quand meme`.
4. Choisir le dossier de vos documents, laisser `Tout indexer dans ce dossier`
   et terminer. Cortex Companion s'ouvre a la fin de l'installation.
5. Dans Companion, ouvrir `Réglages` pour verifier le dossier de la base de
   connaissances. L'executable Cortex installe avec Companion est detecte
   automatiquement.
6. Deposer vos documents dans ce dossier, ouvrir `Base locale`, puis choisir
   `Synchroniser les documents locaux`.
7. Redemarrer votre application IA : Cortex y apparait comme serveur MCP.

Companion permet ensuite de synchroniser, planifier, diagnostiquer et configurer
Cortex sans terminal. Details, mode silencieux et reinstallation :
[Installation Windows](docs/fr/installation-windows.md).

### Archives autonomes (Windows x64, macOS Apple Silicon, Linux x64)

Chaque release fournit aussi une archive ZIP par plateforme. Elle contient le
binaire unique `cortex` ou `cortex.exe` (serveur MCP + CLI, sans Python) et les
licences de toutes les dependances embarquees. Voir
[Distribution autonome](docs/fr/distribution.md).

### Depuis PyPI (Python, avance)

```powershell
py -m pip install --upgrade cortex-local-rag
cortex setup
```

Cette voie installe la CLI et le serveur MCP, mais pas Cortex Companion. Le
modele est telecharge lors de sa premiere utilisation si son cache est vide.

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

Le modele d'embedding est le multilingue ONNX
`paraphrase-multilingual-MiniLM-L12-v2`. L'installeur Windows l'embarque ; une
installation depuis les sources ou un binaire autonome le telecharge si son
cache local est vide.

## Deux modes d'indexation

- **Tout le dossier** (defaut) : tout ce que vous placez dans le dossier
  choisi, a la racine ou dans n'importe quel sous-dossier, devient cherchable.
  Rien a configurer.
- **Sections** (avance) : limite l'indexation a des sous-dossiers nommes que
  vous pouvez chercher separement (defauts `knowledge`, `projects`, `notes`).

Ces modes gouvernent le dossier de documents choisi par l'utilisateur. Les
documents d'ingestion generes sont indexes separement depuis la generation
publiee courante avec `source_kind=doc` et la section `sources`.

Details : [Configuration](docs/fr/configuration.md).

## Commande `cortex`

Le paquet installe expose une commande unique :

| Sous-commande | Role |
|---|---|
| `cortex setup` | Config + index + enregistrement des clients en une fois (`--kb-path`, `--yes`, `--no-index`, `--reset`). |
| `cortex serve` | Lance le serveur MCP (utilise par les clients). |
| `cortex sync` | Synchronisation incrementale de l'index. |
| `cortex search` | Recherche dans l'index depuis la console (aide au debogage). |
| `cortex ingestion` | Affiche la sante d'une source et indique si un rattrapage est du. |
| `cortex confluence` | Stocke le PAT interactivement ou lance le writer sur liste blanche. |
| `cortex config` | Lit ou modifie la configuration via un contrat JSON atomique, notamment pour Companion. |
| `cortex bundle` | Decrit ou verifie une archive portable chiffree. |
| `cortex doctor` | Diagnostic de l'installation (lecture seule). |
| `cortex register` / `cortex unregister` | Ajoute ou retire Cortex des clients MCP. |
| `cortex init` | Cree la seule configuration par utilisateur. |
| `cortex check` | Verifie l'installation. |

`cortex --help` decrit chaque sous-commande et `cortex <commande> --help` decrit
ses options. Une installation sans invite se scripte ainsi :

```powershell
cortex setup --yes --kb-path "D:\Documents\Connaissances"
```

## Outils MCP exposes

| Outil | Description |
|---|---|
| `cortex_search` | Recherche hybride. Parametres : `query`, `section`, `top_k` (1-10), filtres source/auteur et plages de dates de creation/mise a jour. |
| `cortex_sync` | Declenche un sync incremental du dossier choisi et, sur un sync complet, de la generation documentaire courante. |
| `cortex_list_sections` | Liste les sections incluses et les dossiers "out of policy". |
| `cortex_freshness` | Resume en lecture seule de la fraicheur du vault et de l'ingestion. Parametres : `section` (optionnel), `include_entries` (`false` par defaut). |

## Documentation

- [Sommaire](docs/fr/index.md)
- [Installation Windows](docs/fr/installation-windows.md) : installateur unique
  Cortex + Companion + convertisseur Confluence + modeles, choix du corpus,
  mode silencieux, reinstallation.
- [Distribution autonome](docs/fr/distribution.md) : archives par plateforme et builds reproductibles.
- [Installation depuis les sources](docs/fr/setup.md) : prerequis, clients MCP.
- [Guide d'utilisation](docs/fr/user-guide.md) : sync, recherche, outils,
  doctor, logs.
- [FAQ](docs/fr/faq.md) : installation, donnees locales, sync et diagnostic.
- [Notes de version](docs/fr/notes-de-version.md) : changements visibles par
  version et avis sur l'historique publie.
- [Journal technique](CHANGELOG.md) : detail complet des changements par version.
- [Configuration](docs/fr/configuration.md) : `config.toml`, modes d'indexation,
  sections, data home, migration.
- [Planification de l'ingestion](docs/fr/ingestion-scheduling.md) : sante des
  sources, rattrapage, reprises et Planificateur de taches.
- [Migration metadata v2](docs/fr/metadata-v2-migration.md) : metadonnees de
  recherche structurees, sauvegarde, migration et restauration.
- [Writer Confluence](docs/fr/writer-confluence.md) : ingestion REST sur liste
  blanche, Windows Credential Manager, conversion et generations atomiques.
- [Installation reproductible](docs/fr/install-reproductible.md) :
  `requirements.lock`, `--require-hashes`, regeneration du verrou.
- [Specification publique](docs/fr/spec.md) : surface MCP, contrats de l'index,
  donnees, distribution et limites.
- [Architecture](docs/fr/architecture.md) : bout en bout et choix techniques.
- [Securite](docs/fr/security.md) : runtime local, telemetrie off,
  single-writer.

## Prerequis

| Voie | Prerequis |
|---|---|
| Installeur Windows | Aucun Python ni runtime .NET separe. ~500 Mo d'espace minimum (applications, modele + index). |
| Archive autonome | Aucun Python. ~500 Mo d'espace (modele + index). |
| Depuis les sources | Python 3.10+. ~500 Mo d'espace. |
| Client | Claude Desktop/Code, Codex, Gemini, Antigravity, LM Studio, Cursor, Windsurf ou VS Code (support MCP). |

## Licence

Apache 2.0. Voir [LICENSE](LICENSE).

## Validation de la recherche

Le contrat `cortex search --json`, le corpus FR/EN, les mesures de performance et la validation des deux SHA sont décrits dans [le guide de validation](docs/fr/validation-recherche.md).
