# Schema de metadonnees v2 et migration du corpus

**Francais** | [English](../en/metadata-v2-migration.md)

[Retour au sommaire](index.md)

Le schema de metadonnees v2 est le contrat commun retourne a chaque client MCP.
Chaque resultat de recherche expose ces cles, meme lorsqu'une valeur est
indisponible :

`schema_version`, `source_kind`, `source_system`, `source_uid`,
`container_uid`, `title`, `author`, `occurred_at`, `updated_at`,
`canonical_uri`, `path`, `section`, `captured_at`, `content_hash` et
`chunk_index`.

Chroma omet les valeurs indisponibles, car ses metadonnees n'acceptent pas
`null`. Cortex reconstruit le contrat complet a la lecture des resultats. Les
dates filtrables conservent leur valeur RFC 3339 UTC et ajoutent les projections
numeriques `occurred_at_epoch_ms` et `updated_at_epoch_ms`. L'index SQLite FTS5
derive transporte les memes champs de filtre que la branche vectorielle.

`cortex_search` accepte `source_kinds`, `authors`, `occurred_at_from`,
`occurred_at_to`, `updated_at_from` et `updated_at_to`. La reponse structuree a
`schema_version = 2`, rappelle les filtres effectifs et reconstruit chaque cle
commune pour chaque resultat. Les lignes du vault portent `source_kind=note` ;
les documents de la generation d'ingestion courante portent `source_kind=doc`.

Pour le Markdown du vault, `occurred_at` est lu depuis `occurred_at`, `date` ou
`created`, dans cet ordre. La valeur reste null si aucun champ n'existe. Le
mtime fichier est stocke separement dans `file_modified_at` et n'est jamais
utilise comme date de l'information. Les fichiers PDF natifs conservent de meme
une date d'information null, sauf si un producteur propre a la source en fournit
une.

## Migration en une passe

Arreter les processus serveur Cortex longue duree avant la fenetre de
maintenance. Le migrateur prend le verrou single-writer normal, cree une
sauvegarde Chroma et lexicale, verifie une restauration jetable, enregistre des
echantillons de requetes, effectue une passe de sync puis enregistre les
compteurs et la duree :

```powershell
python scripts/migrate_metadata_v2.py --apply `
  --query "Cortex" `
  --query "Datacron" `
  --query "Confluence"
```

La sortie JSON contient le chemin de sauvegarde, les nombres de chunks et de
fichiers avant/apres, les deltas, les compteurs de sync, les echantillons de
requetes et la verification de restauration. Le meme rapport est ecrit dans
`migration-report.json` sous le repertoire de sauvegarde.

Verifier a nouveau une sauvegarde sans toucher l'index vivant :

```powershell
python scripts/migrate_metadata_v2.py --verify-restore <BACKUP_DIRECTORY>
```

## Restauration

La restauration vivante est volontairement explicite. Elle renomme d'abord les
index courants vers des chemins de recuperation horodates, puis restaure la
sauvegarde choisie. Si la copie echoue, l'index courant est automatiquement
remis en place.

```powershell
python scripts/migrate_metadata_v2.py --restore <BACKUP_DIRECTORY> --yes
```

Conserver les chemins `recovery_chroma` et `recovery_lexical` rapportes tant que
le service restaure n'a pas ete valide.
