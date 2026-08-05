# Securite

**Francais** | [English](../en/security.md)

[Retour au sommaire](index.md)

## Runtime local et acces reseau bornes

Tous les clients Chroma sont construits avec
`Settings(anonymized_telemetry=False)` : aucune telemetrie Chroma/PostHog n'est
emise. Cortex n'envoie pas le contenu de la base pendant l'indexation ou la
recherche. Le writer Confluence optionnel effectue uniquement des lectures HTTPS
authentifiees vers l'origine configuree et la liste blanche explicite d'espaces.
L'installeur Windows verifie embarque les modeles et fonctionne hors ligne ; une
installation depuis les sources ou un binaire autonome peut joindre Hugging
Face si un modele manque dans le cache local. Les clients MCP restent des
produits distincts : selon leur politique, ils peuvent transmettre au modele
les resultats d'outils qu'ils ont demandes.

## Frontiere du credential Confluence

Le PAT Confluence est saisi par `getpass` et stocke comme credential Windows
generique pour le compte de tache courant. Il n'est jamais accepte comme
argument CLI, variable d'environnement ou valeur TOML. Les wrappers de secret
redactent leurs representations texte et les logs ne contiennent que les noms
de cible et les types d'erreur.

Cortex controle `auth_expires_at` avant une tentative planifiee. Un credential
expire ou illisible empeche la publication et preserve la generation
precedente. La revocation distante reste un contrat du serveur Confluence :
Cortex observe le rejet lors de la prochaine requete authentifiee et ne garde
pas de second cache du token.

## Vulnerabilite ChromaDB ignoree (PYSEC-2026-311)

L'audit CI ignore explicitement une vulnerabilite : `PYSEC-2026-311`
(CVE-2026-45829), une RCE pre-authentification du serveur HTTP de ChromaDB via
son API REST avec `trust_remote_code=true`. Elle n'est pas exploitable dans
Cortex : Cortex utilise un `PersistentClient` embarque, jamais le serveur HTTP
ChromaDB, et le modele ONNX est fixe localement via fastembed, donc le chemin
`trust_remote_code` n'est jamais emprunte. Un scan confirme l'absence de tout
`HttpClient` dans les sources. L'ignore est documente dans le workflow CI et
doit etre retire des qu'une version corrigee de ChromaDB est publiee (bump du
pin).

## Ecriture single-writer (write lock)

ChromaDB (backend SQLite) n'accepte qu'un seul ecrivain a la fois. Deux
incidents de corruption de l'index (segfault, puis desync HNSW/metadonnees) ont
eu la meme cause racine : deux ecritures concurrentes sur la meme DB
(typiquement `server.py` respawne par Claude Desktop pendant qu'un sync tournait
deja).

Chaque point d'ecriture Chroma acquiert maintenant un verrou inter-processus
exclusif (`filelock`, niveau OS, auto-libere si le process qui le detient meurt,
que ce soit crash, kill ou respawn) avant de toucher la DB. Si un second
ecrivain tente d'ecrire pendant qu'un premier detient le verrou, il echoue
proprement (`CortexWriteLockedError`, timeout borne, jamais d'attente infinie).
`cortex_sync` renvoie alors un message "locked, reessayer plus tard" plutot
qu'une erreur brute. La lecture (`cortex_search`, `cortex_freshness`) n'est
jamais bloquee : Chroma autorise les lectures concurrentes, seule l'ecriture est
single-writer.

Preuve (voir `tests/test_write_lock.py`, 4 tests, processus reels et DB isolee) :
deux ecrivains concurrents produisent exactement un succes et un echec propre,
integrite DB preservee ; scenario respawn-pendant-sync reproduit et bloque ;
lecture non bloquee pendant qu'un ecrivain detient le verrou ; ecrivain tue
brutalement (crash simule) donne un verrou libere automatiquement, sans deadlock
permanent. Configurable via `CORTEX_WRITE_LOCK_PATH` et
`CORTEX_WRITE_LOCK_TIMEOUT_SECONDS` (`config.toml`, 30 s par defaut).

## Logs sans contenu sensible

Les logs locaux (`%LOCALAPPDATA%\Cortex\logs\cortex.log`, rotation 5 Mo x 5) ne
contiennent jamais le texte des documents ou des chunks : uniquement chemins,
statuts, erreurs et compteurs operationnels. Les fichiers TOML utilisateur,
ingestion et Confluence ne contiennent jamais de secret.

## Portee et limites

Cortex protege la disponibilite et l'integrite de son index local. Il ne
chiffre pas la base au repos : sur un poste ou la confidentialite l'exige, la
copie locale doit etre protegee par le chiffrement disque (BitLocker ou
equivalent). Cortex ne gere pas non plus l'authentification des clients MCP :
c'est la responsabilite de chaque client.
