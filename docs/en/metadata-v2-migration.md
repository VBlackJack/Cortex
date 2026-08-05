# Metadata schema v2 and corpus migration

[Francais](../fr/metadata-v2-migration.md) | **English**

[Back to table of contents](index.md)

Metadata schema v2 is the common contract returned to every MCP client. Each
search hit exposes these keys, even when a value is unavailable:

`schema_version`, `source_kind`, `source_system`, `source_uid`,
`container_uid`, `title`, `author`, `occurred_at`, `updated_at`,
`canonical_uri`, `path`, `section`, `captured_at`, `content_hash`, and
`chunk_index`.

Chroma omits unavailable values because Chroma metadata does not accept null.
Cortex reconstructs the complete contract when reading results. Filterable
dates retain their RFC 3339 UTC value and add numeric
`occurred_at_epoch_ms`/`updated_at_epoch_ms` projections. The derived SQLite
FTS5 index carries the same filter fields as the vector branch.

`cortex_search` accepts `source_kinds`, `authors`, `occurred_at_from`,
`occurred_at_to`, `updated_at_from`, and `updated_at_to`. The returned
structured response has `schema_version = 2`, echoes the effective filters,
and reconstructs every common key for each result. Vault rows use
`source_kind=note`; documents from the current ingestion generation use
`source_kind=doc`.

For vault Markdown, `occurred_at` is read from `occurred_at`, `date`, or
`created`, in that order. It remains null when none is present. File mtime is
stored separately as `file_modified_at` and is never used as the information
date. Native PDF files similarly retain a null information date unless a
source-specific producer supplies one.

## One-pass migration

Stop long-running Cortex server processes before the maintenance window. The
migrator holds the normal single-writer lock, creates a Chroma and lexical
backup, verifies a disposable restore, records query samples, performs one sync
pass, and records counts and duration:

```powershell
python scripts/migrate_metadata_v2.py --apply `
  --query "Cortex" `
  --query "Datacron" `
  --query "Confluence"
```

The JSON output includes the backup path, before/after chunk and file counts,
deltas, sync counters, query samples, and restore verification. The same report
is written as `migration-report.json` inside the backup directory.

Verify a backup again without touching the live index:

```powershell
python scripts/migrate_metadata_v2.py --verify-restore <backup-directory>
```

## Restore

The live restore is intentionally explicit. It first renames the current index
to timestamped recovery paths, then restores the selected backup. If copying
the backup fails, the current index is moved back automatically.

```powershell
python scripts/migrate_metadata_v2.py --restore <backup-directory> --yes
```

Keep the reported `recovery_chroma` and `recovery_lexical` paths until the
restored service has been validated.
