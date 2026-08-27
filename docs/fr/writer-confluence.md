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

**Francais** | [English](../en/confluence-writer.md)

[Retour au sommaire](index.md)

Le writer Confluence enumere une liste blanche explicite d'espaces via REST
v1, ne telecharge que les pages nouvelles ou modifiees, puis lance un ou
plusieurs jobs ConfluenceRAGBuilder sequentiels par generation. Chaque job
respecte les limites de nombre de pages et d'octets serialises lues dans le
schema gele. L'infrastructure commune gere le verrou, les reprises, les
generations atomiques, le carry-forward, les tombstones, la retention et l'etat
de sante.

## Configuration

Le fichier writer optionnel est `%APPDATA%\Cortex\confluence.toml`. Les
variables `CORTEX_CONFLUENCE_...` priment sur TOML, qui prime sur les valeurs
par defaut. Aucun espace n'est actif par defaut.

```toml
schema_version = 2
base_url = "https://confluence.example.test"
credential_target = "cortex-spike"
auth_expires_at = "2026-11-01T00:00:00+01:00"
console_path = "C:/Tools/ConfluenceRAGBuilder.Console.exe"
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

`classification` accepte `perso-non-sensible` ou `pro-confidentiel`. Une cible
`pro-confidentiel` reste strictement locale et ne doit jamais etre commitee ni
partagee. La liste des espaces reste uniquement dans TOML : une variable
d'environnement heritee ne peut donc pas elargir silencieusement le perimetre.

Le schema v2 impose `selection` pour chaque espace. `whole_space` conserve le
chemin d'enumeration existant et refuse toute cle ou table `pages` presente,
meme vide. `pages` recupere uniquement les ID numeriques listes. Les ID sont
uniques dans leur espace et chaque page recue est controlee contre `space_key`
avant le staging de son contenu ou de ses pieces jointes.

Une selection vide est legale et doit etre explicite :

```toml
[[spaces]]
space_key = "EMPTY"
target = "knowledge/empty"
classification = "perso-non-sensible"
selection = "pages"
pages = []
```

Ce mode n'enumere aucun espace et ne collecte aucune page Confluence. Retirer
un ID apres une selection complete et reussie retire la page de la generation
suivante et produit son tombstone de document existant. Une page selectionnee
en echec compte dans `failure_threshold` ; elle n'est jamais stagee sous un
autre espace et le moteur commun applique ses regles existantes de
carry-forward et de publication.

Le schema v1 reste accepte sans migration. Une entree v1 ne porte ni
`selection` ni `pages`, signifie toujours `whole_space` et le fichier n'est pas
reecrit au chargement.

### Updates programmatiques atomiques

L'API de mutation partagee lit un seul snapshot d'octets, valide le modele a
partir de ces memes octets et utilise le SHA-256 minuscule du contenu exact
comme jeton CAS. Elle prend ensuite `<confluence.toml>.mutation.lock`, revalide
les octets courants, ecrit et `fsync` un temporaire dans le meme repertoire,
valide ce temporaire sans surcharge d'environnement, puis remplace la cible
atomiquement.

Un update ecrit les octets precedents exacts dans `confluence.toml.bak` avant
le replace de la cible. Une creation initiale ne produit pas de backup. La
reecriture canonique utilise UTF-8 et LF ; les commentaires ne restent pas dans
la nouvelle cible mais demeurent disponibles octet pour octet dans le backup.
Le serialiseur preserve les antislashs Windows, les apostrophes et les URL avec
port explicite. Un conflit CAS ou un lock occupe ne tombe jamais en
last-write-wins.

Ce lock protege uniquement les writers TOML. Il est distinct du lock de sync
d'ingestion et du lock d'ecriture Chroma. Aucune commande CLI de mutation n'est
encore exposee.

## Stocker le PAT

Dans un terminal controle par l'operateur :

```powershell
cortex confluence store-credential
```

L'invite utilise `getpass` et ecrit un identifiant generique dans Windows
Credential Manager. Le PAT n'est jamais accepte en argument, variable
d'environnement ou fichier, et n'est jamais affiche. `auth_expires_at` est une
donnee de configuration, pas un secret.

## Synchronisation et planification

Le schema de metadonnees v2 est requis avant une publication reelle. Le build
courant declare `METADATA_SCHEMA_VERSION = 2` ; le CLI verifie encore cette
barriere avant de lire les credentials ou de contacter Confluence et echoue en
mode ferme si un deploiement futur ou plus ancien ne la respecte pas.

Une fois ce prerequis livre, le Planificateur de taches peut lancer :

```powershell
cortex confluence sync
```

`--force` est reserve a une execution demandee par un operateur. Sinon, le
rattrapage et la cadence de l'infrastructure commune s'appliquent. Le compte de
tache doit acceder a son Credential Manager et a la racine d'ingestion.

L'expiration declaree du credential est controlee avant le lancement du writer.
Un credential expire ou indisponible enregistre une erreur et laisse la
generation precedente servie. La revocation distante du PAT est appliquee par
le serveur Confluence : Cortex l'observe a la prochaine requete authentifiee.
La cadence de synchronisation, et non un cache local du token, borne donc la
duree de presence d'un contenu deja indexe.

Le `README.md` de chaque zone publiee declare les fichiers en lecture seule
pour les humains. Toute modification manuelle est remplacee a la prochaine
generation reussie.

## CLI lisible par une machine

Resoudre un page ID numerique, une URL `viewpage`, une URL
`/spaces/SPACE/pages/ID/Titre`, une URL `/display/SPACE/Titre` ou un tiny link
Kazan `/x/CLE` :

```powershell
cortex confluence resolve "https://kazan.example.test/display/DOC/Run+Book" --json
```

En cas de succes, stdout contient exactement un document JSON. Les erreurs et
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

`configured` vaut true pour une page d'un mapping `whole_space` autorise. Pour
un mapping `pages`, il vaut true uniquement si le page ID est deja liste. Une
page resolue dans un espace hors allowlist est refusee.

Lister les espaces configures, les pages explicitement selectionnees, les
titres connus localement et l'etat global du sync sans reseau ni credential :

```powershell
cortex confluence pages --json
```

```json
{
  "contract_version": 1,
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
    "error_code": null
  }
}
```

Pour `whole_space`, `pages` vaut `null`. Sans generation courante, les titres
des pages configurees valent `null` ; sans etat de sante, les trois champs de
`last_sync` valent `null`.

Le contrat d'exit codes est stable et ne demande aucun parsing de texte humain :

| Code | Signification |
|---:|---|
| `0` | Succes, dont sync publie ou resultat JSON valide |
| `1` | Erreur generale ou de configuration |
| `2` | Lock de sync ingestion deja pris |
| `3` | Sync non requis a cet instant |
| `4` | Credential absent/expire ou authentification distante refusee |
| `5` | Echec reseau ou REST Confluence |
| `6` | Entree `resolve` invalide |
| `7` | Page introuvable |
| `8` | Page resolue hors allowlist d'espaces |

Les codes `0`, `1` et `3` gardent leur signification existante. Tous les
echecs restent non nuls pour le Planificateur de taches, tandis que les codes
dedies exposent une cause exploitable.

## Contrat du convertisseur

Le package vendore `job.schema.json` et `result.schema.json` octet pour octet
depuis le commit ConfluenceRAGBuilder
`fceda69da9246e9cf927ca7b8ad68a330f5a7b9b`. Les deux payloads sont valides en
JSON Schema draft 2020-12. Une divergence de hash ou de format echoue en mode
ferme.

Le writer decoupe le travail dans `batch-0001`, `batch-0002` et les repertoires
suivants, lance la console sequentiellement et applique le seuil d'echec a toute
la generation. Une page dont l'enregistrement serialise ne tient pas sous la
limite d'octets du schema echoue avec `job_payload_too_large` ; les autres pages
continuent.

Un `body.storage.value` explicitement present et vide est un corps de page
valide. Un champ absent, null ou non chaine echoue toujours en mode ferme. Les
octets d'une piece jointe sont stages sous un nom Windows-safe prefixe par son
ID, tandis que `file_name` conserve le titre Confluence original pour la
resolution des macros. Les caracteres Windows invalides, noms de peripheriques
reserves, points/espaces terminaux et la limite de 255 caracteres sont traites
avant le lancement de la console.

Seuls les `markdown_paths` des pages `converted` sont consommes. Les pieces
jointes laissees dans le repertoire de travail par une page `failed` n'entrent
jamais dans une generation publiee.
