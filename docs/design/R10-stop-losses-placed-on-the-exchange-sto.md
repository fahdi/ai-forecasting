# R10 — Stop-losses placed on the exchange (stoploss-on-exchange) so positions survive bot/VPS/network death

Status: designed, not yet implemented. Design council of two independent
designs judged head to head.

## Gap being closed

The flag is set but cannot currently take effect, so the protection R10 exists for — a stop that survives the bot/VPS dying — is not actually in place. config.dry.json:22 sets dry_run: true, and docker-compose.prod.yml:105-107 runs freqtrade with exactly that file (`trade --config /freqtrade/user_data/config.dry.json`). Freqtrade evaluates the stop locally and never places an exchange order whenever dry_run is on: .venv-freqtrade/lib/python3.12/site-packages/freqtrade/strategy/interface.py:1644-1646 (`not self.order_types.get("stoploss_on_exchange") or self.config["dry_run"]`), and backtesting hard-forces it off at optimize/backtesting.py:344-347. There is also no live config at all: `ls user_data/*.json` returns only config.dry.json, yet docs/RUNBOOK.md:49 instructs the operator to put Binance keys in `.env` because "user_data/config.live.json reads env" — that file does not exist. Finally the test is a config-key assertion, not a behavioural one; it would stay green if dry_run were flipped or the live config placed stops locally. Closing the gap: add user_data/config.live.json (dry_run false, env-sourced keys, stoploss_on_exchange true), point a prod override/profile at it, and add tests asserting the live config's dry_run is false while stoploss_on_exchange is true and that the key set matches the dry config. Actual exchange-side placement remains unverifiable from CI and belongs on the go-live checklist alongside R16.

## Chosen approach

Design A (3 slices: live config → honest pure-function status → opt-in prod override), with Design B's mechanism corrections and allowed-divergence parity grafted in, and B's slice 4 (trade-row evidence) cut.

## Rationale

Both designs agree on the shape of the fix; the difference is scope discipline and one factual correction. A is three slices, each independently shippable, each fully testable with Binance returning 451, and its slice 1 lands value on day one by creating the file docs/RUNBOOK.md:49 already tells the operator to configure. B adds a fourth slice that reports on trades that do not and cannot exist (freqtrade is down, dry-run has produced no live positions): it would ship permanently "unproven" and is exactly the manufactured, reporting-on-nothing work to cut. B's real contribution is a correctness catch that sinks A as written: freqtrade does not interpolate ${VAR} inside config JSON, so A's "exchange.key is ${BINANCE_API_KEY}" test would enshrine a config that starts live with a literal "${BINANCE_API_KEY}" string as the API key. The working mechanism is freqtrade's FREQTRADE__EXCHANGE__KEY / FREQTRADE__EXCHANGE__SECRET env overrides, which is also what docker-compose.prod.yml:107-111 already uses for FREQTRADE__TELEGRAM__* and FREQTRADE__API_SERVER__*. So config.live.json keeps key/secret as empty strings (no secret can ever be committed) and the compose override supplies them with the :?set in .env required form, fail-closed on a missing key. Also grafted from B: a named ALLOWED_DIVERGENCE set for the parity test (dry_run_wallet and bot_name legitimately differ) so the test fails loudly on unlisted drift rather than being weakened later, and the explicit replacement of the existing config-key assertion at /Users/isupercoder/Code/github/ai-forecasting/tests/test_ensemble_strategy.py:278 with a behavioural call, so flipping dry_run turns a test red. Ordering deviates from A: the honest status function ships before the compose override, so the health surface is already telling the truth about local-only stops before anything makes real trading one flag away. Slice 3 is the paranoid one and lands last. The status function is a pure function over a parsed dict with the caller owning the file read, returning a dict with a status string, matching /Users/isupercoder/Code/github/ai-forecasting/app/services/market_data_status.py and backup_status.py exactly. No new services, containers or dependencies: a JSON file, a compose override file, one module.

## Grafted, and explicitly rejected

- From Design B: freqtrade does not substitute ${VAR} inside config JSON. Credentials must come from FREQTRADE__EXCHANGE__KEY / FREQTRADE__EXCHANGE__SECRET env overrides (the mechanism docker-compose.prod.yml:107-111 already uses for telegram and api_server), and config.live.json must keep key/secret as empty strings. This replaces Design A's ${VAR}-reference test, which would have shipped a config whose API key is the literal string ${BINANCE_API_KEY}.
- From Design B: the key-parity test uses an explicit named ALLOWED_DIVERGENCE set (dry_run, dry_run_wallet, bot_name) instead of a bare sorted-keys equality, so legitimate divergence is documented and any unlisted new key fails loudly.
- From Design B: explicitly replace the existing config-key assertion at tests/test_ensemble_strategy.py:278-279 with a call to the new status function, so the weak test is deleted rather than left alongside the strong one.
- From Design B: /health/detailed must surface local_only explicitly rather than folding it into healthy, and the status function must fail closed (disabled) on a malformed or missing order_types block.
- From Design B (naming): status values 'placed_on_exchange' is misleading since placement is never observed; use 'preconditions_met' instead. Everything else about B's three-state model is kept.
- Cut from Design B: slice 4 (exchange_stop_evidence over freqtrade's sqlite trade rows). There are zero live trades and freqtrade is down, so it would ship permanently 'unproven' and report on work that does not exist. Its intent is preserved as the go-live checklist item in slice 3.

## Acceptance criteria

- [ ] user_data/config.live.json exists with dry_run false and order_types.stoploss_on_exchange true, so freqtrade's precondition at freqtrade/strategy/interface.py:1644-1646 is satisfied when it is used
- [ ] No API key or secret is ever committed: exchange.key and exchange.secret in config.live.json are empty strings, and credentials reach freqtrade only through FREQTRADE__EXCHANGE__KEY / FREQTRADE__EXCHANGE__SECRET env overrides
- [ ] docker-compose.prod.yml still runs config.dry.json as its default command; going live requires an explicit second -f override file
- [ ] The live override refuses to start without exchange keys (${VAR:?set in .env} form), i.e. fails closed rather than starting unauthenticated
- [ ] Risk parameters (max_open_trades, stake_currency, stake_amount, tradable_balance_ratio, timeframe, pair_whitelist, order_types) are identical between the dry and live configs, enforced by a test that fails on any unlisted key divergence
- [ ] Nothing in the codebase or /health/detailed reports exchange-side stop placement as verified or healthy; the strongest claim available without a live exchange is 'preconditions met, placement unobserved'
- [ ] With the dry config in use (today's prod reality), the status surface says local_only, not healthy
- [ ] The R10 test is behavioural: flipping dry_run to true in config.live.json, or stoploss_on_exchange to false in either config, turns a test red
- [ ] Every test added runs green in CI with no Binance access, no API keys and no running freqtrade
- [ ] docs/RUNBOOK.md no longer references a non-existent file, and carries a go-live checklist item next to R16 for confirming a real stop order exists on the exchange after the first live entry

## Delivery slices

### 1. Add user_data/config.live.json with parity and no-committed-credentials tests

Create /Users/isupercoder/Code/github/ai-forecasting/user_data/config.live.json: a copy of config.dry.json with dry_run set to false, dry_run_wallet removed, bot_name changed to "ensemble-signal-live", and exchange.key / exchange.secret left as empty strings. order_types is byte-for-byte the same as the dry config (stoploss "market", stoploss_on_exchange true, stoploss_on_exchange_interval 60), as are all risk parameters. Credentials are NOT written into this file and NOT written as ${VAR} placeholders: freqtrade does not interpolate ${VAR} inside config JSON, so a placeholder would be used verbatim as the API key. They arrive at runtime via FREQTRADE__EXCHANGE__KEY / FREQTRADE__EXCHANGE__SECRET env overrides, wired in slice 3. Nothing runs this file yet, so this slice changes no running behaviour; it only removes the documented-but-missing file. Update /Users/isupercoder/Code/github/ai-forecasting/docs/RUNBOOK.md:49 so its wording matches the actual env-override mechanism instead of claiming the config "reads env". Fully testable offline: it is a JSON file plus assertions, no exchange, no keys, no freqtrade process.

**Acceptance**

- [ ] user_data/config.live.json exists, is valid JSON once comments are stripped, and is committed
- [ ] dry_run is false and stoploss_on_exchange is true in the live config
- [ ] exchange.key and exchange.secret are empty strings; no ${VAR} placeholder and no real credential is present anywhere in the file
- [ ] order_types and all listed risk parameters are identical to config.dry.json
- [ ] The key-set parity test fails if anyone adds a key to one config and not the other, unless it is named in ALLOWED_DIVERGENCE
- [ ] docs/RUNBOOK.md:49 describes the FREQTRADE__EXCHANGE__* env-override mechanism and no longer points at behaviour that does not exist
- [ ] No compose file, no running service and no existing test changes behaviour in this slice
- [ ] All new tests pass with no Binance access and no API keys

**Tests first**

- Create /Users/isupercoder/Code/github/ai-forecasting/tests/test_freqtrade_config.py with a module-level helper load_ft_config(path) that strips // comments before json.loads (both configs carry comments), and dry_config / live_config fixtures.
- test_live_config_exists: load_ft_config('user_data/config.live.json') succeeds. Must fail first with FileNotFoundError, before the file is written.
- test_live_config_dry_run_is_false: live_config['dry_run'] is False (identity check, not truthiness).
- test_live_config_places_stops_on_exchange: live_config['order_types']['stoploss_on_exchange'] is True, ['stoploss'] == 'market', ['stoploss_on_exchange_interval'] == 60.
- test_live_config_order_types_match_dry: live_config['order_types'] == dry_config['order_types'] exactly.
- test_live_config_risk_params_match_dry: max_open_trades, stake_currency, stake_amount, tradable_balance_ratio, timeframe, trading_mode and exchange['pair_whitelist'] are equal in both configs.
- test_live_config_has_no_committed_credentials: live_config['exchange']['key'] == '' and ['secret'] == '', and no value anywhere in the raw file text matches a plausible API-key pattern (>=20 chars of [A-Za-z0-9]). Guards against both a real key and a useless ${VAR} literal.
- test_configs_agree_on_keys: the recursive key-set symmetric difference between dry_config and live_config equals a module-level ALLOWED_DIVERGENCE = {'dry_run_wallet'} (dry_run and bot_name exist in both, only their values differ). A new unlisted key in either file fails the test.

### 2. Replace the config-key assertion with a pure exchange_stop_status() function and surface it honestly

Add /Users/isupercoder/Code/github/ai-forecasting/app/services/exchange_stop_status.py exposing exchange_stop_status(config: dict) -> dict, a pure function over an already-parsed freqtrade config with the caller owning the file read, returning {'status', 'stoploss_on_exchange', 'dry_run', 'message'} in the same shape as market_data_status(). It encodes freqtrade's own precondition from freqtrade/strategy/interface.py:1644-1646 (an exchange stop is placed only when stoploss_on_exchange is true AND dry_run is false). Statuses: 'preconditions_met' (flag on, dry_run off; actual placement still unobserved and the message must say so), 'local_only' (flag on but dry_run on, i.e. today's prod reality: the stop is evaluated in-process and dies with the bot), 'disabled' (flag off, or order_types missing/malformed). Deliberately no 'healthy' or 'verified' value exists, because exchange-side placement cannot be observed without a live exchange. Module-level DEGRADED_STATUSES constant owned here as in backup_status.py. Delete the assertion at tests/test_ensemble_strategy.py:278-279 and replace it with a call to this function. Wire it into /health/detailed alongside market_data_status, reading the config path the caller supplies from env (default user_data/config.dry.json), and never let 'local_only' roll up as healthy. Fully testable offline: dict in, dict out.

**Acceptance**

- [ ] app/services/exchange_stop_status.py contains one pure function plus module constants; it performs no file I/O, no DB access and no network calls
- [ ] The three statuses are exactly 'preconditions_met', 'local_only', 'disabled'; no status implies observed or verified exchange-side placement
- [ ] A malformed or empty config returns 'disabled', never an optimistic result
- [ ] The weak assertion at tests/test_ensemble_strategy.py:278-279 is deleted, not left in place beside the new test
- [ ] Setting dry_run true in config.live.json, or stoploss_on_exchange false in either config, turns at least one test red
- [ ] /health/detailed reports the exchange-stop component and shows local_only for the currently-running dry config, and local_only does not roll up into an overall healthy claim
- [ ] No new dependency, service or container is introduced
- [ ] All tests pass with freqtrade down and Binance returning 451

**Tests first**

- Create /Users/isupercoder/Code/github/ai-forecasting/tests/test_exchange_stop_status.py; the import of app.services.exchange_stop_status must fail first.
- test_flag_on_and_live_is_preconditions_met: {'dry_run': False, 'order_types': {'stoploss_on_exchange': True}} -> status 'preconditions_met'.
- test_flag_on_but_dry_run_is_local_only: {'dry_run': True, 'order_types': {'stoploss_on_exchange': True}} -> status 'local_only'. This is the exact regression the old key assertion missed.
- test_flag_off_is_disabled: stoploss_on_exchange False yields 'disabled' for both dry_run True and False.
- test_missing_order_types_is_disabled_not_crash: {} and {'dry_run': False} both return 'disabled' with no exception. Fail closed, never an optimistic default.
- test_no_status_claims_verified: 'preconditions_met' is the strongest status the module can return; assert 'healthy' and 'verified' are absent from the set of possible statuses and that the message for 'preconditions_met' states placement is unobserved.
- In tests/test_freqtrade_config.py: test_dry_config_reports_local_only and test_live_config_reports_preconditions_met, feeding the two real files through the function.
- In tests/test_ensemble_strategy.py: replace test_stoploss_on_exchange (currently lines 278-279) with an assertion that exchange_stop_status(config)['status'] == 'local_only' for the dry config, so a dry_run flip is caught behaviourally.
- In /Users/isupercoder/Code/github/ai-forecasting/tests/test_endpoints_health.py: test_detailed_reports_local_only_when_config_is_dry - /health/detailed exposes the exchange-stop component and does not report it as healthy while dry_run is on.

### 3. Opt-in live compose override, with prod staying dry by default

Add /Users/isupercoder/Code/github/ai-forecasting/docker-compose.live.yml, an override that changes only the freqtrade service: command becomes 'trade --config /freqtrade/user_data/config.live.json --strategy EnsembleSignalStrategy', and the environment gains FREQTRADE__EXCHANGE__KEY=${BINANCE_API_KEY:?set in .env} and FREQTRADE__EXCHANGE__SECRET=${BINANCE_API_SECRET:?set in .env}, mirroring the existing FREQTRADE_API_USERNAME pattern at docker-compose.prod.yml:110 so a keyless start fails closed. docker-compose.prod.yml is not modified: an ordinary deploy still runs config.dry.json, which matters because Binance geo-blocks this VPS with HTTP 451 and klines are stale since 2026-07-31, so a live bot would trade on dead data. Going live becomes an explicit 'docker compose -f docker-compose.prod.yml -f docker-compose.live.yml up -d freqtrade'. Add a go-live checklist entry to docs/RUNBOOK.md next to R16: (a) confirm market_data_status reports healthy first, (b) bring up the live override, (c) after the first live entry confirm a real stop order appears in Binance open orders and that freqtrade's REST /status shows a non-null stop_loss_order_id, and only then record R10 as observed. The checklist must state plainly that step (c) cannot be executed from this VPS while Binance returns 451, and that until it is done R10 remains configured-but-unobserved. Testable offline by parsing YAML; no container is started.

**Acceptance**

- [ ] docker-compose.live.yml exists and overrides only the freqtrade service's command and environment
- [ ] docker-compose.prod.yml is unchanged and a plain prod deploy still starts freqtrade in dry-run on config.dry.json
- [ ] Bringing up the live override without BINANCE_API_KEY / BINANCE_API_SECRET in .env fails at startup rather than starting unauthenticated
- [ ] The env var names in the override match what freqtrade expects (FREQTRADE__EXCHANGE__KEY / FREQTRADE__EXCHANGE__SECRET), the same override mechanism already used for telegram and api_server
- [ ] docs/RUNBOOK.md contains a go-live checklist beside R16 that requires market data to be healthy first and requires observing an actual stop order on the exchange, and states that this cannot be done while the VPS is geo-blocked
- [ ] No claim anywhere states that R10 is verified; the strongest recorded state remains configured-but-unobserved
- [ ] All tests pass by parsing files only, with no daemon, no keys and no exchange access

**Tests first**

- Create /Users/isupercoder/Code/github/ai-forecasting/tests/test_compose_live_override.py. Use yaml.safe_load only if PyYAML is already installed (it is a transitive dep of the existing stack); otherwise assert on raw file text rather than adding a dependency. First test asserts docker-compose.live.yml exists and fails before it is written.
- test_prod_freqtrade_still_runs_dry_config: docker-compose.prod.yml's freqtrade command references config.dry.json and does not reference config.live.json. This is the guard against silently flipping the default stack live.
- test_live_override_uses_live_config: the override's freqtrade command references config.live.json and names the same strategy, EnsembleSignalStrategy.
- test_live_override_requires_exchange_keys: FREQTRADE__EXCHANGE__KEY and FREQTRADE__EXCHANGE__SECRET are present in the override's freqtrade environment and both use the ${VAR:?...} required form, so a keyless live start fails closed.
- test_live_override_touches_only_freqtrade: the override defines no service other than freqtrade, so it cannot alter postgres, api, ingestor or dashboard.
- test_live_override_defines_no_new_service_or_volume: assert the override adds no top-level volumes and no new container.
- test_runbook_documents_live_override: docs/RUNBOOK.md contains the two-file 'docker compose -f docker-compose.prod.yml -f docker-compose.live.yml' invocation and a go-live checklist line requiring observation of a real stop order before R10 is marked observed.
