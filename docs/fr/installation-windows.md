# Installation Windows

**Francais** | [English](../en/windows-install.md)

[Retour au sommaire](index.md)

L'installeur Windows est la voie recommandee pour utiliser Cortex sans Python
et sans terminal. Il installe le binaire au scope utilisateur, ajoute Cortex au
PATH et configure les clients MCP pris en charge.

## Installation guidee

1. Telecharger `Cortex-Setup.exe` depuis la
   [GitHub Release](https://github.com/VBlackJack/Cortex/releases) souhaitee.
2. Double-cliquer sur l'installeur. Tant que le binaire n'est pas signe,
   SmartScreen peut afficher un avertissement d'editeur inconnu. Verifier que le
   fichier vient bien de la release officielle avant de choisir
   `Informations complementaires`, puis `Executer quand meme`.
3. Choisir le dossier de base de connaissances. Le defaut est
   `%USERPROFILE%\Documents\Cortex-KB`; il peut rester vide au depart.
4. Laisser `Indexer ce dossier maintenant` coche pour une premiere indexation,
   ou le decocher pour terminer plus vite et synchroniser plus tard.
5. A la fin, redemarrer les applications IA enregistrees.

L'installation ne demande pas de droits administrateur. Cortex est installe
dans `%LOCALAPPDATA%\Programs\Cortex`. Les nouveaux terminaux ouverts apres
l'installation voient la commande `cortex` dans le PATH.

La premiere synchronisation contenant des documents peut telecharger les
modeles FastEmbed/ONNX. Un acces reseau est requis une fois si leur cache est
vide. Le corpus et l'index restent locaux.

## Utilisation sans terminal

Deux raccourcis sont ajoutes au menu Demarrer :

- `Cortex Sync` indexe les nouveaux documents et garde la console ouverte pour
  afficher le resultat.
- `Cortex Doctor` verifie l'installation et garde egalement le resultat visible.

## Installation silencieuse

Pour un deploiement automatise par utilisateur :

```powershell
Cortex-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /KBPATH="C:\Docs\Cortex-KB"
```

Le mode silencieux cree le dossier si necessaire, installe Cortex et enregistre
les clients, mais n'indexe pas immediatement. Ajouter `/INDEX` pour forcer la
premiere indexation pendant le deploiement :

```powershell
Cortex-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /KBPATH="C:\Docs\Cortex-KB" /INDEX
```

Le processus retourne un code non nul si la configuration automatique echoue.

## Desinstallation

Desinstaller Cortex depuis `Parametres > Applications`. Le desinstalleur lance
`cortex unregister --yes --clients all` avant de supprimer le binaire, puis
retire uniquement son entree du PATH utilisateur.

La configuration Cortex, l'index et le dossier de documents sont conserves afin
de ne jamais detruire des donnees utilisateur pendant une desinstallation.
