# Notes de version

**Francais** | [English](../en/release-notes.md)

[Retour au sommaire](index.md)

Cette page resume les changements visibles pour les utilisateurs. Le
[journal technique](../../CHANGELOG.md) contient le detail complet.

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
