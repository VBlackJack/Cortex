# Installation

**Francais** | [English](../en/setup.md)

[Retour au sommaire](index.md)

## Prerequis

| Outil | Version minimale |
|---|---|
| Runtime | Binaire Cortex autonome, ou Python 3.10+ |
| Client | Claude Desktop/Code, Codex ou Gemini avec support MCP |
| Espace disque | ~500 Mo (modele + index) |

Pour un poste cible sans Python, utiliser un binaire autonome publie et voir la
[distribution autonome](distribution.md). Les chemins `install.bat` depuis le
clone et pip ci-dessous restent les options de developpement et d'installation
depuis les sources.

## Installation en un clic

```bat
:: Depuis le dossier ou vous avez clone Cortex
install.bat
```

Le script est portable : il fonctionne quel que soit l'emplacement du clone
(`%~dp0` interne). Il enchaine automatiquement :

1. Detection de Python 3 dans le PATH.
2. Initialisation de `%APPDATA%\Cortex\config.toml` sans ecraser une
   configuration existante.
3. Installation ou mise a jour des dependances pip.
4. Proposition d'enregistrer Cortex dans les clients MCP detectes.
5. Proposition de vider la base vectorielle (utile si le modele change).
6. Validation de l'installation.

Apres l'installation : redemarrer les clients enregistres.

## Installation comme outil utilisateur

Pour installer Cortex comme paquet, sans dependre du dossier du clone :

```powershell
python -m pip install -e .
cortex doctor
```

Les scripts `.bat` restent pleinement pris en charge et `install.bat` ne
requiert pas que le paquet Cortex soit installe. Pour une installation
verrouillee par hash (chaines identiques a l'octet pres), voir
[Installation reproductible](install-reproductible.md).

### Setup en une commande

Une fois le paquet installe, `cortex setup` enchaine les trois etapes en un seul
appel : initialisation de la config, construction de l'index, puis enregistrement
des clients MCP.

```powershell
# Config + index + enregistrement de tous les clients detectes
cortex setup

# Non-interactif (aucune question ; exige CORTEX_KB_PATH pour creer la config)
cortex setup --yes

# Sauter la construction de l'index (utile sur poste a RAM contrainte)
cortex setup --no-index

# Cibler des clients precis
cortex setup --clients claude-desktop,codex
```

`--clients` accepte `all` (defaut), `none`, ou une liste. La construction de
l'index se fait en un seul process (pic RAM superieur a `sync.bat` section par
section) ; `--no-index` permet de lancer `sync.bat` separement ensuite. Un echec
d'enregistrement client est signale en avertissement sans interrompre le reste.

Quand cette commande tourne depuis l'executable autonome, elle enregistre cet
executable avec `serve` comme argument MCP. Depuis une installation pip ou les
sources, elle conserve l'entree Python avec `server.py`.

## Connecter Claude, Codex et Gemini

`setup_config.py` detecte les clients installes, affiche un recapitulatif puis
enregistre le serveur MCP `cortex`. Une configuration JSON ou TOML invalide
fait echouer l'operation avant toute ecriture. Chaque fichier modifie recoit
une sauvegarde horodatee et est remplace atomiquement ; les autres reglages et
serveurs MCP sont conserves.

| Client | Configuration utilisateur | Entree Cortex |
|---|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` | `mcpServers.cortex` |
| Claude Code | Geree par `claude mcp add --scope user` | jamais ecrite directement par Cortex |
| Codex CLI et extension IDE | `~/.codex/config.toml` | `[mcp_servers.cortex]` |
| Gemini CLI et Gemini Code Assist (mode agent VS Code) | `~/.gemini/settings.json` | `mcpServers.cortex` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json` | `mcpServers.cortex` |
| Windsurf | `%USERPROFILE%\.codeium\windsurf\mcp_config.json` | `mcpServers.cortex` |
| VS Code | `%APPDATA%\Code\User\mcp.json` | `servers.cortex` (avec `type: stdio`) |

L'enregistrement se fait au scope user pour les sept clients. Cursor et Windsurf
utilisent la meme cle `mcpServers` que Claude ; VS Code utilise la cle `servers`
avec un champ `type: stdio` (format MCP natif de VS Code).

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

Le mode `--yes` ne pose aucune question : il n'invite jamais a saisir un chemin
(`--init --yes` exige alors `CORTEX_KB_PATH`) et ne deplace jamais un index
existant (la migration reste explicite via `--migrate-data`).

Chaque client lance son propre processus serveur : `cortex serve` pour une
installation autonome, ou `python server.py` pour une installation depuis les
sources ou pip. Les lectures simultanees sont sures. Toutes les ecritures sur
l'index sont serialisees entre processus par le write lock Cortex deja teste en
conditions multi-processus (voir [Securite](security.md)).

## Validation post-installation

```powershell
python setup_config.py --check
```

Verifie : dependances runtime, configuration utilisateur, emplacement d'index
unique ou migration requise, presence de l'entree `cortex` pour chaque client
selectionne, commande serveur et arguments enregistres. La sortie est qualifiee
par client avec `[OK]`, `[SKIP not installed]` ou `[FAIL]`.

Pour un diagnostic support complet, lancer ensuite le
[doctor](user-guide.md#cortex-doctor).
