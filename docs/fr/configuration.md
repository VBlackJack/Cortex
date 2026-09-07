# Configuration

**Français** | [English](../en/configuration.md)

[Retour au sommaire](index.md)

## Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `CORTEX_KB_PATH` | Surcharge optionnelle de `kb_path` | aucune |
| `CORTEX_WRITE_LOCK_PATH` | Surcharge du chemin de verrou | `<data_home>/chroma_db.write.lock` |
| `CORTEX_WRITE_LOCK_TIMEOUT_SECONDS` | Surcharge du timeout de verrou | `30` |
| `CORTEX_MAX_MARKDOWN_FILE_SIZE_BYTES` | Surcharge de la limite Markdown | `1000000` |

La configuration utilisateur vit dans `%APPDATA%\Cortex\config.toml` avec
`schema_version = 1`. Elle ne contient jamais de secret. La précédence est
variable d'environnement > fichier TOML > défaut produit. Les variables
d'environnement historiques restent donc compatibles, mais `install.bat` ne les
crée plus sur une nouvelle installation.

Le schéma v1 accepte les clés optionnelles `chroma_path` et
`index_whole_folder`, donc tout fichier v1 existant reste valide. Par défaut,
la configuration légère reste roaming dans
`%APPDATA%\Cortex`, tandis que l'index, le verrou et les logs volumineux vivent
localement dans `%LOCALAPPDATA%\Cortex`.

## Configurations de sources séparées

Cortex garde trois surfaces TOML strictes et séparées. Une clé inconnue échoue
en mode fermé et aucun de ces fichiers n'accepte de secret :

| Fichier | Portée | Détails |
|---|---|---|
| `%APPDATA%\Cortex\config.toml` | Dossier Markdown/PDF choisi et index dérivés | Cette page |
| `%APPDATA%\Cortex\ingestion.toml` | Générations partagées, rétention, reprise, verrou, durée des credentials et cadence | [Planification de l'ingestion](ingestion-scheduling.md) |
| `%APPDATA%\Cortex\confluence.toml` | URL Confluence, console, expiration déclarée, limites et sélection par espace entier ou par pages | [Writer Confluence](writer-confluence.md) |

Les variables d'environnement priment sur les valeurs TOML correspondantes. Le
PAT est stocké interactivement dans Windows Credential Manager, jamais dans un
fichier TOML ni une variable d'environnement. En l'absence de
`confluence.toml`, le stockage interactif utilise la cible Windows par défaut
`cortex-spike`, mais l'ajout de pages et la collecte restent désactivés jusqu'à
la création du fichier.

`confluence.toml` accepte les schémas v1 et v2. Les fichiers v1 existants
restent des listes blanches d'espaces entiers et ne sont jamais réécrits au
chargement. Le schéma v2 impose `selection = "whole_space"` ou
`selection = "pages"` pour chaque espace ; le mode pages peut volontairement
porter une liste vide.

Les mises à jour programmatiques utilisent un lock de mutation dédié à côté de
`confluence.toml`, distinct du lock de sync d'ingestion et du lock Chroma. Le
writer compare le SHA-256 des octets exacts lus avant de remplacer le fichier.
Un hash périmé ou un lock occupé échoue en mode fermé et impose un rechargement.
Chaque update réussie conserve les octets précédents dans
`confluence.toml.bak`.

La surface Confluence lisible par une machine utilise les mêmes deux fichiers
de configuration :

```powershell
cortex confluence pages --json
cortex confluence resolve 379465380 --json
```

`pages --json` lit uniquement `confluence.toml`, la génération locale `doc`
courante et son état de santé. Cette commande ne lit aucun credential et ne
contacte pas Confluence. `resolve` exige `base_url`, `auth_expires_at`, le
credential Windows nommé et une requête REST Confluence authentifiée. Une
configuration incomplète est classée comme entrée invalide (code 6), pas comme
erreur générale. Une erreur d'usage de la ligne de commande, par exemple une
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

Créer le fichier manuellement ou lancer :

```powershell
python setup_config.py --init
```

`kb_path` est requis pour `cortex_sync` et `cortex_freshness`, sans valeur par
défaut. La recherche continue de fonctionner sur l'index existant lorsqu'il est
absent.

`chroma_path` et `write_lock_path` peuvent être omis pour utiliser le data home
local, ou définis explicitement pour un besoin d'exploitation particulier.

## Dossier entier ou sections

Avec `index_whole_folder = true`, Cortex indexe récursivement tout `kb_path`,
en respectant toujours `excluded_dirs` et `exclude_files`. C'est le mode par
défaut de l'installeur Windows pour un nouveau poste. `included_sections` reste
dans le fichier mais n'est pas utilisé dans ce mode.

Une configuration existante sans `index_whole_folder` garde son comportement
historique : la valeur absente équivaut à `false` et active les sections.

Pour changer proprement de mode sur une installation existante, utiliser le
choix `Reinitialiser` de l'installeur ou :

```powershell
$env:CORTEX_KB_PATH = "D:\Knowledge"
$env:CORTEX_INDEX_MODE = "whole"
cortex setup --reset --yes
```

Le reset supprime `config.toml` et les données générées du data home avant de
reconstruire l'index. Il ne supprime jamais `kb_path`. Sans `--reset`, une
configuration existante reste préservée.

Les sections indexables sont définies par `included_sections` dans
`config.toml`. Un dossier de premier niveau absent de l'allowlist et de la
denylist n'est jamais indexé automatiquement : `cortex_list_sections` le signale
comme "out of policy" jusqu'à une décision explicite. La validation MCP est
insensible à la casse (`KNOWLEDGE` devient `knowledge`).

Depuis Claude, l'outil MCP `cortex_list_sections` liste toutes les sections
disponibles.

### Ajouter une nouvelle section

1. Exporter la section sous le dossier `kb_path` configuré.
2. Ajouter son nom à `included_sections` dans `config.toml`.
3. Lancer `sync.bat` (ou `cortex_sync` depuis Claude).

Sans cet opt-in, le dossier reste visible comme "out of policy" mais n'est
jamais envoyé au modèle d'embedding.

## Contrats d'index (non modifiables)

Les contrats d'index restent centralisés dans `config.py` et ne sont pas
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

`CHUNK_SIZE` est dimensionné pour rester sous la limite de 128 tokens du modèle
MiniLM avec une marge de sécurité. Voir "Pourquoi 512 caractères par chunk ?"
dans l'[architecture](architecture.md).

## Migration de l'ancien index

Si `chroma_db` existe encore à côté du code et que la cible du data home
n'existe pas, `setup_config.py` propose son déplacement :

```powershell
python setup_config.py --migrate-data
```

Le déplacement utilise un renommage atomique et ne crée jamais de copie
silencieuse. Si source et cible sont sur des volumes différents, Cortex refuse
le fallback copie : fermer tous les clients, déplacer le dossier manuellement,
ou configurer temporairement `chroma_path` sur le volume source. Si l'ancien et
le nouvel index existent simultanément, Cortex refuse de choisir ou de les
fusionner. Le fingerprint est contenu dans le dossier déplacé ; le write lock
utilise le data home par défaut, tandis qu'une surcharge explicite existante
reste strictement respectée. Pour rollback, fermer les clients et redéplacer le
dossier dans l'autre sens.
