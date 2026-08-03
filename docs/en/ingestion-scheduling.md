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

The ingestion package owns missed-window detection, bounded transient retries,
credential-expiry checks, and the source-specific overlap lock. Windows Task
Scheduler must only start the installed Cortex CLI on the desired timetable.

Use `cortex ingestion due SOURCE_KIND` at session startup. Exit code `0` means
the configured interval has elapsed and the source command should run. Exit code
`3` means no catch-up is required. Use `cortex ingestion status SOURCE_KIND` to
read the latest atomic health snapshot.

Source adapters call `ingestion.cli.execute_scheduled_attempt` from their CLI
entry point. This keeps retry, catch-up, locking, and credential lifetime policy
outside Task Scheduler definitions.

The optional ingestion settings file is `%APPDATA%\Cortex\ingestion.toml`.
Environment variables prefixed with `CORTEX_INGESTION_` override TOML, and TOML
overrides package defaults. Secret values are never accepted by this file, by
environment variables, or by command-line arguments. Operators create or renew
generic credentials interactively in Windows Credential Manager.

The task account needs read and write access to the configured ingestion data
root and read access to its Windows Credential Manager entry. Published content
is selected through an atomically replaced generation pointer; operators must
not edit generation directories manually.
