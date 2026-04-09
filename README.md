# Cortex — RAG MCP pour base de connaissance Confluence

Cortex est un serveur MCP (Model Context Protocol) qui expose une recherche sémantique sur une base de connaissance exportée depuis Confluence. Il permet à Claude d'interroger la documentation interne sans consommer de fenêtre de contexte.

---

## Fonctionnement en bref

```
G:\_DATA\               ← Export Confluence (fichiers .md)
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
G:\_dev\Cortex\install.bat
```

Le script fait automatiquement :
1. Détecte Python 3 dans le PATH
2. Installe / met à jour les dépendances pip
3. Injecte l'entrée `cortex` dans `claude_desktop_config.json`
4. Propose de vider la base vectorielle (utile si le modèle change)
5. Valide l'installation

Après l'installation : **redémarrer l'application Claude desktop**.

### Prérequis

| Outil | Version minimale |
|---|---|
| Python | 3.9+ |
| Claude desktop app | toute version supportant les MCP |
| Espace disque | ~500 Mo (modèle + index) |

---

## Structure du projet

```
G:\_dev\Cortex\
├── config.py          ← Paramètres centraux (chemins, modèle, sections)
├── chunker.py         ← Découpe les .md en chunks (headers + taille fixe)
├── indexer.py         ← Sync incrémentale vers ChromaDB
├── server.py          ← Serveur MCP FastMCP (cortex_search, cortex_sync)
├── sync.bat           ← Lance le sync section par section
├── install.bat        ← Installation / réinstallation en un clic
├── setup_config.py    ← Helper : patch claude_desktop_config.json + validation
├── requirements.txt   ← Dépendances pip
├── conftest.py        ← Bootstrap pytest (sys.path)
├── tests\             ← Tests unitaires (chunker) + intégration (search)
└── chroma_db\         ← Base vectorielle persistante (générée, ne pas commiter)
```

---

## Configuration

Tout est centralisé dans `config.py` :

```python
KB_PATH             = r"G:\_DATA"               # Racine de la base de connaissance
CHROMA_PATH         = r"G:\_dev\Cortex\chroma_db"
COLLECTION_NAME     = "cortex"
EMBEDDING_MODEL     = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_CHARS         = 400   # taille max d'un chunk en caractères (~110 tokens FR)
CHUNK_OVERLAP_CHARS = 60    # chevauchement entre chunks
EXCLUDE_DIRS        = {"_attachments", "zzz_Corbeille"}
EXCLUDE_FILES       = {"00_INDEX.md"}
KNOWN_SECTIONS      = ["Adsec", "Ansible", "Processes", "Products",
                       "Projects", "Technical Services", "Zabbix"]
```

> `CHUNK_CHARS` est dimensionné pour rester sous la limite de 128 tokens du modèle MiniLM.
> Voir « Pourquoi 400 caractères par chunk ? » dans les choix techniques.

### Ajouter une nouvelle section Confluence

1. Exporter la section depuis Confluence vers `G:\_DATA\<NomSection>\`
2. Ajouter `"NomSection"` à `KNOWN_SECTIONS` dans `config.py`
3. Ajouter la ligne correspondante dans `sync.bat`
4. Lancer `sync.bat` (ou `cortex_sync` depuis Claude)

---

## Indexation

### Sync complète (toutes les sections)

```bat
G:\_dev\Cortex\sync.bat
```

Le sync est **incrémental** : seuls les fichiers nouveaux ou modifiés (détectés par hash MD5) sont retraités. Les fichiers supprimés sont retirés de l'index.

### Sync d'une seule section

```powershell
C:\Python313\python.exe G:\_dev\Cortex\indexer.py Zabbix
```

### Depuis Claude (via MCP)

```
cortex_sync                    # toutes les sections
cortex_sync section="Zabbix"  # une seule section
```

### Repartir de zéro (modèle changé, index corrompu)

1. Quitter l'application Claude desktop
2. Supprimer `G:\_dev\Cortex\chroma_db\`
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
C:\Python313\python.exe G:\_dev\Cortex\indexer.py --search "alertes zabbix"

# Recherche dans une section (la section est positionnelle)
C:\Python313\python.exe G:\_dev\Cortex\indexer.py Ansible --search "deploy ansible"

# Nombre de résultats
C:\Python313\python.exe G:\_dev\Cortex\indexer.py --search "OSCARE" --top-k 10
```

---

## Outils MCP exposés à Claude

| Outil | Description |
|---|---|
| `cortex_search` | Recherche sémantique. Paramètres : `query`, `section` (optionnel), `top_k` (1-10) |
| `cortex_sync` | Déclenche un sync incrémental. Paramètre : `section` (optionnel) |

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

Le `path` stocké dans chaque chunk est relatif à `KB_PATH` (ex. `Zabbix\Zabbix - Architecture.md`). Cela rend l'index portable d'une machine à l'autre tant que l'arborescence sous `KB_PATH` est identique, et c'est aussi la clé utilisée pour le diff incrémental dans `sync()`.

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
C:\Python313\python.exe -m pip install -r G:\_dev\Cortex\requirements.txt
```

---

## Tests

```powershell
C:\Python313\python.exe -m pytest tests/ -v
```

Les tests unitaires (`tests/test_chunker.py`) tournent toujours. Les tests d'intégration (`tests/test_search.py`) sont automatiquement skippés si `chroma_db/` n'existe pas encore.

---

## Validation post-installation

```powershell
C:\Python313\python.exe G:\_dev\Cortex\setup_config.py --check
```

Vérifie : Python accessible · packages importables · entrée `cortex` présente dans `claude_desktop_config.json` avec des chemins valides.
