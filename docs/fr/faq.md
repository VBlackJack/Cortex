# Questions frequentes

**Francais** | [English](../en/faq.md)

[Retour au sommaire](index.md)

Ces reponses decrivent le comportement actuel de Cortex. Pour les procedures
detaillees, voir l'[installation Windows](installation-windows.md),
l'[installation depuis les sources](setup.md), la
[configuration](configuration.md), le [guide d'utilisation](user-guide.md) et la
[securite](security.md).

<!-- faq:install-or-source -->
## Dois-je utiliser l'installeur Windows ou installer Cortex depuis les sources ?

Utilise `Cortex-Setup.exe` pour une installation Windows standard. Il n'exige pas
Python, installe l'application dans `%LOCALAPPDATA%\Programs\Cortex`, ajoute les
raccourcis et le `PATH` utilisateur, et fournit le payload de modeles verifie.
C'est la voie recommandee pour un poste utilisateur.

L'installation depuis les sources demande Python 3.10 ou plus. Choisis-la pour
developper Cortex, modifier le code ou tester une revision qui n'est pas encore
publiee. `install.bat` installe les dependances, initialise la configuration et
propose l'enregistrement des clients. Les binaires autonomes macOS et Linux
n'exigent pas Python non plus.

<!-- faq:data-locations -->
## Ou vivent la configuration, l'index, les modeles et les logs, et quelle place prevoir ?

La configuration legere vit dans `%APPDATA%\Cortex\config.toml`. Par defaut, les
donnees locales generees vivent sous `%LOCALAPPDATA%\Cortex` :

- `chroma_db\` contient l'index vectoriel ;
- `models\` contient les modeles ONNX ;
- `logs\cortex.log` et ses rotations contiennent les journaux ;
- `chroma_db.write.lock` coordonne les ecritures.

Le payload de modeles atteste contient 12 fichiers pour 386 522 634 octets
(368,62 MiB). La taille de l'index depend du corpus. Chaque fichier de log est
borne a 5 000 000 octets, avec cinq sauvegardes au maximum. Les documents source
restent dans le dossier de base de connaissances choisi.

<!-- faq:change-kb -->
## Comment changer le chemin de la base de connaissances apres l'installation ?

Modifie `kb_path` dans `%APPDATA%\Cortex\config.toml`, ferme les clients qui
utilisent Cortex, puis relance-les et execute `cortex sync`. Le nouveau processus
relit la configuration ; le sync incremental ajoute les fichiers du nouveau
dossier et retire de l'index les chemins devenus absents.

Pour repartir avec une configuration et un index neufs, utilise plutot :

```powershell
$env:CORTEX_KB_PATH = "D:\NouvelleBase"
cortex setup --reset --yes
```

Le reset supprime la configuration et les donnees generees de Cortex, jamais les
documents de l'ancienne ou de la nouvelle base. `CORTEX_KB_PATH` surcharge le
fichier de configuration pour le processus courant.

<!-- faq:sync-after-edits -->
## Dois-je reindexer apres avoir ajoute, modifie ou supprime des documents ?

Oui. Cortex n'installe pas de watcher de fichiers. Lance l'une de ces voies :

```powershell
cortex sync
```

Tu peux aussi lancer `sync.bat` ou demander l'outil MCP `cortex_sync` depuis un
client. Le sync est incremental : il retraite les fichiers nouveaux ou modifies
et retire les fichiers supprimes, vides ou devenus exclus. Pour reconstruire de
zero apres un changement de modele ou une corruption, ferme les clients,
supprime `%LOCALAPPDATA%\Cortex\chroma_db` puis relance un sync.

<!-- faq:client-not-seeing-cortex -->
## Mon client ne voit pas Cortex. Que verifier ?

Commence par redemarrer completement le client : les configurations MCP sont
generalement chargees au demarrage. Ensuite, execute :

```powershell
cortex check --clients all
cortex doctor
```

`cortex check` valide les entrees et les chemins enregistres. `cortex doctor`
effectue un diagnostic par couches strictement en lecture seule et distingue
`FAIL`, `WARN`, `UNKNOWN` et `SKIP`. Si l'entree manque, lance
`cortex register --clients all`, puis redemarre encore le client. L'enregistrement
est au scope utilisateur et preserve les autres serveurs MCP des fichiers
partages.

<!-- faq:uninstall -->
## Que supprime la desinstallation Windows, et comment nettoyer completement ?

Le desinstalleur tente d'abord `cortex unregister --yes --clients all`, puis
retire l'application, ses raccourcis, son entree du `PATH` utilisateur et les
fichiers de modeles installes. Les autres serveurs MCP sont preserves.

La base de connaissances n'est jamais supprimee. La configuration
`%APPDATA%\Cortex\config.toml`, l'index et les logs sous
`%LOCALAPPDATA%\Cortex` ne font pas partie des cibles de nettoyage explicites du
desinstalleur et peuvent rester. Pour un nettoyage complet, ferme tous les
clients, desinstalle Cortex, puis supprime manuellement `%APPDATA%\Cortex` et
`%LOCALAPPDATA%\Cortex`. Ne supprime le dossier de documents que si tu veux aussi
effacer tes propres sources.

<!-- faq:logs -->
## Ou sont les logs et comment les lire ?

Le journal principal est `%LOCALAPPDATA%\Cortex\logs\cortex.log`. Cortex ecrit
aussi les messages operationnels sur stderr. Les logs tournent a 5 000 000
octets par fichier avec cinq sauvegardes, et ne contiennent jamais le texte des
documents ou des chunks : seulement chemins, statuts, erreurs et compteurs.

Sous PowerShell, affiche les dernieres lignes avec :

```powershell
Get-Content "$env:LOCALAPPDATA\Cortex\logs\cortex.log" -Tail 100
```

Pour un diagnostic partageable, commence par `cortex doctor` et joins seulement
les lignes de log utiles.

<!-- faq:offline-models -->
## Cortex fonctionne-t-il hors ligne et comment les modeles sont-ils geres ?

L'installeur Windows fournit le payload embedding et reranker sous
`%LOCALAPPDATA%\Cortex\models`. Au demarrage, Cortex verifie chaque fichier avec
le manifeste SHA-256 embarque, puis force `HF_HUB_OFFLINE=1`. Une installation
faite avec cet installeur peut donc indexer et rechercher sans acces Hugging Face.

Une installation depuis les sources ou un binaire autonome nu doit telecharger
les modeles lors du premier usage si son cache est vide. Les revisions et les
fichiers requis sont epingles dans `models.lock`. L'installation des dependances
et ce premier telechargement utilisent le reseau, mais le contenu de la base de
connaissances n'est pas envoye.

<!-- faq:pip-audit -->
## Pourquoi pip-audit ignore-t-il PYSEC-2026-311 pour ChromaDB ?

`PYSEC-2026-311` (`CVE-2026-45829`) concerne une execution de code a distance
avant authentification dans le serveur HTTP ChromaDB, via l'API REST avec
`trust_remote_code=true`. Cortex n'emprunte pas ce chemin : il utilise uniquement
`chromadb.PersistentClient` embarque, sans serveur REST ni `HttpClient`, avec des
modeles ONNX locaux fixes via FastEmbed.

Le workflow CI ignore donc cette seule vulnerabilite tant qu'aucune version
ChromaDB corrigee compatible n'existe. L'audit porte toujours sur tout l'arbre
transitif verrouille et toute autre vulnerabilite fait echouer le job. L'ignore
doit etre retire des qu'un correctif peut etre epingle.

<!-- faq:parallel-clients -->
## Puis-je utiliser plusieurs clients Cortex en parallele ?

Oui pour les recherches. Les lectures `cortex_search` et `cortex_freshness` ne
prennent pas le verrou d'ecriture. En revanche, une seule operation de sync peut
ecrire dans ChromaDB a la fois. Chaque point d'ecriture prend un verrou fichier
au niveau du systeme ; un second writer attend au maximum 30 secondes, puis
echoue proprement sans ecrire et demande de reessayer plus tard.

Evite donc de lancer `sync.bat`, `cortex sync` et `cortex_sync` simultanement.
Laisse le premier sync finir, puis relance le second. Le verrou est libere
automatiquement par le systeme si le processus qui le detenait se termine ou
crashe ; aucun nettoyage manuel d'un verrou perime n'est normalement necessaire.
