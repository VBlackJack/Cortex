# Notes de version

**Francais** | [English](../en/release-notes.md)

[Retour au sommaire](index.md)

Cette page resume les changements visibles pour les utilisateurs. Le
[journal technique](../../CHANGELOG.md) contient le detail complet.

<!-- release:2026-0903-01 -->
## 2026.0903.01 - 2026-09-03

- Le rapport de synchronisation compte desormais les documents sans corps
  indexable. Une page qui ne porte qu'une macro enfants de Confluence, ou aucun
  texte, etait comptee comme ignoree avec les fichiers inchanges et n'etait
  journalisee nulle part. Elle a maintenant son propre compteur et sa propre
  ligne de journal, donc elle est retrouvable.
- Cortex Companion arrete de suivre une synchronisation quand l'ecran qui la
  suit est remplace. L'ecran abandonne continuait a lire l'etat local en
  arriere-plan.
- Cortex Companion renomme trois couleurs de theme pour que chacune porte le
  nom du pinceau qui la lit. Aucun changement visible.

<!-- release:2026-0903-00 -->
## 2026.0903.00 - 2026-09-03

- Une erreur d'usage de la ligne de commande, par exemple une option mal
  tapee, sort desormais avec le code entree invalide (6). Elle sortait avec 2,
  que Cortex Companion lit comme "une autre operation tient l'index".
- `cortex sync --search` ne s'arrete plus sur une console Windows incapable
  d'afficher un caractere de vos notes, par exemple un emoji. Le caractere est
  ecrit sous forme de sequence d'echappement et la suite de la liste s'affiche.
- Cortex Companion retire neuf textes d'interface qu'aucun ecran n'affichait.
  Aucun changement visible.

<!-- release:2026-0902-01 -->
## 2026.0902.01 - 2026-09-02

- Cortex Companion s'ouvre de nouveau normalement. La version `2026.0902.00`
  pouvait s'arreter avant d'afficher sa fenetre a cause d'une liaison invalide
  sur la barre de progression.
- En cas d'echec de demarrage inattendu, la boite de dialogue indique maintenant
  le type et le message de l'exception, en plus du dossier local des journaux.
- La barriere de release ouvre desormais la fenetre Companion complete afin de
  detecter cette categorie d'echec WPF avant publication.

<!-- release:2026-0902-00 -->
## 2026.0902.00 - 2026-09-02

- Le jeton Confluence ne peut plus quitter l'instance que vous avez choisie. Une
  redirection HTTP vers un autre hote est desormais refusee au lieu d'etre suivie
  avec l'en-tete d'authentification.
- L'adresse Confluence doit maintenant etre en `https`, sauf pour une instance
  locale de test. Une adresse en clair exposait le jeton sur le reseau. Companion
  le signale des que vous collez l'URL de la premiere page.
- Companion permet enfin d'interrompre une collecte en cours. Le bouton
  `Interrompre` demande confirmation, annonce ce qui va se passer, puis arrete
  l'operation. La generation deja publiee reste intacte.
- Fermer Companion pendant une operation demande maintenant confirmation, et
  rappelle que l'operation continue en arriere-plan.
- `Collecter Confluence` est remonte sur la carte principale de `Base locale`,
  a cote de la synchronisation locale, au lieu d'etre cache sous les options
  avancees.
- `F5` recharge l'ecran courant et `Ctrl+S` enregistre depuis les Reglages. Le
  raccourci est rappele dans l'infobulle du bouton.
- Les bordures de Companion sont plus lisibles : leur contraste passait sous le
  seuil d'accessibilite sur les lignes mises en avant.
- `cortex --help` decrit maintenant chaque sous-commande, et `cortex sync --help`
  affiche une ligne d'usage que vous pouvez recopier telle quelle.
- `cortex setup --kb-path` permet une installation sans invite sans avoir a
  definir une variable d'environnement au prealable.

<!-- release:2026-0901-05 -->
## 2026.0901.05 - 2026-09-01

- Quand vous collez une URL de page, Companion compte maintenant la page seule,
  son arborescence et l'espace entier avant d'enregistrer le choix. Si la page a
  des descendants, l'arborescence est selectionnee et recommandee par defaut.
- Chaque choix affiche le nombre de pages, une estimation du stockage, son
  emplacement physique et la retention configuree. Le champ `target` est
  clairement presente comme un prefixe logique, avec un bouton pour ouvrir la
  generation courante.
- Une collecte manuelle demarre toujours immediatement. Une modification du
  perimetre invalide aussi la cadence des executions automatisees.
- Pendant une collecte longue, Companion affiche la phase et la progression
  chiffree. Apres la collecte, un perimetre trop etroit signale les descendants
  exclus et propose de passer a l'arborescence en un clic.
- Un rejet par `failure_threshold` explique maintenant le nombre et le taux
  d'echecs, le seuil applique et les actions possibles. Les anciens dossiers
  temporaires Confluence orphelins sont nettoyes prudemment au demarrage.

<!-- release:2026-0901-04 -->
## 2026.0901.04 - 2026-09-01

- Cette version de remplacement publie les correctifs Confluence de
  `2026.0901.03`, dont la construction avait ete bloquee avant publication.
- L'installeur fournit automatiquement le convertisseur console et Companion
  repare les configurations existantes sans demander de chemin a l'utilisateur.
- La fabrication verifie maintenant localement la source, les tests et la
  capacite `--probe` du convertisseur avant de l'inclure dans l'installeur.

<!-- release:2026-0901-03 -->
## 2026.0901.03 - 2026-09-01

- L'installeur fournit maintenant le vrai convertisseur Confluence console.
  Une installation standard ne demande plus aucun chemin de convertisseur.
- Companion verifie le convertisseur en moins de cinq secondes avant de
  l'enregistrer. L'application graphique `ConfluenceRAGBuilder.exe` est refusee
  immediatement au lieu d'ouvrir une fenetre puis d'attendre sans resultat.
- Les fichiers `confluence.toml` schema v2 crees sans `console_path` sont
  repares automatiquement et atomiquement au premier chargement.
- Les echecs indiquent le chemin effectif du convertisseur dans les journaux,
  et les dossiers temporaires `cortex-confluence-*` sont supprimes sur tous les
  chemins de sortie.

<!-- release:2026-0901-02 -->
## 2026.0901.02 - 2026-09-01

- Le delai choisi dans `Réglages` s'applique maintenant a toutes les commandes
  courtes lancees par Companion : connexion, lecture de la configuration Cortex
  et gestion des pages Confluence.
- Sur un poste lent, choisir 60 ou 120 secondes puis `Enregistrer et connecter`
  empeche Companion d'interrompre `cortex.exe` pendant son demarrage.
- Un vrai depassement de delai est maintenant annonce clairement avec l'action
  a effectuer. Il n'est plus masque par le message trompeur `Le CLI a refuse la
  lecture`.
- Les reglages existants sont repris automatiquement ; aucun TOML ni PAT ne doit
  etre ressaisi apres la mise a jour.

<!-- release:2026-0901-01 -->
## 2026.0901.01 - 2026-09-01

- La premiere configuration Confluence se fait maintenant directement dans
  `Pages Confluence`. Collez l'URL d'une page, choisissez la date d'expiration
  du PAT et la classification, puis cliquez sur `Initialiser et ajouter la page`.
- Companion detecte l'adresse de l'instance et la cle d'espace dans les URL qui
  les exposent. Les anciennes URL `viewpage.action` et les liens courts restent
  acceptes ; il suffit alors de saisir la cle d'espace affichee dans Confluence.
- Le fichier `confluence.toml` est cree de facon verrouillee, validee et atomique.
  Le PAT reste uniquement dans le Gestionnaire d'identifiants Windows protege
  par DPAPI ; il n'est jamais ecrit dans ce fichier.
- Le convertisseur externe peut etre selectionne dans le meme ecran. Il est
  facultatif pour gerer les pages, mais reste requis pour lancer leur collecte.

<!-- release:2026-0901-00 -->
## 2026.0901.00 - 2026-09-01

- Le PAT Confluence peut maintenant etre enregistre des la premiere ouverture,
  meme avant la creation de `confluence.toml`. Companion utilise alors la meme
  cible Windows par defaut que Cortex : `cortex-spike`.
- Tant que `confluence.toml` n'existe pas, l'ajout de pages reste desactive et
  l'ecran indique le prerequis au lieu de lancer une commande vouee a echouer.
  Une actualisation suffit a reactiver l'action apres creation du fichier.
- Une configuration incomplete est maintenant signalee comme invalide avec le
  detail utile (`base_url` ou `auth_expires_at` manquant), au lieu du message
  generique `La CLI a refuse la lecture`.

<!-- release:2026-0831-01 -->
## 2026.0831.01 - 2026-08-31

- `Reglages > Authentification Confluence` propose maintenant un champ masque
  pour le Personal Access Token (PAT). Configurez d'abord Confluence, puis
  enregistrez le PAT avant la premiere collecte ou lors de son renouvellement.
- Companion lit le `credential_target` configure et stocke le PAT pour le
  compte Windows courant dans le Gestionnaire d'identifiants Windows, protege
  par DPAPI. Le secret n'est jamais ecrit dans les reglages Companion, le
  fichier TOML Confluence ou les journaux.
- La commande `cortex confluence store-credential` reste disponible pour
  l'administration en ligne de commande et utilise la meme entree securisee.

<!-- release:2026-0831-00 -->
## 2026.0831.00 - 2026-08-31

- Sur un ordinateur lent, `Réglages` permet maintenant de choisir combien de
  temps Companion attend le demarrage de Cortex : 15, 30, 60 ou 120 secondes.
  La valeur par defaut est 30 secondes.
- La verification de version de Cortex ne charge plus les modeles hors ligne.
  La connexion initiale est donc plus rapide, meme si un delai plus long reste
  disponible pour les postes ou Cortex met davantage de temps a demarrer.
- Si Cortex ne repond toujours pas avant la limite choisie, Companion reste en
  lecture seule et l'ecran Pages ne lance pas Cortex une seconde fois.

<!-- release:2026-0827-03 -->
## 2026.0827.03 - 2026-08-27

- Correction : l'ecran Pages affichait une erreur de reponse invalide des qu'un
  espace passait en mode sous-arbre. Ses racines n'etaient pas transmises a
  l'interface. Mettez a jour avant d'utiliser le mode sous-arbre introduit en
  2026.0827.02.

<!-- release:2026-0827-02 -->
## 2026.0827.02 - 2026-08-27

- Un troisieme mode de collecte arrive : le sous-arbre. Chaque page listee
  devient une racine, et Cortex collecte aussi toutes ses pages descendantes.
  Utile quand vous voulez une branche entiere d'un espace sans prendre l'espace
  complet.
- L'arborescence est resolue a chaque collecte, pas figee dans le fichier : les
  pages ajoutees plus tard sous une racine sont reprises automatiquement.
- Dans Companion, le bouton de changement de mode fait maintenant le tour des
  trois modes : espace entier, puis pages explicites, puis sous-arbre. En
  passant de pages a sous-arbre, vos pages deja listees deviennent les racines.
- Une racine de sous-arbre se retire comme n'importe quelle page explicite.

<!-- release:2026-0827-01 -->
## 2026.0827.01 - 2026-08-27

- Une case "Forcer la collecte" permet desormais de lancer une collecte
  Confluence sans attendre l'echeance planifiee par Cortex. Auparavant, une
  collecte deja reussie dans l'intervalle bloquait le bouton jusqu'a
  l'echeance, sans recours depuis l'interface.
- Le message affiche dans ce cas explique ce qui se passe et indique la case a
  cocher, au lieu de presenter un code de sortie brut a cote des vraies
  erreurs.

<!-- release:2026-0827-00 -->
## 2026.0827.00 - 2026-08-27

- Ajouter une page Confluence accepte maintenant l'adresse que le navigateur
  affiche sur les versions recentes de Confluence, de la forme
  `/spaces/ESPACE/pages/ID/Titre`. Il n'est plus necessaire de retrouver l'ID
  numerique a la main. Les autres formes deja reconnues continuent de
  fonctionner.
- Coller l'adresse d'un accueil d'espace, et non d'une page, indique desormais
  ce qui est attendu au lieu d'un simple refus.
- Quand la page appartient a un espace absent du fichier de configuration,
  Companion explique que l'espace doit d'abord y etre declare, et qu'il ne le
  cree pas lui-meme.

<!-- release:2026-0808-00 -->
## 2026.0808.00 - 2026-08-08

- Un seul installeur Windows fournit maintenant Cortex, les modeles hors ligne
  et Cortex Companion. Aucun Python ni runtime .NET separe n'est requis.
- Companion devient le parcours recommande sans terminal : `Réglages` detecte
  Cortex et permet de choisir le dossier documentaire ; `Base locale` puis
  `Synchroniser les documents locaux` lancent et suivent une synchronisation.
- L'export, l'import et le retour arriere des bases sont reportes hors de cette
  release. L'index local peut etre reconstruit depuis le Vault et les sources
  configurees en relancant une synchronisation.
- Les utilisateurs Python avances peuvent installer le paquet public
  `cortex-local-rag` depuis PyPI. Les releases publient aussi la declaration du
  serveur dans le registre MCP.
- La chaine de release construit et teste l'installeur unifie avant de publier
  les paquets et artefacts.

<!-- release:notice-2026-08-06 -->
## Avis du 2026-08-06 - historique publie reecrit

L'historique publie de Cortex a ete reecrit le 2026-08-06. Sept commits d'avril
exposaient une adresse email personnelle dans les champs auteur et committer,
et six trailers exposaient une seconde adresse. Les adresses ne sont pas
reproduites ici.

Tous les identifiants de commit ont change. Un clone cree avant le 2026-08-06
diverge maintenant de `origin/main`. Le moyen le plus simple est de refaire un
clone. Sinon :

```console
git fetch origin
git reset --hard origin/main
```

Attention : `git reset --hard` detruit les modifications locales. Sauvegardez
d'abord tout travail a conserver.

Aucun octet de contenu n'a change et cette reecriture ne modifie aucun
comportement. Les 121 arbres sont byte-identiques dans le meme ordre, les dates
auteur et committer sont inchangees, et `git fsck` a rendu le code 0. Les cinq
tags ont ete repointes. Les cinq Releases GitHub et leurs artefacts restent
telechargeables.

<!-- release:2026-0805-00 -->
## 2026.0805.00 - 2026-08-05

- Cortex peut maintenant produire des generations documentaires atomiques,
  suivre leur fraicheur et indexer les documents de la generation publiee.
- Le writer Confluence optionnel collecte seulement les espaces ou pages
  autorises, conserve les artefacts source et publie le Markdown par generation.
- Le writer gere les pages vides, nettoie les noms de pieces jointes et regroupe
  les conversions en lots.
- La selection de pages, les mutations atomiques de configuration et une
  surface CLI lisible par une interface externe sont disponibles.
- Les metadonnees de recherche v2 ajoutent des filtres structures et une
  migration reversible avec sauvegarde et restauration.
- Antigravity et LM Studio rejoignent les clients MCP detectes par le setup.
- L'installeur ferme l'application avant remplacement et refuse de continuer si
  sa compilation echoue. Les invites du setup expliquent mieux leurs effets.
- Les dependances MCP corrigent CVE-2026-52869, CVE-2026-52870 et
  CVE-2026-59950. Les releases fournissent des checksums et une attestation de
  provenance.
- Une FAQ, une specification publique et les guides FR/EN couvrent ces nouveaux
  parcours.

<!-- release:2026-0716-01 -->
## 2026.0716.01 - 2026-07-16

- L'installeur Windows embarque un modele hors ligne epingle.
- Le runtime verifie le manifeste du modele avant de le charger.

<!-- release:2026-0716-00 -->
## 2026.0716.00 - 2026-07-16

- La documentation met en avant l'installeur Windows et les binaires autonomes.
- Le setup enregistre les clients MCP avant l'indexation initiale. Un echec de
  cette indexation n'annule plus l'enregistrement des clients.
- Le runtime package utilise le magasin de certificats du systeme, notamment
  pour les autorites d'entreprise.

<!-- release:2026-0715-01 -->
## 2026.0715.01 - 2026-07-15

- Un installeur Windows Inno Setup est disponible.
- L'indexation de tout le dossier devient le choix par defaut.
- Une reinstallation peut conserver ou reinitialiser l'etat Cortex.
- `cortex unregister` retire les entrees Cortex des clients MCP.

<!-- release:2026-0715-00 -->
## 2026.0715.00 - 2026-07-15

Premiere version publique : recherche locale multilingue, indexation hybride
vectorielle et lexicale, synchronisation incrementale, outils MCP, setup et
diagnostic, documentation FR/EN et binaires autonomes.
