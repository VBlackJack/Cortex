# Installation

**Français** | [English](../en/setup.md)

[Retour au sommaire](index.md)

## Prérequis

| Outil | Version minimale |
|---|---|
| Runtime | Binaire Cortex autonome, ou Python 3.10+ |
| Client | Claude Desktop/Code, Codex ou Gemini avec support MCP |
| Espace disque | ~500 Mo (modèle + index) |

Pour un poste cible sans Python, utiliser un binaire autonome publié et voir la
[distribution autonome](distribution.md). Les chemins `install.bat` depuis le
clone et pip ci-dessous restent les options de développement et d'installation
depuis les sources.

## Installation en un clic

```bat
:: Depuis le dossier ou vous avez clone Cortex
install.bat
```

Le script est portable : il fonctionne quel que soit l'emplacement du clone
(`%~dp0` interne). Il enchaîne automatiquement :

1. Détection de Python 3 dans le PATH.
2. Initialisation de `%APPDATA%\Cortex\config.toml` sans écraser une
   configuration existante.
3. Installation ou mise à jour des dépendances pip.
4. Proposition d'enregistrer Cortex dans les clients MCP détectés.
5. Proposition de vider la base vectorielle (utile si le modèle change).
6. Validation de l'installation.

Après l'installation : redémarrer les clients enregistrés.

## Installation comme outil utilisateur

Pour installer Cortex comme paquet, sans dépendre du dossier du clone :

```powershell
python -m pip install -e .
cortex doctor
```

Les scripts `.bat` restent pleinement pris en charge et `install.bat` ne
requiert pas que le paquet Cortex soit installé. Pour une installation
verrouillée par hash (chaînes identiques à l'octet près), voir
[Installation reproductible](install-reproductible.md).

### Setup en une commande

Une fois le paquet installé, `cortex setup` enchaîne les trois étapes en un seul
appel : initialisation de la config, construction de l'index, puis enregistrement
des clients MCP.

```powershell
# Config + index + enregistrement de tous les clients detectes
cortex setup

# Non-interactif (aucune question ; exige CORTEX_KB_PATH pour creer la config)
cortex setup --yes

# Sauter la construction de l'index (utile sur poste a RAM contrainte)
cortex setup --no-index

# Reinitialiser explicitement config + index genere avant le setup
cortex setup --reset --yes

# Cibler des clients precis
cortex setup --clients claude-desktop,codex
```

`--clients` accepte `all` (défaut), `none`, ou une liste. La construction de
l'index se fait en un seul process (pic RAM supérieur à `sync.bat` section par
section) ; `--no-index` permet de lancer `sync.bat` séparément ensuite. Un échec
d'enregistrement client est signalé en avertissement sans interrompre le reste.

### Sources d'ingestion optionnelles

`cortex setup` configure le dossier documentaire choisi et les clients MCP. Il
ne crée pas de liste blanche Confluence, ne stocke pas de PAT et n'enregistre
pas de tâche dans le Planificateur de tâches Windows. Sous Windows, Companion
guide la création de la liste blanche depuis `Mes sources`. Ces surfaces
détenues par l'opérateur se configurent séparément :

- [Planification de l'ingestion](ingestion-scheduling.md) pour la cadence, les
  reprises, la santé et la racine de données d'ingestion.
- [Writer Confluence](writer-confluence.md) pour la liste blanche d'espaces,
  l'entrée Credential Manager et la console de conversion.

Quand cette commande tourne depuis l'exécutable autonome, elle enregistre cet
exécutable avec `serve` comme argument MCP. Depuis une installation pip ou les
sources, elle conserve l'entrée Python avec `server.py`.

L'installeur transmet `CORTEX_INDEX_MODE=whole` lors de la création d'une
nouvelle configuration. Le mode avancé utilise `CORTEX_INDEX_MODE=sections` et
`CORTEX_INDEX_SECTIONS=knowledge,projects,notes` ; Cortex crée alors ces
sous-dossiers. Ces variables d'onboarding ne remplacent jamais un choix déjà
persisté dans `config.toml`.

## Connecter Claude, Codex et Gemini

`setup_config.py` détecte les clients installés, affiche un récapitulatif puis
enregistre le serveur MCP `cortex`. Une configuration JSON ou TOML invalide
fait échouer l'opération avant toute écriture. Chaque fichier modifié reçoit
une sauvegarde horodatée et est remplacé atomiquement ; les autres réglages et
serveurs MCP sont conservés.

| Client | Configuration utilisateur | Entrée Cortex |
|---|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` | `mcpServers.cortex` |
| Claude Code | Gérée par `claude mcp add --scope user` | jamais écrite directement par Cortex |
| Codex CLI et extension IDE | `~/.codex/config.toml` | `[mcp_servers.cortex]` |
| Gemini CLI et Gemini Code Assist (mode agent VS Code) | `~/.gemini/settings.json` | `mcpServers.cortex` |
| Antigravity | `~/.gemini/config/mcp_config.json` | `mcpServers.cortex` |
| LM Studio | `~/.lmstudio/mcp.json` | `mcpServers.cortex` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json` | `mcpServers.cortex` |
| Windsurf | `%USERPROFILE%\.codeium\windsurf\mcp_config.json` | `mcpServers.cortex` |
| VS Code | `%APPDATA%\Code\User\mcp.json` | `servers.cortex` (avec `type: stdio`) |

L'enregistrement se fait au scope user pour les neuf clients. Antigravity,
LM Studio, Cursor et Windsurf utilisent la même clé `mcpServers` que Claude ;
VS Code utilise la clé `servers` avec un champ `type: stdio` (format MCP natif
de VS Code). Antigravity est détecté par son répertoire de profil actif
(`~/.gemini/antigravity`) : une installation Gemini CLI seule n'est jamais
enregistrée comme Antigravity.

Ces emplacements et formats suivent les documentations officielles de
[Claude Code](https://docs.anthropic.com/en/docs/claude-code/mcp),
[Codex](https://developers.openai.com/codex/mcp/),
[Gemini CLI](https://google-gemini.github.io/gemini-cli/docs/tools/mcp-server.html)
et [Gemini Code Assist](https://docs.cloud.google.com/gemini/docs/codeassist/use-agentic-chat-pair-programmer).

```powershell
# Tous les clients detectes (comportement par defaut)
python setup_config.py

# Toutes les cibles connues ; les clients absents sont signales SKIP
python setup_config.py --clients all

# Selection explicite
python setup_config.py --clients claude-desktop,codex,gemini

# Validation sans ecriture : entree, commande serveur et arguments
python setup_config.py --check --clients all

# Non-interactif (aucune question) : enregistre les clients detectes
python setup_config.py --yes --clients all
```

Le mode `--yes` ne pose aucune question : il n'invite jamais à saisir un chemin
(`--init --yes` exige alors `CORTEX_KB_PATH`) et ne déplace jamais un index
existant (la migration reste explicite via `--migrate-data`).

Chaque client lance son propre processus serveur : `cortex serve` pour une
installation autonome, ou `python server.py` pour une installation depuis les
sources ou pip. Les lectures simultanées sont sûres. Toutes les écritures sur
l'index sont sérialisées entre processus par le write lock Cortex déjà testé en
conditions multi-processus (voir [Sécurité](security.md)).

## Validation post-installation

```powershell
python setup_config.py --check
```

Vérifie : dépendances runtime, configuration utilisateur, emplacement d'index
unique ou migration requise, présence de l'entrée `cortex` pour chaque client
sélectionné, commande serveur et arguments enregistrés. La sortie est qualifiée
par client avec `[OK]`, `[SKIP not installed]` ou `[FAIL]`.

Pour un diagnostic support complet, lancer ensuite le
[doctor](user-guide.md#cortex-doctor).
