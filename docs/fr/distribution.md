# Distribution autonome

**Francais** | [English](../en/distribution.md)

[Retour au sommaire](index.md)

Cortex peut etre livre sous la forme d'un executable autonome unique qui
contient a la fois le CLI et le serveur MCP stdio. L'executable n'exige pas
Python sur le poste cible.

## Modele de commandes

Le meme binaire expose toute la surface de commandes :

```text
cortex setup
cortex sync
cortex doctor
cortex serve
```

`cortex serve` est le point d'entree du serveur MCP. Il n'est normalement pas
lance a la main : quand `cortex setup` s'execute depuis le binaire autonome, il
enregistre l'executable courant avec l'argument `serve` dans chaque client
selectionne.

L'installation Python reste prise en charge. Dans ce mode, le setup continue
d'enregistrer l'interpreteur Python courant avec `server.py` ; les workflows de
developpement et pip existants ne changent pas.

## Installer un binaire publie

1. Telecharger le binaire de son systeme depuis la GitHub Release correspondante.
2. Le placer dans un emplacement stable qui ne sera ni renomme ni supprime.
3. Sous Linux ou macOS, le rendre executable avec `chmod +x cortex-*`.
4. Lancer `cortex setup` depuis ce binaire, puis redemarrer les clients MCP
   enregistres.

Le setup est au scope utilisateur. L'enregistrement MCP au scope projet est
volontairement exclu de Cortex.

La premiere indexation ou le premier demarrage du serveur peut telecharger les
modeles d'embedding et de reranking configures dans le cache FastEmbed. Un acces
reseau est donc necessaire une fois si le cache de modeles est vide. Le contenu
de la base de connaissance et l'index produit restent locaux.

## Construire localement

Installer Cortex avec la dependance de build optionnelle :

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

Les deux scripts creent un executable PyInstaller one-file sous `dist/`. Le
binaire embarque ChromaDB, FastEmbed, ONNX Runtime, Tokenizers et les modules
Cortex ; il est donc nettement plus lourd qu'un simple CLI Python. Les fichiers
des modeles ne sont pas embarques.

## Workflow de release

Le push d'un tag `v*` demarre `.github/workflows/release.yml`. Le workflow build
sous Windows, macOS arm64 et Linux x64, smoke-teste le CLI et les imports du
serveur, puis attache les trois binaires a la GitHub Release.
`workflow_dispatch` peut construire les memes artefacts sans publier de release.

Le job de release ne doit jamais publier le binaire d'une plateforme dont le
build ou le smoke-test a echoue.
