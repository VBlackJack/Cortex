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

Le writer Confluence enumere une liste blanche explicite d'espaces via REST
v1, ne telecharge que les pages nouvelles ou modifiees, puis lance un seul
processus ConfluenceRAGBuilder par generation. L'infrastructure commune gere le
verrou, les reprises, les generations atomiques, le carry-forward, les
tombstones, la retention et l'etat de sante.

## Configuration

Le fichier writer optionnel est `%APPDATA%\Cortex\confluence.toml`. Les
variables `CORTEX_CONFLUENCE_...` priment sur TOML, qui prime sur les valeurs
par defaut. Aucun espace n'est actif par defaut.

```toml
schema_version = 1
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
```

`classification` accepte `perso-non-sensible` ou `pro-confidentiel`. Une cible
`pro-confidentiel` reste strictement locale et ne doit jamais etre commitee ni
partagee. La liste des espaces reste uniquement dans TOML : une variable
d'environnement heritee ne peut donc pas elargir silencieusement le perimetre.

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

Le rechunk metadonnees v2 doit etre deploye avant la premiere publication
reelle. Tant que Cortex n'expose pas ce contrat deploye,
`cortex confluence sync` s'arrete avant la lecture du secret et avant tout appel
Confluence.

Une fois ce prerequis livre, le Planificateur de taches peut lancer :

```powershell
cortex confluence sync
```

`--force` est reserve a une execution demandee par un operateur. Sinon, le
rattrapage et la cadence de l'infrastructure commune s'appliquent. Le compte de
tache doit acceder a son Credential Manager et a la racine d'ingestion.

Le `README.md` de chaque zone publiee declare les fichiers en lecture seule
pour les humains. Toute modification manuelle est remplacee a la prochaine
generation reussie.

## Contrat du convertisseur

Le package vendore `job.schema.json` et `result.schema.json` octet pour octet
depuis le commit ConfluenceRAGBuilder
`fceda69da9246e9cf927ca7b8ad68a330f5a7b9b`. Les deux payloads sont valides en
JSON Schema draft 2020-12. Une divergence de hash ou de format echoue en mode
ferme.

Seuls les `markdown_paths` des pages `converted` sont consommes. Les pieces
jointes laissees dans le repertoire de travail par une page `failed` n'entrent
jamais dans une generation publiee.
