# Installation

**Francais** | [English](../en/setup.md)

[Retour au sommaire](index.md)

## Prerequis

| Outil | Version minimale |
|---|---|
| Python | 3.10+ |
| Client | Claude Desktop/Code, Codex ou Gemini avec support MCP |
| Espace disque | ~500 Mo (modele + index) |

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

# Validation sans ecriture : entree, executable Python et server.py
python setup_config.py --check --clients all
```

Chaque client lance son propre processus `server.py`, soit environ 150 Mo de
RAM par client actif. Les lectures simultanees sont sures. Toutes les ecritures
sur l'index sont serialisees entre processus par le write lock Cortex deja
teste en conditions multi-processus (voir [Securite](security.md)).

## Validation post-installation

```powershell
python setup_config.py --check
```

Verifie : Python accessible, packages importables, configuration utilisateur
valide, emplacement d'index unique ou migration requise, entree `cortex`
presente pour chaque client selectionne, executable Python et `server.py`
accessibles. La sortie est qualifiee par client avec `[OK]`,
`[SKIP not installed]` ou `[FAIL]`.

Pour un diagnostic support complet, lancer ensuite le
[doctor](user-guide.md#cortex-doctor).
