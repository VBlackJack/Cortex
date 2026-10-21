# Architecture

**Français** | [English](../en/architecture.md)

[Retour au sommaire](index.md)

## Fonctionnement de bout en bout

```
kb_path (.md, .pdf)                  REST Confluence sur liste blanche
      |                                        |
      |                              confluence_writer/
      |                                        |
      |                           ingestion/doc/current.json
      |                                        |
      +------------------+---------------------+
                         |
                         v
  indexer.py             <- Decoupe, hash, vectorise, reconcilie
      |
      +--> chroma_db/    <- Index vectoriel
      +--> lexical.db    <- Index SQLite FTS5
      |
      v
  server.py              <- Serveur MCP (FastMCP)
      |
      v
  Clients MCP            <- Claude / Codex / Gemini
```

Cortex indexe deux domaines de sources isolés. Les fichiers Markdown et PDF
choisis par l'utilisateur vivent sous `kb_path` avec `source_kind=note`. Les
writers optionnels publient des générations Markdown immuables sous la racine
d'ingestion avec `source_kind=doc` ; seule la génération désignée par
`current.json` est éligible. `indexer.py` écrit ChromaDB et SQLite FTS5, puis
`server.py` expose la recherche hybride structurée et la fraîcheur en lecture
seule aux clients MCP.

## Mode par client ou mode partagé

Par défaut (`[server] mode = "per-client"`), chaque session de client MCP lance
son propre `cortex serve`, qui charge le modèle d'embedding, ouvre l'index et ne
sert que ce client. Trente sessions ouvertes font trente processus complets.

Avec `mode = "shared"`, la ligne de commande inscrite dans les clients reste
`cortex serve`, mais elle devient un relais léger :

```
client MCP --stdio--> cortex serve (relais) --+
client MCP --stdio--> cortex serve (relais) --+--> point local --> cortex daemon run
client MCP --stdio--> cortex serve (relais) --+                    (un par utilisateur)
```

**Ce qui est partagé.** Le démon héberge l'unique instance FastMCP et ses quatre
outils, le modèle d'embedding, le reranker, un client Chroma et une connexion
lexicale en lecture seule, le verrou d'écriture et les journaux. Chaque
connexion garde sa propre session MCP : initialisation, identifiants de requête
et annulation. Les outils synchrones s'exécutent dans des threads de travail :
une longue `cortex_sync` ne gèle jamais les autres sessions ; les lectures
passent une à une, et une seconde sync lancée depuis une autre session reçoit la
même réponse "locked" qu'une sync bloquée par un autre processus.

**Voir les autres écrivains.** Un client Chroma de longue durée ne voit pas les
vecteurs écrits par un autre processus : son segment vectoriel reste tel qu'il a
été chargé. Le démon rouvre donc son client avant une lecture dès que les
fichiers de l'index ont changé et que le verrou d'écriture est de nouveau libre :
une `cortex sync` lancée depuis une console ou une tâche planifiée est visible
dès la recherche suivante.

**Sécurité du point d'accès.** Aucun port TCP n'est jamais ouvert. Sous Windows,
le point d'accès est le named pipe `\\.\pipe\cortex-<SID utilisateur>-v1`, créé
avec une DACL qui n'accorde l'accès qu'à l'utilisateur courant,
`FILE_FLAG_FIRST_PIPE_INSTANCE` et `PIPE_REJECT_REMOTE_CLIENTS` ; le démon
vérifie que chaque processus client appartient au même utilisateur, et le relais
vérifie la même chose du processus serveur. Ailleurs, c'est un socket Unix dans
un répertoire 0700 appartenant à l'utilisateur, le socket lui-même en 0600, avec
vérification de l'uid du pair là où la plateforme l'expose. Chaque connexion
s'ouvre par une trame versionnée de 4 Kio au plus, qui porte un jeton aléatoire
de 32 octets que le démon écrit dans `<data home>\daemon\token` à chaque
démarrage ; les lignes JSON-RPC sont ensuite limitées à 8 Mio. Le jeton n'est
jamais journalisé.

**Cycle de vie.**

- Un démon par utilisateur, tenu par `<data home>\daemon\daemon.lock` ; le
  système le libère si le processus meurt.
- Le premier relais qui ne trouve pas de démon en lance un, détaché, puis
  l'attend 10 secondes au plus ; au-delà, il sert lui-même la session en mode
  par client.
- Le démon se draine et s'arrête après `idle_timeout_seconds` sans session,
  quand `config.toml` change (il résout la configuration une fois au démarrage,
  comme tout processus Cortex), sur `cortex daemon stop`, ou quand un relais
  d'une version plus récente le demande. Un drainage laisse finir les requêtes
  en cours, une sync toujours.
- Quand la connexion se ferme, le relais répond une erreur JSON-RPC pour une
  requête en cours, sans jamais la rejouer, puis se reconnecte et rejoue
  l'échange `initialize` de la session. Après trois pertes en cinq minutes, il
  sert le reste de la session dans son propre processus.
- Un relais dont l'environnement `CORTEX_*` diffère de celui du démon, ou qui
  rencontre un démon plus récent ou un point d'accès tenu par un autre
  processus, sert sa session en mode par client. Il ne prend jamais le contrôle
  d'un point d'accès.

Limite connue : un client qui place ses serveurs dans un job Windows tué à la
fermeture sans autoriser la sortie du job (c'est le cas du client du SDK MCP
Python) tue aussi, en se fermant, le démon que son relais a lancé ; les autres
relais en lancent alors un nouveau.

## Structure du projet

```
<install_dir>\          <- Peu importe ou vous clonez Cortex
|-- config.py           <- Contrats produit et configuration resolue
|-- user_config.py      <- Chargement TOML strict et initialisation atomique
|-- chunker.py          <- Decoupe les .md en chunks (headers + taille fixe)
|-- chunker_pdf.py      <- Decoupe les .pdf en chunks (pdfplumber + taille fixe)
|-- chunker_utils.py    <- Fonctions partagees (hash, split, paths)
|-- indexer.py          <- Sync incrementale vers ChromaDB
|-- lexical_index.py    <- Index SQLite FTS5 derive
|-- freshness.py        <- Fraicheur du vault et de la generation courante
|-- ingestion\          <- Generations atomiques, planification, sante, credentials
|-- confluence_writer\  <- Source REST sur liste blanche et pont console
|-- server.py           <- Serveur MCP FastMCP (4 outils Cortex)
|-- daemon_*.py         <- Mode partage : demon, relais, point d'acces, trames
|-- sync.bat            <- Developpement : sync section par section (%~dp0)
|-- install.bat         <- Developpement : installation depuis le clone (%~dp0)
|-- setup_config.py     <- Enregistrement multi-client sur + validation
|-- cli.py              <- Dispatcher des sous-commandes cortex
|-- pyproject.toml      <- Packaging et configuration des outils qualite
|-- requirements.txt    <- Source unique des dependances runtime epinglees
|-- requirements.lock   <- Arbre transitif verrouille par hash (voir install reproductible)
|-- conftest.py         <- Bootstrap pytest (sys.path)
|-- tests\              <- Tests unitaires (chunker) + integration (search)
\-- chroma_db\          <- Ancien emplacement, migre vers le data home utilisateur
```

## Choix techniques

### Pourquoi ONNX / fastembed ?

PyTorch et sentence-transformers détectaient le GPU pendant l'initialisation et
causaient un BSOD (dxgkrnl.sys). Le modèle ONNX via `fastembed` tourne
entièrement sur CPU, utilise ~150 Mo de RAM, et ne touche pas au GPU.

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

Chaque section est un processus Python indépendant dans `sync.bat`. Cela limite
la RAM à ~300 Mo par processus (contre un pic unique si tout est en mémoire) et
permet de reprendre facilement en cas d'erreur.

### Pourquoi l'index incrémental est scopé par section ?

Sans scoping, un sync de la section `operations` pouvait voir les fichiers de
`knowledge` comme "supprimés" et les effacer. La comparaison et les suppressions
sont maintenant limitées à la section en cours.

Le domaine documentaire d'ingestion est réconcilié indépendamment des lignes
du vault. Seule la génération `doc` courante est prise en compte ; une
génération absente, pending ou incomplète préserve les lignes documentaires
déjà indexées au lieu de les purger.

### Pourquoi 512 caractères par chunk ?

Le modèle `paraphrase-multilingual-MiniLM-L12-v2` tronque toute entrée à 128
tokens maximum. Tout ce qui dépasse n'est jamais vu par l'embedding. En
français, 1 token vaut environ 3,5 caractères, donc 512 caractères valent
environ 145 tokens, légèrement au-dessus du plafond théorique, mais le chunker
coupe sur des frontières naturelles (retour à la ligne, fin de phrase) ce qui
produit en pratique des chunks plus courts. Les chunks plus longs (~2000 chars
utilisés au début du projet) faisaient perdre 70 à 80 % du contenu indexé à
l'embedding.

### Pourquoi les chemins en metadata sont relatifs ?

Le `path` stocké dans un chunk du vault est relatif à `CORTEX_KB_PATH` (par
exemple `operations/architecture.md`). Le chemin d'un chunk d'ingestion est
relatif au répertoire `documents` de la génération courante. Chaque domaine
reste ainsi portable et possède une identité stable pour la réconciliation,
sans mélanger le vault et les documents générés.

### Pourquoi tout est portable ?

Les chemins d'installation sont portables. `kb_path` est fourni par la
configuration utilisateur ou `CORTEX_KB_PATH` ; aucune valeur propre à une
machine n'est codée dans les sources :

- `config.py` résout `CHROMA_PATH` vers `%LOCALAPPDATA%\Cortex\chroma_db` ou la
  surcharge utilisateur.
- Les scripts de développement `install.bat` et `sync.bat` utilisent `%~dp0` :
  ils trouvent eux-mêmes leur dossier d'exécution.
- `setup_config.py` détecte sa propre localisation pour enregistrer le serveur
  dans chaque client.
- `%APPDATA%\Cortex\config.toml` sépare les choix roaming du code livré ;
  `%LOCALAPPDATA%\Cortex` contient les données propres au poste.

Conséquence : un développeur peut cloner Cortex dans n'importe quel dossier sur
n'importe quelle machine, lancer `install.bat` et travailler depuis ce clone.
L'utilisateur final ne clone rien : `Cortex-Setup.exe` ou une archive autonome
installe le même code sous forme de dossier d'exécutable autonome.
