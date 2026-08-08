# Installation reproductible

**Francais** | [English](../en/reproducible-install.md)

[Retour au sommaire](index.md)

## Quatre contrats, quatre roles

Cortex distingue quatre niveaux d'epinglage des dependances :

| Fichier | Portee | Usage |
|---|---|---|
| `requirements.txt` | Les dependances d'execution directes, epinglees en version exacte | Source unique lue par `pyproject.toml` ; install standard |
| `requirements.lock` | L'arbre transitif complet, verrouille par hash | Install reproductible et audit supply-chain |
| `requirements-dev.lock` | L'arbre execution + test + build, verrouille par hash | CI, creation des binaires et publication |
| `requirements-model.txt` / `requirements-model.lock` | Les versions de `fastembed` et `huggingface-hub` declarees par `models.lock`, avec leur arbre verrouille par hash | Fabrication et attestation isolees du payload de modeles |

`requirements.txt` fige les versions des paquets que Cortex importe directement,
mais laisse pip resoudre librement leurs propres dependances. `requirements.lock`
fige en plus tout le transitif et attache a chaque paquet ses hashes SHA-256.
`requirements-dev.lock` applique le meme contrat aux outils qui testent et
construisent les artefacts. Pip refuse ainsi tout artefact non repertorie au
lieu de re-resoudre silencieusement une autre version en CI.
Le lock de modeles reste separe car son outil de telechargement est atteste avec
le payload et peut differer de la version transitive utilisee par Cortex.

Le lock est universel (cross-plateforme) : un seul fichier couvre Windows, Linux
et macOS via des marqueurs d'environnement. Il capture les branches
conditionnelles qu'un lock genere sur une seule plateforme raterait, par exemple
`pywin32` et `colorama` uniquement sous Windows, ou les variantes de `numpy` et
`onnxruntime` selon la version de Python.

## Installer avec verrouillage par hash

```powershell
pip install --require-hashes -r requirements.lock
```

Avec `--require-hashes`, pip refuse d'installer tout paquet dont l'archive ne
correspond pas a un hash present dans le lock, et exige que chaque dependance
soit epinglee. C'est le mode a utiliser pour une installation reproductible
(poste de production, CI, audit).

Verification a blanc, sans rien installer :

```powershell
pip install --require-hashes --dry-run -r requirements.lock
```

L'installation standard decrite dans [Installation](setup.md) reste valable pour
un usage courant ; le lock est le mode strict, pas un remplacement obligatoire.

## Regenerer les locks

Des que `requirements.txt` evolue (bump d'une dependance, ajout, retrait), il
faut regenerer `requirements.lock`, sinon les deux divergent. La commande exacte
figure en tete du fichier `requirements.lock` :

```powershell
uv pip compile --universal --generate-hashes --python-version 3.10 requirements.txt -o requirements.lock
```

Points d'attention :

- `uv` sert uniquement a generer le lock (outil de developpement). L'installeur
  reste `pip` : ni l'install standard ni la CI n'ont besoin d'`uv`.
- `--universal` produit le fichier cross-plateforme unique ; ne pas le retirer,
  sinon le lock devient specifique a la plateforme de generation.
- `--python-version 3.10` cible la version minimale supportee, ce qui garantit
  que le lock reste valide sur toute la matrice 3.10 a 3.12.
- Committer `requirements.lock` avec le `requirements.txt` correspondant dans
  le meme commit.

Quand les extras `dev` ou `build` de `pyproject.toml` changent, ou apres la
regeneration du lock d'execution, regenerer aussi le lock de fabrication :

```powershell
uv pip compile --universal --generate-hashes --python-version 3.10 --extra dev --extra build pyproject.toml -o requirements-dev.lock
```

La CI installe `requirements-dev.lock` avec `--require-hashes`, puis le projet
avec `--no-build-isolation --no-deps`. Les tests et les binaires utilisent donc
exactement l'arbre audite, sans seconde resolution implicite.

Quand `fastembed_version` ou `huggingface_hub_version` change dans `models.lock`,
aligner `requirements-model.txt`, puis regenerer son lock :

```powershell
uv pip compile --universal --generate-hashes --python-version 3.10 requirements-model.txt -o requirements-model.lock
```

La release installe ce lock dans un environnement virtuel isole et refuse le
payload si la version installee ne correspond pas exactement a `models.lock`.

## Audit supply-chain en CI

Le job `dependency-audit` de la CI lance `pip-audit` sur `requirements.lock`
avec Python 3.10 et 3.12, donc sur les deux variantes de l'arbre transitif et
non sur les seules dependances directes.
Cela maximise la couverture de detection des vulnerabilites connues. Une
vulnerabilite est ignoree explicitement et documentee dans le workflow
(`PYSEC-2026-311`, chemin serveur HTTP de ChromaDB jamais emprunte par Cortex,
voir [Securite](security.md)) ; toute autre vulnerabilite fait echouer le job.
