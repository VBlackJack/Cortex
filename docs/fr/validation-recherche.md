# Validation de la recherche et des versions associées

**Français** | [English](../en/retrieval-validation.md)

[Retour au sommaire](index.md)

Ces fonctionnalités sont présentes dans les sources non encore publiées. Une
ancienne installation ne fournit pas nécessairement le nouveau contrat JSON.

## Recherche depuis Companion ou la console

```text
cortex search "renouvellement du certificat" --json --section operations --source-kind note --top-k 5
```

Les filtres sont facultatifs. Une réponse réussie contient `contract_version: 1`,
`operation: search`, `status: succeeded`, le mode de classement effectivement
utilisé, un indicateur `degraded` et la liste `results`. Chaque résultat fournit
son titre, son extrait, sa section, son type de source, son chemin, sa date de
mise à jour si elle est connue et une cible d'ouverture éventuelle.

Une erreur renvoie un code de sortie non nul : elle ne doit pas être interprétée
comme une recherche réussie sans résultat. Les requêtes sont limitées à
2 000 caractères, les extraits à 1 200 caractères et les résultats à dix.

La cible d'ouverture privilégie l'URL HTTPS canonique de la source. Pour un
document local, le chemin doit désigner un fichier Markdown, texte ou PDF existant
dans la base configurée. Companion refuse les URL contenant des identifiants,
les chemins de partage réseau et les fichiers exécutables. L'ouverture exige
une action explicite de l'utilisateur.

## Pertinence et performances

Depuis le dépôt source, avec ses dépendances verrouillées installées et un cache
de modèles Cortex existant dont le manifeste est valide :

```powershell
python eval/retrieval_benchmark.py --model-cache "$env:LOCALAPPDATA/Cortex/models" --output local/retrieval/baseline.json
python eval/retrieval_benchmark.py --model-cache "$env:LOCALAPPDATA/Cortex/models" --output local/retrieval/current.json --baseline local/retrieval/baseline.json
```

Le programme crée une base documentaire, une configuration et un index temporaires
dans un processus séparé. Il réutilise les modèles avec l'accès réseau désactivé.
Les fichiers temporaires sont retirés après fermeture du processus et de ses
handles natifs. Il ne synchronise ni l'index utilisateur ni un serveur Confluence.

Le corpus fourni comporte 15 documents synthétiques et 30 questions français/anglais.
Il permet une comparaison reproductible, mais ne remplace pas des jugements de
pertinence sur les documents de l'utilisateur. `--corpus` accepte un autre fichier
respectant la structure de `eval/retrieval_corpus.json`.

Le rapport contient l'empreinte du corpus, les modèles et versions de dépendances,
le rappel, le MRR, le nDCG et la latence p95 des stratégies vectorielle, hybride et
avec reranking. Plusieurs fragments du même document ne gonflent pas le rappel.
Le classement par défaut du produit reste inchangé.

La comparaison à une référence refuse par défaut une baisse de rappel.
`--max-recall-drop` fixe une tolérance absolue ; `--max-latency-ratio` ajoute une
limite facultative sur le rapport des latences p95. Le corpus et le nombre de
résultats doivent correspondre. Une régression est consignée dans le rapport et
produit un code de sortie non nul. Le rapport courant ne peut pas écraser le
fichier de référence utilisé pour sa comparaison.

Les mesures distinguent l'initialisation, l'indexation initiale, le chargement du
reranker, une requête après indexation, la première recherche JSON dans un nouvel
interpréteur, l'indexation incrémentale, la taille de l'index et la mémoire.
Sous Windows, la mémoire est le working set résident au moment de la mesure ;
sous Unix, le maximum RSS du processus. Les caches du système ne sont pas vidés.
Une mesure sur ce petit corpus ne démontre pas la capacité en charge réelle.

Pour mesurer séparément le lancement d'un exécutable précis :

```powershell
python eval/startup_benchmark.py --executable "$env:LOCALAPPDATA/Programs/Cortex/cortex.exe" --output local/retrieval/startup.json
```

Seul `--version` est exécuté. Le rapport conserve le SHA-256 du binaire, sa version
et cinq temps de lancement. Ce test ne mesure pas l'affichage de la fenêtre WPF.

## Reprise et livraison coordonnée

Les tests d'ingestion couvrent l'arrêt brutal avant la publication du pointeur,
la reprise après redémarrage, un disque plein simulé et une énumération interrompue
suivie d'une nouvelle tentative. Ils vérifient la conservation de la génération
servie et l'absence de suppression des sources non observées lors d'une collecte
partielle. Ils ne simulent pas toutes les défaillances possibles du stockage.

Le workflow manuel `release-pair`, présent dans les deux dépôts, exige les deux
SHA complets en minuscules : `cortex_sha` et `companion_sha`. Il contrôle les
révisions réellement récupérées, puis vérifie le verrou partagé, le TOML v1/v2/v3
et le JSON de recherche, et analyse chaque ligne de commande que le bureau construit
avec le parseur Cortex qui l'exécute. Son résumé identifie le couple testé. Le
workflow courant `interoperability` utilise toujours `main` du partenaire par défaut.

Cette validation porte sur l'interopérabilité des sources. Elle ne certifie ni
les octets d'un installeur ni une signature de release.
