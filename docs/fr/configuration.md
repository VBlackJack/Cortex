# Configuration

**Francais** | [English](../en/configuration.md)

[Retour au sommaire](index.md)

## Variables d'environnement

| Variable | Role | Defaut |
|---|---|---|
| `CORTEX_KB_PATH` | Surcharge optionnelle de `kb_path` | aucune |
| `CORTEX_WRITE_LOCK_PATH` | Surcharge du chemin de verrou | `<data_home>/chroma_db.write.lock` |
| `CORTEX_WRITE_LOCK_TIMEOUT_SECONDS` | Surcharge du timeout de verrou | `30` |
| `CORTEX_MAX_MARKDOWN_FILE_SIZE_BYTES` | Surcharge de la limite Markdown | `1000000` |

La configuration utilisateur vit dans `%APPDATA%\Cortex\config.toml` avec
`schema_version = 1`. Elle ne contient jamais de secret. La precedence est
variable d'environnement > fichier TOML > defaut produit. Les variables
d'environnement historiques restent donc compatibles, mais `install.bat` ne les
cree plus sur une nouvelle installation.

Le schema v1 accepte les cles optionnelles `chroma_path` et
`index_whole_folder`, donc tout fichier v1 existant reste valide. Par defaut,
la configuration legere reste roaming dans
`%APPDATA%\Cortex`, tandis que l'index, le verrou et les logs volumineux vivent
localement dans `%LOCALAPPDATA%\Cortex`.

## Configurations de sources separees

Cortex garde trois surfaces TOML strictes et separees. Une cle inconnue echoue
en mode ferme et aucun de ces fichiers n'accepte de secret :

| Fichier | Portee | Details |
|---|---|---|
| `%APPDATA%\Cortex\config.toml` | Dossier Markdown/PDF choisi et index derives | Cette page |
| `%APPDATA%\Cortex\ingestion.toml` | Generations partagees, retention, reprise, verrou, duree des credentials et cadence | [Planification de l'ingestion](ingestion-scheduling.md) |
| `%APPDATA%\Cortex\confluence.toml` | URL Confluence, console, expiration declaree, limites et selection par espace entier ou par pages | [Writer Confluence](writer-confluence.md) |

Les variables d'environnement priment sur les valeurs TOML correspondantes. Le
PAT est stocke interactivement dans Windows Credential Manager, jamais dans un
fichier TOML ni une variable d'environnement. En l'absence de
`confluence.toml`, le stockage interactif utilise la cible Windows par defaut
`cortex-spike`, mais l'ajout de pages et la collecte restent desactives jusqu'a
la creation du fichier.

`confluence.toml` accepte les schemas v1 et v2. Les fichiers v1 existants
restent des listes blanches d'espaces entiers et ne sont jamais reecrits au
chargement. Le schema v2 impose `selection = "whole_space"` ou
`selection = "pages"` pour chaque espace ; le mode pages peut volontairement
porter une liste vide.

Les mises a jour programmatiques utilisent un lock de mutation dedie a cote de
`confluence.toml`, distinct du lock de sync d'ingestion et du lock Chroma. Le
writer compare le SHA-256 des octets exacts lus avant de remplacer le fichier.
Un hash perime ou un lock occupe echoue en mode ferme et impose un rechargement.
Chaque update reussie conserve les octets precedents dans
`confluence.toml.bak`.

La surface Confluence lisible par une machine utilise les memes deux fichiers
de configuration :

```powershell
cortex confluence pages --json
cortex confluence resolve 379465380 --json
```

`pages --json` lit uniquement `confluence.toml`, la generation locale `doc`
courante et son etat de sante. Cette commande ne lit aucun credential et ne
contacte pas Confluence. `resolve` exige `base_url`, `auth_expires_at`, le
credential Windows nomme et une requete REST Confluence authentifiee. Une
configuration incomplete est classee comme entree invalide (code 6), pas comme
erreur generale. Une erreur d'usage de la ligne de commande, par exemple une
option inconnue, sort aussi avec le code 6, pour qu'un client machine ne la
confonde jamais avec un verrou pris (code 2). Voir le
[writer Confluence](writer-confluence.md#cli-lisible-par-une-machine) pour les
contrats JSON et les exit codes.

## Exemple de config.toml

```toml
schema_version = 1
kb_path = "D:\\Knowledge"
chroma_path = "C:\\Users\\me\\AppData\\Local\\Cortex\\chroma_db"
index_whole_folder = true
included_sections = ["knowledge", "projects", "notes"]
excluded_dirs = [".datacron", "_archive", "_trash", "_attachments", "zzz_Corbeille", "_inbox", "_journal"]
exclude_files = ["00_INDEX.md"]
max_markdown_file_size_bytes = 1000000
max_pdf_size_bytes = 50000000
write_lock_path = "C:\\Users\\me\\AppData\\Local\\Cortex\\chroma_db.write.lock"
write_lock_timeout_seconds = 30
```

Creer le fichier manuellement ou lancer :

```powershell
python setup_config.py --init
```

`kb_path` est requis pour `cortex_sync` et `cortex_freshness`, sans valeur par
defaut. La recherche continue de fonctionner sur l'index existant lorsqu'il est
absent.

`chroma_path` et `write_lock_path` peuvent etre omis pour utiliser le data home
local, ou definis explicitement pour un besoin d'exploitation particulier.

## Dossier entier ou sections

Avec `index_whole_folder = true`, Cortex indexe recursivement tout `kb_path`,
en respectant toujours `excluded_dirs` et `exclude_files`. C'est le mode par
defaut de l'installeur Windows pour un nouveau poste. `included_sections` reste
dans le fichier mais n'est pas utilise dans ce mode.

Une configuration existante sans `index_whole_folder` garde son comportement
historique : la valeur absente equivaut a `false` et active les sections.

Pour changer proprement de mode sur une installation existante, utiliser le
choix `Reinitialiser` de l'installeur ou :

```powershell
$env:CORTEX_KB_PATH = "D:\Knowledge"
$env:CORTEX_INDEX_MODE = "whole"
cortex setup --reset --yes
```

Le reset supprime `config.toml` et les donnees generees du data home avant de
reconstruire l'index. Il ne supprime jamais `kb_path`. Sans `--reset`, une
configuration existante reste preservee.

Les sections indexables sont definies par `included_sections` dans
`config.toml`. Un dossier de premier niveau absent de l'allowlist et de la
denylist n'est jamais indexe automatiquement : `cortex_list_sections` le signale
comme "out of policy" jusqu'a une decision explicite. La validation MCP est
insensible a la casse (`KNOWLEDGE` devient `knowledge`).

Depuis Claude, l'outil MCP `cortex_list_sections` liste toutes les sections
disponibles.

### Ajouter une nouvelle section

1. Exporter la section sous le dossier `kb_path` configure.
2. Ajouter son nom a `included_sections` dans `config.toml`.
3. Lancer `sync.bat` (ou `cortex_sync` depuis Claude).

Sans cet opt-in, le dossier reste visible comme "out of policy" mais n'est
jamais envoye au modele d'embedding.

## Contrats d'index (non modifiables)

Les contrats d'index restent centralises dans `config.py` et ne sont pas
modifiables par utilisateur :

```python
COLLECTION_NAME = "cortex"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_POOLING = "mean"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
CHUNKING_CONTRACT_VERSION = "v3"
METADATA_SCHEMA_VERSION = 2
LEXICAL_INDEX_CONTRACT_VERSION = "v2"
SEARCH_TOP_K_MIN = 1
SEARCH_TOP_K_MAX = 10
SEARCH_HYBRID_CANDIDATES = 40
SEARCH_RERANK_CANDIDATES = 20
INGESTION_DOCUMENT_SOURCE_KIND = "doc"
INGESTION_DOCUMENT_SECTION = "sources"
```

`CHUNK_SIZE` est dimensionne pour rester sous la limite de 128 tokens du modele
MiniLM avec une marge de securite. Voir "Pourquoi 512 caracteres par chunk ?"
dans l'[architecture](architecture.md).

## Migration de l'ancien index

Si `chroma_db` existe encore a cote du code et que la cible du data home
n'existe pas, `setup_config.py` propose son deplacement :

```powershell
python setup_config.py --migrate-data
```

Le deplacement utilise un renommage atomique et ne cree jamais de copie
silencieuse. Si source et cible sont sur des volumes differents, Cortex refuse
le fallback copie : fermer tous les clients, deplacer le dossier manuellement,
ou configurer temporairement `chroma_path` sur le volume source. Si l'ancien et
le nouvel index existent simultanement, Cortex refuse de choisir ou de les
fusionner. Le fingerprint est contenu dans le dossier deplace ; le write lock
utilise le data home par defaut, tandis qu'une surcharge explicite existante
reste strictement respectee. Pour rollback, fermer les clients et redeplacer le
dossier dans l'autre sens.
