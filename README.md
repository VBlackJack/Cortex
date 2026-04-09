# Cortex — RAG MCP pour base de connaissance Confluence

Cortex est un serveur MCP (Model Context Protocol) qui expose une recherche sémantique sur une base de connaissance exportée depuis Confluence. Il permet à Claude d'interroger la documentation interne sans consommer de fenêtre de contexte.

---

## Fonctionnement en bref

```
%CORTEX_KB_PATH%        ← Export Confluence (fichiers .md)
      │
      ▼
  indexer.py            ← Découpe, hash, vectorise
      │
      ▼
  chroma_db\            ← Base vectorielle locale (ChromaDB)
      │
      ▼
  server.py             ← Serveur MCP (FastMCP)
      │
      ▼
  Claude desktop app    ← cortex_search / cortex_sync
```

La recherche est **sémantique** (par sens, pas par mot-clé) grâce au modèle ONNX multilingue `paraphrase-multilingual-MiniLM-L12-v2`. Les requêtes en **français et en anglais** fonctionnent.

---

## Installation / Réinstallation

```bat
:: Depuis le dossier où vous avez cloné Cortex
install.bat
```

Le script est **portable** : il fonctionne quel que soit l'emplacement où vous avez cloné Cortex (`%~dp0` interne). Il fait automatiquement :

1. Détecte Python 3 dans le PATH
2. Vérifie / configure `CORTEX_KB_PATH` (chemin vers votre base de connaissance markdown). S'il n'est pas défini, le script demande le chemin et le persiste via `setx`.
3. Installe / met à jour les dépendances pip
4. Injecte l'entrée `cortex` dans `claude_desktop_config.json`
5. Propose de vider la base vectorielle (utile si le modèle change)
6. Valide l'installation

Après l'installation : **redémarrer l'application Claude desktop** *et* ouvrir un nouveau terminal (pour que la variable d'environnement `CORTEX_KB_PATH` soit visible).

### Prérequis

| Outil | Version minimale |
|---|---|
| Python | 3.9+ |
| Claude desktop app | toute version supportant les MCP |
| Espace disque | ~500 Mo (modèle + index) |

---

## Structure du projet

```
<install_dir>\         ← Peu importe où vous clonez Cortex
├── config.py          ← Paramètres centraux (chemins, modèle, sections)
├── chunker.py         ← Découpe les .md en chunks (headers + taille fixe)
├── indexer.py         ← Sync incrémentale vers ChromaDB
├── server.py          ← Serveur MCP FastMCP (cortex_search, cortex_sync)
├── sync.bat           ← Lance le sync section par section (portable, %~dp0)
├── install.bat        ← Installation / réinstallation en un clic (portable)
├── setup_config.py    ← Helper : patch claude_desktop_config.json + validation
├── requirements.txt   ← Dépendances pip
├── conftest.py        ← Bootstrap pytest (sys.path)
├── tests\             ← Tests unitaires (chunker) + intégration (search)
└── chroma_db\         ← Base vectorielle persistante (générée, ne pas commiter)
```

---

## Configuration

### Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `CORTEX_KB_PATH` | **(requis pour indexer)** racine absolue de votre base markdown | — |
| `CORTEX_CHROMA_PATH` | (optionnel) emplacement de la base vectorielle | `<install_dir>\chroma_db` |

`CORTEX_KB_PATH` est défini automatiquement par `install.bat` au premier lancement (via `setx`). Pour le changer manuellement :

```bat
setx CORTEX_KB_PATH "D:\nouveau\chemin\KB"
:: puis ouvrir un nouveau terminal
```

La recherche (`cortex_search`) continue de fonctionner même si `CORTEX_KB_PATH` n'est pas défini — seul l'indexer (`cortex_sync`) en a besoin.

### Paramètres dans `config.py`

Le reste est centralisé dans `config.py` :

```python
COLLECTION_NAME     = "cortex"
EMBEDDING_MODEL     = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_CHARS         = 400   # taille max d'un chunk en caractères (~110 tokens FR)
CHUNK_OVERLAP_CHARS = 60    # chevauchement entre chunks
EXCLUDE_DIRS        = {"_attachments", "zzz_Corbeille"}
EXCLUDE_FILES       = {"00_INDEX.md"}
```

> `CHUNK_CHARS` est dimensionné pour rester sous la limite de 128 tokens du modèle MiniLM.
> Voir « Pourquoi 400 caractères par chunk ? » dans les choix techniques.

### Sections

Les sections sont **auto-découvertes** : tout sous-dossier de premier niveau de `CORTEX_KB_PATH` qui n'est pas dans `EXCLUDE_DIRS` devient une section. Aucune liste à maintenir dans le code.

```powershell
:: Lister les sections détectées
python indexer.py --list-sections
```

Depuis Claude, l'outil MCP `cortex_list_sections` retourne la même chose.

### Ajouter une nouvelle section Confluence

1. Exporter la section depuis Confluence vers `%CORTEX_KB_PATH%\<NomSection>\`
2. Lancer `sync.bat` (ou `cortex_sync` depuis Claude)

C'est tout — pas besoin de modifier le code, la nouvelle section est détectée automatiquement.

---

## Indexation

### Sync complète (toutes les sections)

```bat
:: Depuis le dossier d'install
sync.bat
```

Le sync est **incrémental** : seuls les fichiers nouveaux ou modifiés (détectés par hash MD5) sont retraités. Les fichiers supprimés sont retirés de l'index.

### Sync d'une seule section

```powershell
python indexer.py Zabbix
```

### Depuis Claude (via MCP)

```
cortex_sync                    # toutes les sections
cortex_sync section="Zabbix"  # une seule section
```

### Repartir de zéro (modèle changé, index corrompu)

1. Quitter l'application Claude desktop
2. Supprimer le dossier `chroma_db\` (à côté du code, ou à l'emplacement de `CORTEX_CHROMA_PATH` si défini)
3. Relancer Claude desktop
4. Lancer `sync.bat`

---

## Recherche

### Depuis Claude

Claude appelle automatiquement `cortex_search` quand une question porte sur la documentation interne. Il est aussi possible de le demander explicitement :

> *« Cherche dans Cortex comment configurer les alertes Zabbix »*

### En ligne de commande (debug)

```powershell
# Recherche globale
python indexer.py --search "alertes zabbix"

# Recherche dans une section (la section est positionnelle)
python indexer.py Ansible --search "deploy ansible"

# Nombre de résultats
python indexer.py --search "OSCARE" --top-k 10
```

---

## Outils MCP exposés à Claude

| Outil | Description |
|---|---|
| `cortex_search` | Recherche sémantique. Paramètres : `query`, `section` (optionnel), `top_k` (1-10) |
| `cortex_sync` | Déclenche un sync incrémental. Paramètre : `section` (optionnel) |
| `cortex_list_sections` | Liste les sections détectées sous `CORTEX_KB_PATH` |

---

## Choix techniques

### Pourquoi ONNX / fastembed ?

PyTorch + sentence-transformers détectait le GPU pendant l'initialisation et causait un **BSOD (dxgkrnl.sys)**. Le modèle ONNX via `fastembed` tourne entièrement sur CPU, utilise ~150 Mo de RAM, et ne touche pas au GPU.

### Pourquoi un sync section par section ?

Chaque section est un processus Python indépendant dans `sync.bat`. Cela limite la RAM à ~300 Mo par processus (contre un pic unique si tout est en mémoire) et permet de reprendre facilement en cas d'erreur.

### Pourquoi l'index incrémental est scopé par section ?

Sans scoping, un sync de la section `Zabbix` voyait les fichiers d'`Ansible` comme « supprimés » et les effaçait. Le hash comparison et les suppressions sont maintenant limités à la section en cours.

### Pourquoi 400 caractères par chunk ?

Le modèle `paraphrase-multilingual-MiniLM-L12-v2` tronque toute entrée à **128 tokens maximum**. Tout ce qui dépasse n'est jamais vu par l'embedding. En français, 1 token ≈ 3,5 caractères, donc 400 caractères ≈ 110-115 tokens — on reste sous le plafond avec une marge de sécurité, et on évite que la queue de chaque chunk soit silencieusement ignorée. Les chunks plus longs (~2000 chars utilisés au début du projet) faisaient perdre 70 à 80 % du contenu indexé à l'embedding.

### Pourquoi les chemins en metadata sont relatifs ?

Le `path` stocké dans chaque chunk est relatif à `CORTEX_KB_PATH` (ex. `Zabbix\Zabbix - Architecture.md`). Cela rend l'index portable d'une machine à l'autre tant que l'arborescence sous le KB est identique, et c'est aussi la clé utilisée pour le diff incrémental dans `sync()`.

### Pourquoi tout est portable ?

Aucun chemin absolu n'est codé en dur dans le projet :

- `config.py` dérive `CHROMA_PATH` de `Path(__file__).parent` → la base vectorielle vit toujours à côté du code.
- `install.bat` et `sync.bat` utilisent `%~dp0` → ils trouvent eux-mêmes leur dossier d'exécution.
- `setup_config.py` détecte sa propre localisation pour patcher `claude_desktop_config.json`.
- `CORTEX_KB_PATH` est lu depuis l'environnement → un seul `setx` à faire au premier install, jamais à modifier dans le code.

Conséquence : tu peux cloner Cortex dans n'importe quel dossier sur n'importe quelle machine, lancer `install.bat`, et c'est opérationnel.

---

## Dépendances

```
mcp[cli]       ← Framework MCP (FastMCP)
chromadb       ← Base vectorielle locale
fastembed      ← Embeddings ONNX sans PyTorch
pydantic       ← Validation des paramètres MCP
pytest         ← Tests unitaires (dev only)
```

Installer / mettre à jour :
```powershell
python -m pip install -r requirements.txt
```

---

## Tests

```powershell
python -m pytest tests/ -v
```

Les tests unitaires (`tests/test_chunker.py`) tournent toujours. Les tests d'intégration (`tests/test_search.py`) sont automatiquement skippés si `chroma_db/` n'existe pas encore.

---

## Validation post-installation

```powershell
python setup_config.py --check
```

Vérifie : Python accessible · packages importables · entrée `cortex` présente dans `claude_desktop_config.json` avec des chemins valides.
