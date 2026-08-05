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

# Planifier l'ingestion sous Windows

**Francais** | [English](../en/ingestion-scheduling.md)

[Retour au sommaire](index.md)

Le package d'ingestion gere la detection d'une fenetre manquee, les reprises
transitoires bornees, les controles d'expiration des credentials et le verrou de
chevauchement propre a la source. Le Planificateur de taches Windows doit
uniquement lancer le CLI Cortex installe selon la cadence voulue.

Utiliser `cortex ingestion due SOURCE_KIND` a l'ouverture de session. Le code de
sortie `0` signifie que l'intervalle configure est ecoule et que la commande de
source doit s'executer. Le code `3` signifie qu'aucun rattrapage n'est requis.
Utiliser `cortex ingestion status SOURCE_KIND` pour lire le dernier snapshot de
sante atomique. Une erreur de configuration ou de stockage renvoie le code `1`.

Les adaptateurs de sources appellent `ingestion.cli.execute_scheduled_attempt`
depuis leur point d'entree CLI. Les regles de reprise, rattrapage, verrouillage
et duree de vie des credentials restent ainsi hors des definitions du
Planificateur de taches.

Le fichier de reglages d'ingestion optionnel est
`%APPDATA%\Cortex\ingestion.toml`. Les variables prefixees par
`CORTEX_INGESTION_` priment sur TOML, qui prime sur les valeurs par defaut du
package. Aucun secret n'est accepte par ce fichier, les variables
d'environnement ou les arguments CLI. L'operateur cree ou renouvelle les
credentials generiques interactivement dans Windows Credential Manager.

```toml
schema_version = 1
data_root = "C:\\Users\\<YOUR_ACCOUNT>\\AppData\\Local\\Cortex\\ingestion"
retention_generations = 2
auth_expiry_warning_days = 14
lock_timeout_seconds = 0
retry_attempts = 4
backoff_initial_seconds = 1
backoff_max_seconds = 60
backoff_multiplier = 2
backoff_jitter_ratio = 0.2
schedule_interval_seconds = 86400
```

Chaque cle ci-dessus est optionnelle ; le fichier lui-meme peut etre absent. La
valeur par defaut de `data_root` est `%LOCALAPPDATA%\Cortex\ingestion`.
L'option globale `--config` permet d'inspecter un autre fichier sans changer le
defaut :

```powershell
cortex ingestion --config <INGESTION_CONFIG> status doc
cortex ingestion --config <INGESTION_CONFIG> due doc
```

Le compte de tache doit avoir les droits de lecture et d'ecriture sur la racine
d'ingestion configuree et le droit de lire son entree Windows Credential
Manager. Le contenu publie est selectionne par un pointeur de generation
remplace atomiquement ; l'operateur ne doit jamais modifier manuellement les
repertoires de generations.

Pour l'adaptateur Confluence courant, le Planificateur de taches peut lancer
`cortex confluence sync` ; l'adaptateur effectue lui-meme le controle de
cadence. `cortex confluence sync --force` est reserve a une execution
explicitement demandee par un operateur.
