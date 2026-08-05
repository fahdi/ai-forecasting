# R17 — Backup coverage: the model registry, and proving restore

> **PRD requirement.** Automated daily backup of the database (signals, trades, audit log).

Status: designed, not yet implemented. Produced by a design council of two
independent designs judged head to head.

## Chosen approach

Design A (extend the nightly script and the freshness reporter; three slices)

## Rationale

A wins on fit, cost and time-to-value. Both designs correctly refuse to add a service, but A reuses the three primitives that already exist in scripts/prod_backup.py (partial -> verify -> os.replace, filename-stamp pruning, a restore drill that actually reconstructs the thing) and the one primitive that already exists in backup_status.py (DEGRADED_STATUSES as the single owner of what counts as a fault). B's distinguishing feature is a sidecar manifest of sha256 hashes, which buys very little: tarfile already fails on a CRC mismatch when extracting a gzip member, so a truncated or corrupted archive is caught by the extraction step in the drill without a manifest. What the manifest does buy is a second artifact per night, a second file to prune, a second file to parse in the health path, and a second thing that can itself go stale or malformed. B's slice 4 (audit files on disk that the newest manifest does not list) is the clearest manufactured work in either design: the registry is written by a live trainer, so a file appearing between the snapshot and the audit is normal, and wiring that into a nonzero exit plus a new "incomplete" health status would produce flaky nightly failures and a dashboard that cries wolf. Cut it. A's slice 1 also delivers standalone value on its own night: a verified registry tarball exists where none existed, before any health or drill work lands. Three grafts from B are real and are folded in below: verify every version listed in the index rather than only the active one (an active-only drill passes while rollback targets rot, and rollback is the whole point of history), reject archive members that escape the extraction root (fail-closed extraction, and the stdlib default is unsafe on older Pythons), and print the tarball size in the run line so registry growth is visible in /var/log/aif-backup.log before it fills /opt/backups. One correction applies to both designs: A proposes archiving only versions reachable from active + history, which contradicts its own drill, because ModelRegistry.prune(keep=5) deliberately leaves unprotected versions in registry.json and a restored index referencing an unarchived artifact dir is exactly the failure the drill is supposed to catch. Archive every version listed in the index. Disk growth is already bounded by prune(keep) upstream and keep_days downstream. Everything here is exercised with tmp_path and an injected command runner, so all three slices are green on a VPS that Binance is returning 451 to.

## Grafted, and explicitly rejected

- From B: the restore drill verifies every version listed in the restored index has a non-empty artifact directory, not only the active version. An active-only drill passes while the rollback targets in history rot, which defeats the reason the registry keeps history at all.
- From B: fail-closed extraction. Any archive member whose resolved path escapes the extraction root aborts the drill with a named path, and extraction uses the data filter rather than the permissive stdlib default.
- From B: the run line reports the registry tarball size in KB alongside the existing db size line, so growth in /opt/backups is visible in the cron log before the disk fills.
- From B: explicit fail-closed on an empty or missing registry root, covering the case where cron's working directory does not match the compose project dir and the script would otherwise archive nothing successfully.
- From B: keep the existing top-level database keys in components.backups so the dashboard and tests/test_backup_health_degradation.py keep working across the shape change.
- Rejected from B: the sidecar sha256 manifest (gzip CRC already fails extraction on corruption; the manifest adds a second artifact, a second prune path and a second staleness surface for no new proof).
- Rejected from B: slice 4, the manifest coverage audit and the new incomplete status. Auditing a live trainer's directory against a snapshot taken minutes earlier races normal writes and would make the nightly job flaky and /health/detailed noisy.

## Acceptance criteria

- [ ] The nightly cron run produces two verified artifacts in /opt/backups/ai-forecasting: aif-db-<stamp>.sql.gz and aif-registry-<stamp>.tar.gz, sharing one run stamp.
- [ ] A failure of either half exits nonzero and prints BACKUP FAILED to stderr, so a partial night is loud in /var/log/aif-backup.log rather than a green cron exit.
- [ ] No partial file (.partial or a half-written target) survives any failure path for either artifact.
- [ ] The registry archive is proven restorable: it is extracted into a throwaway directory, loaded through app.models.registry.ModelRegistry, and every version listed in the restored index (not just the active one) is confirmed to have a non-empty artifact directory.
- [ ] An archive member whose resolved path escapes the extraction root fails the drill instead of being written.
- [ ] The registry snapshot fails closed on a missing, empty, or index-less registry root, so a wrong deploy path can never be recorded as a successful backup.
- [ ] /health/detailed reports database and model_registry backup freshness independently and takes the worst of the two, so a fresh pg_dump alongside a missing or stale registry archive reports degraded and names model_registry.
- [ ] The existing top-level backup keys in components.backups (status, latest_backup, age_hours) keep their database meaning, so the dashboard and tests/test_backup_health_degradation.py are not broken by the shape change.
- [ ] DEGRADED_STATUSES in app/services/backup_status.py remains the single owner of which statuses are faults; health.py gains no new hardcoded status literals.
- [ ] No new service, container, image, or third-party dependency: tarfile, hashlib, json, pathlib only.
- [ ] Every test runs offline against tmp_path fixtures and injected runners: no Binance, no live Postgres, no Docker.
- [ ] docker-compose.prod.yml gains no new writable mount; the existing read-only /app/backups mount already exposes both artifacts.

## Delivery slices

### 1. Slice 1: snapshot the model registry as a verified nightly tarball

scripts/prod_backup.py gains backup_registry(registry_dir, backup_dir, keep_days, now=None) -> Path, writing aif-registry-<stamp>.tar.gz using the same partial -> verify -> os.replace discipline as run_backup(), and reusing the same STAMP_FORMAT so the two artifacts of one run share a stamp. Archive contents: registry.json plus the artifact directory of every version listed in that index (not just active + history, because ModelRegistry.prune(keep=5) deliberately leaves unprotected versions in the index and a restored index pointing at an unarchived dir is a broken backup). Torn-write defence: read registry.json into memory once, add the artifact dirs, then add the in-memory index bytes as the final member, so a promotion landing mid-run cannot produce an archive whose index references a directory that was never captured. verify_registry_archive(path) opens the tarball, requires a parseable registry.json member with a non-null active version, and requires a member for every version listed. Fail closed when the registry root is missing, empty, or has no registry.json: raise, write nothing, leave no .partial. prune_old_backups() is parameterised on prefix and suffix so one pruner serves both artifacts and neither can delete the other's files. New CLI flag --registry-dir defaulting to ./models/registry relative to the compose project dir. main() runs the pg_dump first, then the registry snapshot, and exits nonzero if either fails. The run line prints the registry tarball size in KB and the number pruned, mirroring the existing db line.

**Acceptance**

- [ ] A run against a populated tmp registry produces exactly one aif-registry-<stamp>.tar.gz whose stamp matches the same run's aif-db-<stamp>.sql.gz.
- [ ] The archive contains registry.json and an artifact directory for every version_id listed in that index.
- [ ] A missing, empty, or index-less registry root raises, writes no file, and leaves no .partial behind.
- [ ] Pruning is prefix-scoped: pruning one artifact class can never delete a file of the other class.
- [ ] main() exits 1 and prints BACKUP FAILED to stderr when the registry half fails even though pg_dump succeeded.
- [ ] The stdout run line includes the registry tarball size in KB.
- [ ] All new tests pass with no Docker, no Postgres, and no network.

**Tests first**

- tests/test_prod_backup.py::test_backup_registry_writes_archive_with_index_and_artifacts - tmp registry with registry.json and one version dir containing a file yields aif-registry-<stamp>.tar.gz containing both members
- tests/test_prod_backup.py::test_backup_registry_archives_every_version_in_the_index - three registered versions where only one is active and one is in history: all three artifact dirs are present in the archive
- tests/test_prod_backup.py::test_backup_registry_uses_the_index_it_read_not_a_later_one - a registry.json rewritten after enumeration does not change the archived index member
- tests/test_prod_backup.py::test_backup_registry_raises_on_missing_registry_root
- tests/test_prod_backup.py::test_backup_registry_raises_on_registry_root_without_registry_json
- tests/test_prod_backup.py::test_backup_registry_leaves_no_partial_or_target_on_failure - injected failing writer leaves neither .partial nor the stamped target
- tests/test_prod_backup.py::test_verify_registry_archive_rejects_null_active_version
- tests/test_prod_backup.py::test_verify_registry_archive_rejects_index_version_with_no_archived_artifact_dir
- tests/test_prod_backup.py::test_prune_old_backups_is_prefix_scoped - registry archives past keep_days are pruned while aif-db-*.sql.gz files of the same age are untouched, and the reverse
- tests/test_prod_backup.py::test_main_exits_nonzero_when_registry_backup_fails_after_pg_dump_succeeds
- tests/test_prod_backup.py::test_main_run_line_reports_registry_archive_size

### 2. Slice 2: prove the registry restore instead of assuming it

scripts/prod_backup.py gains verify_registry_restore(archive_path) -> dict, symmetric with the existing verify_restore(). It extracts the archive into a tempfile.TemporaryDirectory, rejecting any member whose resolved path escapes the extraction root (fail closed; use the data extraction filter rather than the permissive default). It then constructs a real app.models.registry.ModelRegistry over the extracted root and asserts: active_version() is not None; get(active) returns a record carrying PRIMARY_METRIC; and every version listed in the restored index (grafted from design B, because an active-only check passes while the rollback targets in history rot) has an artifact directory that exists and is non-empty. Returns {"active_version": ..., "versions_verified": n} and raises RuntimeError naming the first offending version or path otherwise. The temp directory is cleaned up on both success and failure. main() calls it after backup_registry() unless --skip-restore-drill, printing a one-line proof in the same shape as the existing 'restore drill ok: N tables' line.

**Acceptance**

- [ ] A clean archive from slice 1 restores, loads through the real ModelRegistry class, and reports the active version id plus the number of versions verified.
- [ ] A version listed in the restored index whose artifact directory is missing or empty fails the drill with that version id in the message, including versions that are only in history.
- [ ] A truncated archive fails the drill rather than passing.
- [ ] An archive member resolving outside the extraction root aborts the drill and creates no file outside the temp root.
- [ ] No temp directory survives either a successful or a failed drill.
- [ ] --skip-restore-drill suppresses the registry drill exactly as it does the Postgres drill; without it, a drill failure exits nonzero.
- [ ] The drill runs with no Docker, no Postgres, and no network.

**Tests first**

- tests/test_prod_backup.py::test_verify_registry_restore_round_trips_a_real_backup - output of backup_registry() restores and reports the active version id and version count
- tests/test_prod_backup.py::test_verify_registry_restore_fails_when_a_history_version_artifact_dir_is_absent - proves the drill is not active-only
- tests/test_prod_backup.py::test_verify_registry_restore_fails_when_an_artifact_dir_is_present_but_empty
- tests/test_prod_backup.py::test_verify_registry_restore_fails_on_truncated_archive
- tests/test_prod_backup.py::test_verify_registry_restore_rejects_member_escaping_extraction_root - a crafted ../ member aborts the drill and writes nothing outside the temp root
- tests/test_prod_backup.py::test_verify_registry_restore_cleans_up_tempdir_on_success_and_on_failure
- tests/test_prod_backup.py::test_main_prints_registry_drill_line_and_skips_it_under_skip_restore_drill
- tests/test_prod_backup.py::test_main_exits_nonzero_when_registry_drill_fails

### 3. Slice 3: per-artifact backup freshness so a partial backup degrades /health/detailed

app/services/backup_status.py generalises its scanner to artifact_status(directory, prefix, suffix, now=None, max_age_hours=MAX_AGE_HOURS) and backup_status_from_env() returns {status: worst, latest_backup, age_hours, artifacts: {database: {...}, model_registry: {...}}}. The three existing top-level keys keep their current database meaning so the dashboard and tests/test_backup_health_degradation.py are not broken by the shape change (grafted from design B); the new artifacts map is additive. worst is the least healthy of the two components judged by the existing DEGRADED_STATUSES frozenset, which stays the single owner of what counts as a fault, so health.py needs no new status literals and its existing check at health.py:161 keeps working unchanged. not_configured stays benign for both components, so local dev without BACKUP_STATUS_DIR is still healthy. Freshness continues to come from the filename stamp, not mtime. Both globs are cheap stats over one already-mounted read-only directory; nothing is decompressed in the health path. docker-compose.prod.yml changes only a comment - the existing /opt/backups/ai-forecasting:/app/backups:ro mount already exposes both artifacts. Release notes must state that a host which has not yet run the slice 1 script will report model_registry missing and degrade /health/detailed on first deploy: that is honest, not a regression.

**Acceptance**

- [ ] backup_status_from_env() returns a per-artifact map for database and model_registry plus an aggregate status equal to the least healthy component.
- [ ] A fresh pg_dump next to a missing or stale registry archive makes /health/detailed report degraded with components.backups.artifacts.model_registry naming the fault.
- [ ] Both artifacts fresh reports healthy; an unset BACKUP_STATUS_DIR reports not_configured for both and does not degrade local dev.
- [ ] components.backups keeps status, latest_backup and age_hours at the top level with their existing database meaning; no existing consumer or test needed rewriting to stay green.
- [ ] DEGRADED_STATUSES remains the only place that defines a fault; app/api/v1/endpoints/health.py gains no hardcoded status strings.
- [ ] The health path performs only filename stats over the existing read-only mount: no archive is opened, no new mount or writable path is added.
- [ ] Release notes state that first deploy on a host predating slice 1 will honestly report model_registry missing.

**Tests first**

- tests/test_backup_status.py::test_reports_database_and_model_registry_independently
- tests/test_backup_status.py::test_fresh_db_with_no_registry_archive_is_degraded_and_names_model_registry
- tests/test_backup_status.py::test_fresh_db_with_registry_archive_past_max_age_is_stale_overall
- tests/test_backup_status.py::test_both_fresh_is_healthy
- tests/test_backup_status.py::test_unset_directory_is_not_configured_for_both_components_and_stays_benign
- tests/test_backup_status.py::test_top_level_status_latest_backup_and_age_hours_still_describe_the_database - locks the compatibility contract for existing consumers
- tests/test_backup_status.py::test_malformed_filename_stamps_are_ignored_for_both_prefixes
- tests/test_backup_health_degradation.py::test_detailed_health_degrades_when_only_the_registry_backup_is_missing - /health/detailed returns degraded and components.backups.artifacts.model_registry.status == 'missing'
- tests/test_backup_health_degradation.py::test_detailed_health_stays_healthy_when_both_artifacts_are_fresh
- tests/test_backup_health_degradation.py::test_existing_db_only_degradation_behaviour_is_unchanged
