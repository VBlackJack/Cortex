# Distribution autonome

**Français** | [English](../en/distribution.md)

[Retour au sommaire](index.md)

Cortex peut être livré sous la forme d'une archive ZIP autonome. Elle se
décompresse dans un dossier `cortex/` qui contient un exécutable fournissant à
la fois le CLI et le serveur MCP stdio, son dossier de runtime `_internal` et
les licences exactes de ses dépendances embarquées. L'exécutable embarque
CPython 3.13 et n'exige pas Python sur le poste cible.

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
   ni supprimé. Garder le dossier `cortex/` entier : l'exécutable a besoin du
   dossier `_internal` à côté de lui, et le dossier `licenses` l'accompagne.
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

Les deux scripts créent un build PyInstaller en dossier, `dist/cortex/` avec
l'exécutable à côté de `_internal/`, et un inventaire de licences vérifié sous
`dist/licenses/`. Le dossier embarque ChromaDB, FastEmbed, ONNX Runtime,
Tokenizers et les modules Cortex ; il est donc nettement plus lourd qu'un simple
CLI Python. Les fichiers des modèles ne sont pas embarqués. Comme rien n'est
décompressé au démarrage, l'exécutable démarre en une à trois secondes.

## Workflow de release

Le push d'un tag `v*` démarre `.github/workflows/release.yml`.
`workflow_dispatch` construit les mêmes artefacts pour un candidat, sur une
référence Companion choisie, sans rien publier. Les jobs s'enchaînent dans cet
ordre, et chacun exige la réussite du précédent :

1. **Porte de recherche.** Le benchmark de recherche bilingue de
   `.github/workflows/retrieval.yml` doit d'abord réussir.
2. **Vérification.** Sous CPython 3.13 : le tag doit être égal à `_version.py`
   et à la version de `server.json` ; puis `ruff`, `mypy`, la suite `pytest`
   complète et `pip-audit` sur les trois arbres verrouillés par hash
   (`requirements.lock`, `requirements-dev.lock`, `requirements-model.lock`)
   avec la même liste d'exceptions évaluées que la CI.
3. **Build.** Trois builds portables, Windows x64, macOS arm64 et Linux x64,
   chacun avec l'interpréteur CPython 3.13 figé. PyInstaller produit un dossier
   (`cortex` ou `cortex.exe` à côté de `_internal`) ; le build vérifie
   l'architecture du runner, génère et vérifie l'inventaire de licences,
   smoke-teste le CLI et les imports du serveur, puis archive le dossier dans un
   unique dossier `cortex/` avec ses licences.
4. **Installeur Windows.** Le leg Windows vérifie et publie le Cortex Companion
   apparié (le tag Companion de même nom) et le convertisseur console
   Confluence épinglé, prépare le payload de modèles embarqué et le vérifie
   contre `models/manifest.json`, puis compile le `Cortex-Setup.exe` combiné avec
   Inno Setup. Un smoke test hors ligne l'installe avec Hugging Face hors ligne,
   puis lance une synchronisation, une recherche et une recherche JSON sur les
   modèles installés.
5. **Signature.** Quand les secrets `WINDOWS_CERT_PFX_BASE64` et
   `WINDOWS_CERT_PASSWORD` existent, `cortex.exe`, le convertisseur,
   `CortexCompanion.exe`, le désinstalleur embarqué et `Cortex-Setup.exe` sont
   signés Authenticode, et le certificat est supprimé en fin de job quelle que
   soit l'issue. Sans ces secrets, le build continue sans signature ;
   l'empreinte de l'installeur doit alors être comparée à `SHA256SUMS` avant
   exécution.
6. **Distribution Python.** La wheel est construite avec des métadonnées
   reproductibles, contrôlée par `twine`, installée sur `requirements.lock` dans
   un environnement virtuel propre et smoke-testée.
7. **PyPI et registre MCP.** La wheel est publiée sur PyPI par trusted
   publishing (étape sautée quand cette version exacte y est déjà), puis le
   `server.json` validé est publié dans le registre MCP.
8. **GitHub Release.** Le job refuse tout ce qui n'est pas l'ensemble exact des
   cinq actifs : `Cortex-Setup.exe`, `cortex-windows-x64.zip`,
   `cortex-macos-arm64.zip`, `cortex-linux-x64.zip` et la wheel
   `cortex_local_rag`. Il écrit ensuite `SHA256SUMS`, produit une attestation de
   provenance de build pour chaque actif et publie la release en une fois, sans
   notes générées par GitHub.

Le job de release ne doit jamais publier l'archive d'une plateforme dont le
build, l'inventaire de licences ou le smoke-test a échoué.

La CI teste chaque push sous Python 3.11, 3.12 et 3.13. Son analyse des
dépendances tourne aussi chaque lundi : un nouvel avis sur une dépendance
verrouillée apparaît entre deux releases au lieu d'attendre le tag suivant.
