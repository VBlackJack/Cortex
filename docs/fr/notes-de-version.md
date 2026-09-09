# Notes de version

**FranÃ§ais** | [English](../en/release-notes.md)

[Retour au sommaire](index.md)

Cette page rÃ©sume les changements visibles pour les utilisateurs. Le
[journal technique](../../CHANGELOG.md) contient le dÃ©tail complet.

Les commandes de l'interface sont nommÃ©es comme la version actuelle les affiche, y
compris dans les entrÃ©es des versions antÃ©rieures, afin qu'une commande citÃ©e ici se
retrouve Ã  l'Ã©cran aujourd'hui.

<!-- release:2026-0909-03 -->
## 2026.0909.03 - 2026-09-09

L’installation Windows se termine désormais sans indexer les documents dans un processus caché. Après avoir cliqué sur Terminer, lancez la synchronisation dans Cortex Companion pour suivre son résultat. Les mises à jour et remises à zéro suivent aussi ce parcours. Les déploiements automatisés doivent remplacer l’ancienne option `/INDEX` par une commande `cortex sync` après la fin réussie de l’installation.

<!-- release:2026-0909-02 -->
## 2026.0909.02 - 2026-09-09

Publie les corrections dâ€™ingestion et de recherche multilingue de 2026.0909.01 avec le bon ensemble de fichiers. La version prÃ©cÃ©dente a atteint PyPI et le registre MCP ; la publication de ses binaires GitHub a Ã©tÃ© arrÃªtÃ©e par le contrÃ´le des artefacts. Les rapports du benchmark restent des preuves CI.

<!-- release:2026-0909-01 -->
## 2026.0909.01 - 2026-09-09

- Les documents Confluence retirÃ©s sont rÃ©conciliÃ©s aussi pour les cibles personnalisÃ©es. Un sous-arbre illisible prÃ©serve la derniÃ¨re gÃ©nÃ©ration publiÃ©e.
- Un changement de cible ou de classification rÃ©gÃ©nÃ¨re les Ã©lÃ©ments concernÃ©s. Une application partielle reste en attente au lieu d'annoncer la nouvelle configuration comme entiÃ¨rement appliquÃ©e.
- La recherche utilise par dÃ©faut le vectoriel multilingue. Les modes hybride et rerank restent accessibles par `--retrieval-mode` en CLI et `retrieval_mode` en MCP. Les clients existants utilisent le nouveau dÃ©faut sans changer leurs commandes.
- AprÃ¨s mise Ã  jour, la prochaine collecte rÃ©ussie renouvelle une fois les anciennes rÃ©visions de publication ; la synchronisation d'index suivante retire les versions obsolÃ¨tes accumulÃ©es. Aucune suppression manuelle d'index n'est nÃ©cessaire.

<!-- release:2026-0909-00 -->
## 2026.0909.00 - 2026-09-09

- Mes sources rÃ©unit les documents locaux et Confluence. Mettre Ã  jour mes documents collecte les sources configurÃ©es puis les indexe, avec une prochaine action claire sur lâ€™accueil.
- La recherche propose un aperÃ§u redimensionnable et des actions de rÃ©cupÃ©ration sans rÃ©sultat. Les paramÃ¨tres mettent les documents et Confluence en premier et signalent les changements de dossier non enregistrÃ©s.
- Les catalogues volumineux sont lus intÃ©gralement dans leur limite de sÃ©curitÃ©. Lâ€™arbre rÃ©alise les lignes visibles, conserve le rÃ©sumÃ© de sÃ©lection et ouvre les branches correspondantes pendant le filtrage.
- Annuler une lecture de pages ou la prÃ©paration de la confirmation conserve le brouillon sans enregistrer les changements. Un Ã©chec dâ€™Ã©dition peut Ãªtre repris tant que la configuration enregistrÃ©e nâ€™a pas changÃ©.
- Une mise Ã  jour locale rÃ©ussie indique dÃ©sormais que les documents sont prÃªts sans exiger Confluence. Changer le dossier documentaire enregistrÃ© ou la configuration impose une nouvelle indexation, y compris aprÃ¨s redÃ©marrage de Companion.
- Les guides anglais et franÃ§ais utilisent dÃ©sormais les libellÃ©s actuels de lâ€™interface.

Mettre Ã  jour Cortex et Companion ensemble avec lâ€™installeur combinÃ©. Lancer une mise Ã  jour documentaire aprÃ¨s la mise Ã  niveau : les anciens historiques dâ€™indexation ne contiennent pas la preuve de configuration nÃ©cessaire pour confirmer la disponibilitÃ©.

<!-- release:2026-0908-01 -->
## 2026.0908.01 - 2026-09-08

- Changer de mode d'indexation ne laisse plus de copies pÃ©rimÃ©es dans l'index. Une note modifiÃ©e aprÃ¨s le changement gardait sa version prÃ©cÃ©dente Ã  cÃ´tÃ© de la version courante, et une recherche pouvait rendre les deux ; la prochaine synchronisation retire ces copies et ne garde que la version courante.
- Cortex Doctor ne signale plus les documents Confluence comme des fichiers manquants. Ils vivent dans le magasin propre de Cortex, pas dans le dossier de la base de connaissances, et le rÃ©sumÃ© de fraÃ®cheur les laisse dÃ©sormais de cÃ´tÃ©.
- Cortex Doctor ne compte comme rÃ©centes que les erreurs de synchronisation des sept derniers jours, dit combien de lignes plus anciennes il a laissÃ©es de cÃ´tÃ©, et n'avertit plus pour du bruit ancien.
- La synchronisation que l'installateur lance aprÃ¨s une mise Ã  jour Ã©crit dÃ©sormais dans le journal comme une synchronisation manuelle.
- L'historique de Companion conserve une opÃ©ration dont le rapport n'a pas de compteur. Il indique que les compteurs dÃ©taillÃ©s ne sont pas disponibles au lieu d'afficher une entrÃ©e illisible.

Mettez Ã  jour Cortex et Companion ensemble avec l'installateur combinÃ©.

<!-- release:2026-0908-00 -->
## 2026.0908.00 - 2026-09-08

- Coller une page qu'une source collecte dÃ©jÃ  ne finit plus par un refus. La fenÃªtre de pÃ©rimÃ¨tre le dit d'emblÃ©e, et une fois le pÃ©rimÃ¨tre choisi Companion montre les deux faÃ§ons de fusionner, cÃ´te Ã  cÃ´te : Ã©largir la source, ou remplacer sa sÃ©lection, chacune avec les documents qu'elle ajoute et retire. Une page situÃ©e sous un sous-arbre suivi est reconnue aussi ; elle passait pour nouvelle et se faisait refuser plus tard.
- La recherche n'a plus d'exigence de version Ã  elle. Elle suit la vÃ©rification de dÃ©marrage comme toutes les autres fonctions, et le message qui rÃ©clamait une version prÃ©cise de Cortex a disparu.
- Le document de prÃ©visualisation de la ligne de commande dit si l'espace configurÃ© collecte dÃ©jÃ  la page, et par quelle page listÃ©e.

Mettez Cortex et Companion Ã  jour ensemble avec l'installeur combinÃ©.

<!-- release:2026-0907-03 -->
## 2026.0907.03 - 2026-09-07

- Rien ne change Ã  l'Ã©cran. Cette version porte les contrÃ´les qui gardent Cortex et Companion en phase : chaque ligne de commande que Companion envoie Ã  Cortex est dÃ©sormais vÃ©rifiÃ©e contre Cortex lui-mÃªme avant une release, si bien qu'une commande renommÃ©e fait Ã©chouer la construction plutÃ´t que le bureau.
- Deux tests qui dÃ©pendaient de la charge de la machine n'en dÃ©pendent plus.

Mettez Cortex et Companion Ã  jour ensemble avec l'installeur combinÃ©.

<!-- release:2026-0907-02 -->
## 2026.0907.02 - 2026-09-07

- Le chargement de l'arborescence d'un grand espace va maintenant jusqu'au bout au lieu de s'arrÃªter en chemin. Lire un espace entier demande environ deux minutes pour six mille pages, bien au-delÃ  du dÃ©lai par dÃ©faut et Ã  quelques secondes prÃ¨s sous le plus Ã©levÃ© : cette lecture dispose donc de son propre budget, et si elle manque quand mÃªme de temps, le message indique combien de pages avaient Ã©tÃ© lues.
- La fenÃªtre de pÃ©rimÃ¨tre signale qu'une page est dÃ©jÃ  suivie, pour que le choix se fasse en le sachant plutÃ´t que d'Ãªtre refusÃ© ensuite.
- Companion refuse un Cortex plus ancien que celui qu'il embarque, et le dit, au lieu d'Ã©chouer plus tard sans explication.

Mettez Cortex et Companion Ã  jour ensemble avec l'installeur combinÃ©.

<!-- release:2026-0907-01 -->
## 2026.0907.01 - 2026-09-07

- Companion parle anglais. Son interface n'existait qu'en franÃ§ais, quelle que soit la langue de Windows ; elle suit dÃ©sormais la langue de Windows et propose un choix explicite dans les RÃ©glages, appliquÃ© au prochain dÃ©marrage.
- Une langue que Companion ne fournit pas retombe sur l'anglais plutÃ´t que sur le franÃ§ais.
- La documentation franÃ§aise nomme les commandes en franÃ§ais, accents compris, et la documentation anglaise les nomme en anglais, afin qu'une commande citÃ©e dans une page se retrouve Ã  l'Ã©cran.

Mettez Cortex et Companion Ã  jour ensemble avec l'installeur combinÃ©.

<!-- release:2026-0907-00 -->
## 2026.0907.00 - 2026-09-07

- L'ajout d'une source Confluence rÃ©pond en une seconde environ, quelle que soit la taille de l'espace. La mesure du pÃ©rimÃ¨tre ne parcourt plus l'espace page par page, ce qui prenait plus de trois minutes sur un grand espace et n'affichait rien du tout dans Companion.
- La fenÃªtre de pÃ©rimÃ¨tre est de nouveau lisible. Ses trois options s'affichaient dans la couleur de texte du systÃ¨me sur le fond sombre.
- Un dÃ©lai dÃ©passÃ© le dit dÃ©sormais. Le chargement d'une arborescence n'accuse plus la connexion rÃ©seau, et le conseil nomme le dÃ©lai maximal rÃ©ellement sÃ©lectionnable au lieu de suggÃ©rer une augmentation qui revient en arriÃ¨re sans le dire.
- Les comptages de pages d'un espace entier peuvent varier de un. La page collÃ©e n'est plus comptÃ©e deux fois, et un espace oÃ¹ aucune page n'est visible affiche zÃ©ro au lieu de un.

Mettez Cortex et Companion Ã  jour ensemble avec l'installeur combinÃ©. Un dÃ©ploiement Confluence dont la recherche ne renvoie pas de total ne peut pas mesurer un pÃ©rimÃ¨tre, et le dit maintenant au lieu de rÃ©essayer.

<!-- release:2026-0906-02 -->
## 2026.0906.02 - 2026-09-06

- Retrouvez et modifiez vos sources depuis Mes sources, avec recherche et arborescence.
- VÃ©rifiez les pages et sous-pages concernÃ©es avant d'enregistrer ; mettez la recherche Ã  jour maintenant ou plus tard.
- Annulez le dernier retrait pendant la session si la configuration est inchangÃ©e. Aucun original Confluence n'est supprimÃ©.
- Suivez la disponibilitÃ© et reprenez une erreur avec RÃ©essayer ou Reconnecter Confluence.

Mettez Cortex et Companion Ã  jour ensemble avec l'installeur combinÃ©. La recette utilisateur et les contrÃ´les d'accessibilitÃ© natifs restent manuels.

<!-- release:2026-0906-01 -->
## 2026.0906.01 - 2026-09-06

- Companion propose un accueil guidÃ© et un historique des opÃ©rations.
- Ajouter du contenu Confluence en collant un lien de page ou d'espace ; la connexion se fait dans le mÃªme Ã©cran si nÃ©cessaire.
- VÃ©rifier le nombre de pages avant de confirmer le pÃ©rimÃ¨tre. Une annulation ou une erreur d'authentification prÃ©serve les sources configurÃ©es.
- La collecte guidÃ©e lance l'indexation seulement aprÃ¨s une collecte rÃ©ussie ; une fraÃ®cheur inconnue reste explicite.
- Les aperÃ§us de recherche permettent de copier les extraits et rÃ©fÃ©rences ; la vÃ©rification des mises Ã  jour est disponible Ã  la demande.

Mettre Cortex et Companion Ã  jour ensemble avec l'installeur combinÃ©. Les essais avec compte Confluence rÃ©el, Narrator et DPI physique restent manuels.

<!-- release:2026-0906-00 -->
## 2026.0906.00 - 2026-09-06

- Companion propose un Ã©cran de recherche avec extraits, filtres et ouverture
  explicite de la source, via le nouveau contrat `cortex search --json`.
- La recherche peut Ãªtre interrompue avec Ã‰chap et Ã©carte les rÃ©ponses aux critÃ¨res
  modifiÃ©s. Les sources impossibles Ã  ouvrir prÃ©sentent une explication.
- Les saisies non enregistrÃ©es des rÃ©glages et de la programmation sont conservÃ©es
  au rechargement ; la fraÃ®cheur et les actions de rÃ©cupÃ©ration sont accessibles.
- La gÃ©nÃ©ration publiÃ©e et la derniÃ¨re indexation rÃ©ussie observÃ©e sont
  distinguÃ©es dans Companion ; une preuve absente reste non confirmÃ©e.
- Les erreurs de journal ne bloquent plus les workers ; un dÃ©faut de purge
  aprÃ¨s publication est signalÃ© comme une maintenance dÃ©gradÃ©e.
- La recherche Ã©carte les candidats lexicaux supprimÃ©s de Chroma et prÃ©serve
  les domaines locaux et collectÃ©s ayant des chemins identiques.
- Un corpus FR/EN, des benchmarks isolÃ©s et des tests de reprise complÃ¨tent
  les validations. Le workflow `release-pair` vÃ©rifie deux SHA explicites.

Voir [le guide de validation](validation-recherche.md) pour les commandes et
les limites, notamment l'absence de validation manuelle Narrator/multi-Ã©cran.

<!-- release:2026-0904-03 -->
## 2026.0904.03 - 2026-09-04

- Lancer la suite de tests de Cortex sur un poste de dÃ©veloppement n'Ã©crit plus
  dans le vrai journal de Cortex, donc `cortex doctor` sur ce poste ne liste
  plus d'erreurs venues des fixtures de test.
- Cortex Companion : les deux preuves d'interopÃ©rabilitÃ© conservÃ©es sous
  `tests/interop` sont dÃ©crites dans le README, avec ce qu'elles vÃ©rifient et
  comment les lancer.

<!-- release:2026-0904-02 -->
## 2026.0904.02 - 2026-09-04

- `cortex sync` lancÃ© depuis une console ou depuis `sync.bat` rend le mÃªme code
  de sortie que le mode `--json` : un sync partiel ou en Ã©chec ne se termine
  plus par `0` sans rien dire, et Ctrl+C arrÃªte proprement avec le code `130`.
- Nouvelle commande `cortex search "votre question"` pour interroger l'index
  depuis la console, avec `--section` et `--top-k`. L'ancienne forme
  `cortex sync --search` reste acceptÃ©e.
- Chaque option de la ligne de commande est expliquÃ©e dans `--help`, et le
  message affichÃ© quand aucun dossier n'est configurÃ© renvoie vers
  `cortex setup`.
- Cortex Companion affiche un compteur de fichiers pendant la synchronisation
  locale au lieu d'une barre indÃ©terminÃ©e ; il faut ce Cortex pour le voir.
- Companion : le PAT Confluence s'enregistre uniquement dans RÃ©glages, les
  libellÃ©s de navigation et de boutons sont harmonisÃ©s, EntrÃ©e valide le champ
  en cours de saisie, un Ã©cran bloquÃ© indique quel Ã©cran ouvrir, et un succÃ¨s de
  programmation n'est plus affichÃ© comme un avertissement.
- Les pages franÃ§aises de l'installeur retrouvent leurs accents.

<!-- release:2026-0904-01 -->
## 2026.0904.01 - 2026-09-04

- Le fichier de configuration Confluence Ã©crit dÃ©sormais les identifiants de
  page d'une seule faÃ§on. Ce sont des tables `[[spaces.pages]]`, et un espace
  configurÃ© sans aucune page omet simplement la clef au lieu d'Ã©crire une liste
  vide en ligne. Les fichiers Ã©crits avant cette version continuent de
  fonctionner tels quels ; seul `selection = "subtree"` porte encore
  `pages = []`, parce que la clef y est obligatoire et que TOML ne sait pas
  Ã©crire une liste de tables vide.

<!-- release:2026-0904-00 -->
## 2026.0904.00 - 2026-09-04

- Un espace Confluence qui ne collecte rien n'a plus l'air en bonne santÃ©. Un
  espace dont la sÃ©lection de pages est vide est nommÃ© dans le journal, compte
  Ã  part des espaces qui ont produit des pages, et fait passer la santÃ© de la
  source en dÃ©gradÃ©e. Auparavant il n'Ã©numÃ©rait rien, ne journalisait rien,
  comptait comme un succÃ¨s et laissait la santÃ© Ã  `ok` : un espace pouvait
  rester non indexÃ© pendant des heures alors que tous les signaux disaient que
  la synchronisation s'Ã©tait bien passÃ©e.
- Cortex Companion ne laisse plus un espace autorisÃ© sans rien Ã  collecter sans
  vous le dire. Autoriser un espace et ajouter sa page sont dÃ©sormais un seul
  geste : si la page n'est pas ajoutÃ©e, Companion demande s'il faut garder un
  espace qui ne collectera rien, et le retire si vous refusez. Le premier
  lancement pose la mÃªme question, et retirer la derniÃ¨re page d'une sÃ©lection
  aussi.
- Chaque carte d'espace indique ce que la derniÃ¨re collecte a couvert : un
  espace Ã  zÃ©ro page se lit comme tel, sans ouvrir un journal ni un fichier de
  configuration.

<!-- release:2026-0903-02 -->
## 2026.0903.02 - 2026-09-03

- Cortex Companion sait autoriser un nouvel espace Confluence depuis l'Ã©cran
  `Pages`. Collez l'URL de n'importe quelle page de l'espace, choisissez sa
  classification, confirmez : modifier `confluence.toml` Ã  la main n'est plus
  le seul chemin. Seul l'Ã©cran de premier lancement en Ã©tait capable, et il
  disparaÃ®t dÃ¨s que le fichier existe.
- Ajouter une page d'un espace pas encore autorisÃ© ne s'arrÃªte plus sur une
  erreur. La carte est prÃ©remplie avec l'URL que vous venez de coller, elle
  nomme l'espace concernÃ©, et la confirmer ajoute votre page dans la foulÃ©e.
- Les messages d'erreur ne se terminent plus par les lignes de journal Ã©crites
  par Cortex pendant son travail. Seule la phrase qui vous est destinÃ©e reste.

<!-- release:2026-0903-01 -->
## 2026.0903.01 - 2026-09-03

- Le rapport de synchronisation compte dÃ©sormais les documents sans corps
  indexable. Une page qui ne porte qu'une macro enfants de Confluence, ou aucun
  texte, Ã©tait comptÃ©e comme ignorÃ©e avec les fichiers inchangÃ©s et n'Ã©tait
  journalisÃ©e nulle part. Elle a maintenant son propre compteur et sa propre
  ligne de journal, donc elle est retrouvable.
- Cortex Companion arrÃªte de suivre une synchronisation quand l'Ã©cran qui la
  suit est remplacÃ©. L'Ã©cran abandonnÃ© continuait Ã  lire l'Ã©tat local en
  arriÃ¨re-plan.
- Cortex Companion renomme trois couleurs de thÃ¨me pour que chacune porte le
  nom du pinceau qui la lit. Aucun changement visible.

<!-- release:2026-0903-00 -->
## 2026.0903.00 - 2026-09-03

- Une erreur d'usage de la ligne de commande, par exemple une option mal
  tapÃ©e, sort dÃ©sormais avec le code entrÃ©e invalide (6). Elle sortait avec 2,
  que Cortex Companion lit comme "une autre opÃ©ration tient l'index".
- `cortex sync --search` ne s'arrÃªte plus sur une console Windows incapable
  d'afficher un caractÃ¨re de vos notes, par exemple un emoji. Le caractÃ¨re est
  Ã©crit sous forme de sÃ©quence d'Ã©chappement et la suite de la liste s'affiche.
- Cortex Companion retire neuf textes d'interface qu'aucun Ã©cran n'affichait.
  Aucun changement visible.

<!-- release:2026-0902-01 -->
## 2026.0902.01 - 2026-09-02

- Cortex Companion s'ouvre de nouveau normalement. La version `2026.0902.00`
  pouvait s'arrÃªter avant d'afficher sa fenÃªtre Ã  cause d'une liaison invalide
  sur la barre de progression.
- En cas d'Ã©chec de dÃ©marrage inattendu, la boÃ®te de dialogue indique maintenant
  le type et le message de l'exception, en plus du dossier local des journaux.
- La barriÃ¨re de release ouvre dÃ©sormais la fenÃªtre Companion complÃ¨te afin de
  dÃ©tecter cette catÃ©gorie d'Ã©chec WPF avant publication.

<!-- release:2026-0902-00 -->
## 2026.0902.00 - 2026-09-02

- Le jeton Confluence ne peut plus quitter l'instance que vous avez choisie. Une
  redirection HTTP vers un autre hÃ´te est dÃ©sormais refusÃ©e au lieu d'Ãªtre suivie
  avec l'en-tÃªte d'authentification.
- L'adresse Confluence doit maintenant Ãªtre en `https`, sauf pour une instance
  locale de test. Une adresse en clair exposait le jeton sur le rÃ©seau. Companion
  le signale dÃ¨s que vous collez l'URL de la premiÃ¨re page.
- Companion permet enfin d'interrompre une collecte en cours. Le bouton
  `Interrompre` demande confirmation, annonce ce qui va se passer, puis arrÃªte
  l'opÃ©ration. La gÃ©nÃ©ration dÃ©jÃ  publiÃ©e reste intacte.
- Fermer Companion pendant une opÃ©ration demande maintenant confirmation, et
  rappelle que l'opÃ©ration continue en arriÃ¨re-plan.
- `Collecter Confluence` est remontÃ© sur la carte principale de `Base locale`,
  Ã  cÃ´tÃ© de la synchronisation locale, au lieu d'Ãªtre cachÃ© sous les options
  avancÃ©es.
- `F5` recharge l'Ã©cran courant et `Ctrl+S` enregistre depuis les RÃ©glages. Le
  raccourci est rappelÃ© dans l'infobulle du bouton.
- Les bordures de Companion sont plus lisibles : leur contraste passait sous le
  seuil d'accessibilitÃ© sur les lignes mises en avant.
- `cortex --help` dÃ©crit maintenant chaque sous-commande, et `cortex sync --help`
  affiche une ligne d'usage que vous pouvez recopier telle quelle.
- `cortex setup --kb-path` permet une installation sans invite sans avoir Ã 
  dÃ©finir une variable d'environnement au prÃ©alable.

<!-- release:2026-0901-05 -->
## 2026.0901.05 - 2026-09-01

- Quand vous collez une URL de page, Companion compte maintenant la page seule,
  son arborescence et l'espace entier avant d'enregistrer le choix. Si la page a
  des descendants, l'arborescence est sÃ©lectionnÃ©e et recommandÃ©e par dÃ©faut.
- Chaque choix affiche le nombre de pages, une estimation du stockage, son
  emplacement physique et la rÃ©tention configurÃ©e. Le champ `target` est
  clairement prÃ©sentÃ© comme un prÃ©fixe logique, avec un bouton pour ouvrir la
  gÃ©nÃ©ration courante.
- Une collecte manuelle dÃ©marre toujours immÃ©diatement. Une modification du
  pÃ©rimÃ¨tre invalide aussi la cadence des exÃ©cutions automatisÃ©es.
- Pendant une collecte longue, Companion affiche la phase et la progression
  chiffrÃ©e. AprÃ¨s la collecte, un pÃ©rimÃ¨tre trop Ã©troit signale les descendants
  exclus et propose de passer Ã  l'arborescence en un clic.
- Un rejet par `failure_threshold` explique maintenant le nombre et le taux
  d'Ã©checs, le seuil appliquÃ© et les actions possibles. Les anciens dossiers
  temporaires Confluence orphelins sont nettoyÃ©s prudemment au dÃ©marrage.

<!-- release:2026-0901-04 -->
## 2026.0901.04 - 2026-09-01

- Cette version de remplacement publie les correctifs Confluence de
  `2026.0901.03`, dont la construction avait Ã©tÃ© bloquÃ©e avant publication.
- L'installeur fournit automatiquement le convertisseur console et Companion
  rÃ©pare les configurations existantes sans demander de chemin Ã  l'utilisateur.
- La fabrication vÃ©rifie maintenant localement la source, les tests et la
  capacitÃ© `--probe` du convertisseur avant de l'inclure dans l'installeur.

<!-- release:2026-0901-03 -->
## 2026.0901.03 - 2026-09-01

- L'installeur fournit maintenant le vrai convertisseur Confluence console.
  Une installation standard ne demande plus aucun chemin de convertisseur.
- Companion vÃ©rifie le convertisseur en moins de cinq secondes avant de
  l'enregistrer. L'application graphique `ConfluenceRAGBuilder.exe` est refusÃ©e
  immÃ©diatement au lieu d'ouvrir une fenÃªtre puis d'attendre sans rÃ©sultat.
- Les fichiers `confluence.toml` schema v2 crÃ©Ã©s sans `console_path` sont
  rÃ©parÃ©s automatiquement et atomiquement au premier chargement.
- Les Ã©checs indiquent le chemin effectif du convertisseur dans les journaux,
  et les dossiers temporaires `cortex-confluence-*` sont supprimÃ©s sur tous les
  chemins de sortie.

<!-- release:2026-0901-02 -->
## 2026.0901.02 - 2026-09-01

- Le dÃ©lai choisi dans `RÃ©glages` s'applique maintenant Ã  toutes les commandes
  courtes lancÃ©es par Companion : connexion, lecture de la configuration Cortex
  et gestion des pages Confluence.
- Sur un poste lent, choisir 60 ou 120 secondes puis `Enregistrer et connecter`
  empÃªche Companion d'interrompre `cortex.exe` pendant son dÃ©marrage.
- Un vrai dÃ©passement de dÃ©lai est maintenant annoncÃ© clairement avec l'action
  Ã  effectuer. Il n'est plus masquÃ© par le message trompeur `Le CLI a refuse la
  lecture`.
- Les rÃ©glages existants sont repris automatiquement ; aucun TOML ni PAT ne doit
  Ãªtre ressaisi aprÃ¨s la mise Ã  jour.

<!-- release:2026-0901-01 -->
## 2026.0901.01 - 2026-09-01

- La premiÃ¨re configuration Confluence se fait maintenant directement dans
  `Pages Confluence`. Collez l'URL d'une page, choisissez la date d'expiration
  du PAT et la classification, puis cliquez sur `Initialiser et ajouter la page`.
- Companion dÃ©tecte l'adresse de l'instance et la clÃ© d'espace dans les URL qui
  les exposent. Les anciennes URL `viewpage.action` et les liens courts restent
  acceptÃ©s ; il suffit alors de saisir la clÃ© d'espace affichÃ©e dans Confluence.
- Le fichier `confluence.toml` est crÃ©Ã© de faÃ§on verrouillÃ©e, validÃ©e et atomique.
  Le PAT reste uniquement dans le Gestionnaire d'identifiants Windows protÃ©gÃ©
  par DPAPI ; il n'est jamais Ã©crit dans ce fichier.
- Le convertisseur externe peut Ãªtre sÃ©lectionnÃ© dans le mÃªme Ã©cran. Il est
  facultatif pour gÃ©rer les pages, mais reste requis pour lancer leur collecte.

<!-- release:2026-0901-00 -->
## 2026.0901.00 - 2026-09-01

- Le PAT Confluence peut maintenant Ãªtre enregistrÃ© dÃ¨s la premiÃ¨re ouverture,
  mÃªme avant la crÃ©ation de `confluence.toml`. Companion utilise alors la mÃªme
  cible Windows par dÃ©faut que Cortex : `cortex-spike`.
- Tant que `confluence.toml` n'existe pas, l'ajout de pages reste dÃ©sactivÃ© et
  l'Ã©cran indique le prÃ©requis au lieu de lancer une commande vouÃ©e Ã  Ã©chouer.
  Une actualisation suffit Ã  rÃ©activer l'action aprÃ¨s crÃ©ation du fichier.
- Une configuration incomplÃ¨te est maintenant signalÃ©e comme invalide avec le
  dÃ©tail utile (`base_url` ou `auth_expires_at` manquant), au lieu du message
  gÃ©nÃ©rique `La CLI a refuse la lecture`.

<!-- release:2026-0831-01 -->
## 2026.0831.01 - 2026-08-31

- `RÃ©glages > Authentification Confluence` propose maintenant un champ masquÃ©
  pour le Personal Access Token (PAT). Configurez d'abord Confluence, puis
  enregistrez le PAT avant la premiÃ¨re collecte ou lors de son renouvellement.
- Companion lit le `credential_target` configurÃ© et stocke le PAT pour le
  compte Windows courant dans le Gestionnaire d'identifiants Windows, protÃ©gÃ©
  par DPAPI. Le secret n'est jamais Ã©crit dans les rÃ©glages Companion, le
  fichier TOML Confluence ou les journaux.
- La commande `cortex confluence store-credential` reste disponible pour
  l'administration en ligne de commande et utilise la mÃªme entrÃ©e sÃ©curisÃ©e.

<!-- release:2026-0831-00 -->
## 2026.0831.00 - 2026-08-31

- Sur un ordinateur lent, `RÃ©glages` permet maintenant de choisir combien de
  temps Companion attend le dÃ©marrage de Cortex : 15, 30, 60 ou 120 secondes.
  La valeur par dÃ©faut est 30 secondes.
- La vÃ©rification de version de Cortex ne charge plus les modÃ¨les hors ligne.
  La connexion initiale est donc plus rapide, mÃªme si un dÃ©lai plus long reste
  disponible pour les postes oÃ¹ Cortex met davantage de temps Ã  dÃ©marrer.
- Si Cortex ne rÃ©pond toujours pas avant la limite choisie, Companion reste en
  lecture seule et l'Ã©cran Pages ne lance pas Cortex une seconde fois.

<!-- release:2026-0827-03 -->
## 2026.0827.03 - 2026-08-27

- Correction : l'Ã©cran Pages affichait une erreur de rÃ©ponse invalide dÃ¨s qu'un
  espace passait en mode sous-arbre. Ses racines n'Ã©taient pas transmises Ã 
  l'interface. Mettez Ã  jour avant d'utiliser le mode sous-arbre introduit en
  2026.0827.02.

<!-- release:2026-0827-02 -->
## 2026.0827.02 - 2026-08-27

- Un troisiÃ¨me mode de collecte arrive : le sous-arbre. Chaque page listÃ©e
  devient une racine, et Cortex collecte aussi toutes ses pages descendantes.
  Utile quand vous voulez une branche entiÃ¨re d'un espace sans prendre l'espace
  complet.
- L'arborescence est rÃ©solue Ã  chaque collecte, pas figÃ©e dans le fichier : les
  pages ajoutÃ©es plus tard sous une racine sont reprises automatiquement.
- Dans Companion, le bouton de changement de mode fait maintenant le tour des
  trois modes : espace entier, puis pages explicites, puis sous-arbre. En
  passant de pages Ã  sous-arbre, vos pages dÃ©jÃ  listÃ©es deviennent les racines.
- Une racine de sous-arbre se retire comme n'importe quelle page explicite.

<!-- release:2026-0827-01 -->
## 2026.0827.01 - 2026-08-27

- Une case "Forcer la collecte" permet dÃ©sormais de lancer une collecte
  Confluence sans attendre l'Ã©chÃ©ance planifiÃ©e par Cortex. Auparavant, une
  collecte dÃ©jÃ  rÃ©ussie dans l'intervalle bloquait le bouton jusqu'Ã 
  l'Ã©chÃ©ance, sans recours depuis l'interface.
- Le message affichÃ© dans ce cas explique ce qui se passe et indique la case Ã 
  cocher, au lieu de prÃ©senter un code de sortie brut Ã  cÃ´tÃ© des vraies
  erreurs.

<!-- release:2026-0827-00 -->
## 2026.0827.00 - 2026-08-27

- Ajouter une page Confluence accepte maintenant l'adresse que le navigateur
  affiche sur les versions rÃ©centes de Confluence, de la forme
  `/spaces/ESPACE/pages/ID/Titre`. Il n'est plus nÃ©cessaire de retrouver l'ID
  numÃ©rique Ã  la main. Les autres formes dÃ©jÃ  reconnues continuent de
  fonctionner.
- Coller l'adresse d'un accueil d'espace, et non d'une page, indique dÃ©sormais
  ce qui est attendu au lieu d'un simple refus.
- Quand la page appartient Ã  un espace absent du fichier de configuration,
  Companion explique que l'espace doit d'abord y Ãªtre dÃ©clarÃ©, et qu'il ne le
  crÃ©e pas lui-mÃªme.

<!-- release:2026-0808-00 -->
## 2026.0808.00 - 2026-08-08

- Un seul installeur Windows fournit maintenant Cortex, les modÃ¨les hors ligne
  et Cortex Companion. Aucun Python ni runtime .NET sÃ©parÃ© n'est requis.
- Companion devient le parcours recommandÃ© sans terminal : `RÃ©glages` dÃ©tecte
  Cortex et permet de choisir le dossier documentaire ; `Base locale` puis
  `Synchroniser les documents locaux` lancent et suivent une synchronisation.
- L'export, l'import et le retour arriÃ¨re des bases sont reportÃ©s hors de cette
  release. L'index local peut Ãªtre reconstruit depuis le Vault et les sources
  configurÃ©es en relanÃ§ant une synchronisation.
- Les utilisateurs Python avancÃ©s peuvent installer le paquet public
  `cortex-local-rag` depuis PyPI. Les releases publient aussi la dÃ©claration du
  serveur dans le registre MCP.
- La chaÃ®ne de release construit et teste l'installeur unifiÃ© avant de publier
  les paquets et artefacts.

<!-- release:notice-2026-08-06 -->
## Avis du 2026-08-06 - historique publiÃ© rÃ©Ã©crit

L'historique publiÃ© de Cortex a Ã©tÃ© rÃ©Ã©crit le 2026-08-06. Sept commits d'avril
exposaient une adresse email personnelle dans les champs auteur et committer,
et six trailers exposaient une seconde adresse. Les adresses ne sont pas
reproduites ici.

Tous les identifiants de commit ont changÃ©. Un clone crÃ©Ã© avant le 2026-08-06
diverge maintenant de `origin/main`. Le moyen le plus simple est de refaire un
clone. Sinon :

```console
git fetch origin
git reset --hard origin/main
```

Attention : `git reset --hard` dÃ©truit les modifications locales. Sauvegardez
d'abord tout travail Ã  conserver.

Aucun octet de contenu n'a changÃ© et cette rÃ©Ã©criture ne modifie aucun
comportement. Les 121 arbres sont byte-identiques dans le mÃªme ordre, les dates
auteur et committer sont inchangÃ©es, et `git fsck` a rendu le code 0. Les cinq
tags ont Ã©tÃ© repointÃ©s. Les cinq Releases GitHub et leurs artefacts restent
tÃ©lÃ©chargeables.

<!-- release:2026-0805-00 -->
## 2026.0805.00 - 2026-08-05

- Cortex peut maintenant produire des gÃ©nÃ©rations documentaires atomiques,
  suivre leur fraÃ®cheur et indexer les documents de la gÃ©nÃ©ration publiÃ©e.
- Le writer Confluence optionnel collecte seulement les espaces ou pages
  autorisÃ©s, conserve les artefacts source et publie le Markdown par gÃ©nÃ©ration.
- Le writer gÃ¨re les pages vides, nettoie les noms de piÃ¨ces jointes et regroupe
  les conversions en lots.
- La sÃ©lection de pages, les mutations atomiques de configuration et une
  surface CLI lisible par une interface externe sont disponibles.
- Les mÃ©tadonnÃ©es de recherche v2 ajoutent des filtres structurÃ©s et une
  migration rÃ©versible avec sauvegarde et restauration.
- Antigravity et LM Studio rejoignent les clients MCP dÃ©tectÃ©s par le setup.
- L'installeur ferme l'application avant remplacement et refuse de continuer si
  sa compilation Ã©choue. Les invites du setup expliquent mieux leurs effets.
- Les dÃ©pendances MCP corrigent CVE-2026-52869, CVE-2026-52870 et
  CVE-2026-59950. Les releases fournissent des checksums et une attestation de
  provenance.
- Une FAQ, une spÃ©cification publique et les guides FR/EN couvrent ces nouveaux
  parcours.

<!-- release:2026-0716-01 -->
## 2026.0716.01 - 2026-07-16

- L'installeur Windows embarque un modÃ¨le hors ligne Ã©pinglÃ©.
- Le runtime vÃ©rifie le manifeste du modÃ¨le avant de le charger.

<!-- release:2026-0716-00 -->
## 2026.0716.00 - 2026-07-16

- La documentation met en avant l'installeur Windows et les binaires autonomes.
- Le setup enregistre les clients MCP avant l'indexation initiale. Un Ã©chec de
  cette indexation n'annule plus l'enregistrement des clients.
- Le runtime package utilise le magasin de certificats du systÃ¨me, notamment
  pour les autoritÃ©s d'entreprise.

<!-- release:2026-0715-01 -->
## 2026.0715.01 - 2026-07-15

- Un installeur Windows Inno Setup est disponible.
- L'indexation de tout le dossier devient le choix par dÃ©faut.
- Une rÃ©installation peut conserver ou rÃ©initialiser l'Ã©tat Cortex.
- `cortex unregister` retire les entrÃ©es Cortex des clients MCP.

<!-- release:2026-0715-00 -->
## 2026.0715.00 - 2026-07-15

PremiÃ¨re version publique : recherche locale multilingue, indexation hybride
vectorielle et lexicale, synchronisation incrÃ©mentale, outils MCP, setup et
diagnostic, documentation FR/EN et binaires autonomes.
