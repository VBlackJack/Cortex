# Schéma de métadonnées v2 et migration du corpus

**Français** | [English](../en/metadata-v2-migration.md)

[Retour au sommaire](index.md)

Le schéma de métadonnées v2 est le contrat commun retourné à chaque client MCP.
Chaque résultat de recherche expose ces clés, même lorsqu'une valeur est
indisponible :

`schema_version`, `source_kind`, `source_system`, `source_uid`,
`container_uid`, `title`, `author`, `occurred_at`, `updated_at`,
`canonical_uri`, `path`, `section`, `captured_at`, `content_hash` et
`chunk_index`.

Chroma omet les valeurs indisponibles, car ses métadonnées n'acceptent pas
`null`. Cortex reconstruit le contrat complet à la lecture des résultats. Les
dates filtrables conservent leur valeur RFC 3339 UTC et ajoutent les projections
numériques `occurred_at_epoch_ms` et `updated_at_epoch_ms`. L'index SQLite FTS5
dérivé transporte les mêmes champs de filtre que la branche vectorielle.

`cortex_search` accepte `source_kinds`, `authors`, `occurred_at_from`,
`occurred_at_to`, `updated_at_from` et `updated_at_to`. La réponse structurée a
`schema_version = 2`, rappelle les filtres effectifs et reconstruit chaque clé
commune pour chaque résultat. Les lignes du vault portent `source_kind=note` ;
les documents de la génération d'ingestion courante portent `source_kind=doc`.

Pour le Markdown du vault, `occurred_at` est lu depuis `occurred_at`, `date` ou
`created`, dans cet ordre. La valeur reste null si aucun champ n'existe. Le
mtime fichier est stocké séparément dans `file_modified_at` et n'est jamais
utilisé comme date de l'information. Les fichiers PDF natifs conservent de même
une date d'information null, sauf si un producteur propre à la source en fournit
une.

## Migration en une passe

Arrêter les processus serveur Cortex longue durée avant la fenêtre de
maintenance. Le migrateur prend le verrou single-writer normal, crée une
sauvegarde Chroma et lexicale, vérifie une restauration jetable, enregistre des
échantillons de requêtes, effectue une passe de sync puis enregistre les
compteurs et la durée :

```powershell
python scripts/migrate_metadata_v2.py --apply `
  --query "Cortex" `
  --query "Datacron" `
  --query "Confluence"
```

La sortie JSON contient le chemin de sauvegarde, les nombres de chunks et de
fichiers avant/après, les deltas, les compteurs de sync, les échantillons de
requêtes et la vérification de restauration. Le même rapport est écrit dans
`migration-report.json` sous le répertoire de sauvegarde.

Vérifier à nouveau une sauvegarde sans toucher l'index vivant :

```powershell
python scripts/migrate_metadata_v2.py --verify-restore <BACKUP_DIRECTORY>
```

## Restauration

La restauration vivante est volontairement explicite. Elle renomme d'abord les
index courants vers des chemins de récupération horodatés, puis restaure la
sauvegarde choisie. Si la copie échoue, l'index courant est automatiquement
remis en place.

```powershell
python scripts/migrate_metadata_v2.py --restore <BACKUP_DIRECTORY> --yes
```

Conserver les chemins `recovery_chroma` et `recovery_lexical` rapportés tant que
le service restauré n'a pas été validé.
