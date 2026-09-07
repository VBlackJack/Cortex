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

**Français** | [English](../en/ingestion-scheduling.md)

[Retour au sommaire](index.md)

Le package d'ingestion gère la détection d'une fenêtre manquée, les reprises
transitoires bornées, les contrôles d'expiration des credentials et le verrou de
chevauchement propre à la source. Le Planificateur de tâches Windows doit
uniquement lancer le CLI Cortex installé selon la cadence voulue.

Utiliser `cortex ingestion due SOURCE_KIND` à l'ouverture de session. Le code de
sortie `0` signifie que l'intervalle configuré est écoulé et que la commande de
source doit s'exécuter. Le code `3` signifie qu'aucun rattrapage n'est requis.
Utiliser `cortex ingestion status SOURCE_KIND` pour lire le dernier snapshot de
santé atomique. Une erreur de configuration ou de stockage renvoie le code `1`.
Pour Confluence, le nom convivial `confluence` et le nom canonique `doc`
consultent le même snapshot ; toute autre valeur est refusée avant l'accès au
stockage.

Les adaptateurs de sources appellent `ingestion.cli.execute_scheduled_attempt`
depuis leur point d'entrée CLI. Les règles de reprise, rattrapage, verrouillage
et durée de vie des credentials restent ainsi hors des définitions du
Planificateur de tâches.

Le fichier de réglages d'ingestion optionnel est
`%APPDATA%\Cortex\ingestion.toml`. Les variables préfixées par
`CORTEX_INGESTION_` priment sur TOML, qui prime sur les valeurs par défaut du
package. Aucun secret n'est accepté par ce fichier, les variables
d'environnement ou les arguments CLI. L'opérateur crée ou renouvelle les
credentials génériques interactivement dans Windows Credential Manager.

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

Chaque clé ci-dessus est optionnelle ; le fichier lui-même peut être absent. La
valeur par défaut de `data_root` est `%LOCALAPPDATA%\Cortex\ingestion`.
L'option globale `--config` permet d'inspecter un autre fichier sans changer le
défaut :

```powershell
cortex ingestion --config <INGESTION_CONFIG> status doc
cortex ingestion --config <INGESTION_CONFIG> due doc
```

Le compte de tâche doit avoir les droits de lecture et d'écriture sur la racine
d'ingestion configurée et le droit de lire son entrée Windows Credential
Manager. Le contenu publié est sélectionné par un pointeur de génération
remplacé atomiquement ; l'opérateur ne doit jamais modifier manuellement les
répertoires de générations.

Pour l'adaptateur Confluence courant, le Planificateur de tâches peut lancer
`cortex confluence sync` ; l'adaptateur effectue lui-même le contrôle de
cadence. `cortex confluence sync --force` est réservé à une exécution
explicitement demandée par un opérateur.
