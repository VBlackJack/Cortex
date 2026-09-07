# Installation reproductible

**Français** | [English](../en/reproducible-install.md)

[Retour au sommaire](index.md)

## Quatre contrats, quatre rôles

Cortex distingue quatre niveaux d'épinglage des dépendances :

| Fichier | Portée | Usage |
|---|---|---|
| `requirements.txt` | Les dépendances d'exécution directes, épinglées en version exacte | Source unique lue par `pyproject.toml` ; install standard |
| `requirements.lock` | L'arbre transitif complet, verrouillé par hash | Install reproductible et audit supply-chain |
| `requirements-dev.lock` | L'arbre exécution + test + build, verrouillé par hash | CI, création des binaires et publication |
| `requirements-model.txt` / `requirements-model.lock` | Les versions de `fastembed` et `huggingface-hub` déclarées par `models.lock`, avec leur arbre verrouillé par hash | Fabrication et attestation isolées du payload de modèles |

`requirements.txt` fige les versions des paquets que Cortex importe directement,
mais laisse pip résoudre librement leurs propres dépendances. `requirements.lock`
fige en plus tout le transitif et attache à chaque paquet ses hashes SHA-256.
`requirements-dev.lock` applique le même contrat aux outils qui testent et
construisent les artefacts. Pip refuse ainsi tout artefact non répertorié au
lieu de re-résoudre silencieusement une autre version en CI.
Le lock de modèles reste séparé car son outil de téléchargement est attesté avec
le payload et peut différer de la version transitive utilisée par Cortex.

Le lock est universel (cross-plateforme) : un seul fichier couvre Windows, Linux
et macOS via des marqueurs d'environnement. Il capture les branches
conditionnelles qu'un lock généré sur une seule plateforme raterait, par exemple
`pywin32` et `colorama` uniquement sous Windows, ou les variantes de `numpy` et
`onnxruntime` selon la version de Python.

## Installer avec verrouillage par hash

```powershell
pip install --require-hashes -r requirements.lock
```

Avec `--require-hashes`, pip refuse d'installer tout paquet dont l'archive ne
correspond pas à un hash présent dans le lock, et exige que chaque dépendance
soit épinglée. C'est le mode à utiliser pour une installation reproductible
(poste de production, CI, audit).

Vérification à blanc, sans rien installer :

```powershell
pip install --require-hashes --dry-run -r requirements.lock
```

L'installation standard décrite dans [Installation](setup.md) reste valable pour
un usage courant ; le lock est le mode strict, pas un remplacement obligatoire.

## Régénérer les locks

Dès que `requirements.txt` évolue (bump d'une dépendance, ajout, retrait), il
faut régénérer `requirements.lock`, sinon les deux divergent. La commande exacte
figure en tête du fichier `requirements.lock` :

```powershell
uv pip compile --universal --generate-hashes --python-version 3.10 requirements.txt -o requirements.lock
```

Points d'attention :

- `uv` sert uniquement à générer le lock (outil de développement). L'installeur
  reste `pip` : ni l'install standard ni la CI n'ont besoin d'`uv`.
- `--universal` produit le fichier cross-plateforme unique ; ne pas le retirer,
  sinon le lock devient spécifique à la plateforme de génération.
- `--python-version 3.10` cible la version minimale supportée, ce qui garantit
  que le lock reste valide sur toute la matrice 3.10 à 3.12.
- Committer `requirements.lock` avec le `requirements.txt` correspondant dans
  le même commit.

Quand les extras `dev` ou `build` de `pyproject.toml` changent, ou après la
régénération du lock d'exécution, régénérer aussi le lock de fabrication :

```powershell
uv pip compile --universal --generate-hashes --python-version 3.10 --extra dev --extra build pyproject.toml -o requirements-dev.lock
```

La CI installe `requirements-dev.lock` avec `--require-hashes`, puis le projet
avec `--no-build-isolation --no-deps`. Les tests et les binaires utilisent donc
exactement l'arbre audité, sans seconde résolution implicite.

Quand `fastembed_version` ou `huggingface_hub_version` change dans `models.lock`,
aligner `requirements-model.txt`, puis régénérer son lock :

```powershell
uv pip compile --universal --generate-hashes --python-version 3.10 requirements-model.txt -o requirements-model.lock
```

La release installe ce lock dans un environnement virtuel isolé et refuse le
payload si la version installée ne correspond pas exactement à `models.lock`.

## Audit supply-chain en CI

Le job `dependency-audit` de la CI lance `pip-audit` sur `requirements.lock`
avec Python 3.10 et 3.12, donc sur les deux variantes de l'arbre transitif et
non sur les seules dépendances directes.
Cela maximise la couverture de détection des vulnérabilités connues. Une
vulnérabilité est ignorée explicitement et documentée dans le workflow
(`PYSEC-2026-311`, chemin serveur HTTP de ChromaDB jamais emprunté par Cortex,
voir [Sécurité](security.md)) ; toute autre vulnérabilité fait échouer le job.
