# R16 — Binance API keys without withdrawal permission, IP-restricted to the VPS, server-side env only, never in git

Status: designed, not yet implemented. Design council of two independent
designs judged head to head.

## Gap being closed

Nothing machine-checks the two properties the requirement is actually about. Missing: (1) a live-mode preflight that calls Binance GET /sapi/v1/account (or /sapi/v1/capital/config) and refuses to start when enableWithdrawals is true or the key is not IP-restricted, wired into the freqtrade entrypoint so live cannot boot on an over-permissioned key; (2) a cheap CI guard asserting every checked-in freqtrade config has empty key/secret and that config.live.json is gitignored. Currently vacuously satisfied only because no live keys exist yet (dry-run, G2 not started per docs/RUNBOOK.md:105-110).

## Chosen approach

Design B (four slices), trimmed to three: its stricter fail-closed truth table and repo-hygiene rigour win, but slice 4 (health reporting of the preflight verdict) is cut as reporting on work that does not exist yet.

## Rationale

Both designs converge on the same shape (pure policy module + thin callers), so the decision comes down to detail quality and scope discipline. B is stronger where it matters: it treats non-boolean/missing fields as malformed rather than falsy-pass, refuses to let a guard pass vacuously when it globs zero config files, flags password/uid alongside key/secret, and rejects unparseable config text instead of silently skipping it. Those are exactly the ways a fail-closed guard rots into a no-op. A is stronger on scope: three slices, no new health surface, one Binance call, no verdict artefact. B's slice 4 fails the "no manufactured work" test - it would ship a /health/detailed section that can only ever say "unverified" until G2 funds a live key on a non-geo-blocked host, i.e. reporting on a system that does not exist. Cut it; re-open it when a real preflight has ever run. On endpoint choice, A's own risk note is correct and decides it: GET /sapi/v1/account reports permission flags but not ipRestrict. GET /sapi/v1/account/apiRestrictions returns enableWithdrawals, enableSpotAndMarginTrading and ipRestrict together, so one signed call covers R16 - no second endpoint, no ipList invention. Slice 1 delivers value on the first commit and is provably red-then-green today: /Users/isupercoder/Code/github/ai-forecasting/.gitignore currently has no user_data/config.live.json rule, so the guard genuinely fails against HEAD before the rule is added. Everything is testable with Binance returning 451 and freqtrade down, because the only network call lives behind an injected fetcher. One implementation constraint both designs missed: /Users/isupercoder/Code/github/ai-forecasting/user_data/config.dry.json is JSONC (json.load raises JSONDecodeError at line 2 on the // comment header), so the guard needs a comment-tolerant parse and must not treat a comment as malformed.

## Grafted, and explicitly rejected

- From A: three slices only. B's slice 4 (verdict artefact + /health/detailed exchange_key section) is cut entirely - with no live key ever having run it could only report "unverified" forever, which is monitoring a system that does not exist. Revisit after the first real preflight run at G2.
- From A: one Binance call, not two. Use GET /sapi/v1/account/apiRestrictions, which returns enableWithdrawals, ipRestrict and enableSpotAndMarginTrading together - A's risk note correctly identifies that /sapi/v1/account omits ipRestrict.
- From A: no verdict file, so no new mount, no staleness threshold, no second source of truth to age out.
- From B: strict identity checks against booleans, so "false", 0 and 1 are malformed rather than coerced to a pass.
- From B: empty config mapping is itself a finding, so a renamed directory or broken glob cannot make the guard pass vacuously.
- From B: unparseable config text is a finding, not a silent skip.
- From B: flag password and uid alongside key and secret - freqtrade accepts all four.
- From B: no "not_configured" escape hatch in the status set, and a test asserting BLOCKING/BENIGN partition every status the module can return.
- From B: explicit test that secrets never appear in output on any failure path.
- From B: explicit test that the dry-run compose command is unchanged, not just that the live one is gated.
- Dropped from B: the BINANCE_EXPECTED_IP / ipList membership check. apiRestrictions does not return the allowed IP list, so that check would be built on a field we cannot confirm exists. Replaced with an honest docstring and RUNBOOK line saying ipRestrict proves restriction exists but not that it points at this VPS.
- New, missed by both: user_data/config.dry.json is JSONC (json.load raises JSONDecodeError on its `//` comment header), so the guard needs comment-tolerant parsing with a test proving a commented config reads clean rather than malformed.
- New, missed by both: the config guard's refusal must not be suppressible by ALLOW_RED_CI - a red suite can be an operator judgement call, a committed API key cannot.
- New: .gitignore currently lacks the user_data/config.live.json rule, so slice 1 is genuinely red against HEAD before the rule is added - a real red-to-green, not a test written to pass.

## Acceptance criteria

- [ ] No checked-in file under user_data/ can carry a non-empty exchange key, secret, password or uid without CI going red, and the check runs in the existing Backend (pytest) job - no new CI job, service, container, cron entry or third-party dependency is added by any slice.
- [ ] user_data/config.live.json is ignored by /Users/isupercoder/Code/github/ai-forecasting/.gitignore, and a commit removing that rule turns CI red.
- [ ] The definition of an acceptable live key exists once, as pure functions in app/services/key_policy.py taking already-fetched payloads and returning a status dict, matching the shape of app/services/backup_status.py (module owns its own BLOCKING/BENIGN status sets; callers never restate them as literals).
- [ ] Every non-compliant outcome - withdrawals enabled, not IP-restricted, missing field, non-boolean field, empty payload, HTTP error, timeout, HTTP 451, missing env - resolves to a non-zero exit. There is no status, code path or env flag by which an unproven key results in freqtrade starting live.
- [ ] The dry-run path is byte-for-byte unchanged: the freqtrade service in docker-compose.prod.yml still starts with `trade --config /freqtrade/user_data/config.dry.json --strategy EnsembleSignalStrategy` and needs no keys, no env vars and no Binance reachability.
- [ ] The full suite passes on this VPS with Binance returning 451, no live API keys in existence and freqtrade down. No test makes a network call.
- [ ] No test, log line, error message or CI output ever prints an API key or secret, including on the failure paths.
- [ ] Each slice is preceded by tests that fail for the intended reason (assertion, not ImportError against a file that was never created as part of the same commit), and each ships as one release via scripts/release.py.

## Delivery slices

### 1. Slice 1 - CI guard: no credentials in any checked-in freqtrade config, and config.live.json is gitignored

New pure module /Users/isupercoder/Code/github/ai-forecasting/app/services/key_policy.py exposing `config_credential_findings(configs: dict[str, str], gitignore_text: str) -> list[str]`, where `configs` maps path -> raw file text and the return is a list of human-readable findings (empty means clean). A finding is raised for: any config whose exchange.key, exchange.secret, exchange.password or exchange.uid is a non-empty string; any config text that will not parse; an empty `configs` mapping (a guard that inspected nothing must not report clean, or a renamed directory silently disables it); and a gitignore that does not ignore user_data/config.live.json (a commented-out or partial line does not count). A config with no top-level `exchange` block is NOT a finding - freqtrade configs legitimately split, and treating absence as a fault would fail on files that carry no credentials at all; the empty-mapping check is what stops the vacuous pass. Parsing must tolerate `//` line comments: user_data/config.dry.json opens with a comment header and plain json.load raises JSONDecodeError at line 2, so strip comments before parsing and prove a commented config is clean, not malformed. The caller owns the globbing: new /Users/isupercoder/Code/github/ai-forecasting/scripts/check_exchange_config.py reads user_data/*.json plus .gitignore, prints each finding and exits 1 if any. Wired two places: a `Run exchange config guard` step in the existing Backend (pytest) job in .github/workflows/ci.yml, and a call at the top of main() in scripts/ci_gate.py that exits non-zero before the SHA check and is deliberately NOT overridable by ALLOW_RED_CI - a red test suite can be a judgement call at 3am, a committed API key never is. The slice also adds the missing `user_data/config.live.json` line to .gitignore, which is what takes the new guard from red to green against HEAD. Fully valuable and fully testable today: pure text in, findings out, no Binance, no keys, no freqtrade.

**Acceptance**

- [ ] app/services/key_policy.py contains no I/O: no open(), no glob, no os.environ, no network. The caller passes text.
- [ ] scripts/check_exchange_config.py exits 0 against the current repo tree and 1 against a temp tree with a credential-bearing config.
- [ ] `user_data/config.live.json` is present in /Users/isupercoder/Code/github/ai-forecasting/.gitignore and the guard fails if it is removed.
- [ ] The Backend (pytest) CI job runs the guard as an added step; no new workflow or job is created.
- [ ] ci_gate.py refuses to proceed on findings and ALLOW_RED_CI=1 does not suppress that refusal (existing ALLOW_RED_CI behaviour for the SHA check is unchanged).
- [ ] No test hits the network.

**Tests first**

- tests/test_key_policy.py::test_clean_config_and_gitignore_yields_no_findings - config text shaped like user_data/config.dry.json (key "", secret "") plus a gitignore containing user_data/config.live.json -> []
- tests/test_key_policy.py::test_jsonc_comment_header_parses_clean - config text whose first lines are `//` comments (as config.dry.json actually is) must be parsed, not reported malformed
- tests/test_key_policy.py::test_each_credential_field_is_flagged - parametrised over key, secret, password, uid; each non-empty value yields exactly one finding naming both the path and the field
- tests/test_key_policy.py::test_finding_text_does_not_echo_the_credential_value - the finding names the field, never the value
- tests/test_key_policy.py::test_config_without_exchange_block_is_not_a_finding
- tests/test_key_policy.py::test_unparseable_config_text_is_a_finding - malformed JSON is a violation, not a silent skip
- tests/test_key_policy.py::test_empty_config_mapping_is_a_finding - scanning zero files must fail so a bad glob cannot pass vacuously
- tests/test_key_policy.py::test_gitignore_without_config_live_rule_is_a_finding, and ::test_commented_out_gitignore_rule_does_not_count
- tests/test_check_exchange_config.py::test_exits_one_and_prints_findings_for_a_credentialed_temp_repo_tree
- tests/test_check_exchange_config.py::test_exits_zero_against_the_real_repo_tree_as_it_stands - the committed repo must be clean after the .gitignore line is added
- tests/test_ci_gate.py::test_ci_gate_exits_non_zero_when_config_findings_exist_even_with_allow_red_ci_set

### 2. Slice 2 - Pure fail-closed evaluator of Binance key permissions

Add `key_permission_status(restrictions: dict | None) -> dict` to app/services/key_policy.py, returning {"status": str, "reasons": list[str]} over an already-fetched GET /sapi/v1/account/apiRestrictions payload (that endpoint, not /sapi/v1/account, is the one that reports ipRestrict alongside enableWithdrawals and enableSpotAndMarginTrading, so R16 needs exactly one call). Status is "compliant" only when enableWithdrawals is exactly False, ipRestrict is exactly True and enableSpotAndMarginTrading is exactly True - identity checks against booleans, so the string "false", 0 and 1 are malformed rather than quietly accepted. Every other outcome is a fault with a reason: "withdrawals_enabled", "not_ip_restricted", "spot_trading_disabled", "malformed" (a required field absent, null, or not a bool; payload not a dict), "unavailable" (payload is None, i.e. the caller's fetch failed, timed out or was geo-blocked). There is deliberately no "not_configured" escape hatch and no default-pass branch. The module owns BLOCKING_STATUSES / BENIGN_STATUSES exactly as backup_status.py owns DEGRADED_STATUSES, with only "compliant" benign, so a future status cannot read as healthy at a caller that hardcoded a literal. Honest limitation stated in the docstring: apiRestrictions reports that a key is IP-restricted but not which IPs, so this function can prove restriction exists and cannot prove it is restricted to this VPS - that remains an operator step recorded in docs/RUNBOOK.md, and the docstring must say so rather than implying more coverage than the API gives. No network, no env, no keys: the caller owns the query. Ships value alone as the single reviewable definition of what R16 permits.

**Acceptance**

- [ ] key_permission_status returns "compliant" for exactly one input shape and every mutation of that shape returns a non-compliant status.
- [ ] BLOCKING_STATUSES and BENIGN_STATUSES are defined in key_policy.py and partition the full set of statuses the function can return; a test enforces the partition.
- [ ] The function performs no I/O and takes no env vars.
- [ ] The docstring states plainly that ipRestrict proves restriction exists but not that the allowed IP is this VPS.

**Tests first**

- tests/test_key_policy.py::test_withdrawals_disabled_ip_restricted_spot_enabled_is_compliant
- ::test_enable_withdrawals_true_is_withdrawals_enabled - even when every other field is fine
- ::test_ip_restrict_false_is_not_ip_restricted
- ::test_spot_trading_disabled_is_a_fault
- ::test_none_payload_is_unavailable_never_compliant - the geo-blocked / failed-fetch case
- ::test_each_missing_required_field_is_malformed - parametrised over the three fields
- ::test_non_boolean_values_are_malformed - "false" (string), 0, 1, None each rejected rather than coerced
- ::test_non_dict_payload_is_malformed - list, string, int
- ::test_multiple_faults_are_all_reported - withdrawals enabled AND ip_restrict false yields both reasons
- ::test_blocking_statuses_covers_every_non_compliant_status_the_module_can_return - enumerate the module's statuses and assert none besides "compliant" is benign

### 3. Slice 3 - Fail-closed live preflight wired into the freqtrade entrypoint

New /Users/isupercoder/Code/github/ai-forecasting/scripts/live_preflight.py owns the single network call: an HMAC-SHA256-signed GET /sapi/v1/account/apiRestrictions using BINANCE_API_KEY / BINANCE_API_SECRET from the environment (stdlib urllib + hmac, no new dependency), passing the decoded payload to key_permission_status. The HTTP call is one module-level function injected as a default argument so tests substitute a fake and never touch the network. Exit 0 only on "compliant"; exit 1 with the reasons on stderr for every other case: missing or empty env vars (checked before any request is attempted), non-200 response, HTTP 451 (distinct geo-block message so the failure is diagnosable rather than mysterious), timeout, connection error, unparseable body, and any fault status. Failure output includes the reasons and never the key or secret. Wire it into the freqtrade service in docker-compose.prod.yml as a live-only command chain (`python /freqtrade/user_data/live_preflight.py && freqtrade trade --config /freqtrade/user_data/config.live.json ...`), leaving the current dry-run command line untouched, so this slice is CI-green and deployable with freqtrade down and Binance blocked. Add a docs/RUNBOOK.md note under the G2 section: the signed request cannot be exercised from this VPS while Binance returns 451, so the live path is shipped unverified against real Binance by construction, and G2 must run scripts/live_preflight.py from a permitted host before funding. That unverifiability is precisely why the failure mode is refuse-to-start rather than warn-and-continue. Do not claim this slice proves live safety in production - it proves the refusal logic, and the RUNBOOK must say which half is proven.

**Acceptance**

- [ ] scripts/live_preflight.py exits 0 on exactly one condition (fetch succeeded AND key_permission_status returned "compliant") and non-zero on every other path, including all exception paths.
- [ ] The env-var check runs before any request; a test asserts the injected fetcher is not called when credentials are absent.
- [ ] No new Python dependency is added (stdlib urllib/hmac/hashlib only) and no new container, service or cron entry is created.
- [ ] docker-compose.prod.yml's freqtrade dry-run command string is unchanged; the preflight appears only on the live-config command.
- [ ] docs/RUNBOOK.md states that the real signed request is unverified from this VPS due to HTTP 451 and that G2 must run the preflight from a permitted host before funding.
- [ ] No test performs a network call; every test injects the fetcher.
- [ ] No log or error output contains the API key or secret.

**Tests first**

- tests/test_live_preflight.py::test_exits_zero_when_fetcher_returns_a_compliant_payload
- ::test_exits_non_zero_when_withdrawals_enabled_and_reason_on_stderr
- ::test_exits_non_zero_when_not_ip_restricted
- ::test_exits_non_zero_when_fetcher_raises_timeout_or_connection_error - fail closed, never skip
- ::test_http_451_exits_non_zero_with_a_distinct_geo_block_message
- ::test_non_200_and_unparseable_body_each_exit_non_zero
- ::test_missing_or_empty_api_key_or_secret_exits_non_zero_before_any_call - assert the fetcher was never invoked
- ::test_neither_key_nor_secret_appears_in_stdout_or_stderr_on_any_failure_path
- ::test_signed_request_shape_without_sending_it - default fetcher's request builder produces the apiRestrictions path, a timestamp, recvWindow, a signature param and the X-MBX-APIKEY header
- tests/test_ensemble_strategy.py (extend) ::test_prod_compose_freqtrade_command_is_unchanged_for_dry_run and ::test_live_command_gates_trade_behind_the_preflight - parse docker-compose.prod.yml and assert both
