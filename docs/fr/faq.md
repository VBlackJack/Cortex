# Questions fréquentes

**Français** | [English](../en/faq.md)

[Retour au sommaire](index.md)

Ces réponses décrivent le comportement actuel de Cortex. Pour les procédures
détaillées, voir l'[installation Windows](installation-windows.md),
l'[installation depuis les sources](setup.md), la
[configuration](configuration.md), le [guide d'utilisation](user-guide.md) et la
[sécurité](security.md).

<!-- faq:install-or-source -->
## Dois-je utiliser l'installeur Windows ou installer Cortex depuis les sources ?

Utilise `Cortex-Setup.exe` pour une installation Windows standard. Il n'exige pas
Python, installe l'application dans `%LOCALAPPDATA%\Programs\Cortex`, ajoute les
raccourcis et le `PATH` utilisateur, et fournit le payload de modèles vérifié.
C'est la voie recommandée pour un poste utilisateur.

L'installation depuis les sources demande Python 3.10 ou plus. Choisis-la pour
développer Cortex, modifier le code ou tester une révision qui n'est pas encore
publiée. `install.bat` installe les dépendances, initialise la configuration et
propose l'enregistrement des clients. Les binaires autonomes macOS et Linux
n'exigent pas Python non plus.

<!-- faq:data-locations -->
## Où vivent la configuration, l'index, les modèles et les logs, et quelle place prévoir ?

La configuration légère vit dans `%APPDATA%\Cortex\config.toml`. Par défaut, les
données locales générées vivent sous `%LOCALAPPDATA%\Cortex` :

- `chroma_db\` contient l'index vectoriel ;
- `models\` contient les modèles ONNX ;
- `logs\cortex.log` et ses rotations contiennent les journaux ;
- `chroma_db.write.lock` coordonne les écritures.

Le payload de modèles attesté contient 12 fichiers pour 386 522 634 octets
(368,62 MiB). La taille de l'index dépend du corpus. Chaque fichier de log est
borné à 5 000 000 octets, avec cinq sauvegardes au maximum. Les documents source
restent dans le dossier de base de connaissances choisi.

<!-- faq:change-kb -->
## Comment changer le chemin de la base de connaissances après l'installation ?

Modifie `kb_path` dans `%APPDATA%\Cortex\config.toml`, ferme les clients qui
utilisent Cortex, puis relance-les et exécute `cortex sync`. Le nouveau processus
relit la configuration ; le sync incrémental ajoute les fichiers du nouveau
dossier et retire de l'index les chemins devenus absents.

Pour repartir avec une configuration et un index neufs, utilise plutôt :

```powershell
$env:CORTEX_KB_PATH = "D:\NouvelleBase"
cortex setup --reset --yes
```

Le reset supprime la configuration et les données générées de Cortex, jamais les
documents de l'ancienne ou de la nouvelle base. `CORTEX_KB_PATH` surcharge le
fichier de configuration pour le processus courant.

<!-- faq:sync-after-edits -->
## Dois-je réindexer après avoir ajouté, modifié ou supprimé des documents ?

Oui. Cortex n'installe pas de watcher de fichiers. Lance l'une de ces voies :

```powershell
cortex sync
```

Tu peux aussi lancer `sync.bat` ou demander l'outil MCP `cortex_sync` depuis un
client. Le sync est incrémental : il retraite les fichiers nouveaux ou modifiés
et retire les fichiers supprimés, vides ou devenus exclus. Pour reconstruire de
zéro après un changement de modèle ou une corruption, ferme les clients,
supprime `%LOCALAPPDATA%\Cortex\chroma_db` puis relance un sync.

<!-- faq:client-not-seeing-cortex -->
## Mon client ne voit pas Cortex. Que vérifier ?

Commence par redémarrer complètement le client : les configurations MCP sont
généralement chargées au démarrage. Ensuite, exécute :

```powershell
cortex check --clients all
cortex doctor
```

`cortex check` valide les entrées et les chemins enregistrés. `cortex doctor`
effectue un diagnostic par couches strictement en lecture seule et distingue
`FAIL`, `WARN`, `UNKNOWN` et `SKIP`. Si l'entrée manque, lance
`cortex register --clients all`, puis redémarre encore le client. L'enregistrement
est au scope utilisateur et préserve les autres serveurs MCP des fichiers
partagés.

<!-- faq:uninstall -->
## Que supprime la désinstallation Windows, et comment nettoyer complètement ?

Le désinstalleur tente d'abord `cortex unregister --yes --clients all`, puis
retire l'application, ses raccourcis, son entrée du `PATH` utilisateur et les
fichiers de modèles installés. Les autres serveurs MCP sont préservés.

La base de connaissances n'est jamais supprimée. La configuration
`%APPDATA%\Cortex\config.toml`, l'index et les logs sous
`%LOCALAPPDATA%\Cortex` ne font pas partie des cibles de nettoyage explicites du
désinstalleur et peuvent rester. Pour un nettoyage complet, ferme tous les
clients, désinstalle Cortex, puis supprime manuellement `%APPDATA%\Cortex` et
`%LOCALAPPDATA%\Cortex`. Ne supprime le dossier de documents que si tu veux aussi
effacer tes propres sources.

<!-- faq:logs -->
## Où sont les logs et comment les lire ?

Le journal principal est `%LOCALAPPDATA%\Cortex\logs\cortex.log`. Cortex écrit
aussi les messages opérationnels sur stderr. Les logs tournent à 5 000 000
octets par fichier avec cinq sauvegardes, et ne contiennent jamais le texte des
documents ou des chunks : seulement chemins, statuts, erreurs et compteurs.

Sous PowerShell, affiche les dernières lignes avec :

```powershell
Get-Content "$env:LOCALAPPDATA\Cortex\logs\cortex.log" -Tail 100
```

Pour un diagnostic partageable, commence par `cortex doctor` et joins seulement
les lignes de log utiles.

<!-- faq:offline-models -->
## Cortex fonctionne-t-il hors ligne et comment les modèles sont-ils gérés ?

L'installeur Windows fournit le payload embedding et reranker sous
`%LOCALAPPDATA%\Cortex\models`. Au démarrage, Cortex vérifie chaque fichier avec
le manifeste SHA-256 embarqué, puis force `HF_HUB_OFFLINE=1`. Une installation
faite avec cet installeur peut donc indexer et rechercher sans accès Hugging Face.

Une installation depuis les sources ou un binaire autonome nu doit télécharger
les modèles lors du premier usage si son cache est vide. Les révisions et les
fichiers requis sont épinglés dans `models.lock`. L'installation des dépendances
et ce premier téléchargement utilisent le réseau, mais le contenu de la base de
connaissances n'est pas envoyé.

<!-- faq:pip-audit -->
## Pourquoi pip-audit ignore-t-il PYSEC-2026-311 pour ChromaDB ?

`PYSEC-2026-311` (`CVE-2026-45829`) concerne une exécution de code à distance
avant authentification dans le serveur HTTP ChromaDB, via l'API REST avec
`trust_remote_code=true`. Cortex n'emprunte pas ce chemin : il utilise uniquement
`chromadb.PersistentClient` embarqué, sans serveur REST ni `HttpClient`, avec des
modèles ONNX locaux fixés via FastEmbed.

Le workflow CI ignore donc cette seule vulnérabilité tant qu'aucune version
ChromaDB corrigée compatible n'existe. L'audit porte toujours sur tout l'arbre
transitif verrouillé et toute autre vulnérabilité fait échouer le job. L'ignore
doit être retiré dès qu'un correctif peut être épinglé.

<!-- faq:parallel-clients -->
## Puis-je utiliser plusieurs clients Cortex en parallèle ?

Oui pour les recherches. Les lectures `cortex_search` et `cortex_freshness` ne
prennent pas le verrou d'écriture. En revanche, une seule opération de sync peut
écrire dans ChromaDB à la fois. Chaque point d'écriture prend un verrou fichier
au niveau du système ; un second writer attend au maximum 30 secondes, puis
échoue proprement sans écrire et demande de réessayer plus tard.

Évite donc de lancer `sync.bat`, `cortex sync` et `cortex_sync` simultanément.
Laisse le premier sync finir, puis relance le second. Le verrou est libéré
automatiquement par le système si le processus qui le détenait se termine ou
crashe ; aucun nettoyage manuel d'un verrou périmé n'est normalement nécessaire.
