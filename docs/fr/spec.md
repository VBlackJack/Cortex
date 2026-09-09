# Cortex - Contrat public du serveur MCP et de l'index

**Français** | [English](../en/spec.md)

> **Statut** : Spec v2.1 - normative, synchronisée avec `main`
> **Auteur** : Julien Bombled
> **Date** : 2026-08-05
> **Licence** : [Apache 2.0](../../LICENSE)
> **Portée** : Ce document définit les surfaces, formats et invariants observables de
> Cortex. Les choix de conception détaillés restent dans
> [architecture.md](architecture.md).

Les mots "doit", "ne doit pas" et "jamais" expriment des contrats de
l'implémentation actuelle. Ce document ne décrit aucun comportement futur ou
aspirationnel.

---

<!-- spec:identity -->
## 1. Identité du produit et frontière de lecture

Cortex est un serveur RAG local et multi-client exposé par MCP. Il indexe les
fichiers Markdown et PDF choisis par l'utilisateur ainsi que le Markdown de la
génération d'ingestion publiée courante, puis retourne aux clients les passages
jugés pertinents. Les fichiers sous `kb_path` restent l'autorité du domaine
`note` ; la génération immutable courante est l'autorité du domaine `doc`.
ChromaDB et l'index lexical sont des données dérivées reconstructibles.

| Surface | Contrat observable |
|---|---|
| Documents utilisateur | Lecture seule : aucun outil MCP ne crée, ne modifie, ne renomme ou ne supprime un fichier Markdown ou PDF sous `kb_path` |
| Documents générés | Les writers de sources publient des générations immuables hors de `kb_path` ; seul `current.json` choisit la génération servie |
| Index dérivé | `cortex_sync` peut créer et modifier les index vectoriel et lexical locaux depuis les deux domaines |
| Recherche | Lecture de l'index avec retour des chunks, repères de source et verdict de fraîcheur |
| Runtime | Traitement CPU local ; Cortex force `CUDA_VISIBLE_DEVICES` à une valeur vide |

La surface cliente MCP est donc en lecture seule vis-à-vis du corpus, mais pas
vis-à-vis des données dérivées : `cortex_sync` est une opération d'écriture sur
l'index. Cortex ne fournit aucun outil d'édition de contenu, aucun journal de
mutations documentaires et aucun mécanisme d'écriture dans `kb_path`. Le CLI
opérateur séparé peut publier du contenu source généré par un writer
explicitement configuré.

<!-- spec:mcp-tools -->
## 2. Transport et surface des quatre outils MCP

Le point d'entrée `cortex serve` lance FastMCP par `mcp.run()` sur stdio. Le CLI
Cortex n'expose aucun transport HTTP ou WebSocket et n'ouvre aucun listener
réseau. Le code du serveur enregistre exactement quatre tools et aucun resource
ou prompt MCP propre à Cortex.

| Tool | Paramètres | Comportement | Format de réponse |
|---|---|---|---|
| `cortex_search` | `query: str`, `section`, `top_k`, `source_kinds`, `authors` et bornes RFC 3339 de création/mise à jour optionnels | Recherche vectorielle locale par défaut, `retrieval_mode` facultatif (`vector`, `hybrid`, `rerank`), filtres de métadonnées, fallback vectoriel et fraîcheur par domaine | Objet structuré schema v2 avec filtres effectifs, résultats, citations, pertinence, fraîcheur, métadonnées et Markdown de compatibilité |
| `cortex_sync` | `section: Optional[str] = None` | Réconciliation incrémentale d'une section ou de toute la portée configurée | Markdown : `published_files`, `added_chunks`, `deleted_chunks`, `removed_files`, `skipped_files`, `empty_files`, `errors` |
| `cortex_list_sections` | aucun | Liste les sections incluses et les dossiers de premier niveau hors politique | Markdown : sections indexables puis dossiers `out of policy` |
| `cortex_freshness` | `section: Optional[str] = None`, `include_entries: bool = False` | Compare les sources vivantes aux métadonnées d'index sans les modifier | Objet structuré : contrat, scope, résumé, durée et, sur demande, entrées par fichier |

Les noms de section sont résolus sans tenir compte de la casse. Une section
inconnue retourne une erreur avec les sections disponibles. Les erreurs de
configuration, de migration, de fingerprint et de verrou sont converties en
réponses explicites ; elles ne deviennent pas des traces brutes côté client.

<!-- spec:search -->
## 3. Contrat de recherche

`cortex_search` borne toujours `top_k` entre 1 et 10. En mode hybride, chaque
branche récupère au plus 40 candidats. Les résultats vectoriels ChromaDB et les
résultats lexicaux SQLite FTS5 sont fusionnés par Reciprocal Rank Fusion avec
`k = 60`, puis les 20 premiers candidats sont proposés au reranker ONNX
`jinaai/jina-reranker-v1-tiny-en` uniquement en mode explicite `rerank`.
Le mode par défaut est `vector` : sans index lexical ni reranker. Le reranker est
chargé à la demande. La CLI expose `--retrieval-mode` et MCP `retrieval_mode`.

| Mode retourné | Condition | Ordre final |
|---|---|---|
| `hybrid+rerank` | Mode explicite `rerank`, index lexical compatible et reranker disponible | Score du cross-encoder, avec ordre stable en cas d'égalité |
| `hybrid` | Mode explicite `hybrid`, ou échec du reranker en mode `rerank` | Ordre RRF ; motif de dégradation uniquement en cas de panne |
| `vector-only` | Défaut ou `vector` explicite (sans fallback) ; panne lexicale dans un mode facultatif | Distance cosinus ChromaDB ; motif de fallback uniquement en cas de panne |

L'index lexical neutralise la syntaxe FTS5 de la requête en ne gardant que les
tokens de mots, chacun entre guillemets. Il est dérivé exclusivement des chunks
ChromaDB. ChromaDB reste l'autorité : une panne lexicale dégrade la recherche
mais ne rend pas l'index vectoriel invalide.

Chaque hit Markdown contient son titre ou son chemin, la section et le heading,
une pertinence vectorielle lorsque disponible, un verdict de fraîcheur et le
texte du chunk. Un hit uniquement lexical porte la pertinence `lexical-only`.
Une recherche vide de résultats indique encore le mode et le motif de fallback
éventuel.

<!-- spec:indexing -->
## 4. Pipeline d'indexation et de synchronisation

| Étape | Contrat observable |
|---|---|
| Sélection vault | Seuls les `.md` et `.pdf` dans la portée `kb_path` configurée sont candidats ; les dossiers pointés et les denylist sont exclus |
| Sélection ingestion | Seuls les fichiers `.md` listés par le manifeste sous `documents/` dans la génération choisie par `current.json` sont candidats |
| Snapshot | Markdown est décodé en UTF-8 strict ; PDF est lu et extrait depuis le même snapshot binaire immutable |
| Chunking | H1-H3 pour Markdown, pages pour PDF, fenêtre de 512 caractères, overlap de 64 et fusion des petites queues sous 300 caractères |
| Identité | `{path}::{content_hash}::{chunking_contract_version}::{ordinal}` avec chemin POSIX relatif, SHA-256 des octets exacts et version `v3` |
| Publication vectorielle | Upsert ChromaDB par lots de 100, puis relecture et vérification de tous les IDs et métadonnées attendus |
| Suppression | Les anciens IDs ne sont supprimés qu'après publication vérifiée de la nouvelle version |
| Index lexical | SQLite FTS5 est mis à jour après ChromaDB et reconstruit depuis ChromaDB s'il est absent, incompatible ou désynchronisé |

Le chunk Markdown conserve le titre de frontmatter simple lorsqu'il existe,
sinon le stem du fichier. Le chunk PDF porte un titre dérivé du nom de fichier
et un heading `Page N`. Tous les chunks portent le schema de métadonnées v2,
dont `source_kind`, `source_system`, les IDs stables de source/conteneur, le
titre, l'auteur, les dates source, l'URI canonique, le chemin relatif, la
section, la date de capture, le `content_hash` logique et `chunk_index`. Les
métadonnées internes de l'index portent aussi le hash du fichier exact, le
nombre de chunks attendu, le contrat de fraîcheur et la version du contrat de
chunking.

Le sync est hash-aware. Une version déjà complète et cohérente est ignorée. Un
fichier devenu absent, exclu, vide ou trop grand est retiré des deux index.
Tout document dont le corps est vide ou trop grand à découper incrémente
`empty_files`, qu'il ait eu ou non du contenu indexé à retirer, et chacun est
journalisé en `file_not_indexable`. Un document sans contenu indexable n'est pas
une erreur : `errors` reste inchangé. Une erreur de lecture, de décodage,
d'extraction ou de publication incrémente `errors` et préserve l'ancienne
version vectorielle. La réconciliation reste
bornée à la section en cours ; en mode dossier entier, la section interne
réservée `.` représente tout `kb_path`. Un sync complet réconcilie aussi
`source_kind=doc` dans la section `sources`. Il lit uniquement la génération
courante complète et préserve les lignes documentaires existantes lorsque la
source, le pointeur, le manifeste ou le répertoire `documents` est indisponible
ou incomplet.

<!-- spec:freshness -->
## 5. Contrat de fraîcheur v1

Le contrat observable porte l'identifiant `freshness-contract-v1` et la version
de hash `v1`. Le `file_content_hash` interne est le SHA-256 minuscule des octets
exacts lus : aucune normalisation de fins de ligne, de BOM ou d'Unicode n'est
appliquée. Pour un document Markdown généré, le `content_hash` public peut
porter le hash de frontmatter valide du corps Markdown normalisé fourni par le
producteur ; l'identité fichier et la fraîcheur utilisent toujours
`file_content_hash`. Les octets PDF sont hashés tels quels ; Markdown doit en
plus être un UTF-8 valide.

| Statut | Signification |
|---|---|
| `fresh` | Tous les chunks indexés partagent le contrat courant et leur hash égale le snapshot vivant |
| `stale` | Le contrat est cohérent mais le hash vivant diffère |
| `unknown` | Métadonnées legacy, incomplètes, incohérentes ou hors contrat courant |
| `unindexed` | Source éligible produisant des chunks, mais aucun chunk indexé |
| `no_chunks` | Source présente mais vide ou au-dessus de la limite de taille |
| `missing` | Chemin indexé absent du corpus vivant |
| `excluded` | Source vivante ou chemin indexé maintenant exclu par la politique |
| `error` | Chemin indexé non fiable, lecture impossible, UTF-8 invalide ou extraction en erreur |

Le rapport contient toujours `contract_id`, `read_only: true`,
`freshness_is_not_completeness: true`, le scope, un résumé par statut et
`duration_ms`. Les entrées détaillées sont absentes par défaut dans l'outil MCP
et ajoutées seulement avec `include_entries=true`. Les dossiers hors politique
sont listés dans le scope, sans être présentés comme des sources indexables.

La fraîcheur est diagnostiquée, jamais réparée automatiquement. Cortex
n'installe pas de watcher et ne lance pas de sweep implicite avant une lecture.
Il faut exécuter `cortex sync`, `sync.bat` ou `cortex_sync` après une modification
du corpus. `cortex_search` rehash chaque chemin unique retourné dans son propre
domaine : `kb_path` pour les hits du vault et la racine `documents/` de la
génération courante pour les hits `doc`. Une racine indisponible préserve le hit
et marque sa fraîcheur `unavailable`.

Quand l'état d'ingestion existe, `cortex_freshness` retourne aussi une fraîcheur
en deux étages. L'étage source rapporte la santé remote-to-disk ; l'étage index
intègre une comparaison `ingestion_index` dédiée entre la génération courante
et les lignes `doc` indexées. Le rapport d'ingestion est omis lorsque ce domaine
est absent.

<!-- spec:integrity-concurrency -->
## 6. Intégrité de l'index et concurrence

La collection ChromaDB `cortex` utilise la distance cosinus et un fingerprint
composé du modèle d'embedding, de la version FastEmbed et du pooling `mean`.
Une divergence refuse la recherche et les écritures, car les espaces vectoriels
ne sont pas compatibles. Un index legacy sans fingerprint n'est estampillé que
si son contrat attesté correspond exactement au runtime courant.

| Opération | Verrou et comportement |
|---|---|
| Recherche et rapport de fraîcheur | Aucun verrou de sync sur les lectures en régime établi |
| Création ou estampillage de collection | Verrou exclusif avant toute mutation ChromaDB |
| Sync vectoriel et lexical | Un verrou exclusif couvre l'appel complet et se réutilise de façon réentrante dans le processus |
| Contention | Attente bornée à 30 secondes par défaut, puis `CortexWriteLockedError` sans écriture |
| Fin anormale du writer | Le verrou fichier de niveau OS est libéré automatiquement |

Plusieurs clients peuvent rechercher en parallèle. Une seule opération de sync
peut écrire à la fois ; les autres writers doivent attendre ou réessayer après
le timeout. Le chemin et le timeout du verrou sont configurables. Si la mise à
jour lexicale échoue après une publication vectorielle valide, ChromaDB reste
l'autorité et le prochain prepare lexical détecte l'écart d'IDs et reconstruit
FTS5.

<!-- spec:clients -->
## 7. Neuf clients MCP au scope utilisateur

Le registre de setup contient exactement neuf IDs. Cortex ne définit aucune
cible de configuration au scope projet.

| ID CLI | Client | Cible utilisateur | Format |
|---|---|---|---|
| `claude-desktop` | Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` | JSON `mcpServers.cortex` |
| `claude-code` | Claude Code | `claude mcp add --scope user` | CLI Claude, scope `user` |
| `codex` | Codex CLI et extension IDE | `~/.codex/config.toml` | TOML `[mcp_servers.cortex]` |
| `gemini` | Gemini CLI et Gemini Code Assist | `~/.gemini/settings.json` | JSON `mcpServers.cortex` |
| `antigravity` | Antigravity | `~/.gemini/config/mcp_config.json` | JSON `mcpServers.cortex` |
| `lmstudio` | LM Studio | `~/.lmstudio/mcp.json` | JSON `mcpServers.cortex` |
| `cursor` | Cursor | `~/.cursor/mcp.json` | JSON `mcpServers.cortex` |
| `windsurf` | Windsurf | `~/.codeium/windsurf/mcp_config.json` | JSON `mcpServers.cortex` |
| `vscode` | VS Code | `%APPDATA%\Code\User\mcp.json` | JSON `servers.cortex`, `type: stdio` |

Une installation Python enregistre l'interpréteur absolu avec `server.py`. Un
binaire autonome enregistre son propre chemin avec l'argument `serve`.
L'enregistrement et la désinstallation ne changent que l'entrée `cortex`,
préservent les autres serveurs et créent une sauvegarde avant la modification
d'un fichier existant. La détection est best-effort ; Antigravity exige son
profil live `~/.gemini/antigravity` pour éviter un faux positif Gemini.

<!-- spec:data-locations -->
## 8. Configuration et emplacements de données

| Donnée | Emplacement par défaut | Contrat |
|---|---|---|
| Base de connaissances | Chemin choisi dans `kb_path` | Source utilisateur, jamais supprimée par setup ou reset |
| Configuration | Windows : `%APPDATA%\Cortex\config.toml` ; autres : `~/.config/Cortex/config.toml` | TOML strict, `schema_version = 1`, clés inconnues refusées |
| Data home | Windows : `%LOCALAPPDATA%\Cortex` ; autres : `$XDG_DATA_HOME/Cortex` ou `~/.local/share/Cortex` | Racine des données générées propres au poste |
| Index vectoriel | `<data_home>/chroma_db` | Surchargeable par `chroma_path` |
| Index lexical | `<parent de chroma_path>/lexical.db` | SQLite FTS5 dérivé de ChromaDB |
| Verrou | `<data_home>/chroma_db.write.lock` | Surchargeable par config ou environnement |
| Modèles | `<data_home>/models` | Cache FastEmbed partagé par embedding et reranker |
| Logs | `<data_home>/logs/cortex.log` | 5 000 000 octets par fichier, cinq sauvegardes |

La précédence de configuration est environnement, puis TOML, puis défaut
produit. `CORTEX_KB_PATH` peut surcharger le corpus. Les limites par défaut sont
1 000 000 octets pour Markdown et 50 000 000 pour PDF. Les chemins indexés sont
stockés relativement à `kb_path` avec des séparateurs POSIX.

Si un index legacy existe à côté du code, Cortex refuse de créer un second
index actif. La migration utilise un renommage atomique sans fallback copie ;
si la source legacy et la cible existent toutes les deux, Cortex refuse de
choisir ou de fusionner.

<!-- spec:distribution -->
## 9. Distribution, modèles et release

| Canal | Contenu et contrat |
|---|---|
| Sources Python | Python 3.10 ou plus, pins directs dans `requirements.txt`, arbre transitif universel et hashé dans `requirements.lock` |
| Binaires autonomes | Windows x64, macOS arm64 et Linux x64 ; CLI et serveur stdio sans Python, modèles non embarqués |
| Installeur Windows | `Cortex-Setup.exe`, x64 compatible, sans élévation, binaire plus payload de modèles dans `%LOCALAPPDATA%\Cortex\models` |
| Métadonnées de release | `SHA256SUMS` pour les artefacts et attestation GitHub de provenance du build |

La version du package suit le CalVer `YYYY.MMDD.XX` en date UTC ; le compteur
sur deux chiffres distingue plusieurs releases le même jour. Un tag `v*`
déclenche les builds des trois plateformes. Seul un run de tag atteint le job
de publication ; `workflow_dispatch` construit sans publier.

La chaîne Windows échoue fermée. Le payload modèle est acquis depuis les
révisions de `models.lock`, comparé au manifeste SHA-256 commité, matérialisé
avec les seuls fichiers déclarés, puis re-vérifié. Le wrapper de build refuse
un exécutable absent, une version binaire différente, un payload modèle absent
ou vide et toute compilation directe sans defines valides. Au runtime, la
présence de `manifest.json` impose la vérification de chaque fichier avant les
imports ML, puis active `HF_HUB_OFFLINE=1`.

Les binaires autonomes nus et les installations depuis les sources n'embarquent
pas les modèles. Si leur cache est vide, le premier usage peut les télécharger.
Le workflow release smoke-teste séparément l'installeur Windows avec le réseau
Hugging Face forcé hors ligne.

<!-- spec:limits-security -->
## 10. Sécurité et limites assumées

| Limite | Contrat actuel |
|---|---|
| Transport MCP | stdio uniquement ; aucun endpoint HTTP ou WebSocket Cortex |
| Écriture documentaire | Aucun tool MCP n'écrit de contenu source ; `cortex_sync` écrit les index dérivés, tandis que des CLI de sources explicites peuvent publier des générations immuables hors de `kb_path` |
| Scope client | Enregistrement utilisateur uniquement ; aucun scope projet |
| Formats source | Markdown UTF-8 et PDF natif uniquement, avec limites de taille configurées |
| Détection des changements | Aucun watcher ; sync explicite requis |
| Chiffrement et authentification | Aucun chiffrement Cortex au repos et aucune authentification des clients MCP |
| Réseau | L'installeur vérifié fonctionne hors ligne ; source et binaire nu peuvent télécharger des modèles manquants ; le writer Confluence optionnel lit son origine HTTPS configurée |
| Secrets | Les PAT Confluence sont acceptés uniquement par une invite interactive et stockés dans Windows Credential Manager, jamais dans TOML, l'environnement, les arguments ou les logs |

ChromaDB est toujours ouvert par `chromadb.PersistentClient` avec
`anonymized_telemetry=False`. Cortex ne lance jamais le serveur HTTP ChromaDB,
n'utilise pas `HttpClient` et ne passe pas `trust_remote_code=true`. Pour cette
raison, le workflow CI ignore temporairement `PYSEC-2026-311`
(`CVE-2026-45829`), qui vise ce chemin serveur HTTP. Cet ignore unique doit être
retiré lorsqu'une version ChromaDB corrigée compatible peut être épinglée.

Cortex n'envoie pas le contenu du corpus vers un service distant. Un client MCP
est toutefois un produit distinct : il peut transmettre au modèle les chunks
qu'il a demandés selon sa propre politique. La confidentialité du poste, le
chiffrement disque et l'autorisation du client restent hors de la frontière
Cortex. Voir [security.md](security.md) et [faq.md](faq.md).

<!-- spec:version-license -->
## 11. Version de la spec, frontière documentaire et licence

| Version de la spec | Date | Changement |
|---|---|---|
| 2.1 | 2026-08-05 | Filtres metadata v2, générations d'ingestion, writer Confluence et fraîcheur en deux étages |
| 2.0 | 2026-07-21 | Première spécification publique alignée sur l'implémentation de `main` |

Cette spec est la référence des contrats observables du serveur MCP, des index,
du setup et de la distribution. La topologie interne et les raisons des choix
techniques restent dans [architecture.md](architecture.md) ; les réglages
opérationnels restent dans [configuration.md](configuration.md) et le parcours
utilisateur dans le [guide](user-guide.md).

Cette spec et l'implémentation de référence [Cortex](../../README.fr.md) sont
publiées sous la [licence Apache, version 2.0](../../LICENSE).
