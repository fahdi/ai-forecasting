# R12 — Telegram bot (Freqtrade native): status, daily/weekly P&L, trade notifications, /forceexit all and /stopbuy kill switch for both stakeholders

Status: designed, not yet implemented. Design council of two independent
designs judged head to head.

## Gap being closed

Feature is wired but never turned on or exercised: no token/chat_id, enabled=false, no notification_settings block (defaults apply), no second-stakeholder mechanism in config beyond the runbook's group-chat instruction, and the kill-switch drill in docs/RUNBOOK.md:85-88 is unperformed (no docs/gates artifact). Zero test coverage — tests/test_ensemble_strategy.py TestRiskConfiguration (lines 254-305) asserts max_open_trades, stake, whitelist, stoploss_on_exchange and timeframe against config.dry.json but contains no telegram assertion; grep for 'telegram' in tests/ matches nothing. Closing it: create the bot, set the three .env vars, add a config assertion in the Strategy CI job (which parses config.dry.json already), and run + document the drill. Note the whole thing is moot while the freqtrade container is down in prod.

## Chosen approach

Design A (config-and-verification framing), with two grafts from Design B and one slice cut

## Rationale

Both designs agree on the core shape: a config contract test in the existing Strategy CI job, a pure status function in the backup_status.py idiom, and an honest drill artifact. A wins on operational cost and fail-safety. B's distinguishing move is wiring the drill check into scripts/ci_gate.py, which is wrong: ci_gate.py exists to answer one narrow question ("did CI pass for this exact SHA?") and is invoked by scripts/deploy_prod.sh. Bolting a permanently-red Telegram drill check onto it means every deploy of every unrelated slice is blocked (or the override flag becomes routine, which destroys the gate's meaning). B compounds this by having telegram_control_status() read the drill markdown file, coupling a runtime health endpoint to a docs artifact and giving the pure function a filesystem dependency backup_status.py's caller-owns-the-read pattern deliberately avoids. Grafted from B: the four-state status vocabulary, where enabled-but-blank is 'incomplete' (a fault, fail-closed) rather than lumped with not_configured, and the explicit credential-leak test. Cut from A: slice 3 (compose parity) is real but too thin to be its own release, so its assertions fold into slice 1; and A's slice 4 test-the-template machinery is manufactured work (tests asserting a markdown placeholder exists, shipped before the drill can run), so slice 3 here is the drill itself, explicitly blocked, with exactly one anti-rubber-stamp test that lands with the drill rather than before it. Slice 1 delivers value on day one: config.dry.json today has telegram with three keys and no notification_settings, so freqtrade would come up with default notifications and nobody would know which trade events actually fire; the test turns that into a reviewed, CI-enforced contract with zero new deps and no new CI job.

## Grafted, and explicitly rejected

- From Design B: the four-state status vocabulary, splitting enabled-but-blank into its own 'incomplete' status that is DEGRADED, rather than folding it into not_configured. A half-configured kill switch is a fault, and freqtrade fails it silently (logs an error and keeps trading), so it must be visible.
- From Design B: the explicit test_status_never_leaks_credentials assertion on the stringified result, so the bot token and chat_id cannot reach /health/detailed responses or logs.
- From Design B: naming the configured-but-unexercised state 'configured_unproven' — it says the honest thing in the status enum itself rather than relying on a comment.
- From Design B's risk list: keep notification_settings minimal and pinned to keys the installed freqtrade 2026.6 accepts, since CI only parses JSON and would not catch a key that breaks container startup.
- From Design A slice 3 (cut as a standalone slice): the compose parity assertions, folded into slice 1's test set.

## Acceptance criteria

- [ ] Slices 1 and 2 are fully green with Binance geo-blocked, freqtrade down, no Telegram token and no live keys. Neither slice makes any network call.
- [ ] No new service, container, CI job, or third-party dependency is introduced. Slice 1 rides the existing Strategy CI job (which already parses user_data/config.dry.json); slice 2 rides the existing backend pytest job.
- [ ] Committed defaults stay fail-closed: user_data/config.dry.json keeps telegram.enabled=false with empty token and chat_id, and env.example keeps TELEGRAM_ENABLED=false with blank token/chat_id. No real bot token or chat_id is ever committed.
- [ ] Nothing anywhere reports Telegram control as 'healthy' or R12 as done on the strength of non-empty config strings. The strongest claim the system makes before the drill is 'configured, unproven', and that state is degraded in /health/detailed.
- [ ] Each slice is cut with scripts/release.py after its tests are written first and observed failing for the right reason (KeyError / ImportError / missing key), not after the implementation.

## Delivery slices

### 1. Slice 1 — Telegram config contract and env plumbing asserted in the Strategy CI job

user_data/config.dry.json currently carries only {"telegram": {"enabled": false, "token": "", "chat_id": ""}} and no notification_settings, so a container started with FREQTRADE__TELEGRAM__ENABLED=true would inherit whatever freqtrade's defaults happen to be for that version. This slice adds an explicit notification_settings block (entry, entry_fill, exit, exit_fill, protection_trigger set to "on") next to the existing keys, keeps enabled=false / token="" / chat_id="" as the fail-closed committed defaults (prod flips them via the FREQTRADE__TELEGRAM__* env overrides that already exist at docker-compose.yml:81-83 and docker-compose.prod.yml:110-112), and locks the whole thing plus the env plumbing behind tests. Fully offline: this is JSON and text parsing, no freqtrade, no Binance, no token. Value on day one: the set of trade events the bot will announce becomes a reviewed contract, so an edit that silences exit notifications turns the Strategy CI job red instead of producing a bot that quietly says nothing; and the three env overrides can no longer be added to one compose file and forgotten in the other, which would mean the kill switch works in dev and silently does not in prod. Do not add a chat_id list or any per-stakeholder key: freqtrade's chat_id is a scalar, and the group chat described in docs/RUNBOOK.md:76-82 is the only both-stakeholders mechanism that exists.

**Acceptance**

- [ ] The new tests are written and observed failing (notification_settings raises KeyError) before config.dry.json is edited.
- [ ] user_data/config.dry.json parses as valid JSON-with-comments under the same loader the strategy job already uses, and telegram.enabled remains false with empty token and chat_id.
- [ ] notification_settings contains only keys accepted by the installed freqtrade version (2026.6). If a key is uncertain, leave it out — an over-specified block can fail container startup, and CI only parses JSON so it would not catch that.
- [ ] The Strategy CI job goes green on the new tests with no workflow file change, no new job, and no new dependency.
- [ ] No test asserts on any secret value; assertions are on presence, type and emptiness only.
- [ ] Released with scripts/release.py as one release.

**Tests first**

- tests/test_ensemble_strategy.py — add class TestTelegramConfiguration. Lift the existing comment-stripping `config` fixture used by TestRiskConfiguration (lines 254-305) to module scope rather than duplicating the strip logic.
- test_telegram_disabled_by_default_in_committed_config — config['telegram']['enabled'] is False and token == chat_id == ''. Passes today; it is the guard that a real credential is never committed into config.dry.json.
- test_notification_settings_declare_trade_events — config['telegram']['notification_settings'] maps entry, entry_fill, exit, exit_fill and protection_trigger to 'on'. MUST FAIL FIRST with KeyError: 'notification_settings'.
- test_single_scalar_chat_id — config['telegram']['chat_id'] is a string, not a list, documenting that one group chat is the both-stakeholders mechanism.
- test_env_example_declares_telegram_vars_fail_closed — env.example contains TELEGRAM_ENABLED=false and blank TELEGRAM_TOKEN= / TELEGRAM_CHAT_ID=.
- tests/test_compose_telegram_env.py (new, or fold into the class above if a compose-reading test file already exists) — parameterized over docker-compose.yml and docker-compose.prod.yml: each file's freqtrade service declares all three of FREQTRADE__TELEGRAM__ENABLED, FREQTRADE__TELEGRAM__TOKEN, FREQTRADE__TELEGRAM__CHAT_ID. Passes today; it is the regression guard for a one-sided edit.

### 2. Slice 2 — telegram_status(): /health/detailed reports configured-but-unproven, never healthy

New app/services/telegram_status.py exposing telegram_status(enabled, token, chat_id) -> dict and telegram_status_from_env(), mirroring app/services/backup_status.py exactly: pure over scalars, caller owns the environment read, module-owned DEGRADED_STATUSES and BENIGN_STATUSES frozensets so health.py never restates status literals (the same mistake backup_status.py's docstring records at lines 20-23). Statuses: 'not_configured' when enabled is false (benign — local dev and every dry-run host today), 'incomplete' when enabled but token or chat_id is blank (DEGRADED — this is the silent-failure mode where freqtrade logs an error and keeps trading with no control channel), 'configured_unproven' when all three are set (also DEGRADED — a non-empty string is not evidence that a message can be delivered, and honest monitoring forbids calling an unexercised kill switch healthy). The function never returns 'healthy' and never returns the token or chat_id, only the status enum and booleans. app/api/v1/endpoints/health.py gains a 'telegram' component alongside 'backups' (around lines 151-165), using the module's DEGRADED_STATUSES the same way. Fully offline: no Telegram API call, no freqtrade, no Binance. Value today: the moment someone sets the three env vars, the platform says out loud that the kill switch is configured but never exercised, instead of the current state where /health/detailed is silent about Telegram entirely and 'no token set' is indistinguishable from 'working'.

**Acceptance**

- [ ] tests/test_telegram_status.py is written and fails with ImportError (module absent) before app/services/telegram_status.py exists.
- [ ] telegram_status() takes only scalars, performs no I/O and no network call; only telegram_status_from_env() touches os.environ, matching backup_status.py's split.
- [ ] DEGRADED_STATUSES and BENIGN_STATUSES are defined in telegram_status.py and imported by health.py — health.py contains no telegram status string literal.
- [ ] The returned dict never contains the token or chat_id, so /health/detailed responses and logs cannot leak the bot credential.
- [ ] With no Telegram env vars set (the state on every host today) /health/detailed is unchanged in overall status: 'not_configured' is benign.
- [ ] Backend CI green; released with scripts/release.py.

**Tests first**

- tests/test_telegram_status.py (new) — pure table tests, no fixtures beyond monkeypatch for the env variant.
- test_disabled_is_not_configured_and_benign — telegram_status(False, '', '')['status'] == 'not_configured' and that value is in BENIGN_STATUSES.
- test_enabled_with_blank_token_is_incomplete and test_enabled_with_blank_chat_id_is_incomplete — status == 'incomplete' and it is in DEGRADED_STATUSES (fail-closed: half-configured is a fault, not an absence).
- test_fully_configured_is_unproven_not_healthy — status == 'configured_unproven', it is in DEGRADED_STATUSES, and 'healthy' appears nowhere in the returned dict's values.
- test_status_never_leaks_credentials — str(result) contains neither the token nor the chat_id value.
- test_from_env_reads_the_three_documented_vars — monkeypatch TELEGRAM_ENABLED / TELEGRAM_TOKEN / TELEGRAM_CHAT_ID and assert 'configured_unproven'; assert 'true', '1' and 'yes' all parse truthy so a plausible .env spelling is not silently off, and that an unset TELEGRAM_ENABLED yields 'not_configured'.
- tests/test_health.py — /health/detailed includes a 'telegram' component; with TELEGRAM_ENABLED=true and a blank token the overall detailed status is degraded.

### 3. Slice 3 — BLOCKED: run and record the kill-switch drill (do not start until freqtrade runs)

Plain statement: this slice cannot be done now and must not be opened for work. Proving /forceexit all and /stopbuy requires a live bot talking to a running freqtrade container, and freqtrade is DOWN because Binance geo-blocks this VPS with HTTP 451. Telegram itself is not blocked; freqtrade cannot start against an unreachable exchange. When freqtrade runs again: create the bot via @BotFather, put the token and the group chat_id in .env (chmod 600, never committed), add both stakeholders to that group, set TELEGRAM_ENABLED=true, restart the freqtrade service, then execute the drill in order — /status, /stopbuy, confirm in the container logs that no new entries are taken, /forceexit all, confirm positions are flat — and record it in docs/gates/G1-telegram-killswitch-drill.md alongside the existing docs/gates/G0-report.md. The record carries: a first-line STATUS of PASSED or FAILED, the date, the operator, both stakeholder handles, the freqtrade version, the last four digits of the chat_id only (never the full id, never the token), and the log excerpts for /stopbuy and /forceexit. docs/RUNBOOK.md:76-88 is updated to point at the artifact instead of asking for a screenshot nobody checks. Only when this artifact exists does R12 stop being 'wired but unverified'. Nothing about this slice is shipped early: no template, no placeholder file, no test that asserts a placeholder exists. Until then R12 is reported as incomplete, and slice 2's /health/detailed correctly says configured_unproven.

**Acceptance**

- [ ] This issue stays blocked and is not counted toward R12 until freqtrade is running again. Do not mark R12 done on the strength of slices 1 and 2.
- [ ] The drill is executed against a dry-run freqtrade, not live trading, and both stakeholders individually confirm they can see notifications and issue /stopbuy from the group chat.
- [ ] docs/gates/G1-telegram-killswitch-drill.md exists with STATUS: PASSED plus date, operator, both handles, freqtrade version, chat_id last four only, and the two log excerpts.
- [ ] No token, no full chat_id, and no .env content is committed anywhere in the artifact or the tests.
- [ ] docs/RUNBOOK.md section 5 points at the artifact path and drops the unenforceable 'screenshot in docs/gates/' instruction.
- [ ] If the drill fails, STATUS: FAILED is recorded with what broke and the slice stays open. A failed drill is a valid, expected outcome to record — it is never rewritten as PASSED after a retry without a new dated entry.

**Tests first**

- Written and landed WITH the drill, not before. tests/test_gate_artifacts.py (new) — test_telegram_drill_artifact_declares_a_status: docs/gates/G1-telegram-killswitch-drill.md exists and its STATUS line is exactly PASSED or FAILED, so the gate cannot be left ambiguous.
- test_passed_drill_carries_evidence — if STATUS is PASSED the file also contains a date, two stakeholder handles, and non-empty /stopbuy and /forceexit log excerpt sections. This is the anti-rubber-stamp check: the only automated defence against declaring the kill switch proven from a ticked box.
- test_drill_artifact_carries_no_raw_credentials — the artifact contains no string matching the Telegram bot-token shape (digits, colon, 35 chars) and no full chat_id, only a last-four suffix.
- No test can prove the bot delivered a message. That verification is the manual drill; automation here only checks that the drill was recorded honestly.
