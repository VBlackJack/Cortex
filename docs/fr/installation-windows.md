# Installation Windows

**Français** | [English](../en/windows-install.md)

[Retour au sommaire](index.md)

L'installeur Windows est la voie recommandée pour utiliser Cortex sans Python
et sans terminal. Le même fichier installe la CLI Cortex, les modèles hors
ligne et Cortex Companion, l'interface graphique. Il ajoute Cortex au PATH et
configure les clients MCP pris en charge.

## Installation guidée

1. Télécharger `Cortex-Setup.exe` et `SHA256SUMS` depuis la
   [GitHub Release](https://github.com/VBlackJack/Cortex/releases) souhaitée.
2. Dans PowerShell, exécuter
   `Get-FileHash .\Cortex-Setup.exe -Algorithm SHA256`, puis vérifier que
   l'empreinte correspond exactement à la ligne `Cortex-Setup.exe` de
   `SHA256SUMS`.
3. Double-cliquer seulement après cette vérification. Tant que le binaire
   n'est pas signé, SmartScreen peut encore afficher un avertissement d'éditeur
   inconnu ; choisir alors `Informations complémentaires`, puis
   `Exécuter quand même`.
4. Choisir le dossier de base de connaissances. Le défaut est
   `%USERPROFILE%\Documents\Cortex-KB`; il peut rester vide au départ.
5. Garder `Tout indexer dans ce dossier` pour que les documents posés à la
   racine ou dans n'importe quel sous-dossier soient cherchables. Le mode
   avancé `Organiser en sections` limite l'indexation aux dossiers indiqués ;
   les défauts sont `knowledge` (référence), `projects` (travail) et `notes`
   (notes libres).
6. Sur la page de fin, laisser `Lancer Cortex Companion` coché et cliquer sur
   `Terminer`. L’installation ne lance jamais l’indexation.
7. Dans Companion, ouvrir `Base locale`, puis choisir `Synchroniser les documents
   locaux` au moment souhaité. La durée dépend du nombre et de la taille des
   documents ; suivre le résultat dans cet écran. Redémarrer ensuite les
   applications IA enregistrées.

L'installation ne demande pas de droits administrateur. Cortex est installé
dans `%LOCALAPPDATA%\Programs\Cortex`. Les nouveaux terminaux ouverts après
l'installation voient la commande `cortex` dans le PATH.

L'installeur embarque Cortex Companion, le convertisseur Confluence console et
les modèles FastEmbed/ONNX vérifiés par manifeste. La première synchronisation
fonctionne donc hors ligne et ne télécharge aucun modèle. Le corpus et l'index
restent locaux.

### Première configuration Confluence

Après la connexion de Companion à Cortex :

1. Dans `Réglages`, enregistrer le PAT Confluence masqué.
2. Dans `Mes sources`, choisir `Ajouter une source`, puis coller l'URL complète d'une page.
3. Choisir l'expiration du PAT et la classification, puis vérifier la clé
   d'espace détectée.
4. Cliquer sur `Voir les documents à ajouter`, puis confirmer la page.

Companion crée et valide `%APPDATA%\Cortex\confluence.toml`. Aucune édition
manuelle n'est nécessaire. Le PAT reste dans le Gestionnaire d'identifiants
Windows protégé par DPAPI et n'est pas copié dans le TOML.
Le convertisseur livré est sélectionné et validé automatiquement. Les options
avancées permettent uniquement aux développeurs de tester un autre binaire.

## Utilisation sans terminal

Cortex Companion est ajouté au menu Démarrer et s'ouvre après l'installation
guidée. Pour le premier usage :

1. Ouvrir `Réglages`. Companion détecte normalement le `cortex.exe` installé
   dans le dossier parent de la même installation Cortex. Si le chemin doit
   être corrigé, choisir
   `%LOCALAPPDATA%\Programs\Cortex\cortex.exe`, puis `Enregistrer et connecter`.
   Sur un poste lent, choisir aussi un délai maximal des commandes Cortex de
   15, 30, 60 ou 120 secondes ; le défaut est 30 secondes. Depuis
   `2026.0901.02`, cette valeur s'applique à la vérification de compatibilité,
   à la lecture des réglages Cortex et aux commandes `Mes sources`. Si le
   délai est dépassé, Companion garde les mutations désactivées et indique de
   revenir dans `Réglages` pour augmenter la valeur.
2. Vérifier le `Dossier de la base de connaissances`. Pour le changer, choisir
   un dossier existant, puis `Enregistrer le dossier`.
3. Ajouter les documents dans ce dossier.
4. Ouvrir `Base locale`, puis choisir `Synchroniser les documents locaux`.
   L'écran reste utilisable pour suivre le résultat et consulter les détails en
   cas d'échec.

Companion suit la langue de Windows. Pour le lire dans une autre langue qu'il
fournit, en choisir une sous `Langue de l'interface` dans `Réglages` ;
`Langue de Windows` rétablit le défaut. Le changement s'applique au prochain
démarrage de Companion.

Deux raccourcis techniques restent disponibles dans le menu Démarrer :

- `Cortex Sync` indexe les nouveaux documents et garde la console ouverte pour
  afficher le résultat.
- `Cortex Doctor` vérifie l'installation et garde également le résultat visible.

## Installation silencieuse

Pour un déploiement automatisé par utilisateur :

```powershell
Cortex-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /KBPATH="C:\Docs\Cortex-KB"
```

Le mode silencieux crée le dossier si nécessaire, installe Cortex et Companion,
et enregistre les clients, mais ne lance pas Companion et n’indexe aucun
document. L’ancienne option `/INDEX` est refusée avant l’installation. Lancer
la synchronisation séparément après la fin réussie de l’installeur :

```powershell
$installation = Start-Process .\Cortex-Setup.exe -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /KBPATH="C:\Docs\Cortex-KB"' -Wait -PassThru -WindowStyle Hidden
if ($installation.ExitCode -ne 0) { throw "Cortex installation failed." }
& "$env:LOCALAPPDATA\Programs\Cortex\cortex.exe" sync
if ($LASTEXITCODE -ne 0) { throw "Cortex synchronization failed." }
```

Le défaut silencieux est `/INDEXMODE=whole`. Pour le mode avancé :

```powershell
Cortex-Setup.exe /VERYSILENT /KBPATH="C:\Docs\Cortex-KB" /INDEXMODE=sections /SECTIONS="knowledge,projects,notes"
```

Le processus retourne un code non nul si la configuration automatique échoue.

## Réinstallation et remise à zéro

Si `%APPDATA%\Cortex\config.toml` existe déjà, l'assistant propose deux choix :

- `Garder ma configuration` est le défaut prudent. Le dossier, le mode et
  l'index existants sont conservés ; Cortex réenregistre les clients sans indexer.
- `Reinitialiser` supprime uniquement la configuration Cortex et les données
  générées sous `%LOCALAPPDATA%\Cortex`, puis applique le dossier et le mode
  choisis dans l'assistant. Le dossier de documents n'est jamais supprimé.

Fermer les applications IA avant une réinitialisation : un serveur actif peut
tenir l'index ouvert et faire échouer proprement l'opération. En silencieux,
le défaut reste Keep ; `/RESETCONFIG` demande explicitement le reset :

```powershell
Cortex-Setup.exe /VERYSILENT /RESETCONFIG /KBPATH="C:\Docs\Cortex-KB" /INDEXMODE=whole
```

## Désinstallation

Désinstaller Cortex depuis `Parametres > Applications`. Le désinstalleur lance
`cortex unregister --yes --clients all` avant de supprimer le binaire, puis
retire uniquement son entrée du PATH utilisateur. Companion supprime aussi sa
tâche planifiée seulement si son jeton d'appartenance correspond ; une tâche
absente ou étrangère n'est jamais supprimée.

La configuration Cortex, les réglages locaux de Companion, l'index et le
dossier de documents sont conservés afin de ne jamais détruire des données
utilisateur pendant une désinstallation.
