# Architecture

**Francais** | [English](../en/architecture.md)

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

Cortex indexe deux domaines de sources isoles. Les fichiers Markdown et PDF
choisis par l'utilisateur vivent sous `kb_path` avec `source_kind=note`. Les
writers optionnels publient des generations Markdown immuables sous la racine
d'ingestion avec `source_kind=doc` ; seule la generation designee par
`current.json` est eligible. `indexer.py` ecrit ChromaDB et SQLite FTS5, puis
`server.py` expose la recherche hybride structuree et la fraicheur en lecture
seule aux clients MCP.

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
|-- sync.bat            <- Lance le sync section par section (portable, %~dp0)
|-- install.bat         <- Installation / reinstallation en un clic (portable)
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

PyTorch et sentence-transformers detectaient le GPU pendant l'initialisation et
causaient un BSOD (dxgkrnl.sys). Le modele ONNX via `fastembed` tourne
entierement sur CPU, utilise ~150 Mo de RAM, et ne touche pas au GPU.

### Pourquoi un fingerprint d'embedding ?

L'index et les requetes doivent utiliser exactement le meme espace vectoriel.
Cortex stocke donc dans les metadonnees Chroma le modele, la version de
`fastembed` et le pooling (`mean`, contrat explicite depuis le correctif
qdrant/fastembed#436 actif en v0.6.0 pour ce modele). Au demarrage, avant une
recherche et avant toute ecriture, Cortex refuse l'acces si une valeur differe
et indique la procedure de reconstruction. L'index historique atteste le
2026-07-12 est migre une seule fois vers le fingerprint
`fastembed=0.8.0 / pooling=mean`.

### Pourquoi un sync section par section ?

Chaque section est un processus Python independant dans `sync.bat`. Cela limite
la RAM a ~300 Mo par processus (contre un pic unique si tout est en memoire) et
permet de reprendre facilement en cas d'erreur.

### Pourquoi l'index incremental est scope par section ?

Sans scoping, un sync de la section `operations` pouvait voir les fichiers de
`knowledge` comme "supprimes" et les effacer. La comparaison et les suppressions
sont maintenant limitees a la section en cours.

Le domaine documentaire d'ingestion est reconcilie independamment des lignes
du vault. Seule la generation `doc` courante est prise en compte ; une
generation absente, pending ou incomplete preserve les lignes documentaires
deja indexees au lieu de les purger.

### Pourquoi 512 caracteres par chunk ?

Le modele `paraphrase-multilingual-MiniLM-L12-v2` tronque toute entree a 128
tokens maximum. Tout ce qui depasse n'est jamais vu par l'embedding. En
francais, 1 token vaut environ 3,5 caracteres, donc 512 caracteres valent
environ 145 tokens, legerement au-dessus du plafond theorique, mais le chunker
coupe sur des frontieres naturelles (retour a la ligne, fin de phrase) ce qui
produit en pratique des chunks plus courts. Les chunks plus longs (~2000 chars
utilises au debut du projet) faisaient perdre 70 a 80 % du contenu indexe a
l'embedding.

### Pourquoi les chemins en metadata sont relatifs ?

Le `path` stocke dans un chunk du vault est relatif a `CORTEX_KB_PATH` (par
exemple `operations/architecture.md`). Le chemin d'un chunk d'ingestion est
relatif au repertoire `documents` de la generation courante. Chaque domaine
reste ainsi portable et possede une identite stable pour la reconciliation,
sans melanger le vault et les documents generes.

### Pourquoi tout est portable ?

Les chemins d'installation sont portables. `kb_path` est fourni par la
configuration utilisateur ou `CORTEX_KB_PATH` ; aucune valeur propre a une
machine n'est codee dans les sources :

- `config.py` resout `CHROMA_PATH` vers `%LOCALAPPDATA%\Cortex\chroma_db` ou la
  surcharge utilisateur.
- `install.bat` et `sync.bat` utilisent `%~dp0` : ils trouvent eux-memes leur
  dossier d'execution.
- `setup_config.py` detecte sa propre localisation pour enregistrer le serveur
  dans chaque client.
- `%APPDATA%\Cortex\config.toml` separe les choix roaming du code livre ;
  `%LOCALAPPDATA%\Cortex` contient les donnees propres au poste.

Consequence : tu peux cloner Cortex dans n'importe quel dossier sur n'importe
quelle machine, lancer `install.bat`, et c'est operationnel.
