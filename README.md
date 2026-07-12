# Cortex — RAG MCP pour base de connaissance Confluence

Cortex est un serveur MCP (Model Context Protocol) qui expose une recherche sémantique sur une base de connaissance exportée depuis Confluence. Il permet à Claude d'interroger la documentation interne sans consommer de fenêtre de contexte.

---

## Fonctionnement en bref

```
kb_path (TOML/env)      ← Export Confluence (fichiers .md)
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
  Claude desktop app    ← recherche / sync / sections / fraîcheur
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
2. Initialise `%APPDATA%\Cortex\config.toml` sans écraser une configuration existante.
3. Installe / met à jour les dépendances pip
4. Injecte l'entrée `cortex` dans `claude_desktop_config.json`
5. Propose de vider la base vectorielle (utile si le modèle change)
6. Valide l'installation

Après l'installation : **redémarrer l'application Claude desktop**.

### Prérequis

| Outil | Version minimale |
|---|---|
| Python | 3.10+ |
| Claude desktop app | toute version supportant les MCP |
| Espace disque | ~500 Mo (modèle + index) |

---

## Structure du projet

```
<install_dir>\         ← Peu importe où vous clonez Cortex
├── config.py          ← Contrats produit et configuration résolue
├── user_config.py     ← Chargement TOML strict et initialisation atomique
├── chunker.py         ← Découpe les .md en chunks (headers + taille fixe)
├── chunker_pdf.py     ← Découpe les .pdf en chunks (pdfplumber + taille fixe)
├── chunker_utils.py   ← Fonctions partagées (hash, split, paths)
├── indexer.py         ← Sync incrémentale vers ChromaDB
├── server.py          ← Serveur MCP FastMCP (4 outils Cortex)
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
| `CORTEX_KB_PATH` | Surcharge optionnelle de `kb_path` | aucune |
| `CORTEX_WRITE_LOCK_PATH` | Surcharge du chemin de verrou | à côté de l'installation |
| `CORTEX_WRITE_LOCK_TIMEOUT_SECONDS` | Surcharge du timeout de verrou | `30` |
| `CORTEX_MAX_MARKDOWN_FILE_SIZE_BYTES` | Surcharge de la limite Markdown | `1000000` |

La configuration utilisateur vit dans `%APPDATA%\Cortex\config.toml` avec
`schema_version = 1`. Elle ne contient jamais de secret. La précédence est
**variable d'environnement > fichier TOML > défaut produit**. Les variables
d'environnement historiques restent donc compatibles, mais `install.bat` ne
les crée plus sur une nouvelle installation.

```toml
schema_version = 1
kb_path = "D:\\Knowledge"
included_sections = ["knowledge", "operations", "projects", "sources", "_memory", "_drafts"]
excluded_dirs = [".datacron", "_archive", "_trash", "_attachments", "zzz_Corbeille", "_inbox", "_journal"]
exclude_files = ["00_INDEX.md"]
max_markdown_file_size_bytes = 1000000
max_pdf_size_bytes = 50000000
write_lock_path = "D:\\Apps\\Cortex\\chroma_db.write.lock"
write_lock_timeout_seconds = 30
```

Créer le fichier manuellement ou lancer :

```powershell
python setup_config.py --init
```

`kb_path` est requis pour `cortex_sync` et `cortex_freshness`, sans valeur par
défaut. La recherche continue de fonctionner sur l'index existant lorsqu'il
est absent.

### Paramètres dans `config.py`

Les contrats d'index restent centralisés dans `config.py` et ne sont pas
modifiables par utilisateur :

```python
COLLECTION_NAME = "cortex"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_POOLING = "mean"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
CHUNKING_CONTRACT_VERSION = "v1"
SEARCH_TOP_K_MIN = 1
SEARCH_TOP_K_MAX = 10
```

> `CHUNK_SIZE` est dimensionné pour rester sous la limite de 128 tokens du modèle MiniLM avec une marge de sécurité.
> Voir « Pourquoi 512 caractères par chunk ? » dans les choix techniques.

### Sections

Les sections indexables sont définies par `included_sections` dans
`config.toml`. Un dossier de premier niveau absent de l'allowlist et de la
denylist n'est jamais indexé automatiquement : `cortex_list_sections` le
signale comme « out of policy » jusqu'à une décision explicite. La validation
MCP est case-insensitive (`KNOWLEDGE` → `knowledge`).

Depuis Claude, l'outil MCP `cortex_list_sections` liste toutes les sections disponibles.

### Ajouter une nouvelle section Confluence

1. Exporter la section sous le dossier `kb_path` configuré.
2. Ajouter son nom à `included_sections` dans `config.toml`.
3. Lancer `sync.bat` (ou `cortex_sync` depuis Claude).

Sans cet opt-in, le dossier reste visible comme « out of policy » mais n'est
jamais envoyé au modèle d'embedding.

---

## Indexation

### Sync complète (toutes les sections)

```bat
:: Depuis le dossier d'install
sync.bat
```

Le sync est **incrémental** : seuls les fichiers nouveaux ou modifiés
(détectés par SHA-256 et version du contrat de chunking) sont retraités. Les
fichiers supprimés, vidés ou devenus exclus sont retirés de l'index.

### Sync d'une seule section

```powershell
python indexer.py operations
```

### Depuis Claude (via MCP)

```
cortex_sync                    # toutes les sections
cortex_sync section="operations"  # une seule section
```

### Repartir de zéro (modèle changé, index corrompu)

1. Quitter l'application Claude desktop
2. Supprimer le dossier `chroma_db\` (à côté du code)
3. Relancer Claude desktop
4. Lancer `sync.bat`

### Écriture concurrente (single-writer) - protocole manuel retiré

ChromaDB (backend SQLite) n'accepte qu'un seul écrivain à la fois. Deux
incidents de corruption de l'index (segfault, puis désync HNSW/métadonnées)
ont eu la même cause racine : deux écritures concurrentes sur la même DB
(typiquement `server.py` respawné par Claude Desktop pendant qu'un sync
tournait déjà). Le contournement manuel utilisé jusqu'ici - tuer
`server.py` et retirer temporairement l'entrée `cortex` de
`claude_desktop_config.json` avant tout sync - n'était pas fiable (Claude
Desktop réécrit cette entrée depuis son propre état interne, donc un
respawn pouvait survenir en plein sync malgré le retrait).

**Depuis le lot design "single-writer lock" (write_lock.py) : ce protocole
manuel n'est plus nécessaire pour la sécurité.** Chaque point d'écriture
Chroma (`indexer.sync()`, `sync_hash_aware.sync_section()`,
`scripts/b2_delete_missing.py`, `scripts/b2_rebuild_index.py`) acquiert
maintenant un verrou inter-processus exclusif (`filelock`, niveau OS,
auto-libéré si le process qui le détient meurt - crash, kill, respawn - peu
importe) avant de toucher la DB. Si un second écrivain tente d'écrire
pendant qu'un premier détient le verrou, il échoue proprement
(`CortexWriteLockedError`, timeout borné, jamais d'attente infinie) au lieu
d'écrire en concurrence. `cortex_sync` (l'outil MCP) renvoie un message
"locked, réessayer plus tard" dans ce cas plutôt qu'une erreur brute. La
lecture (`cortex_search`, `cortex_freshness`) n'est jamais bloquée - Chroma
autorise les lectures concurrentes, seule l'écriture est single-writer.

Preuve (voir `tests/test_write_lock.py`, 4 tests, processus réels et DB
isolée) : deux écrivains concurrents -> exactement un aboutit, l'autre
échoue proprement, intégrité DB préservée ; scénario respawn-pendant-sync
reproduit et bloqué ; lecture non bloquée pendant qu'un écrivain détient le
verrou ; écrivain tué brutalement (crash simulé) -> verrou libéré
automatiquement, pas de deadlock permanent. Configurable via
`CORTEX_WRITE_LOCK_PATH` et `CORTEX_WRITE_LOCK_TIMEOUT_SECONDS`
(`config.toml`, 30s par défaut).

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
python indexer.py knowledge --search "procédure de déploiement"

# Nombre de résultats
python indexer.py --search "OSCARE" --top-k 10
```

---

## Outils MCP exposés à Claude

| Outil | Description |
|---|---|
| `cortex_search` | Recherche sémantique. Paramètres : `query`, `section` (optionnel), `top_k` (1-10) |
| `cortex_sync` | Déclenche un sync incrémental. Paramètre : `section` (optionnel) |
| `cortex_list_sections` | Liste les sections incluses et les dossiers « out of policy » |
| `cortex_freshness` | Résumé de fraîcheur par défaut. Paramètres : `section` (optionnel), `include_entries` (`false` par défaut) |

---

## Choix techniques

### Pourquoi ONNX / fastembed ?

PyTorch + sentence-transformers détectait le GPU pendant l'initialisation et causait un **BSOD (dxgkrnl.sys)**. Le modèle ONNX via `fastembed` tourne entièrement sur CPU, utilise ~150 Mo de RAM, et ne touche pas au GPU.

### Pourquoi un fingerprint d'embedding ?

L'index et les requêtes doivent utiliser exactement le même espace vectoriel.
Cortex stocke donc dans les métadonnées Chroma le modèle, la version de
`fastembed` et le pooling (`mean`, contrat explicite depuis le correctif
qdrant/fastembed#436 actif en v0.6.0 pour ce modèle). Au démarrage, avant une
recherche et avant toute écriture, Cortex refuse l'accès si une valeur diffère
et indique la procédure de reconstruction. L'index historique attesté le
2026-07-12 est migré une seule fois vers le fingerprint
`fastembed=0.8.0 / pooling=mean`.

### Pourquoi un sync section par section ?

Chaque section est un processus Python indépendant dans `sync.bat`. Cela limite la RAM à ~300 Mo par processus (contre un pic unique si tout est en mémoire) et permet de reprendre facilement en cas d'erreur.

### Pourquoi l'index incrémental est scopé par section ?

Sans scoping, un sync de la section `operations` pouvait voir les fichiers de
`knowledge` comme « supprimés » et les effacer. La comparaison et les
suppressions sont maintenant limitées à la section en cours.

### Pourquoi 512 caractères par chunk ?

Le modèle `paraphrase-multilingual-MiniLM-L12-v2` tronque toute entrée à **128 tokens maximum**. Tout ce qui dépasse n'est jamais vu par l'embedding. En français, 1 token ≈ 3,5 caractères, donc 512 caractères ≈ 145 tokens — légèrement au-dessus du plafond théorique, mais le chunker coupe sur des frontières naturelles (retour à la ligne, fin de phrase) ce qui produit en pratique des chunks plus courts. Les chunks plus longs (~2000 chars utilisés au début du projet) faisaient perdre 70 à 80 % du contenu indexé à l'embedding.

### Pourquoi les chemins en metadata sont relatifs ?

Le `path` stocké dans chaque chunk est relatif à `CORTEX_KB_PATH` (ex.
`operations/architecture.md`). Cela rend l'index portable d'une machine à
l'autre tant que l'arborescence sous le KB est identique, et sert aussi à la
réconciliation incrémentale.

### Pourquoi tout est portable ?

Les chemins d'installation sont portables. `kb_path` est fourni par la
configuration utilisateur ou `CORTEX_KB_PATH` ; aucune valeur propre à une
machine n'est codée dans les sources :

- `config.py` dérive `CHROMA_PATH` de `Path(__file__).parent` → la base vectorielle vit toujours à côté du code.
- `install.bat` et `sync.bat` utilisent `%~dp0` → ils trouvent eux-mêmes leur dossier d'exécution.
- `setup_config.py` détecte sa propre localisation pour patcher `claude_desktop_config.json`.
- `%APPDATA%\Cortex\config.toml` sépare les choix utilisateur du code livré.

Conséquence : tu peux cloner Cortex dans n'importe quel dossier sur n'importe quelle machine, lancer `install.bat`, et c'est opérationnel.

---

## Dépendances

```
mcp[cli]==1.27.0
chromadb==1.5.7
fastembed==0.8.0
pydantic==2.12.5
pdfplumber==0.11.9
filelock==3.25.2
tomli==2.2.1; python_version < "3.11"
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

Vérifie : Python accessible · packages importables · configuration utilisateur
valide · entrée `cortex` présente dans `claude_desktop_config.json` avec des
chemins valides.
