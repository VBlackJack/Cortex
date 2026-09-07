---
verified: 2026-09-01
tested_on: "CortexCompanion 2026.0901.05 / Windows / .NET 10"
---

<!--
Copyright 2026 Julien Bombled

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Writer Confluence

**Français** | [English](../en/confluence-writer.md)

[Retour au sommaire](index.md)

Le writer Confluence énumère une liste blanche explicite d'espaces via REST
v1, ne télécharge que les pages nouvelles ou modifiées, puis lance un ou
plusieurs jobs ConfluenceRAGBuilder séquentiels par génération. Chaque job
respecte les limites de nombre de pages et d'octets sérialisés lues dans le
schema gelé. L'infrastructure commune gère le verrou, les reprises, les
générations atomiques, le carry-forward, les tombstones, la rétention et l'état
de santé.

## Gestion des sources dans Companion (2026.0906.02)

La version appariée 2026.0906.02 propose **Mes sources**, un éditeur pré-rempli,
le retrait confirmé de pages ou d'espaces et l'ouverture des originaux dans
Confluence. Les retraits modifient uniquement le suivi Cortex et prennent effet
dans la recherche après une collecte et une indexation réussies.

Le retrait de la dernière source écrit explicitement `spaces = []` dans une
configuration schema v2 ou v3. Cette liste volontairement vide autorise une
publication vide avec les tombstones des anciens documents. Une clé `spaces`
absente reste une configuration incomplète et la collecte est refusée.
Les validations de connexion, de credentials et les protections de publication
restent applicables. Cette capacité requiert Cortex et Companion 2026.0906.02 ou ultérieurs ;
elle n'est pas disponible dans la release installée 2026.0906.01.


## Configuration

Le fichier writer optionnel est `%APPDATA%\Cortex\confluence.toml`. Les
variables `CORTEX_CONFLUENCE_...` priment sur TOML, qui prime sur les valeurs
par défaut. Aucun espace n'est actif par défaut.

### Initialisation guidée avec Companion

Quand le fichier n'existe pas, ouvrir `Pages Confluence` dans Companion :

1. Coller l'URL complète d'une première page Confluence.
2. Vérifier la clé d'espace détectée. Les URL `viewpage.action` et les liens
   courts ne la contiennent pas ; la saisir alors manuellement.
3. Choisir la date d'expiration déclarée du PAT et la classification. La valeur
   par défaut est `pro-confidentiel`.
4. Cliquer sur `Initialiser et ajouter la page`. Companion mesure alors la page
   seule, son sous-arbre et l'espace complet avant de demander le périmètre.
   Quand la racine a des descendants, `Cette page et son arborescence` est le
   choix recommandé et sélectionné par défaut.

Le convertisseur console est inclus dans l'installeur sous
`%LOCALAPPDATA%\Programs\Cortex\Converters`. Companion le détecte, vérifie son
contrat `--probe` et écrit le chemin automatiquement. Le choix manuel reste
masqué dans les options avancées pour les développeurs. Une application WPF ou
un binaire incompatible est refusé avant l'enregistrement.

Companion conserve le contexte d'instance tel que `/wiki`, crée une sélection
vide sous `confluence/<CLE_ESPACE>`, puis enregistre le périmètre confirmé par le
contrat Cortex. Les trois choix affichent leur nombre de pages et une estimation
de stockage avant toute écriture. La création utilise le verrou de mutation,
vérifie que le fichier est toujours absent, valide le rendu et le remplace
atomiquement. Le PAT ne transite jamais par ce fichier : il reste dans le
Gestionnaire d'identifiants Windows du compte courant.

Le TOML manuel ci-dessous reste disponible pour les configurations avancées ou
les environnements non Windows.

Sur un poste lent, le délai choisi dans `Réglages > Délai maximal des commandes
Cortex` s'applique aussi à la lecture de cette liste et à la résolution d'une
page. Choisir 60 ou 120 secondes, puis `Enregistrer et connecter`, si Cortex
met plusieurs secondes à démarrer. Un dépassement de délai est indiqué comme
tel ; il n'est plus présenté comme un refus de lecture du CLI.

`base_url` doit être en `https`, sauf pour un hôte de bouclage. Le PAT part en
en-tête `Authorization` sur chaque requête : une origine en clair le publierait
sur le réseau. Les redirections qui changent d'origine sont refusées, jamais
suivies. Voir [Sécurité](security.md).

```toml
schema_version = 2
base_url = "https://confluence.example.test"
credential_target = "cortex-spike"
auth_expires_at = "2026-11-01T00:00:00+01:00"
max_attachment_size_mb = 50
failure_threshold = 0.10

[[spaces]]
space_key = "DOC"
target = "knowledge/confluence"
classification = "perso-non-sensible"
selection = "whole_space"

[[spaces]]
space_key = "RUN"
target = "knowledge/runbooks"
classification = "pro-confidentiel"
selection = "pages"

[[spaces.pages]]
page_id = "379465380"

[[spaces.pages]]
page_id = "379465381"
```

Sur Windows installé, `console_path` est facultatif : Cortex utilise le binaire
livré avec l'application. Un chemin TOML ou
`CORTEX_CONFLUENCE_CONSOLE_PATH` remplace ce défaut uniquement pour un usage de
développement et doit répondre au probe console schema 1.

`classification` accepte `perso-non-sensible` ou `pro-confidentiel`. Une cible
`pro-confidentiel` reste strictement locale et ne doit jamais être commitée ni
partagée. La liste des espaces reste uniquement dans TOML : une variable
d'environnement héritée ne peut donc pas élargir silencieusement le périmètre.

Le schema v2 impose `selection` pour chaque espace. `whole_space` conserve le
chemin d'énumération existant et refuse toute clé ou table `pages` présente,
même vide. `pages` récupère uniquement les ID numériques listés. Les ID sont
uniques dans leur espace et chaque page reçue est contrôlée contre `space_key`
avant le staging de son contenu ou de ses pièces jointes.

Une sélection vide est légale. Les identifiants de page sont toujours des
tables `[[spaces.pages]]`, donc une sélection explicite qui ne contient rien
omet simplement la clef :

```toml
[[spaces]]
space_key = "EMPTY"
target = "knowledge/empty"
classification = "perso-non-sensible"
selection = "pages"
```

`pages = []` reste lu comme la même sélection vide, et reste la forme qu'écrit
Companion pour `selection = "subtree"`, où les deux lecteurs exigent la
présence de la clef et où TOML ne sait pas écrire une liste de tables vide.
En dehors de ce seul cas, la forme en ligne n'apparaît plus dans un fichier
écrit par Companion.

Ce mode n'énumère aucun espace et ne collecte aucune page Confluence. Retirer
un ID après une sélection complète et réussie retire la page de la génération
suivante et produit son tombstone de document existant. Une page sélectionnée
en échec compte dans `failure_threshold` ; elle n'est jamais stagée sous un
autre espace et le moteur commun applique ses règles existantes de
carry-forward et de publication.

Le schema v3 ajoute `selection = "subtree"`. La table `pages` liste alors des
racines de sous-arbre, et non l'ensemble complet des pages : chaque racine est
collectée avec toutes ses pages descendantes courantes, résolues au moment de
la collecte. Une racine sans descendant ne collecte qu'elle-même. Des racines
dont les sous-arbres se recouvrent collectent chaque page une seule fois. La
table `pages` doit être présente et peut être vide, exactement comme pour la
sélection `pages`, et `subtree` est refusé en schema v1 et v2.

```toml
[[spaces]]
space_key = "DOC"
target = "knowledge/doc"
classification = "perso-non-sensible"
selection = "subtree"

[[spaces.pages]]
page_id = "1001"
```

Les descendants sont lus par la recherche CQL `ancestor` et non par l'endpoint
`content/{id}/descendant/page`, qui répond HTTP 500 sur les déploiements Kazan
mesurés.

### Périmètre, stockage et rétention

`cortex confluence preview <reference> --json` résout la racine puis mesure les
trois choix avant une mutation : une page, son sous-arbre et l'espace entier.
L'estimation est volontairement approximative et utilise 384 Kio par page ; les
pièces jointes et le contenu réel peuvent produire un volume différent.

Le champ `target`, par exemple `confluence/CCSP`, est un préfixe logique dans la
génération et l'index. Ce n'est pas un dossier créé dans le Vault utilisateur.
Les documents publiés sont sous la racine d'ingestion, dans
`doc/generations/<generation_id>/documents`. Companion affiche cette racine,
`retention_generations` et propose d'ouvrir le dossier de la génération courante.
Le publisher atomique conserve au plus ce nombre de générations après une
publication réussie ; la valeur par défaut est `2`.

Le schema v1 reste accepté sans migration. Une entrée v1 ne porte ni
`selection` ni `pages`, signifie toujours `whole_space` et le fichier n'est pas
réécrit au chargement.

### Updates programmatiques atomiques

L'API de mutation partagée lit un seul snapshot d'octets, valide le modèle à
partir de ces mêmes octets et utilise le SHA-256 minuscule du contenu exact
comme jeton CAS. Elle prend ensuite `<confluence.toml>.mutation.lock`, revalide
les octets courants, écrit et `fsync` un temporaire dans le même répertoire,
valide ce temporaire sans surcharge d'environnement, puis remplace la cible
atomiquement.

Un update écrit les octets précédents exacts dans `confluence.toml.bak` avant
le replace de la cible. Une création initiale ne produit pas de backup. La
réécriture canonique utilise UTF-8 et LF ; les commentaires ne restent pas dans
la nouvelle cible mais demeurent disponibles octet pour octet dans le backup.
Le sérialiseur préserve les antislashs Windows, les apostrophes et les URL avec
port explicite. Un conflit CAS ou un lock occupé ne tombe jamais en
last-write-wins.

Ce lock protège uniquement les writers TOML. Il est distinct du lock de sync
d'ingestion et du lock d'écriture Chroma. Aucune commande CLI de mutation n'est
encore exposée.

Autoriser un espace ne demande pas de modifier le TOML à la main. Dans Cortex
Companion, l'écran `Pages` porte une carte `Autoriser un nouvel espace` : collez
l'URL de n'importe quelle page de l'espace, choisissez la classification, puis
confirmez. Companion lit la clef d'espace dans l'URL, refuse une URL qui ne
nomme aucun espace ou qui pointe vers un autre serveur Confluence, et écrit
l'entrée `[[spaces]]` sous le même verrou CAS que toute autre mutation. L'espace
entre vide, en mode pages explicites : l'autoriser ne collecte donc rien par
lui-même. Quand `Résoudre et ajouter` refuse une page parce que son espace n'est
pas autorisé, cette même carte est préremplie avec l'URL collée, et la confirmer
ajoute la page dans la foulée.

## Stocker le PAT

Stockez le PAT avant la première synchronisation Confluence et répétez
l'opération à chaque renouvellement du jeton. Si `CONFLUENCE.toml` n'existe
pas encore, Cortex et Companion utilisent la même cible Windows par défaut,
`cortex-spike`. Le fichier reste toutefois obligatoire avant d'ajouter des
pages ou de lancer une collecte, car il porte notamment `base_url`,
`auth_expires_at` et la liste blanche des espaces.

Avec Cortex Companion, ouvrez `Réglages > Authentification Confluence`,
saisissez le PAT dans le champ masqué, puis sélectionnez `Enregistrer le PAT`.
Companion lit la cible validée dans la configuration Confluence, ou reprend la
cible par défaut si le fichier est absent, puis écrit directement l'identifiant
générique du compte Windows courant dans le Gestionnaire d'identifiants Windows.
La valeur est protégée par DPAPI et n'est jamais copiée dans les réglages
Companion, le TOML ou les journaux. Si la configuration choisit plus tard une
autre cible, enregistrez de nouveau le PAT pour la cible affichée.

Pour une administration en ligne de commande, utilisez un terminal contrôlé
par l'opérateur :

```powershell
cortex confluence store-credential
```

L'invite utilise `getpass` et écrit un identifiant générique dans Windows
Credential Manager. Le PAT n'est jamais accepté en argument, variable
d'environnement ou fichier, et n'est jamais affiché. `auth_expires_at` est une
donnée de configuration, pas un secret.

## Synchronisation et planification

Le schema de métadonnées v2 est requis avant une publication réelle. Le build
courant déclare `METADATA_SCHEMA_VERSION = 2` ; le CLI vérifie encore cette
barrière avant de lire les credentials ou de contacter Confluence et échoue en
mode fermé si un déploiement futur ou plus ancien ne la respecte pas.

Une fois ce prérequis livré, le Planificateur de tâches peut lancer :

```powershell
cortex confluence sync
```

`--force` est réservé à une exécution demandée par un opérateur. Le bouton
`Collecter Confluence` de Companion l'utilise systématiquement : une action
manuelle n'est jamais bloquée par la cadence. Les exécutions planifiées gardent
le rattrapage et la cadence de l'infrastructure commune. Un hash canonique de la
sélection effective rend aussi une exécution due dès que le périmètre change.
Le compte de tâche doit accéder à son Credential Manager et à la racine
d'ingestion.

Pendant une collecte, stderr émet des lignes JSON préfixées par
`CORTEX_PROGRESS ` pour les phases `enumeration`, `staging`, `conversion` et
`publication`. Companion les affiche sous la forme phase et `n/total`. La
synchronisation locale `cortex sync` reste une action distincte et affiche sa
phase d'indexation.

L'expiration déclarée du credential est contrôlée avant le lancement du writer.
Un credential expiré ou indisponible enregistre une erreur et laisse la
génération précédente servie. La révocation distante du PAT est appliquée par
le serveur Confluence : Cortex l'observe à la prochaine requête authentifiée.
La cadence de synchronisation, et non un cache local du token, borne donc la
durée de présence d'un contenu déjà indexé.

Le `README.md` de chaque zone publiée déclare les fichiers en lecture seule
pour les humains. Toute modification manuelle est remplacée à la prochaine
génération réussie.

## CLI lisible par une machine

Résoudre un page ID numérique, une URL `viewpage`, une URL
`/spaces/SPACE/pages/ID/Titre`, une URL `/display/SPACE/Titre` ou un tiny link
Kazan `/x/CLE` :

```powershell
cortex confluence resolve "https://kazan.example.test/display/DOC/Run+Book" --json
```

En cas de succès, stdout contient exactement un document JSON. Les erreurs et
les logs ne partagent jamais stdout avec ce contrat :

```json
{
  "contract_version": 1,
  "page_id": "379465380",
  "title": "Run Book",
  "space_key": "DOC",
  "configured": true
}
```

`configured` vaut true pour une page d'un mapping `whole_space` autorisé. Pour
un mapping `pages`, il vaut true uniquement si le page ID est déjà listé. Une
page résolue dans un espace hors allowlist est refusée.

Mesurer le périmètre avant de modifier la configuration :

```powershell
cortex confluence preview "https://kazan.example.test/display/DOC/Run+Book" --json
```

`cortex confluence catalog <espace> --json` lit l'arborescence complète depuis la
liste de contenus, jamais depuis l'index de recherche : une page que le sélecteur
ne montre pas est une page que personne ne peut choisir. Elle coûte une requête
par tranche de 200 pages et prend environ deux minutes sur un espace de six
mille, donc elle émet des enregistrements `CORTEX_PROGRESS` sur stderr pour la
phase `enumeration`, comptés contre une estimation indexée obtenue en une
requête supplémentaire. Un déploiement incapable de répondre à cette estimation
obtient quand même son catalogue, en silence et sans progression.

Le contrat `preview` v1 fournit `page_only`, `subtree` et `whole_space`, chacun
avec `page_count` et `estimated_bytes`, ainsi que `recommended_selection`,
`storage_root` et `retention_generations`.

Les valeurs `subtree` et `whole_space` sont des comptages lus dans l'index de
recherche Confluence, une requête chacun. Énumérer un grand espace pour obtenir
ces deux entiers prenait plusieurs minutes et dépassait le délai de tout appelant
graphique. Trois conséquences en découlent.

- Les comptages viennent de l'index et sont filtrés par les permissions, alors
  que `sync` et `catalog` lisent la liste de contenus. Les deux divergent
  réellement, et pas seulement après un import massif ou pendant une
  réindexation : sur le déploiement mesuré, l'index contient 5916 pages d'un
  espace dont la liste en renvoie 5918, et les deux pages manquantes sont des
  pages courantes vieilles de plusieurs mois, donc aucune nouvelle tentative n'y
  changera rien. `last_sync.scope_summaries[].available_page_count` peut donc ne
  pas correspondre à un preview pris juste avant, d'un petit nombre plutôt que
  d'un ordre de grandeur.
- `whole_space` n'ajoute plus la racine résolue. Une racine qui n'est pas une
  page courante de l'espace n'est plus comptée deux fois, et un espace sans page
  visible mesure désormais zéro au lieu de un. `page_only` et `subtree` comptent
  toujours la racine elle-même.
- Le comptage du sous-arbre restreint sa requête à l'espace résolu : un
  descendant que le serveur rattache à un autre espace est donc exclu en
  silence, là où l'énumération effectuée par `sync` refuse le sous-arbre entier.
  Un preview peut ainsi mesurer un périmètre qu'une collecte ultérieure refuse.

Un déploiement dont le point d'entrée de recherche ne renvoie pas `totalSize` ne
peut pas répondre à un preview. La commande sort en `1` avec un message nommant
la requête, plutôt que de retomber sur l'énumération qu'elle existe pour éviter ;
le code `5` reste réservé aux échecs qu'une nouvelle tentative peut lever.

Lister les espaces configurés, les pages explicitement sélectionnées, les
titres connus localement et l'état global du sync sans réseau ni credential :

```powershell
cortex confluence pages --json
```

```json
{
  "contract_version": 2,
  "spaces": [
    {
      "space_key": "RUN",
      "selection": "pages",
      "target": "knowledge/runbooks",
      "classification": "pro-confidentiel",
      "pages": [
        {"page_id": "379465380", "title": "Run Book"},
        {"page_id": "379465381", "title": null}
      ]
    }
  ],
  "last_sync": {
    "last_success_at": "2026-08-05T10:00:00Z",
    "status": "ok",
    "error_code": null,
    "scope_summaries": [
      {
        "space_key": "RUN",
        "selection": "pages",
        "selected_page_count": 2,
        "available_page_count": 14,
        "excluded_descendant_count": 12
      }
    ]
  }
}
```

Pour `whole_space`, `pages` vaut `null`. Sans génération courante, les titres
des pages configurées valent `null` ; sans état de santé, les champs principaux
de `last_sync` valent `null` et `scope_summaries` est vide. Une sélection
`pages` qui exclut des descendants connus produit une synthèse exploitable par
l'action Companion `Élargir à l'arborescence`.

Le contrat d'exit codes est stable et ne demande aucun parsing de texte humain :

| Code | Signification |
|---:|---|
| `0` | Succès, dont sync publié ou résultat JSON valide |
| `1` | Erreur générale ou de configuration |
| `2` | Lock de sync ingestion déjà pris |
| `3` | Sync non requis à cet instant |
| `4` | Credential absent/expiré ou authentification distante refusée |
| `5` | Échec réseau ou REST Confluence |
| `6` | Entrée `resolve` invalide |
| `7` | Page introuvable |
| `8` | Page résolue hors allowlist d'espaces |

Les codes `0`, `1` et `3` gardent leur signification existante. Tous les
échecs restent non nuls pour le Planificateur de tâches, tandis que les codes
dédiés exposent une cause exploitable.

## Contrat du convertisseur

Le package vendore `job.schema.json` et `result.schema.json` octet pour octet
depuis le commit ConfluenceRAGBuilder
`fceda69da9246e9cf927ca7b8ad68a330f5a7b9b`. Les deux payloads sont valides en
JSON Schema draft 2020-12. Une divergence de hash ou de format échoue en mode
fermé.

Le writer découpe le travail dans `batch-0001`, `batch-0002` et les répertoires
suivants, lance la console séquentiellement et applique le seuil d'échec à toute
la génération. Une page dont l'enregistrement sérialisé ne tient pas sous la
limite d'octets du schema échoue avec `job_payload_too_large` ; les autres pages
continuent.

Si le taux d'échec dépasse `failure_threshold`, aucune nouvelle génération
n'est publiée et la précédente reste active. L'état de santé indique alors le
nombre de pages en échec sur le total demandé, le taux mesuré, le seuil appliqué
et les deux actions possibles : corriger puis relancer, ou augmenter le seuil de
façon délibérée pour autoriser une publication partielle.

Un espace configuré qui n'a rien collecté est signalé, jamais passé sous
silence. Chaque espace reçoit une ligne `confluence_space_collected` disant ce
qu'il a sélectionné et ce qui était disponible ; un espace dont la sélection
donne zéro page ajoute un avertissement `space_selection_empty`, et un espace
qui laisse des descendants de côté ajoute `space_selection_narrow`. La santé
publiée passe alors en `degraded` avec le code `space_selection_empty` : un
espace sans page n'a aucun document à échouer, et laisserait sinon la
synchronisation paraître saine. Les échecs réels gardent la priorité,
`partial_failure` l'emporte dès qu'un document a échoué ou a été reporté. La
ligne de fin de collecte porte désormais `spaces_configured` et
`spaces_with_pages` au lieu d'un compte unique, pour qu'un espace qui n'a rien
produit ne soit jamais compté comme un succès.

Au début de chaque collecte, Cortex balaie uniquement les répertoires directs,
non symboliques, nommés `%TEMP%\cortex-confluence-*` et âgés d'au moins 24 heures.
Les workspaces plus récents peuvent appartenir à une collecte encore active et
sont conservés.

Un `body.storage.value` explicitement présent et vide est un corps de page
valide. Un champ absent, null ou non chaîne échoue toujours en mode fermé. Les
octets d'une pièce jointe sont stagés sous un nom Windows-safe préfixé par son
ID, tandis que `file_name` conserve le titre Confluence original pour la
résolution des macros. Les caractères Windows invalides, noms de périphériques
réservés, points/espaces terminaux et la limite de 255 caractères sont traités
avant le lancement de la console.

Seuls les `markdown_paths` des pages `converted` sont consommés. Les pièces
jointes laissées dans le répertoire de travail par une page `failed` n'entrent
jamais dans une génération publiée.


## Liens de source Companion (2026.0906.01)

La résolution et la prévisualisation acceptent `/spaces/KEY`, `/spaces/KEY/overview`, `/spaces/KEY/pages` et `/display/KEY/`, avec le chemin de contexte configuré. Elles résolvent la page d'accueil via REST v1, vérifient l'espace et l'identifiant numérique retournés, puis mesurent les périmètres page, arborescence et espace entier. L'espace entier peut inclure des pages hors de l'arborescence d'accueil. Les origines étrangères et espaces hors liste autorisée sont refusés avant tout accès réseau. Ce support exige Cortex et Companion 2026.0906.01 ou ultérieur.

Référence REST : [API espaces Atlassian](https://developer.atlassian.com/server/confluence/rest/v9210/api-group-space/).

## Contrats de gestion des sources (non publiés)

`cortex confluence --config <fichier> catalog <CLE_ESPACE> --json` lit les titres
et les ancêtres des pages d'un espace déjà autorisé. Le contrat version 1 contient
`space_key` et `pages` (`page_id`, `title`, `ancestor_ids`). La lecture suit les
pages REST avec contrôle d'origine, limite de 10 000 pages et refus des données
incomplètes ; aucun contenu de page ou pièce jointe n'est téléchargé.

`cortex confluence --config <fichier> source-status --json` reste local, sans PAT
ni réseau. Le contrat version 1 expose `selection_current`, `generation_id` et
`status`. Companion compare aussi la génération indexée observée avant d'afficher
Disponible. Les contrats existants pages/resolve/preview restent inchangés.
