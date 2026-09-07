# Distribution autonome

**Français** | [English](../en/distribution.md)

[Retour au sommaire](index.md)

Cortex peut être livré sous la forme d'une archive ZIP autonome. Elle contient
un exécutable unique qui fournit à la fois le CLI et le serveur MCP stdio,
ainsi que les licences exactes de ses dépendances embarquées. L'exécutable
n'exige pas Python sur le poste cible.

## Modèle de commandes

Le même binaire expose toute la surface de commandes :

```text
cortex setup
cortex unregister
cortex sync
cortex doctor
cortex serve
```

`cortex serve` est le point d'entrée du serveur MCP. Il n'est normalement pas
lancé à la main : quand `cortex setup` s'exécute depuis le binaire autonome, il
enregistre l'exécutable courant avec l'argument `serve` dans chaque client
sélectionné.

L'installation Python reste prise en charge. Dans ce mode, le setup continue
d'enregistrer l'interpréteur Python courant avec `server.py` ; les workflows de
développement et pip existants ne changent pas.

## Installer sous Windows

Pour un utilisateur non technique, télécharger `Cortex-Setup.exe` depuis la
release. L'assistant installe Cortex sans droits administrateur, collecte le
dossier de documents, ajoute le binaire au PATH et enregistre les clients MCP.
Voir le [guide d'installation Windows](installation-windows.md).

L'archive `cortex-windows-x64.zip` reste disponible pour un usage portable ou
avancé.

## Installer une archive autonome publiée

1. Télécharger l'archive de son système et `SHA256SUMS` depuis la GitHub Release
   correspondante, puis vérifier son empreinte SHA-256.
2. Extraire toute l'archive dans un emplacement stable qui ne sera ni renommé
   ni supprimé. Conserver le dossier `licenses` avec le binaire.
3. Sous Linux ou macOS, rendre le binaire exécutable avec `chmod +x cortex`.
4. Lancer `cortex setup` depuis ce binaire, puis redémarrer les clients MCP
   enregistrés.

Le setup est au scope utilisateur. L'enregistrement MCP au scope projet est
volontairement exclu de Cortex.

La première indexation ou le premier démarrage du serveur peut télécharger les
modèles d'embedding et de reranking configurés dans le cache FastEmbed. Un accès
réseau est donc nécessaire une fois si le cache de modèles est vide. Le contenu
de la base de connaissance et l'index produit restent locaux.

## Construire localement

Installer Cortex avec la dépendance de build optionnelle :

```powershell
python -m pip install -e ".[build]"
```

Sous Windows :

```powershell
./scripts/build_installer.ps1 -Clean
```

Sous Linux ou macOS :

```bash
./scripts/build_installer.sh --clean
```

Les deux scripts créent un exécutable PyInstaller one-file et un inventaire de
licences vérifié sous `dist/`. Le binaire embarque ChromaDB, FastEmbed, ONNX
Runtime, Tokenizers et les modules Cortex ; il est donc nettement plus lourd
qu'un simple CLI Python. Les fichiers des modèles ne sont pas embarqués.

## Workflow de release

Le push d'un tag `v*` démarre `.github/workflows/release.yml`. Le workflow build
sous Windows x64, macOS arm64 et Linux x64, smoke-teste le CLI et les imports du
serveur, puis attache trois archives ZIP avec leurs licences à la GitHub Release.
Le leg Windows compile aussi `Cortex-Setup.exe` avec Inno Setup et l'attache à
la release. Cette version Windows n'est pas signée ; son empreinte doit être
comparée à `SHA256SUMS` avant exécution. Le job de publication génère les
empreintes de tous les artefacts et produit une attestation de provenance
GitHub avant de publier la release en une fois. `workflow_dispatch` peut
construire les mêmes artefacts sans publier de release.

Le job de release ne doit jamais publier l'archive d'une plateforme dont le
build, l'inventaire de licences ou le smoke-test a échoué.
