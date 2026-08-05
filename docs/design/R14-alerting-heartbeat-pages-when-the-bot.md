# R14 — Alerting: heartbeat pages when the bot goes silent; alerts on circuit-breaker trips, API failures, abnormal drawdown

Status: designed, not yet implemented. Design council of two independent
designs judged head to head.

## Gap being closed

No liveness ping from the api or freqtrade (the ingestor is the only pinger, and it is the container that is down - so the heartbeat currently reports the wrong subsystem's death). No alert on circuit-breaker/MaxDrawdown trips, no alert on signal-API failure, no drawdown alert, no alert on backup failure or stale market data. The HEALTHCHECKS_URL wiring in scripts/stream_klines.py:35-44 is itself untested (tests/test_kline_stream_permanent_errors.py:105-120 monkeypatches KlineStreamConsumer away before that branch matters), so a typo there ships silently. Closing it: a small watchdog (api-side scheduled ping + a poller that turns /health/detailed degradation and Freqtrade protection locks into a healthchecks.io fail signal or Telegram message), plus tests.

## Chosen approach

Design A (scripts/watchdog.py + pure decision modules in app/services/), with three grafts from B

## Rationale

The two designs converge on the same architecture (pure functions over scalars + one host-cron poller, no new services or dependencies), so the decision comes down to four concrete differences.

A wins on fit and operational cost. Its slice 1 is a strict extraction of the untested closure at scripts/stream_klines.py:35-44 into app/services/heartbeat.py and nothing more. B's slice 1 bolts on a second liveness path (HEALTHCHECKS_API_URL, a new docker-compose.prod.yml env line, and a FastAPI startup task or an /internal/heartbeat route) and then admits in its own behaviour text that the cron form is preferable — at which point the api-side ping is exactly what slice 2's watchdog already does, since the watchdog's own GET of /health/detailed is the api liveness proof. That is manufactured work and a lifecycle hook we do not need. Cut.

A also wins on naming and module boundaries: watchdog_verdict() in app/services/watchdog.py, with a module-owned FAULT_STATUSES frozenset, mirrors backup_status.py's DEGRADED_STATUSES/BENIGN_STATUSES exactly (that file already documents why the consumer must not restate status literals). B's single app/services/alert_status.py accumulates two unrelated concerns (health-payload verdicts and freqtrade lock rows) in one module.

Three grafts from B, all real improvements:
1. Ping on ok as well as fail. A's slice 2 only fail-pings, which leaves the watchdog itself unmonitored — if cron never fires, nothing happens and nothing is noticed. Pinging the base url on ok turns healthchecks.io into a dead-man's switch for the watchdog. This is the single most valuable idea in B.
2. Exit code 2 on ping delivery failure, distinct from 1 (fault signalled). "Send attempted" is not "alert delivered"; house style forbids reporting healthy when unproven, and the same applies to reporting alerted when unproven.
3. Slice 3 reads Freqtrade's pairlocks table rather than parsing the log. A itself flags log-format coupling as a risk that a freqtrade upgrade silently breaks. pairlocks (pair, lock_end_time, reason, active) is a stable schema, sqlalchemy is already a dependency, and the caller-owns-the-query split is exactly the house pattern. Fixture rows test it with no running freqtrade.

Further scope cuts beyond either design: no /health/detailed protections component. The api container does not mount the freqtrade sqlite file and adding that mount is a deploy change for a display-only surface. scripts/watchdog.py runs on the host next to scripts/prod_backup.py, where the db already is; it owns the query and merges the result into the verdict as a synthetic component. One place, no mount, no compose change.

On alert fatigue, both designs raise it and both answer correctly: market_data is stale today because Binance returns 451, so the check will sit red until the ingestor is relocated. We accept a permanently red check. No suppression list, no known-outage exclusion, no downgrading stale to healthy — any such logic would hide the next real outage, and the system genuinely is down.

Slice 1 delivers value on day one (closes a branch where a typo ships silently, and hands slice 2 its pinger). Slice 2 is the payload: it is the first alert path that reports the right subsystem's death, and it is fully exercisable offline against a fixture /health/detailed payload plus a fake HTTP getter. Slice 3 is honestly the weakest — see its behaviour text for what CI cannot prove.

## Grafted, and explicitly rejected

- From Design B slice 2: ping healthchecks on ok as well as on fail, so a watchdog that stops running trips the check by omission. Design A only fail-pinged, leaving the watchdog itself unmonitored.
- From Design B slice 2: a third exit code (2) for ping delivery failure, distinct from 1 (fault signalled), plus logging the delivered payload. Never let an undelivered alert look like a healthy run.
- From Design B slice 3: read Freqtrade's pairlocks table rather than parsing the freqtrade log. Design A flagged its own log parser as format-coupled and liable to break silently on a freqtrade upgrade; a table read with sqlalchemy (already a dependency) is stable and matches the caller-owns-the-query pattern.
- From Design B slice 3: distinguish the 43200-candle MaxDrawdown kill switch from a 24h StoplossGuard cooldown in the alert text, since one needs a human and the other clears itself.
- From Design B slice 2: fail closed on a malformed or non-JSON health body, not just on a missing one.
- REJECTED from Design B slice 1: the api-side liveness ping (HEALTHCHECKS_API_URL, a docker-compose.prod.yml env line, and a FastAPI startup task or /internal/heartbeat route). The watchdog's own GET of /health/detailed already proves the api is serving, so this is a second mechanism for a signal we get for free.
- REJECTED from Design A slice 3: adding a freqtrade_protections component to /health/detailed. The api container does not mount the freqtrade sqlite file; adding that mount is a deploy change for a display-only surface. The host-cron watchdog owns the query instead.
- REJECTED from Design A slice 1: a build_heartbeat variant that takes a fail-endpoint argument. A separate fail_url() helper is simpler and keeps the builder single-purpose.

## Acceptance criteria

- [ ] No new service, container, or third-party dependency is introduced. httpx and sqlalchemy are already in use; nothing else is added.
- [ ] Every new decision function is pure over already-fetched inputs (payload dicts, row tuples, scalars) with the caller owning all I/O, matching /Users/isupercoder/Code/github/ai-forecasting/app/services/market_data_status.py and /Users/isupercoder/Code/github/ai-forecasting/app/services/backup_status.py.
- [ ] Every slice's tests pass with no network access, no Binance reachability, no exchange API keys, and no running freqtrade process.
- [ ] Fail-closed everywhere: a missing, malformed, unreachable, or unparseable input never yields 'ok'/'healthy'. Unknown or unrecognised statuses are surfaced as faults, not silently treated as benign.
- [ ] Status-set membership (which statuses count as a fault) is owned by the module that defines the statuses and imported by consumers, never restated as a literal at the call site.
- [ ] The watchdog pings healthchecks.io on success as well as on failure, so a watchdog that stops running makes the check go late and pages.
- [ ] Delivery of an alert is never reported as successful unless the ping call returned successfully; a failed ping is distinguishable from a successful one by exit code and by log line.
- [ ] No alert suppression, allowlisting, or known-outage exclusion logic is added. The current Binance 451 outage is allowed to hold the check red.
- [ ] Tests are written first and observed failing for the right reason (assertion about missing behaviour, not ImportError on a typo) before implementation.
- [ ] Each slice ships independently: it merges green on the existing backend CI job, is cut as one release via scripts/release.py, and leaves the repo deployable.
- [ ] Any new env var is added to /Users/isupercoder/Code/github/ai-forecasting/env.example and documented in docs/RUNBOOK.md with the exact crontab line where applicable.
- [ ] Nothing in the code or docs claims coverage of a failure mode that is not actually exercised by a test; known blind spots are stated plainly in the runbook.

## Delivery slices

### 1. R14.1 — Extract the untested heartbeat wiring into app/services/heartbeat.py

Today the only heartbeat pinger in the system is an inline closure at /Users/isupercoder/Code/github/ai-forecasting/scripts/stream_klines.py:35-44, inside the ingestor container — the one process that is currently down. Worse, that branch is untested: tests/test_kline_stream_permanent_errors.py monkeypatches KlineStreamConsumer away before the branch matters, so a typo in it ships silently and the heartbeat is simply never sent.

Create /Users/isupercoder/Code/github/ai-forecasting/app/services/heartbeat.py with two small pieces:

  build_heartbeat(url: str | None, *, get=None, timeout: float = 5.0) -> Callable[[], None] | None
    Returns None when url is None, empty, or whitespace-only (so the default stays heartbeat-free). Otherwise returns a zero-arg callable that performs get(url, timeout=timeout). The default get is httpx.get, imported at module level. The returned callable does NOT swallow exceptions — swallowing is already the consumer's job in KlineStreamConsumer._maybe_heartbeat, and duplicating it here would make a broken url untestable.

  fail_url(url: str) -> str
    Returns url with exactly one '/fail' suffix appended, without mutating or double-appending if the base already ends in '/fail'. Slice R14.2 needs this; it lives here so the url shape is defined in one place.

Rewrite scripts/stream_klines.py to call build_heartbeat(os.environ.get("HEALTHCHECKS_URL")) and pass the result straight into KlineStreamConsumer(heartbeat_fn=...). Delete the inline import and closure. No behaviour change for the ingestor.

Fully testable offline with an injected fake get. Valuable today despite the ingestor being down: it converts a silently-unverified branch into a covered one and gives R14.2 its delivery mechanism.

**Acceptance**

- [ ] app/services/heartbeat.py exists and exports build_heartbeat and fail_url; it imports nothing from scripts/ and nothing from app.api.
- [ ] scripts/stream_klines.py contains no inline heartbeat closure and no function-local httpx import; it calls build_heartbeat.
- [ ] The heartbeat_fn kwarg reaching KlineStreamConsumer is asserted by a test in both the configured and unconfigured cases, without the consumer being monkeypatched away first.
- [ ] build_heartbeat treats a whitespace-only url the same as an unset one, and attempts no request in that case.
- [ ] The returned callable propagates exceptions rather than swallowing them; a test proves it.
- [ ] No change to KlineStreamConsumer's behaviour or signature. The ingestor's runtime behaviour with HEALTHCHECKS_URL set is byte-for-byte equivalent to today's.
- [ ] No new dependency; httpx is already used in the repo.

**Tests first**

- tests/test_heartbeat.py::test_none_url_returns_none — build_heartbeat(None) returns None
- tests/test_heartbeat.py::test_blank_url_returns_none — build_heartbeat("") and build_heartbeat("   ") return None, and the injected fake get is never called
- tests/test_heartbeat.py::test_callable_gets_configured_url_and_timeout — build_heartbeat("https://hc.example/uuid", get=fake) returns a callable; invoking it calls fake exactly once with that url and timeout=5.0
- tests/test_heartbeat.py::test_custom_timeout_is_passed_through
- tests/test_heartbeat.py::test_get_exception_propagates — a fake get that raises causes the returned callable to raise, proving the builder does not swallow
- tests/test_heartbeat.py::test_fail_url_appends_once — fail_url("https://hc.example/uuid") == "https://hc.example/uuid/fail"
- tests/test_heartbeat.py::test_fail_url_is_idempotent — fail_url(fail_url(u)) == fail_url(u), and the base url string is not mutated
- tests/test_kline_stream_permanent_errors.py::test_stream_klines_builds_heartbeat_from_env — run scripts/stream_klines.main() with HEALTHCHECKS_URL set, capturing the KlineStreamConsumer constructor kwargs (do NOT monkeypatch the class away before the branch runs); assert heartbeat_fn is not None
- tests/test_kline_stream_permanent_errors.py::test_stream_klines_heartbeat_none_when_env_unset — same harness with HEALTHCHECKS_URL absent; assert heartbeat_fn is None

### 2. R14.2 — scripts/watchdog.py turns /health/detailed degradation into a healthchecks page

Today a signal-API failure, stale klines, or a broken nightly backup only mutate a JSON body that nobody reads. /health/detailed already reports database, redis, storage, model_storage, market_data and backups. Nothing polls it. This slice makes it page.

Add /Users/isupercoder/Code/github/ai-forecasting/app/services/watchdog.py with one pure function:

  watchdog_verdict(payload: dict | None, *, fetch_error: str | None = None, extra_components: dict | None = None) -> dict
    Returns {"status": "ok" | "fault", "faults": [component names, sorted], "reasons": [str], }.
    Fail-closed rules, all owned by this module:
      - payload is None, not a dict, or fetch_error is set => status "fault", reason naming the api as unreachable. This is the case where the api container itself is dead, and it must never raise.
      - payload lacking a "components" mapping => "fault" (malformed, not healthy).
      - module-owned BENIGN_STATUSES = frozenset({"healthy", "not_configured"}). Any component whose status is not in that set — including "unknown" and any status string this module has never seen — is a fault, named in faults with its status in reasons. Do NOT enumerate bad statuses; enumerate good ones, so a new status added upstream fails closed by default.
      - top-level status of "degraded"/"unhealthy" is a fault even if the components mapping is empty.
      - extra_components is merged over the payload's components before judging; R14.3 uses it. Default None means no extras.

Add /Users/isupercoder/Code/github/ai-forecasting/scripts/watchdog.py, a host-cron script alongside scripts/prod_backup.py:
  - Reads WATCHDOG_HEALTH_URL (default http://localhost:8000/api/v1/health/detailed) and HEALTHCHECKS_WATCHDOG_URL from os.environ.
  - GETs the health url with a short timeout. Any exception (connect error, timeout, non-2xx, non-JSON body) is caught and converted into fetch_error text — never a traceback.
  - Calls watchdog_verdict, prints one human-readable summary line naming the faulting components, then delivers: build_heartbeat(base_url) on ok, build_heartbeat(fail_url(base_url)) on fault. It pings on BOTH outcomes so healthchecks.io detects a watchdog that stopped running (missed ping => check goes late => page). That dead-man's-switch property is the point; a fail-only watchdog is invisible when cron breaks.
  - Exit codes: 0 = ok and ping delivered; 1 = fault and fail-ping delivered; 2 = the ping itself raised (delivery unproven), with the delivery failure printed. A muted alert channel must not look like a healthy system.
  - If HEALTHCHECKS_WATCHDOG_URL is unset, print that alerting is not configured and exit 2 — unconfigured is not ok.
  - Keep the argument surface to nothing but env vars so the crontab line is trivial.

Document HEALTHCHECKS_WATCHDOG_URL and WATCHDOG_HEALTH_URL in env.example, and add the exact crontab line plus the exit-code table to docs/RUNBOOK.md.

Fully valuable and fully testable without Binance, keys, or freqtrade: the api is up while the ingestor is down, so this is the first signal that reports the right subsystem's death, and it covers backup failure and stale klines with no new moving parts. Two honest caveats to state in the runbook rather than paper over: (a) if this VPS cannot reach hc-ping.io, alerting is dead — the exit-2 path plus cron mail is the only backstop, and it is not proven by CI; (b) market_data is stale right now because of the Binance 451, so the check will sit red until the ingestor is relocated. No suppression is added.

**Acceptance**

- [ ] app/services/watchdog.py contains no I/O: no httpx, no os.environ, no file or socket access. All inputs are passed in by the caller.
- [ ] BENIGN_STATUSES is an allowlist owned by app/services/watchdog.py. A status string the module has never seen produces a fault, proven by a test using an invented status.
- [ ] watchdog_verdict never raises for any input, including None, non-dict, and deeply malformed payloads; tests cover each.
- [ ] scripts/watchdog.py pings the base url on ok and base+"/fail" on fault, reusing build_heartbeat and fail_url from R14.1 rather than reimplementing either.
- [ ] Exit codes are exactly 0 = ok delivered, 1 = fault delivered, 2 = delivery unproven or alerting unconfigured, and each is covered by a test.
- [ ] No exception from the health fetch or from JSON decoding escapes the script; the process always reaches a delivery attempt.
- [ ] No suppression, allowlist, or known-outage exclusion for market_data staleness exists anywhere in the slice.
- [ ] HEALTHCHECKS_WATCHDOG_URL and WATCHDOG_HEALTH_URL are present in env.example; docs/RUNBOOK.md contains the verbatim crontab line, the exit-code table, and an explicit statement that hc-ping.io reachability from this VPS is not proven by CI.
- [ ] No new container, service, systemd unit, or dependency. The script runs from host cron next to scripts/prod_backup.py.
- [ ] All tests pass with no network access.

**Tests first**

- tests/test_watchdog.py::test_all_components_healthy_is_ok — status "ok", faults empty
- tests/test_watchdog.py::test_not_configured_component_is_benign — a backups component reporting "not_configured" does not produce a fault
- tests/test_watchdog.py::test_none_payload_is_fault — watchdog_verdict(None) => fault, reason names the api as unreachable
- tests/test_watchdog.py::test_fetch_error_is_fault — a healthy-looking payload plus fetch_error set still yields fault
- tests/test_watchdog.py::test_non_dict_and_missing_components_are_faults — [], "", {} and {"status":"healthy"} with no components all fail closed
- tests/test_watchdog.py::test_stale_market_data_and_stale_backups_named — both component names appear in faults, using a realistic /health/detailed shape
- tests/test_watchdog.py::test_unhealthy_component_named_with_reason — e.g. database unhealthy
- tests/test_watchdog.py::test_unknown_status_is_fault — a component with status "unknown" is never ok
- tests/test_watchdog.py::test_unrecognised_status_is_fault — an invented status string like "weird" fails closed (proves BENIGN_STATUSES is an allowlist, not a denylist)
- tests/test_watchdog.py::test_degraded_top_level_is_fault_even_with_benign_components
- tests/test_watchdog.py::test_extra_components_are_judged — an injected extra component with a non-benign status produces a fault named after it
- tests/test_watchdog_script.py::test_ok_pings_base_url_and_exits_zero — fake getter returns a healthy payload; assert the ping url is exactly the base url and exit code is 0
- tests/test_watchdog_script.py::test_fault_pings_fail_url_and_exits_one — assert the ping url is exactly base + "/fail"
- tests/test_watchdog_script.py::test_health_fetch_exception_becomes_fail_ping_not_crash — the health getter raises; assert a fail ping was sent and exit code is 1, with no traceback escaping
- tests/test_watchdog_script.py::test_non_json_health_body_is_fault
- tests/test_watchdog_script.py::test_ping_delivery_failure_exits_two — the ping raises; assert exit code 2 and that the printed output says delivery failed rather than claiming the alert was sent
- tests/test_watchdog_script.py::test_missing_healthchecks_url_exits_two — unconfigured alerting is not reported as ok
- tests/test_watchdog_script.py::test_summary_line_names_faulting_components

### 3. R14.3 — Freqtrade protection locks (StoplossGuard / MaxDrawdown) become a watchdog fault

EnsembleSignalStrategy declares three protections at /Users/isupercoder/Code/github/ai-forecasting/user_data/strategies/EnsembleSignalStrategy.py:89-119: a StoplossGuard (4 stops in 24h => 24-candle halt), a -5% MaxDrawdown (1440-candle halt) and a -15% MaxDrawdown kill (43200-candle halt, effectively permanent). When any of them trips, trading stops and the only record is a log line — Telegram is disabled by default. Nobody is told. This slice makes a trip page through the exact path built in R14.2.

Add /Users/isupercoder/Code/github/ai-forecasting/app/services/freqtrade_protection_status.py with one pure function:

  protection_status(rows: Iterable[Any] | None, now: datetime) -> dict
    rows are what the caller SELECTed from Freqtrade's pairlocks table: (pair, lock_end_time, reason, active). Returns {"status": "healthy" | "locked" | "unknown" | "not_configured", "active_locks": [{"pair", "reason", "unlocks_at", "kill_switch": bool}], "message": str}.
    Rules:
      - rows is None => "not_configured" (no FREQTRADE_DB_URL set; local dev has no freqtrade db). Benign.
      - empty rows, or every lock expired (lock_end_time <= now) or inactive => "healthy".
      - any active unexpired lock => "locked", listing pair, reason and unlocks_at.
      - a lock whose remaining duration exceeds a module constant KILL_SWITCH_HOURS (set to a value that separates the 43200-candle kill from a 24h StoplossGuard halt — document the arithmetic in a comment) is flagged kill_switch: true, so a permanent halt is distinguishable from a routine cooldown in the alert text.
      - any row that is missing fields, has an unparseable timestamp, or is otherwise malformed => "unknown" with the reason in message. Never "healthy". A schema drift after a freqtrade upgrade must page, not go quiet.
    Parsing the freqtrade LOG was considered and rejected: log lines are format-coupled and change across releases, while pairlocks is a stable table the ORM-free query can read with sqlalchemy, which is already a dependency.

Wire it into scripts/watchdog.py: read FREQTRADE_DB_URL from env; when unset, pass rows=None. When set, open a connection and SELECT pair, lock_end_time, reason, active FROM pairlocks — the query lives in the script, not in the service, matching backup_status/market_data_status. Any exception from connecting or querying (file missing, table missing, locked db) is converted into an "unknown" component with the error text, never a crash and never a skip. Merge the result into watchdog_verdict via extra_components under the key "freqtrade_protections". Because "locked" and "unknown" are both outside BENIGN_STATUSES, a trip pages with zero additional wiring; add no new branch to the verdict function.

Document FREQTRADE_DB_URL in env.example and add a runbook section on what a kill_switch alert means and that clearing it requires a human.

What CI can and cannot prove, stated plainly: the decision function and the error handling are fully covered by fixture rows and a fake connection, with no running freqtrade. What is NOT covered is the pairlocks schema itself — no test asserts that a real freqtrade sqlite file has those columns, because freqtrade is down and there is no live db to point at. That is a genuine gap; the fail-closed "unknown" path is what keeps it from being a silent one, and the runbook must say so rather than implying the alert is verified end to end.

**Acceptance**

- [ ] app/services/freqtrade_protection_status.py performs no I/O: no sqlalchemy engine creation, no os.environ, no file access. The SELECT lives in scripts/watchdog.py.
- [ ] Log-file parsing is not used anywhere in this slice.
- [ ] Every malformed-input path returns "unknown"; there is no code path in which unparseable or partially readable rows produce "healthy", and tests cover missing fields, wrong arity, and bad timestamps.
- [ ] A database connection or query error in scripts/watchdog.py produces a freqtrade_protections component with status "unknown", never an omitted component and never an unhandled exception.
- [ ] watchdog_verdict gains no protection-specific branch; "locked" and "unknown" fault purely by falling outside the existing BENIGN_STATUSES allowlist.
- [ ] A kill-switch-duration lock is reported distinctly from a routine cooldown in the alert text, and the candle-to-hours arithmetic behind KILL_SWITCH_HOURS is documented in a comment.
- [ ] No change to docker-compose.prod.yml, no new volume mount, and no new component added to /health/detailed — the watchdog runs on the host where the freqtrade db already lives.
- [ ] FREQTRADE_DB_URL is documented in env.example, and docs/RUNBOOK.md states both what a kill_switch alert means and that the pairlocks schema is unverified against a live freqtrade instance.
- [ ] All tests pass with no running freqtrade, no exchange keys, and no network access.

**Tests first**

- tests/test_freqtrade_protection_status.py::test_rows_none_is_not_configured
- tests/test_freqtrade_protection_status.py::test_no_rows_is_healthy
- tests/test_freqtrade_protection_status.py::test_expired_lock_is_healthy — lock_end_time in the past is not an alert
- tests/test_freqtrade_protection_status.py::test_inactive_lock_is_healthy — active falsy is ignored even if unexpired
- tests/test_freqtrade_protection_status.py::test_active_stoplossguard_lock_is_locked — pair, reason and unlocks_at are surfaced, kill_switch False
- tests/test_freqtrade_protection_status.py::test_max_drawdown_kill_lock_flagged_as_kill_switch — a lock ending far in the future (the 43200-candle halt) sets kill_switch True, distinguishing it from a 24h halt
- tests/test_freqtrade_protection_status.py::test_multiple_locks_all_listed
- tests/test_freqtrade_protection_status.py::test_malformed_row_returns_unknown — missing field, wrong arity, and unparseable lock_end_time each yield "unknown", never "healthy"
- tests/test_freqtrade_protection_status.py::test_one_bad_row_among_good_rows_still_unknown — a partially readable result set does not get reported as healthy
- tests/test_watchdog.py::test_locked_protections_component_is_a_fault — extra_components={"freqtrade_protections": {"status": "locked"}} produces a fault naming that component, with no new branch added to watchdog_verdict
- tests/test_watchdog.py::test_unknown_protections_component_is_a_fault
- tests/test_watchdog_script.py::test_protection_lock_triggers_fail_ping — end to end with a fake row source and a fake pinger: fail url pinged, exit 1
- tests/test_watchdog_script.py::test_freqtrade_db_url_unset_yields_not_configured_and_stays_ok
- tests/test_watchdog_script.py::test_freqtrade_db_error_becomes_unknown_component_not_a_skip — the connection raises; assert a fail ping is sent and the summary names freqtrade_protections, rather than the component being silently omitted
