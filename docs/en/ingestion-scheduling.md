<!--
Copyright 2026 Julien Bombled

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Scheduling ingestion on Windows

[Francais](../fr/ingestion-scheduling.md) | **English**

[Back to table of contents](index.md)

The ingestion package owns missed-window detection, bounded transient retries,
credential-expiry checks, and the source-specific overlap lock. Windows Task
Scheduler must only start the installed Cortex CLI on the desired timetable.

Use `cortex ingestion due SOURCE_KIND` at session startup. Exit code `0` means
the configured interval has elapsed and the source command should run. Exit code
`3` means no catch-up is required. Use `cortex ingestion status SOURCE_KIND` to
read the latest atomic health snapshot. Configuration or storage errors return
exit code `1`.
For Confluence, the user-facing `confluence` name and canonical `doc` name read
the same snapshot; every other value is rejected before storage access.

Source adapters call `ingestion.cli.execute_scheduled_attempt` from their CLI
entry point. This keeps retry, catch-up, locking, and credential lifetime policy
outside Task Scheduler definitions.

The optional ingestion settings file is `%APPDATA%\Cortex\ingestion.toml`.
Environment variables prefixed with `CORTEX_INGESTION_` override TOML, and TOML
overrides package defaults. Secret values are never accepted by this file, by
environment variables, or by command-line arguments. Operators create or renew
generic credentials interactively in Windows Credential Manager.

```toml
schema_version = 1
data_root = "C:\\Users\\<YOUR_ACCOUNT>\\AppData\\Local\\Cortex\\ingestion"
retention_generations = 2
auth_expiry_warning_days = 14
lock_timeout_seconds = 0
retry_attempts = 4
backoff_initial_seconds = 1
backoff_max_seconds = 60
backoff_multiplier = 2
backoff_jitter_ratio = 0.2
schedule_interval_seconds = 86400
```

Every key above is optional; the file itself may be absent. The default
`data_root` is `%LOCALAPPDATA%\Cortex\ingestion`. Use the top-level `--config`
option to inspect another file without changing the default:

```powershell
cortex ingestion --config <INGESTION_CONFIG> status doc
cortex ingestion --config <INGESTION_CONFIG> due doc
```

The task account needs read and write access to the configured ingestion data
root and read access to its Windows Credential Manager entry. Published content
is selected through an atomically replaced generation pointer; operators must
not edit generation directories manually.

For the current Confluence adapter, Task Scheduler can invoke
`cortex confluence sync`; the adapter itself performs the due check. Use
`cortex confluence sync --force` only for an explicit operator-requested run.
