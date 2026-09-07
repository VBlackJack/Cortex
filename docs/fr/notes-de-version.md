# Notes de version

**Français** | [English](../en/release-notes.md)

[Retour au sommaire](index.md)

Cette page résume les changements visibles pour les utilisateurs. Le
[journal technique](../../CHANGELOG.md) contient le détail complet.

<!-- release:2026-0907-00 -->
## 2026.0907.00 - 2026-09-07

- L'ajout d'une source Confluence répond en une seconde environ, quelle que soit la taille de l'espace. La mesure du périmètre ne parcourt plus l'espace page par page, ce qui prenait plus de trois minutes sur un grand espace et n'affichait rien du tout dans Companion.
- La fenêtre de périmètre est de nouveau lisible. Ses trois options s'affichaient dans la couleur de texte du système sur le fond sombre.
- Un délai dépassé le dit désormais. Le chargement d'une arborescence n'accuse plus la connexion réseau, et le conseil nomme le délai maximal réellement sélectionnable au lieu de suggérer une augmentation qui revient en arrière sans le dire.
- Les comptages de pages d'un espace entier peuvent varier de un. La page collée n'est plus comptée deux fois, et un espace où aucune page n'est visible affiche zéro au lieu de un.

Mettez Cortex et Companion à jour ensemble avec l'installeur combiné. Un déploiement Confluence dont la recherche ne renvoie pas de total ne peut pas mesurer un périmètre, et le dit maintenant au lieu de réessayer.

<!-- release:2026-0906-02 -->
## 2026.0906.02 - 2026-09-06

- Retrouvez et modifiez vos sources depuis Mes sources, avec recherche et arborescence.
- Vérifiez les pages et sous-pages concernées avant d'enregistrer ; mettez la recherche à jour maintenant ou plus tard.
- Annulez le dernier retrait pendant la session si la configuration est inchangée. Aucun original Confluence n'est supprimé.
- Suivez la disponibilité et reprenez une erreur avec Réessayer ou Reconnecter Confluence.

Mettez Cortex et Companion à jour ensemble avec l'installeur combiné. La recette utilisateur et les contrôles d'accessibilité natifs restent manuels.

<!-- release:2026-0906-01 -->
## 2026.0906.01 - 2026-09-06

- Companion propose un accueil guidé et un historique des opérations.
- Ajouter du contenu Confluence en collant un lien de page ou d'espace ; la connexion se fait dans le même écran si nécessaire.
- Vérifier le nombre de pages avant de confirmer le périmètre. Une annulation ou une erreur d'authentification préserve les sources configurées.
- La collecte guidée lance l'indexation seulement après une collecte réussie ; une fraîcheur inconnue reste explicite.
- Les aperçus de recherche permettent de copier les extraits et références ; la vérification des mises à jour est disponible à la demande.

Mettre Cortex et Companion à jour ensemble avec l'installeur combiné. Les essais avec compte Confluence réel, Narrator et DPI physique restent manuels.

<!-- release:2026-0906-00 -->
## 2026.0906.00 - 2026-09-06

- Companion propose un écran de recherche avec extraits, filtres et ouverture
  explicite de la source, via le nouveau contrat `cortex search --json`.
- La recherche peut être interrompue avec Échap et écarte les réponses aux critères
  modifiés. Les sources impossibles à ouvrir présentent une explication.
- Les saisies non enregistrées des réglages et de la programmation sont conservées
  au rechargement ; la fraîcheur et les actions de récupération sont accessibles.
- La génération publiée et la dernière indexation réussie observée sont
  distinguées dans Companion ; une preuve absente reste non confirmée.
- Les erreurs de journal ne bloquent plus les workers ; un défaut de purge
  après publication est signalé comme une maintenance dégradée.
- La recherche écarte les candidats lexicaux supprimés de Chroma et préserve
  les domaines locaux et collectés ayant des chemins identiques.
- Un corpus FR/EN, des benchmarks isolés et des tests de reprise complètent
  les validations. Le workflow `release-pair` vérifie deux SHA explicites.

Voir [le guide de validation](validation-recherche.md) pour les commandes et
les limites, notamment l'absence de validation manuelle Narrator/multi-écran.

<!-- release:2026-0904-03 -->
## 2026.0904.03 - 2026-09-04

- Lancer la suite de tests de Cortex sur un poste de développement n'écrit plus
  dans le vrai journal de Cortex, donc `cortex doctor` sur ce poste ne liste
  plus d'erreurs venues des fixtures de test.
- Cortex Companion : les deux preuves d'interopérabilité conservées sous
  `tests/interop` sont décrites dans le README, avec ce qu'elles vérifient et
  comment les lancer.

<!-- release:2026-0904-02 -->
## 2026.0904.02 - 2026-09-04

- `cortex sync` lancé depuis une console ou depuis `sync.bat` rend le même code
  de sortie que le mode `--json` : un sync partiel ou en échec ne se termine
  plus par `0` sans rien dire, et Ctrl+C arrête proprement avec le code `130`.
- Nouvelle commande `cortex search "votre question"` pour interroger l'index
  depuis la console, avec `--section` et `--top-k`. L'ancienne forme
  `cortex sync --search` reste acceptée.
- Chaque option de la ligne de commande est expliquée dans `--help`, et le
  message affiché quand aucun dossier n'est configuré renvoie vers
  `cortex setup`.
- Cortex Companion affiche un compteur de fichiers pendant la synchronisation
  locale au lieu d'une barre indéterminée ; il faut ce Cortex pour le voir.
- Companion : le PAT Confluence s'enregistre uniquement dans Réglages, les
  libellés de navigation et de boutons sont harmonisés, Entrée valide le champ
  en cours de saisie, un écran bloqué indique quel écran ouvrir, et un succès de
  programmation n'est plus affiché comme un avertissement.
- Les pages françaises de l'installeur retrouvent leurs accents.

<!-- release:2026-0904-01 -->
## 2026.0904.01 - 2026-09-04

- Le fichier de configuration Confluence écrit désormais les identifiants de
  page d'une seule façon. Ce sont des tables `[[spaces.pages]]`, et un espace
  configuré sans aucune page omet simplement la clef au lieu d'écrire une liste
  vide en ligne. Les fichiers écrits avant cette version continuent de
  fonctionner tels quels ; seul `selection = "subtree"` porte encore
  `pages = []`, parce que la clef y est obligatoire et que TOML ne sait pas
  écrire une liste de tables vide.

<!-- release:2026-0904-00 -->
## 2026.0904.00 - 2026-09-04

- Un espace Confluence qui ne collecte rien n'a plus l'air en bonne santé. Un
  espace dont la sélection de pages est vide est nommé dans le journal, compte
  à part des espaces qui ont produit des pages, et fait passer la santé de la
  source en dégradée. Auparavant il n'énumérait rien, ne journalisait rien,
  comptait comme un succès et laissait la santé à `ok` : un espace pouvait
  rester non indexé pendant des heures alors que tous les signaux disaient que
  la synchronisation s'était bien passée.
- Cortex Companion ne laisse plus un espace autorisé sans rien à collecter sans
  vous le dire. Autoriser un espace et ajouter sa page sont désormais un seul
  geste : si la page n'est pas ajoutée, Companion demande s'il faut garder un
  espace qui ne collectera rien, et le retire si vous refusez. Le premier
  lancement pose la même question, et retirer la dernière page d'une sélection
  aussi.
- Chaque carte d'espace indique ce que la dernière collecte a couvert : un
  espace à zéro page se lit comme tel, sans ouvrir un journal ni un fichier de
  configuration.

<!-- release:2026-0903-02 -->
## 2026.0903.02 - 2026-09-03

- Cortex Companion sait autoriser un nouvel espace Confluence depuis l'écran
  `Pages`. Collez l'URL de n'importe quelle page de l'espace, choisissez sa
  classification, confirmez : modifier `confluence.toml` à la main n'est plus
  le seul chemin. Seul l'écran de premier lancement en était capable, et il
  disparaît dès que le fichier existe.
- Ajouter une page d'un espace pas encore autorisé ne s'arrête plus sur une
  erreur. La carte est préremplie avec l'URL que vous venez de coller, elle
  nomme l'espace concerné, et la confirmer ajoute votre page dans la foulée.
- Les messages d'erreur ne se terminent plus par les lignes de journal écrites
  par Cortex pendant son travail. Seule la phrase qui vous est destinée reste.

<!-- release:2026-0903-01 -->
## 2026.0903.01 - 2026-09-03

- Le rapport de synchronisation compte désormais les documents sans corps
  indexable. Une page qui ne porte qu'une macro enfants de Confluence, ou aucun
  texte, était comptée comme ignorée avec les fichiers inchangés et n'était
  journalisée nulle part. Elle a maintenant son propre compteur et sa propre
  ligne de journal, donc elle est retrouvable.
- Cortex Companion arrête de suivre une synchronisation quand l'écran qui la
  suit est remplacé. L'écran abandonné continuait à lire l'état local en
  arrière-plan.
- Cortex Companion renomme trois couleurs de thème pour que chacune porte le
  nom du pinceau qui la lit. Aucun changement visible.

<!-- release:2026-0903-00 -->
## 2026.0903.00 - 2026-09-03

- Une erreur d'usage de la ligne de commande, par exemple une option mal
  tapée, sort désormais avec le code entrée invalide (6). Elle sortait avec 2,
  que Cortex Companion lit comme "une autre opération tient l'index".
- `cortex sync --search` ne s'arrête plus sur une console Windows incapable
  d'afficher un caractère de vos notes, par exemple un emoji. Le caractère est
  écrit sous forme de séquence d'échappement et la suite de la liste s'affiche.
- Cortex Companion retire neuf textes d'interface qu'aucun écran n'affichait.
  Aucun changement visible.

<!-- release:2026-0902-01 -->
## 2026.0902.01 - 2026-09-02

- Cortex Companion s'ouvre de nouveau normalement. La version `2026.0902.00`
  pouvait s'arrêter avant d'afficher sa fenêtre à cause d'une liaison invalide
  sur la barre de progression.
- En cas d'échec de démarrage inattendu, la boîte de dialogue indique maintenant
  le type et le message de l'exception, en plus du dossier local des journaux.
- La barrière de release ouvre désormais la fenêtre Companion complète afin de
  détecter cette catégorie d'échec WPF avant publication.

<!-- release:2026-0902-00 -->
## 2026.0902.00 - 2026-09-02

- Le jeton Confluence ne peut plus quitter l'instance que vous avez choisie. Une
  redirection HTTP vers un autre hôte est désormais refusée au lieu d'être suivie
  avec l'en-tête d'authentification.
- L'adresse Confluence doit maintenant être en `https`, sauf pour une instance
  locale de test. Une adresse en clair exposait le jeton sur le réseau. Companion
  le signale dès que vous collez l'URL de la première page.
- Companion permet enfin d'interrompre une collecte en cours. Le bouton
  `Interrompre` demande confirmation, annonce ce qui va se passer, puis arrête
  l'opération. La génération déjà publiée reste intacte.
- Fermer Companion pendant une opération demande maintenant confirmation, et
  rappelle que l'opération continue en arrière-plan.
- `Collecter Confluence` est remonté sur la carte principale de `Base locale`,
  à côté de la synchronisation locale, au lieu d'être caché sous les options
  avancées.
- `F5` recharge l'écran courant et `Ctrl+S` enregistre depuis les Réglages. Le
  raccourci est rappelé dans l'infobulle du bouton.
- Les bordures de Companion sont plus lisibles : leur contraste passait sous le
  seuil d'accessibilité sur les lignes mises en avant.
- `cortex --help` décrit maintenant chaque sous-commande, et `cortex sync --help`
  affiche une ligne d'usage que vous pouvez recopier telle quelle.
- `cortex setup --kb-path` permet une installation sans invite sans avoir à
  définir une variable d'environnement au préalable.

<!-- release:2026-0901-05 -->
## 2026.0901.05 - 2026-09-01

- Quand vous collez une URL de page, Companion compte maintenant la page seule,
  son arborescence et l'espace entier avant d'enregistrer le choix. Si la page a
  des descendants, l'arborescence est sélectionnée et recommandée par défaut.
- Chaque choix affiche le nombre de pages, une estimation du stockage, son
  emplacement physique et la rétention configurée. Le champ `target` est
  clairement présenté comme un préfixe logique, avec un bouton pour ouvrir la
  génération courante.
- Une collecte manuelle démarre toujours immédiatement. Une modification du
  périmètre invalide aussi la cadence des exécutions automatisées.
- Pendant une collecte longue, Companion affiche la phase et la progression
  chiffrée. Après la collecte, un périmètre trop étroit signale les descendants
  exclus et propose de passer à l'arborescence en un clic.
- Un rejet par `failure_threshold` explique maintenant le nombre et le taux
  d'échecs, le seuil appliqué et les actions possibles. Les anciens dossiers
  temporaires Confluence orphelins sont nettoyés prudemment au démarrage.

<!-- release:2026-0901-04 -->
## 2026.0901.04 - 2026-09-01

- Cette version de remplacement publie les correctifs Confluence de
  `2026.0901.03`, dont la construction avait été bloquée avant publication.
- L'installeur fournit automatiquement le convertisseur console et Companion
  répare les configurations existantes sans demander de chemin à l'utilisateur.
- La fabrication vérifie maintenant localement la source, les tests et la
  capacité `--probe` du convertisseur avant de l'inclure dans l'installeur.

<!-- release:2026-0901-03 -->
## 2026.0901.03 - 2026-09-01

- L'installeur fournit maintenant le vrai convertisseur Confluence console.
  Une installation standard ne demande plus aucun chemin de convertisseur.
- Companion vérifie le convertisseur en moins de cinq secondes avant de
  l'enregistrer. L'application graphique `ConfluenceRAGBuilder.exe` est refusée
  immédiatement au lieu d'ouvrir une fenêtre puis d'attendre sans résultat.
- Les fichiers `confluence.toml` schema v2 créés sans `console_path` sont
  réparés automatiquement et atomiquement au premier chargement.
- Les échecs indiquent le chemin effectif du convertisseur dans les journaux,
  et les dossiers temporaires `cortex-confluence-*` sont supprimés sur tous les
  chemins de sortie.

<!-- release:2026-0901-02 -->
## 2026.0901.02 - 2026-09-01

- Le délai choisi dans `Réglages` s'applique maintenant à toutes les commandes
  courtes lancées par Companion : connexion, lecture de la configuration Cortex
  et gestion des pages Confluence.
- Sur un poste lent, choisir 60 ou 120 secondes puis `Enregistrer et connecter`
  empêche Companion d'interrompre `cortex.exe` pendant son démarrage.
- Un vrai dépassement de délai est maintenant annoncé clairement avec l'action
  à effectuer. Il n'est plus masqué par le message trompeur `Le CLI a refuse la
  lecture`.
- Les réglages existants sont repris automatiquement ; aucun TOML ni PAT ne doit
  être ressaisi après la mise à jour.

<!-- release:2026-0901-01 -->
## 2026.0901.01 - 2026-09-01

- La première configuration Confluence se fait maintenant directement dans
  `Pages Confluence`. Collez l'URL d'une page, choisissez la date d'expiration
  du PAT et la classification, puis cliquez sur `Initialiser et ajouter la page`.
- Companion détecte l'adresse de l'instance et la clé d'espace dans les URL qui
  les exposent. Les anciennes URL `viewpage.action` et les liens courts restent
  acceptés ; il suffit alors de saisir la clé d'espace affichée dans Confluence.
- Le fichier `confluence.toml` est créé de façon verrouillée, validée et atomique.
  Le PAT reste uniquement dans le Gestionnaire d'identifiants Windows protégé
  par DPAPI ; il n'est jamais écrit dans ce fichier.
- Le convertisseur externe peut être sélectionné dans le même écran. Il est
  facultatif pour gérer les pages, mais reste requis pour lancer leur collecte.

<!-- release:2026-0901-00 -->
## 2026.0901.00 - 2026-09-01

- Le PAT Confluence peut maintenant être enregistré dès la première ouverture,
  même avant la création de `confluence.toml`. Companion utilise alors la même
  cible Windows par défaut que Cortex : `cortex-spike`.
- Tant que `confluence.toml` n'existe pas, l'ajout de pages reste désactivé et
  l'écran indique le prérequis au lieu de lancer une commande vouée à échouer.
  Une actualisation suffit à réactiver l'action après création du fichier.
- Une configuration incomplète est maintenant signalée comme invalide avec le
  détail utile (`base_url` ou `auth_expires_at` manquant), au lieu du message
  générique `La CLI a refuse la lecture`.

<!-- release:2026-0831-01 -->
## 2026.0831.01 - 2026-08-31

- `Reglages > Authentification Confluence` propose maintenant un champ masqué
  pour le Personal Access Token (PAT). Configurez d'abord Confluence, puis
  enregistrez le PAT avant la première collecte ou lors de son renouvellement.
- Companion lit le `credential_target` configuré et stocke le PAT pour le
  compte Windows courant dans le Gestionnaire d'identifiants Windows, protégé
  par DPAPI. Le secret n'est jamais écrit dans les réglages Companion, le
  fichier TOML Confluence ou les journaux.
- La commande `cortex confluence store-credential` reste disponible pour
  l'administration en ligne de commande et utilise la même entrée sécurisée.

<!-- release:2026-0831-00 -->
## 2026.0831.00 - 2026-08-31

- Sur un ordinateur lent, `Réglages` permet maintenant de choisir combien de
  temps Companion attend le démarrage de Cortex : 15, 30, 60 ou 120 secondes.
  La valeur par défaut est 30 secondes.
- La vérification de version de Cortex ne charge plus les modèles hors ligne.
  La connexion initiale est donc plus rapide, même si un délai plus long reste
  disponible pour les postes où Cortex met davantage de temps à démarrer.
- Si Cortex ne répond toujours pas avant la limite choisie, Companion reste en
  lecture seule et l'écran Pages ne lance pas Cortex une seconde fois.

<!-- release:2026-0827-03 -->
## 2026.0827.03 - 2026-08-27

- Correction : l'écran Pages affichait une erreur de réponse invalide dès qu'un
  espace passait en mode sous-arbre. Ses racines n'étaient pas transmises à
  l'interface. Mettez à jour avant d'utiliser le mode sous-arbre introduit en
  2026.0827.02.

<!-- release:2026-0827-02 -->
## 2026.0827.02 - 2026-08-27

- Un troisième mode de collecte arrive : le sous-arbre. Chaque page listée
  devient une racine, et Cortex collecte aussi toutes ses pages descendantes.
  Utile quand vous voulez une branche entière d'un espace sans prendre l'espace
  complet.
- L'arborescence est résolue à chaque collecte, pas figée dans le fichier : les
  pages ajoutées plus tard sous une racine sont reprises automatiquement.
- Dans Companion, le bouton de changement de mode fait maintenant le tour des
  trois modes : espace entier, puis pages explicites, puis sous-arbre. En
  passant de pages à sous-arbre, vos pages déjà listées deviennent les racines.
- Une racine de sous-arbre se retire comme n'importe quelle page explicite.

<!-- release:2026-0827-01 -->
## 2026.0827.01 - 2026-08-27

- Une case "Forcer la collecte" permet désormais de lancer une collecte
  Confluence sans attendre l'échéance planifiée par Cortex. Auparavant, une
  collecte déjà réussie dans l'intervalle bloquait le bouton jusqu'à
  l'échéance, sans recours depuis l'interface.
- Le message affiché dans ce cas explique ce qui se passe et indique la case à
  cocher, au lieu de présenter un code de sortie brut à côté des vraies
  erreurs.

<!-- release:2026-0827-00 -->
## 2026.0827.00 - 2026-08-27

- Ajouter une page Confluence accepte maintenant l'adresse que le navigateur
  affiche sur les versions récentes de Confluence, de la forme
  `/spaces/ESPACE/pages/ID/Titre`. Il n'est plus nécessaire de retrouver l'ID
  numérique à la main. Les autres formes déjà reconnues continuent de
  fonctionner.
- Coller l'adresse d'un accueil d'espace, et non d'une page, indique désormais
  ce qui est attendu au lieu d'un simple refus.
- Quand la page appartient à un espace absent du fichier de configuration,
  Companion explique que l'espace doit d'abord y être déclaré, et qu'il ne le
  crée pas lui-même.

<!-- release:2026-0808-00 -->
## 2026.0808.00 - 2026-08-08

- Un seul installeur Windows fournit maintenant Cortex, les modèles hors ligne
  et Cortex Companion. Aucun Python ni runtime .NET séparé n'est requis.
- Companion devient le parcours recommandé sans terminal : `Réglages` détecte
  Cortex et permet de choisir le dossier documentaire ; `Base locale` puis
  `Synchroniser les documents locaux` lancent et suivent une synchronisation.
- L'export, l'import et le retour arrière des bases sont reportés hors de cette
  release. L'index local peut être reconstruit depuis le Vault et les sources
  configurées en relançant une synchronisation.
- Les utilisateurs Python avancés peuvent installer le paquet public
  `cortex-local-rag` depuis PyPI. Les releases publient aussi la déclaration du
  serveur dans le registre MCP.
- La chaîne de release construit et teste l'installeur unifié avant de publier
  les paquets et artefacts.

<!-- release:notice-2026-08-06 -->
## Avis du 2026-08-06 - historique publié réécrit

L'historique publié de Cortex a été réécrit le 2026-08-06. Sept commits d'avril
exposaient une adresse email personnelle dans les champs auteur et committer,
et six trailers exposaient une seconde adresse. Les adresses ne sont pas
reproduites ici.

Tous les identifiants de commit ont changé. Un clone créé avant le 2026-08-06
diverge maintenant de `origin/main`. Le moyen le plus simple est de refaire un
clone. Sinon :

```console
git fetch origin
git reset --hard origin/main
```

Attention : `git reset --hard` détruit les modifications locales. Sauvegardez
d'abord tout travail à conserver.

Aucun octet de contenu n'a changé et cette réécriture ne modifie aucun
comportement. Les 121 arbres sont byte-identiques dans le même ordre, les dates
auteur et committer sont inchangées, et `git fsck` a rendu le code 0. Les cinq
tags ont été repointés. Les cinq Releases GitHub et leurs artefacts restent
téléchargeables.

<!-- release:2026-0805-00 -->
## 2026.0805.00 - 2026-08-05

- Cortex peut maintenant produire des générations documentaires atomiques,
  suivre leur fraîcheur et indexer les documents de la génération publiée.
- Le writer Confluence optionnel collecte seulement les espaces ou pages
  autorisés, conserve les artefacts source et publie le Markdown par génération.
- Le writer gère les pages vides, nettoie les noms de pièces jointes et regroupe
  les conversions en lots.
- La sélection de pages, les mutations atomiques de configuration et une
  surface CLI lisible par une interface externe sont disponibles.
- Les métadonnées de recherche v2 ajoutent des filtres structurés et une
  migration réversible avec sauvegarde et restauration.
- Antigravity et LM Studio rejoignent les clients MCP détectés par le setup.
- L'installeur ferme l'application avant remplacement et refuse de continuer si
  sa compilation échoue. Les invites du setup expliquent mieux leurs effets.
- Les dépendances MCP corrigent CVE-2026-52869, CVE-2026-52870 et
  CVE-2026-59950. Les releases fournissent des checksums et une attestation de
  provenance.
- Une FAQ, une spécification publique et les guides FR/EN couvrent ces nouveaux
  parcours.

<!-- release:2026-0716-01 -->
## 2026.0716.01 - 2026-07-16

- L'installeur Windows embarque un modèle hors ligne épinglé.
- Le runtime vérifie le manifeste du modèle avant de le charger.

<!-- release:2026-0716-00 -->
## 2026.0716.00 - 2026-07-16

- La documentation met en avant l'installeur Windows et les binaires autonomes.
- Le setup enregistre les clients MCP avant l'indexation initiale. Un échec de
  cette indexation n'annule plus l'enregistrement des clients.
- Le runtime package utilise le magasin de certificats du système, notamment
  pour les autorités d'entreprise.

<!-- release:2026-0715-01 -->
## 2026.0715.01 - 2026-07-15

- Un installeur Windows Inno Setup est disponible.
- L'indexation de tout le dossier devient le choix par défaut.
- Une réinstallation peut conserver ou réinitialiser l'état Cortex.
- `cortex unregister` retire les entrées Cortex des clients MCP.

<!-- release:2026-0715-00 -->
## 2026.0715.00 - 2026-07-15

Première version publique : recherche locale multilingue, indexation hybride
vectorielle et lexicale, synchronisation incrémentale, outils MCP, setup et
diagnostic, documentation FR/EN et binaires autonomes.
