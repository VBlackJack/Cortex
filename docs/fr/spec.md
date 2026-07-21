# Cortex - Contrat public du serveur MCP et de l'index

**Francais** | [English](../en/spec.md)

> **Statut** : Spec v2.0 - normative, synchronisee avec `main`
> **Auteur** : Julien Bombled
> **Date** : 2026-07-21
> **Licence** : [Apache 2.0](../../LICENSE)
> **Portee** : Ce document definit les surfaces, formats et invariants observables de
> Cortex. Les choix de conception detailles restent dans
> [architecture.md](architecture.md).

Les mots "doit", "ne doit pas" et "jamais" expriment des contrats de
l'implementation actuelle. Ce document ne decrit aucun comportement futur ou
aspirationnel.

---

<!-- spec:identity -->
## 1. Identite du produit et frontiere de lecture

Cortex est un serveur RAG local et multi-client expose par MCP. Il indexe des
fichiers Markdown et PDF choisis par l'utilisateur, puis retourne aux clients
les passages juges pertinents. Les documents sous `kb_path` restent la source de
verite ; ChromaDB et l'index lexical sont des donnees derivees reconstructibles.

| Surface | Contrat observable |
|---|---|
| Documents source | Lecture seule : aucun outil MCP ne cree, ne modifie, ne renomme ou ne supprime un fichier Markdown ou PDF |
| Index derive | `cortex_sync` peut creer et modifier les index vectoriel et lexical locaux |
| Recherche | Lecture de l'index avec retour des chunks, reperes de source et verdict de fraicheur |
| Runtime | Traitement CPU local ; Cortex force `CUDA_VISIBLE_DEVICES` a une valeur vide |

La surface cliente est donc en lecture seule vis-a-vis du corpus, mais pas
vis-a-vis des donnees derivees : `cortex_sync` est une operation d'ecriture sur
l'index. Cortex ne fournit aucun outil d'edition de contenu, aucun journal de
mutations documentaires et aucun mecanisme d'ecriture dans `kb_path`.

<!-- spec:mcp-tools -->
## 2. Transport et surface des quatre outils MCP

Le point d'entree `cortex serve` lance FastMCP par `mcp.run()` sur stdio. Le CLI
Cortex n'expose aucun transport HTTP ou WebSocket et n'ouvre aucun listener
reseau. Le code du serveur enregistre exactement quatre tools et aucun resource
ou prompt MCP propre a Cortex.

| Tool | Parametres | Comportement | Format de reponse |
|---|---|---|---|
| `cortex_search` | `query: str`, `section: Optional[str] = None`, `top_k: int = 5` | Recherche hybride locale, avec fallback vectoriel et annotation de fraicheur | Markdown : mode, fallback eventuel, titre ou chemin, section, heading, pertinence, fraicheur et texte |
| `cortex_sync` | `section: Optional[str] = None` | Reconciliation incrementale d'une section ou de toute la portee configuree | Markdown : `published_files`, `added_chunks`, `deleted_chunks`, `removed_files`, `skipped_files`, `errors` |
| `cortex_list_sections` | aucun | Liste les sections incluses et les dossiers de premier niveau hors politique | Markdown : sections indexables puis dossiers `out of policy` |
| `cortex_freshness` | `section: Optional[str] = None`, `include_entries: bool = False` | Compare les sources vivantes aux metadonnees d'index sans les modifier | Objet structure : contrat, scope, resume, duree et, sur demande, entrees par fichier |

Les noms de section sont resolus sans tenir compte de la casse. Une section
inconnue retourne une erreur avec les sections disponibles. Les erreurs de
configuration, de migration, de fingerprint et de verrou sont converties en
reponses explicites ; elles ne deviennent pas des traces brutes cote client.

<!-- spec:search -->
## 3. Contrat de recherche hybride

`cortex_search` borne toujours `top_k` entre 1 et 10. En mode hybride, chaque
branche recupere au plus 20 candidats. Les resultats vectoriels ChromaDB et les
resultats lexicaux SQLite FTS5 sont fusionnes par Reciprocal Rank Fusion avec
`k = 60`, puis les 10 premiers candidats sont proposes au reranker ONNX
`jinaai/jina-reranker-v1-tiny-en`.

| Mode retourne | Condition | Ordre final |
|---|---|---|
| `hybrid+rerank` | Index lexical compatible et reranker disponible | Score du cross-encoder, avec ordre stable en cas d'egalite |
| `hybrid` | Fusion disponible mais reranker non charge ou en erreur | Ordre RRF, avec motif de degradation |
| `vector-only` | Index lexical absent, incompatible ou illisible | Distance cosinus ChromaDB, avec motif de fallback |

L'index lexical neutralise la syntaxe FTS5 de la requete en ne gardant que les
tokens de mots, chacun entre guillemets. Il est derive exclusivement des chunks
ChromaDB. ChromaDB reste l'autorite : une panne lexicale degrade la recherche
mais ne rend pas l'index vectoriel invalide.

Chaque hit Markdown contient son titre ou son chemin, la section et le heading,
une pertinence vectorielle lorsque disponible, un verdict de fraicheur et le
texte du chunk. Un hit uniquement lexical porte la pertinence `lexical-only`.
Une recherche vide de resultats indique encore le mode et le motif de fallback
eventuel.

<!-- spec:indexing -->
## 4. Pipeline d'indexation et de synchronisation

| Etape | Contrat observable |
|---|---|
| Selection | Seuls les `.md` et `.pdf` dans la portee configuree sont candidats ; les dossiers pointes et les denylist sont exclus |
| Snapshot | Markdown est decode en UTF-8 strict ; PDF est lu et extrait depuis le meme snapshot binaire immutable |
| Chunking | H1-H3 pour Markdown, pages pour PDF, fenetre de 512 caracteres, overlap de 64 et fusion des petites queues sous 300 caracteres |
| Identite | `{path}::{content_hash}::{chunking_contract_version}::{ordinal}` avec chemin POSIX relatif, SHA-256 des octets exacts et version `v3` |
| Publication vectorielle | Upsert ChromaDB par lots de 100, puis relecture et verification de tous les IDs et metadonnees attendus |
| Suppression | Les anciens IDs ne sont supprimes qu'apres publication verifiee de la nouvelle version |
| Index lexical | SQLite FTS5 est mis a jour apres ChromaDB et reconstruit depuis ChromaDB s'il est absent, incompatible ou desynchronise |

Le chunk Markdown conserve le titre de frontmatter simple lorsqu'il existe,
sinon le stem du fichier. Le chunk PDF porte un titre derive du nom de fichier
et un heading `Page N`. Tous les chunks portent `path`, `section`, `title`,
`header`, `chunk_index`, `content_hash`, `expected_chunk_count`, le contrat de
fraicheur et la version du contrat de chunking.

Le sync est hash-aware. Une version deja complete et coherente est ignoree. Un
fichier devenu absent, exclu, vide ou trop grand est retire des deux index. Une
erreur de lecture, de decodage, d'extraction ou de publication incremente
`errors` et preserve l'ancienne version vectorielle. La reconciliation reste
bornee a la section en cours ; en mode dossier entier, la section interne
reservee `.` represente tout `kb_path`.

<!-- spec:freshness -->
## 5. Contrat de fraicheur v1

Le contrat observable porte l'identifiant `freshness-contract-v1` et la version
de hash `v1`. `content_hash` est le SHA-256 minuscule des octets exacts lus :
aucune normalisation de fins de ligne, de BOM ou d'Unicode n'est appliquee. Les
octets PDF sont hashes tels quels ; Markdown doit en plus etre un UTF-8 valide.

| Statut | Signification |
|---|---|
| `fresh` | Tous les chunks indexes partagent le contrat courant et leur hash egale le snapshot vivant |
| `stale` | Le contrat est coherent mais le hash vivant differe |
| `unknown` | Metadonnees legacy, incompletes, incoherentes ou hors contrat courant |
| `unindexed` | Source eligible produisant des chunks, mais aucun chunk indexe |
| `no_chunks` | Source presente mais vide ou au-dessus de la limite de taille |
| `missing` | Chemin indexe absent du corpus vivant |
| `excluded` | Source vivante ou chemin indexe maintenant exclu par la politique |
| `error` | Chemin indexe non fiable, lecture impossible, UTF-8 invalide ou extraction en erreur |

Le rapport contient toujours `contract_id`, `read_only: true`,
`freshness_is_not_completeness: true`, le scope, un resume par statut et
`duration_ms`. Les entrees detaillees sont absentes par defaut dans l'outil MCP
et ajoutees seulement avec `include_entries=true`. Les dossiers hors politique
sont listes dans le scope, sans etre presentes comme des sources indexables.

La fraicheur est diagnostiquee, jamais reparee automatiquement. Cortex
n'installe pas de watcher et ne lance pas de sweep implicite avant une lecture.
Il faut executer `cortex sync`, `sync.bat` ou `cortex_sync` apres une modification
du corpus. `cortex_search` rehash chaque chemin unique retourne ; sans `kb_path`
accessible, il conserve les hits et marque leur fraicheur `unavailable`.

<!-- spec:integrity-concurrency -->
## 6. Integrite de l'index et concurrence

La collection ChromaDB `cortex` utilise la distance cosinus et un fingerprint
compose du modele d'embedding, de la version FastEmbed et du pooling `mean`.
Une divergence refuse la recherche et les ecritures, car les espaces vectoriels
ne sont pas compatibles. Un index legacy sans fingerprint n'est estampille que
si son contrat atteste correspond exactement au runtime courant.

| Operation | Verrou et comportement |
|---|---|
| Recherche et rapport de fraicheur | Aucun verrou de sync sur les lectures en regime etabli |
| Creation ou estampillage de collection | Verrou exclusif avant toute mutation ChromaDB |
| Sync vectoriel et lexical | Un verrou exclusif couvre l'appel complet et se reutilise de facon reentrante dans le processus |
| Contention | Attente bornee a 30 secondes par defaut, puis `CortexWriteLockedError` sans ecriture |
| Fin anormale du writer | Le verrou fichier de niveau OS est libere automatiquement |

Plusieurs clients peuvent rechercher en parallele. Une seule operation de sync
peut ecrire a la fois ; les autres writers doivent attendre ou reessayer apres
le timeout. Le chemin et le timeout du verrou sont configurables. Si la mise a
jour lexicale echoue apres une publication vectorielle valide, ChromaDB reste
l'autorite et le prochain prepare lexical detecte l'ecart d'IDs et reconstruit
FTS5.

<!-- spec:clients -->
## 7. Neuf clients MCP au scope utilisateur

Le registre de setup contient exactement neuf IDs. Cortex ne definit aucune
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

Une installation Python enregistre l'interpreteur absolu avec `server.py`. Un
binaire autonome enregistre son propre chemin avec l'argument `serve`.
L'enregistrement et la desinstallation ne changent que l'entree `cortex`,
preservent les autres serveurs et creent une sauvegarde avant la modification
d'un fichier existant. La detection est best-effort ; Antigravity exige son
profil live `~/.gemini/antigravity` pour eviter un faux positif Gemini.

<!-- spec:data-locations -->
## 8. Configuration et emplacements de donnees

| Donnee | Emplacement par defaut | Contrat |
|---|---|---|
| Base de connaissances | Chemin choisi dans `kb_path` | Source utilisateur, jamais supprimee par setup ou reset |
| Configuration | Windows : `%APPDATA%\Cortex\config.toml` ; autres : `~/.config/Cortex/config.toml` | TOML strict, `schema_version = 1`, cles inconnues refusees |
| Data home | Windows : `%LOCALAPPDATA%\Cortex` ; autres : `$XDG_DATA_HOME/Cortex` ou `~/.local/share/Cortex` | Racine des donnees generees propres au poste |
| Index vectoriel | `<data_home>/chroma_db` | Surchargeable par `chroma_path` |
| Index lexical | `<parent de chroma_path>/lexical.db` | SQLite FTS5 derive de ChromaDB |
| Verrou | `<data_home>/chroma_db.write.lock` | Surchargeable par config ou environnement |
| Modeles | `<data_home>/models` | Cache FastEmbed partage par embedding et reranker |
| Logs | `<data_home>/logs/cortex.log` | 5 000 000 octets par fichier, cinq sauvegardes |

La precedence de configuration est environnement, puis TOML, puis defaut
produit. `CORTEX_KB_PATH` peut surcharger le corpus. Les limites par defaut sont
1 000 000 octets pour Markdown et 50 000 000 pour PDF. Les chemins indexes sont
stockes relativement a `kb_path` avec des separateurs POSIX.

Si un index legacy existe a cote du code, Cortex refuse de creer un second
index actif. La migration utilise un renommage atomique sans fallback copie ;
si la source legacy et la cible existent toutes les deux, Cortex refuse de
choisir ou de fusionner.

<!-- spec:distribution -->
## 9. Distribution, modeles et release

| Canal | Contenu et contrat |
|---|---|
| Sources Python | Python 3.10 ou plus, pins directs dans `requirements.txt`, arbre transitif universel et hashe dans `requirements.lock` |
| Binaires autonomes | Windows x64, macOS arm64 et Linux x64 ; CLI et serveur stdio sans Python, modeles non embarques |
| Installeur Windows | `Cortex-Setup.exe`, x64 compatible, sans elevation, binaire plus payload de modeles dans `%LOCALAPPDATA%\Cortex\models` |
| Metadonnees de release | `SHA256SUMS` pour les artefacts et attestation GitHub de provenance du build |

La version du package suit le CalVer `YYYY.MMDD.XX` en date UTC ; le compteur
sur deux chiffres distingue plusieurs releases le meme jour. Un tag `v*`
declenche les builds des trois plateformes. Seul un run de tag atteint le job
de publication ; `workflow_dispatch` construit sans publier.

La chaine Windows echoue fermee. Le payload modele est acquis depuis les
revisions de `models.lock`, compare au manifeste SHA-256 commite, materialise
avec les seuls fichiers declares, puis re-verifie. Le wrapper de build refuse
un executable absent, une version binaire differente, un payload modele absent
ou vide et toute compilation directe sans defines valides. Au runtime, la
presence de `manifest.json` impose la verification de chaque fichier avant les
imports ML, puis active `HF_HUB_OFFLINE=1`.

Les binaires autonomes nus et les installations depuis les sources n'embarquent
pas les modeles. Si leur cache est vide, le premier usage peut les telecharger.
Le workflow release smoke-teste separement l'installeur Windows avec le reseau
Hugging Face force hors ligne.

<!-- spec:limits-security -->
## 10. Securite et limites assumees

| Limite | Contrat actuel |
|---|---|
| Transport MCP | stdio uniquement ; aucun endpoint HTTP ou WebSocket Cortex |
| Ecriture documentaire | Aucun tool MCP n'ecrit dans la base de connaissances ; `cortex_sync` ecrit seulement les index derives |
| Scope client | Enregistrement utilisateur uniquement ; aucun scope projet |
| Formats source | Markdown UTF-8 et PDF natif uniquement, avec limites de taille configurees |
| Detection des changements | Aucun watcher ; sync explicite requis |
| Chiffrement et authentification | Aucun chiffrement Cortex au repos et aucune authentification des clients MCP |
| Reseau | L'installeur verifie fonctionne hors ligne ; source et binaire nu peuvent telecharger des modeles manquants |

ChromaDB est toujours ouvert par `chromadb.PersistentClient` avec
`anonymized_telemetry=False`. Cortex ne lance jamais le serveur HTTP ChromaDB,
n'utilise pas `HttpClient` et ne passe pas `trust_remote_code=true`. Pour cette
raison, le workflow CI ignore temporairement `PYSEC-2026-311`
(`CVE-2026-45829`), qui vise ce chemin serveur HTTP. Cet ignore unique doit etre
retire lorsqu'une version ChromaDB corrigee compatible peut etre epinglee.

Cortex n'envoie pas le contenu du corpus vers un service distant. Un client MCP
est toutefois un produit distinct : il peut transmettre au modele les chunks
qu'il a demandes selon sa propre politique. La confidentialite du poste, le
chiffrement disque et l'autorisation du client restent hors de la frontiere
Cortex. Voir [security.md](security.md) et [faq.md](faq.md).

<!-- spec:version-license -->
## 11. Version de la spec, frontiere documentaire et licence

| Version de la spec | Date | Changement |
|---|---|---|
| 2.0 | 2026-07-21 | Premiere specification publique alignee sur l'implementation de `main` |

Cette spec est la reference des contrats observables du serveur MCP, des index,
du setup et de la distribution. La topologie interne et les raisons des choix
techniques restent dans [architecture.md](architecture.md) ; les reglages
operationnels restent dans [configuration.md](configuration.md) et le parcours
utilisateur dans le [guide](user-guide.md).

Cette spec et l'implementation de reference [Cortex](../../README.md) sont
publiees sous la [licence Apache, version 2.0](../../LICENSE).
