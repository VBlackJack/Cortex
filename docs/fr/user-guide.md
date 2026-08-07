# Guide d'utilisation

**Francais** | [English](../en/user-guide.md)

[Retour au sommaire](index.md)

## Indexation (sync)

### Sync complete (toutes les sections)

```bat
:: Depuis le dossier d'install
sync.bat
```

Le sync est incremental : seuls les fichiers nouveaux ou modifies (detectes par
SHA-256 et version du contrat de chunking) sont retraites. Les fichiers
supprimes, vides ou devenus exclus sont retires de l'index.

Un sync complet reconcilie aussi le Markdown de la generation d'ingestion
publiee courante. Les generations pending ou incompletes ne sont jamais
indexees ; une generation indisponible preserve les lignes `doc` deja indexees.

Sur une nouvelle installation Windows, ce sync couvre tout le dossier de base
de connaissances, recursivement. Le filtrage par section ci-dessous concerne
uniquement le mode avance.

### Sync d'une seule section

```powershell
python indexer.py operations
```

### Depuis un client MCP

```
cortex_sync                       # toutes les sections
cortex_sync section="operations"  # une seule section
```

### Repartir de zero (modele change, index corrompu)

1. Quitter tous les clients MCP connectes a Cortex.
2. Supprimer le dossier `%LOCALAPPDATA%\Cortex\chroma_db\` (ou le `chroma_path`
   configure).
3. Relancer les clients MCP.
4. Lancer `sync.bat`.

## Recherche

### Depuis un client MCP

Le client peut appeler automatiquement `cortex_search` quand une question porte
sur la documentation interne. Il est aussi possible de le demander
explicitement, par exemple : "Cherche dans Cortex comment configurer les
alertes Zabbix".

### En ligne de commande (debug)

```powershell
# Recherche globale
python indexer.py --search "alertes zabbix"

# Recherche dans une section (la section est positionnelle)
python indexer.py knowledge --search "procedure de deploiement"

# Nombre de resultats
python indexer.py --search "OSCARE" --top-k 10
```

Les reponses de recherche utilisent le schema de metadonnees v2. En plus de
`section`, la recherche accepte `source_kinds`, `authors`, `occurred_at_from`,
`occurred_at_to`, `updated_at_from` et `updated_at_to`. Les bornes de dates sont
des timestamps RFC 3339. Chaque resultat contient les metadonnees reconstruites,
une citation, la pertinence et un verdict de fraicheur resolu dans son propre
domaine vault ou ingestion.

## Les quatre outils MCP

| Outil | Description |
|---|---|
| `cortex_search` | Recherche hybride. Parametres : `query`, `section`, `top_k` (1-10), filtres source/auteur et plages de dates de creation/mise a jour. |
| `cortex_sync` | Declenche un sync incremental et inclut la generation documentaire courante sur un sync complet. Parametre : `section` (optionnel). |
| `cortex_list_sections` | Liste les sections incluses et les dossiers "out of policy". |
| `cortex_freshness` | Fraicheur du vault et de l'ingestion en deux etages, en lecture seule. Parametres : `section` (optionnel), `include_entries` (`false` par defaut). |

Quand l'ingestion existe, `cortex_freshness` rapporte la sante remote-to-disk,
l'identifiant de generation courant et le statut disk-to-index. Le resume dedie
`ingestion_index` est omis lorsqu'aucune generation documentaire n'est
disponible.

## Operations d'ingestion

Le CLI d'ingestion generique rapporte le dernier etat de sante atomique de la
source et indique si un rattrapage est du. L'adaptateur Confluence stocke son
PAT interactivement et passe par les memes moteur de verrou, reprise,
expiration et generation :

```powershell
cortex ingestion status doc
cortex ingestion due doc
cortex confluence store-credential
cortex confluence sync
cortex confluence sync --force
```

Voir [Planification de l'ingestion](ingestion-scheduling.md) pour les codes de
sortie et les reglages, et [Writer Confluence](writer-confluence.md) pour la
liste blanche et le contrat du convertisseur.

## Cortex Doctor

Le premier outil a lancer pour un diagnostic support est strictement
read-only : il ne repare, ne cree et n'ecrit rien, pas meme un log applicatif.
L'index est inspecte via SQLite `mode=ro&immutable=1` plutot que par
`PersistentClient`.

```powershell
# Rapport lisible a copier-coller
python setup_config.py --doctor
cortex doctor

# Schema JSON stable (schema_version = 1)
python setup_config.py --doctor --json
```

Le rapport couvre Python et les dependances, la configuration et `kb_path`,
l'etat de migration, le nombre de chunks, le fingerprint, la fraicheur en mode
summary, le write lock, les dernieres erreurs de sync, puis chaque client par
couches : binaire, extension VS Code eventuelle, entree MCP, chemins et
authentification. `UNKNOWN` signifie toujours "non sondable automatiquement" et
fournit l'action manuelle a effectuer ; il n'est jamais presente comme OK.

Un seul handshake global lance reellement `server.py`, envoie MCP `initialize`,
verifie la reponse puis termine le processus avec un timeout de 20 secondes. Le
serveur utilise pour cette sonde un lifespan diagnostique qui n'ouvre pas Chroma
(`PersistentClient` modifierait SQLite a la simple ouverture) puisque l'index a
deja ete controle separement en lecture seule.

Le code de sortie vaut `0` lorsqu'il n'existe aucun `[FAIL]`. Les statuts
`[WARN]`, `[UNKNOWN]`, `[INFO]` et `[SKIP]` restent informatifs.

Les sous-commandes installees sont des dispatchers minces vers les memes points
d'entree que les scripts historiques :

```powershell
cortex setup [--clients all] [--no-index] [--reset] [--yes]
cortex sync [section] [--json]
cortex ingestion [--config FILE] {status,due} SOURCE_KIND
cortex confluence [--config FILE] [--ingestion-config FILE] {store-credential,sync}
cortex doctor [--json]
cortex init
cortex register [--clients all]
cortex check [--clients all]
```

`cortex sync --json` ecrit exactement un document JSON versionne sur stdout,
tandis que les journaux operationnels restent sur stderr. Son code de sortie
vaut `0` pour un sync reussi, `1` pour un sync partiel ou en echec, `2` lorsqu'un
verrou d'ecriture est indisponible et `6` pour une entree ou une configuration
invalide. La recherche n'est pas disponible en mode JSON. Sans `--json`, le
comportement historique du sync humain reste inchange.

`cortex setup` enchaine init, index et enregistrement des clients en un appel
(voir [Installation](setup.md#setup-en-une-commande)).

## Logs locaux bornes

Chaque processus Cortex conserve la sortie stderr attendue par les clients MCP
et ecrit en plus dans `%LOCALAPPDATA%\Cortex\logs\cortex.log`. La rotation est
bornee a 5 Mo par fichier et 5 sauvegardes. Les logs ne contiennent jamais le
texte des documents ou des chunks : uniquement chemins, statuts, erreurs et
compteurs operationnels.

## Tests

```powershell
python -m pytest tests/ -v
```

Les tests unitaires (`tests/test_chunker.py`) tournent toujours. Les tests
d'integration (`tests/test_search.py`) sont automatiquement skippes si le
`chroma_path` resolu n'existe pas encore.

### Barriere qualite locale

```powershell
python -m pip install -e ".[dev]"
python -m pre_commit run --all-files
```

Chaque commit passe Ruff, mypy en mode strict et la suite pytest complete. La CI
rejoue ces memes hooks, sans configuration qualite parallele.
