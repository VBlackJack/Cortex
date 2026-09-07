# Sécurité

**Français** | [English](../en/security.md)

[Retour au sommaire](index.md)

## Runtime local et accès réseau bornés

Tous les clients Chroma sont construits avec
`Settings(anonymized_telemetry=False)` : aucune télémétrie Chroma/PostHog n'est
émise. Cortex n'envoie pas le contenu de la base pendant l'indexation ou la
recherche. Le writer Confluence optionnel effectue uniquement des lectures HTTPS
authentifiées vers l'origine configurée et la liste blanche explicite d'espaces.
L'installeur Windows vérifié embarque les modèles et fonctionne hors ligne ; une
installation depuis les sources ou un binaire autonome peut joindre Hugging
Face si un modèle manque dans le cache local. Les clients MCP restent des
produits distincts : selon leur politique, ils peuvent transmettre au modèle
les résultats d'outils qu'ils ont demandés.

## Frontière du credential Confluence

Le PAT Confluence est saisi par `getpass` et stocké comme credential Windows
générique pour le compte de tâche courant. Il n'est jamais accepté comme
argument CLI, variable d'environnement ou valeur TOML. Les wrappers de secret
rédactent leurs représentations texte et les logs ne contiennent que les noms
de cible et les types d'erreur.

Cortex contrôle `auth_expires_at` avant une tentative planifiée. Un credential
expiré ou illisible empêche la publication et préserve la génération
précédente. La révocation distante reste un contrat du serveur Confluence :
Cortex observe le rejet lors de la prochaine requête authentifiée et ne garde
pas de second cache du token.

## Transport du PAT Confluence

Le PAT voyage en en-tête `Authorization: Bearer` sur chaque requête, donc deux
règles encadrent le transport.

`base_url` doit être en `https`. Une origine `http` distante est refusée à la
validation de la configuration, du côté Cortex comme du côté Companion, parce
qu'elle publierait le jeton en clair sur le réseau. Les hôtes de bouclage
(`localhost`, `127.0.0.1`, `::1`) restent acceptés en `http` : aucun paquet ne
quitte la machine.

Aucune redirection HTTP ne sort de l'origine choisie. L'opener urllib par défaut
rejoue tous les en-têtes de requête, `Authorization` compris, vers l'hôte nommé
par une redirection, quel qu'il soit. Le transport Cortex résout donc lui-même
les redirections : il compare l'origine de chaque saut à celle de la requête
initiale, refuse le saut si elle diffère, et borne le nombre de sauts. Une
instance Confluence compromise ou un intermédiaire ne peuvent pas faire suivre
le jeton vers une origine tierce.

## Vulnérabilité ChromaDB ignorée (PYSEC-2026-311)

L'audit CI ignore explicitement une vulnérabilité : `PYSEC-2026-311`
(CVE-2026-45829), une RCE pré-authentification du serveur HTTP de ChromaDB via
son API REST avec `trust_remote_code=true`. Elle n'est pas exploitable dans
Cortex : Cortex utilise un `PersistentClient` embarqué, jamais le serveur HTTP
ChromaDB, et le modèle ONNX est fixé localement via fastembed, donc le chemin
`trust_remote_code` n'est jamais emprunté. Un scan confirme l'absence de tout
`HttpClient` dans les sources. L'ignore est documenté dans le workflow CI et
doit être retiré dès qu'une version corrigée de ChromaDB est publiée (bump du
pin).

## Écriture single-writer (write lock)

ChromaDB (backend SQLite) n'accepte qu'un seul écrivain à la fois. Deux
incidents de corruption de l'index (segfault, puis desync HNSW/métadonnées) ont
eu la même cause racine : deux écritures concurrentes sur la même DB
(typiquement `server.py` respawné par Claude Desktop pendant qu'un sync tournait
déjà).

Chaque point d'écriture Chroma acquiert maintenant un verrou inter-processus
exclusif (`filelock`, niveau OS, auto-libéré si le process qui le détient meurt,
que ce soit crash, kill ou respawn) avant de toucher la DB. Si un second
écrivain tente d'écrire pendant qu'un premier détient le verrou, il échoue
proprement (`CortexWriteLockedError`, timeout borné, jamais d'attente infinie).
`cortex_sync` renvoie alors un message "locked, réessayer plus tard" plutôt
qu'une erreur brute. La lecture (`cortex_search`, `cortex_freshness`) n'est
jamais bloquée : Chroma autorise les lectures concurrentes, seule l'écriture est
single-writer.

Preuve (voir `tests/test_write_lock.py`, 4 tests, processus réels et DB isolée) :
deux écrivains concurrents produisent exactement un succès et un échec propre,
intégrité DB préservée ; scénario respawn-pendant-sync reproduit et bloqué ;
lecture non bloquée pendant qu'un écrivain détient le verrou ; écrivain tué
brutalement (crash simulé) donne un verrou libéré automatiquement, sans deadlock
permanent. Configurable via `CORTEX_WRITE_LOCK_PATH` et
`CORTEX_WRITE_LOCK_TIMEOUT_SECONDS` (`config.toml`, 30 s par défaut).

## Logs sans contenu sensible

Les logs locaux (`%LOCALAPPDATA%\Cortex\logs\cortex.log`, rotation 5 Mo x 5) ne
contiennent jamais le texte des documents ou des chunks : uniquement chemins,
statuts, erreurs et compteurs opérationnels. Les fichiers TOML utilisateur,
ingestion et Confluence ne contiennent jamais de secret.

## Portée et limites

Cortex protège la disponibilité et l'intégrité de son index local. Il ne
chiffre pas la base au repos : sur un poste où la confidentialité l'exige, la
copie locale doit être protégée par le chiffrement disque (BitLocker ou
équivalent). Cortex ne gère pas non plus l'authentification des clients MCP :
c'est la responsabilité de chaque client.
