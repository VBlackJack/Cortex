# Guide d'utilisation

**Français** | [English](../en/user-guide.md)

[Retour au sommaire](index.md)

## Indexation (sync)

### Sync complète (toutes les sections)

```bat
:: Depuis le dossier d'install
sync.bat
```

Le sync est incrémental : seuls les fichiers nouveaux ou modifiés (détectés par
SHA-256 et version du contrat de chunking) sont retraités. Les fichiers
supprimés, vides ou devenus exclus sont retirés de l'index.

Un sync complet réconcilie aussi le Markdown de la génération d'ingestion
publiée courante. Les générations pending ou incomplètes ne sont jamais
indexées ; une génération indisponible préserve les lignes `doc` déjà indexées.

Sur une nouvelle installation Windows, ce sync couvre tout le dossier de base
de connaissances, récursivement. Le filtrage par section ci-dessous concerne
uniquement le mode avancé.

### Sync d'une seule section

```powershell
python indexer.py operations
```

### Depuis un client MCP

```
cortex_sync                       # toutes les sections
cortex_sync section="operations"  # une seule section
```

### Repartir de zéro (modèle changé, index corrompu)

1. Quitter tous les clients MCP connectés à Cortex.
2. Supprimer le dossier `%LOCALAPPDATA%\Cortex\chroma_db\` (ou le `chroma_path`
   configuré).
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
cortex search "alertes zabbix"

# Recherche dans une section
cortex search "procedure de deploiement" --section knowledge

# Nombre de resultats
cortex search "OSCARE" --top-k 10
```

Les réponses de recherche utilisent le schema de métadonnées v2. En plus de
`section`, la recherche accepte `source_kinds`, `authors`, `occurred_at_from`,
`occurred_at_to`, `updated_at_from` et `updated_at_to`. Les bornes de dates sont
des timestamps RFC 3339. Chaque résultat contient les métadonnées reconstruites,
une citation, la pertinence et un verdict de fraîcheur résolu dans son propre
domaine vault ou ingestion.

## Les quatre outils MCP

| Outil | Description |
|---|---|
| `cortex_search` | Recherche hybride. Paramètres : `query`, `section`, `top_k` (1-10), filtres source/auteur et plages de dates de création/mise à jour. |
| `cortex_sync` | Déclenche un sync incrémental et inclut la génération documentaire courante sur un sync complet. Paramètre : `section` (optionnel). |
| `cortex_list_sections` | Liste les sections incluses et les dossiers "out of policy". |
| `cortex_freshness` | Fraîcheur du vault et de l'ingestion en deux étages, en lecture seule. Paramètres : `section` (optionnel), `include_entries` (`false` par défaut). |

Quand l'ingestion existe, `cortex_freshness` rapporte la santé remote-to-disk,
l'identifiant de génération courant et le statut disk-to-index. Le résumé dédié
`ingestion_index` est omis lorsqu'aucune génération documentaire n'est
disponible.

## Opérations d'ingestion

Le CLI d'ingestion générique rapporte le dernier état de santé atomique de la
source et indique si un rattrapage est dû. L'adaptateur Confluence stocke son
PAT interactivement et passe par les mêmes moteur de verrou, reprise, expiration
et génération. Le PAT peut être enregistré sans terminal depuis
`Réglages > Connexion Confluence` dans Companion, même avant la création
du fichier grâce à la cible `cortex-spike` par défaut. Ouvrir ensuite
`Mes sources` : l'assistant crée la configuration à partir d'une URL de
page, de l'expiration du PAT, de l'espace et de la classification. Le parcours
en ligne de commande reste disponible :

```powershell
cortex ingestion status doc
cortex ingestion due doc
cortex confluence store-credential
cortex confluence sync
cortex confluence sync --force
```

Voir [Planification de l'ingestion](ingestion-scheduling.md) pour les codes de
sortie et les réglages, et [Writer Confluence](writer-confluence.md) pour la
liste blanche et le contrat du convertisseur.

## Cortex Doctor

Le premier outil à lancer pour un diagnostic support est strictement
read-only : il ne répare, ne crée et n'écrit rien, pas même un log applicatif.
L'index est inspecté via SQLite `mode=ro&immutable=1` plutôt que par
`PersistentClient`.

```powershell
# Rapport lisible a copier-coller
python setup_config.py --doctor
cortex doctor

# Schema JSON stable (schema_version = 1)
python setup_config.py --doctor --json
```

Le rapport couvre Python et les dépendances, la configuration et `kb_path`,
l'état de migration, le nombre de chunks, le fingerprint, la fraîcheur en mode
summary, le write lock, les dernières erreurs de sync, puis chaque client par
couches : binaire, extension VS Code éventuelle, entrée MCP, chemins et
authentification. `UNKNOWN` signifie toujours "non sondable automatiquement" et
fournit l'action manuelle à effectuer ; il n'est jamais présenté comme OK.

Un seul handshake global lance réellement `server.py`, envoie MCP `initialize`,
vérifie la réponse puis termine le processus avec un timeout de 20 secondes. Le
serveur utilise pour cette sonde un lifespan diagnostique qui n'ouvre pas Chroma
(`PersistentClient` modifierait SQLite à la simple ouverture) puisque l'index a
déjà été contrôlé séparément en lecture seule.

Le code de sortie vaut `0` lorsqu'il n'existe aucun `[FAIL]`. Les statuts
`[WARN]`, `[UNKNOWN]`, `[INFO]` et `[SKIP]` restent informatifs.

Les sous-commandes installées sont des dispatchers minces vers les mêmes points
d'entrée que les scripts historiques :

```powershell
cortex setup [--clients all] [--no-index] [--reset] [--yes]
cortex sync [section] [--json]
cortex search QUERY [--section SECTION] [--top-k N]
cortex ingestion [--config FILE] {status,due} SOURCE_KIND
cortex confluence [--config FILE] [--ingestion-config FILE] {store-credential,sync}
cortex doctor [--json]
cortex init
cortex register [--clients all]
cortex check [--clients all]
```

`cortex sync --json` écrit exactement un document JSON versionné sur stdout,
tandis que les journaux opérationnels restent sur stderr. Son code de sortie
vaut `0` pour un sync réussi, `1` pour un sync partiel ou en échec, `2` lorsqu'un
verrou d'écriture est indisponible et `6` pour une entrée ou une configuration
invalide. La recherche n'est pas disponible en mode JSON. Sans `--json`, le
sync humain garde sa sortie de journal mais rend les mêmes codes de sortie :
un sync partiel ou en échec ne se termine plus par `0`. Une interruption par
Ctrl+C rend `130`, sans trace d'appel. `cortex sync --search` reste accepté
comme alias de `cortex search`.

`cortex setup` enchaîne init, index et enregistrement des clients en un appel
(voir [Installation](setup.md#setup-en-une-commande)).

## Logs locaux bornés

Chaque processus Cortex conserve la sortie stderr attendue par les clients MCP
et écrit en plus dans `%LOCALAPPDATA%\Cortex\logs\cortex.log`. La rotation est
bornée à 5 Mo par fichier et 5 sauvegardes. Les logs ne contiennent jamais le
texte des documents ou des chunks : uniquement chemins, statuts, erreurs et
compteurs opérationnels.

## Tests

```powershell
python -m pytest tests/ -v
```

Les tests unitaires (`tests/test_chunker.py`) tournent toujours. Les tests
d'intégration (`tests/test_search.py`) sont automatiquement skippés si le
`chroma_path` résolu n'existe pas encore.

### Barrière qualité locale

```powershell
python -m pip install -e ".[dev]"
python -m pre_commit run --all-files
```

Chaque commit passe Ruff, mypy en mode strict et la suite pytest complète. La CI
rejoue ces mêmes hooks, sans configuration qualité parallèle.
