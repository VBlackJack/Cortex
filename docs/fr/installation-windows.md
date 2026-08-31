# Installation Windows

**Francais** | [English](../en/windows-install.md)

[Retour au sommaire](index.md)

L'installeur Windows est la voie recommandee pour utiliser Cortex sans Python
et sans terminal. Le meme fichier installe la CLI Cortex, les modeles hors
ligne et Cortex Companion, l'interface graphique. Il ajoute Cortex au PATH et
configure les clients MCP pris en charge.

## Installation guidee

1. Telecharger `Cortex-Setup.exe` et `SHA256SUMS` depuis la
   [GitHub Release](https://github.com/VBlackJack/Cortex/releases) souhaitee.
2. Dans PowerShell, executer
   `Get-FileHash .\Cortex-Setup.exe -Algorithm SHA256`, puis verifier que
   l'empreinte correspond exactement a la ligne `Cortex-Setup.exe` de
   `SHA256SUMS`.
3. Double-cliquer seulement apres cette verification. Tant que le binaire
   n'est pas signe, SmartScreen peut encore afficher un avertissement d'editeur
   inconnu ; choisir alors `Informations complementaires`, puis
   `Executer quand meme`.
4. Choisir le dossier de base de connaissances. Le defaut est
   `%USERPROFILE%\Documents\Cortex-KB`; il peut rester vide au depart.
5. Garder `Tout indexer dans ce dossier` pour que les documents poses a la
   racine ou dans n'importe quel sous-dossier soient cherchables. Le mode
   avance `Organiser en sections` limite l'indexation aux dossiers indiques ;
   les defauts sont `knowledge` (reference), `projects` (travail) et `notes`
   (notes libres).
6. Laisser `Indexer ce dossier maintenant` coche pour une premiere indexation,
   ou le decocher pour terminer plus vite et synchroniser plus tard.
7. A la fin, laisser `Lancer Cortex Companion` coche. Redemarrer ensuite les
   applications IA enregistrees.

L'installation ne demande pas de droits administrateur. Cortex est installe
dans `%LOCALAPPDATA%\Programs\Cortex`. Les nouveaux terminaux ouverts apres
l'installation voient la commande `cortex` dans le PATH.

L'installeur embarque Cortex Companion et les modeles FastEmbed/ONNX verifies
par manifeste. La premiere synchronisation fonctionne donc hors ligne et ne
telecharge aucun modele. Le corpus et l'index restent locaux.

## Utilisation sans terminal

Cortex Companion est ajoute au menu Demarrer et s'ouvre apres l'installation
guidee. Pour le premier usage :

1. Ouvrir `Réglages`. Companion detecte normalement le `cortex.exe` installe
   dans le dossier parent de la meme installation Cortex. Si le chemin doit
   etre corrige, choisir
   `%LOCALAPPDATA%\Programs\Cortex\cortex.exe`, puis `Enregistrer et connecter`.
   Sur un poste lent, choisir aussi un delai de demarrage de 15, 30, 60 ou
   120 secondes ; le defaut est 30 secondes. Ce delai concerne uniquement la
   verification de compatibilite au demarrage. S'il est depasse, Companion
   reste en lecture seule afin de ne pas lancer d'actions avec un Cortex non
   confirme.
2. Verifier le `Dossier de la base de connaissances`. Pour le changer, choisir
   un dossier existant, puis `Enregistrer le dossier`.
3. Ajouter les documents dans ce dossier.
4. Ouvrir `Base locale`, puis choisir `Synchroniser les documents locaux`.
   L'ecran reste utilisable pour
   suivre le resultat et consulter les details en cas d'echec.

Deux raccourcis techniques restent disponibles dans le menu Demarrer :

- `Cortex Sync` indexe les nouveaux documents et garde la console ouverte pour
  afficher le resultat.
- `Cortex Doctor` verifie l'installation et garde egalement le resultat visible.

## Installation silencieuse

Pour un deploiement automatise par utilisateur :

```powershell
Cortex-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /KBPATH="C:\Docs\Cortex-KB"
```

Le mode silencieux cree le dossier si necessaire, installe Cortex et Companion,
et enregistre les clients, mais ne lance pas Companion et n'indexe pas
immediatement. Ajouter `/INDEX` pour forcer la premiere indexation pendant le
deploiement :

```powershell
Cortex-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /KBPATH="C:\Docs\Cortex-KB" /INDEX
```

Le defaut silencieux est `/INDEXMODE=whole`. Pour le mode avance :

```powershell
Cortex-Setup.exe /VERYSILENT /KBPATH="C:\Docs\Cortex-KB" /INDEXMODE=sections /SECTIONS="knowledge,projects,notes"
```

Le processus retourne un code non nul si la configuration automatique echoue.

## Reinstallation et remise a zero

Si `%APPDATA%\Cortex\config.toml` existe deja, l'assistant propose deux choix :

- `Garder ma configuration` est le defaut prudent. Le dossier, le mode et
  l'index existants sont conserves ; Cortex reindexe et reenregistre les clients.
- `Reinitialiser` supprime uniquement la configuration Cortex et les donnees
  generees sous `%LOCALAPPDATA%\Cortex`, puis applique le dossier et le mode
  choisis dans l'assistant. Le dossier de documents n'est jamais supprime.

Fermer les applications IA avant une reinitialisation : un serveur actif peut
tenir l'index ouvert et faire echouer proprement l'operation. En silencieux,
le defaut reste Keep ; `/RESETCONFIG` demande explicitement le reset :

```powershell
Cortex-Setup.exe /VERYSILENT /RESETCONFIG /KBPATH="C:\Docs\Cortex-KB" /INDEXMODE=whole /INDEX
```

## Desinstallation

Desinstaller Cortex depuis `Parametres > Applications`. Le desinstalleur lance
`cortex unregister --yes --clients all` avant de supprimer le binaire, puis
retire uniquement son entree du PATH utilisateur. Companion supprime aussi sa
tache planifiee seulement si son jeton d'appartenance correspond ; une tache
absente ou etrangere n'est jamais supprimee.

La configuration Cortex, les reglages locaux de Companion, l'index et le
dossier de documents sont conserves afin de ne jamais detruire des donnees
utilisateur pendant une desinstallation.
