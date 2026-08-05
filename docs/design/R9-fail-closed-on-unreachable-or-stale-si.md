# R9 — Fail-closed on unreachable or stale signal: no new entries, existing positions managed to exit

Status: designed, not yet implemented. Design council of two independent
designs judged head to head.

## Gap being closed

Two gaps. (1) The second half of R9 — "manages existing positions to exit" — is not implemented. user_data/strategies/EnsembleSignalStrategy.py:186-194 only emits exit_long when a signal came back non-None with direction "flat" and confidence >= 0.60; when the API is unreachable or the signal is stale, the strategy emits nothing and holds. custom_exit (:203-215) checks only the 5-day max hold, so during a signal-API outage an open position is held for up to 5 days with no signal-driven exit, protected only by the -5% stop and the trailing stop (which, per R10 below, are currently local-only). Fix is small and self-contained: a custom_exit branch that exits (or flags for exit) after N consecutive stale/None fetches, plus a test in tests/test_ensemble_strategy.py::TestExit. (2) Semantic drift worth a decision, not necessarily a code change: R8 defines the evaluation cycle as the 1-hour candle, but STALE_AFTER is derived from the 4h signal interval (app/services/signal_service.py:9-10, :30-31), giving an effective 12-hour freshness window from candle open — pinned deliberately in tests/test_signal_staleness.py:30,37-43. So the bot will open a position on a signal up to 12 hours old, not 2 hours. That is defensible against the 4h horizon but is not what R9's wording says; either the PRD or the constant should be reconciled.

## Chosen approach

Design B (outage clock), with Design A's refactor-first ordering grafted in and B's cold-start seed corrected

## Rationale

Both designs implement the same fail-closed rule; the difference is how the outage is measured. B measures it in time (last_good_signal_at vs now vs grace), A measures it in consecutive bad fetches. B wins on four of the five criteria.

Fit with existing patterns: /Users/isupercoder/Code/github/ai-forecasting/app/services/signal_service.py already expresses freshness in time (STALE_AFTER = 2 * INTERVAL_DELTA), and decision.evaluate_entry already treats staleness as a time-derived boolean. A time-denominated grace is the same unit as the rest of the system; a fetch counter introduces a second, incompatible unit ("3 candles") that only means anything if you know the call cadence.

Fail-safety and testability: A's counter is incremented in populate_exit_trend and read in custom_exit, so it is silently wrong if freqtrade ever calls custom_exit without a preceding populate_exit_trend for that pair, or calls populate_exit_trend more than once per candle (backtest/dry-run ordering). A names this risk itself and proposes a test to discover whether the ordering holds — that is an unresolved dependency on freqtrade internals we cannot observe in production right now (Binance is 451-blocked, freqtrade is down). B's clock degrades gracefully under either ordering: extra calls are idempotent, missed calls only delay the exit, never invert the decision. That matters more than usual precisely because we cannot verify against a running bot.

Operational cost: identical (no new services, deps, or containers in either).

Speed to value: A's slice 1 (collapse the duplicated exit rule onto decision.evaluate_exit) is strictly better ordering than B's, which buries the same refactor inside the wiring slice. Grafted as slice 1: it ships on its own, has an existing regression net in tests/test_ensemble_strategy.py::TestExit, and gives the outage branch exactly one home before it is written.

One correction to B, because its stated cold-start behaviour is a live hazard: B seeds the clock from trade.open_date_utc when no last-good signal has been recorded in this process. That means a freqtrade restart with a perfectly healthy signal API immediately liquidates any position older than the grace period, since the clock start is backdated to trade open. Fail-closed must not mean "exit on a restart". The seed is therefore the later of trade.open_date_utc and the strategy's own start time, recorded once in __init__. Consequence: after a restart the bot gets one full grace period to prove the API is reachable, and if it is not, the position still exits — the fail-closed property is preserved, the false liquidation is not. B's other risks (coordinated exits across all open positions during an API outage; the clock only advances while freqtrade itself is running) are real and are stated in the slices rather than engineered away, because they are inherent to R9's requirement.

Design A's slice 3 and B's slice 3 are the same freshness-semantics decision. Kept as the final slice, in A's shape (keep the 12-hour constant, amend the PRD), because narrowing STALE_AFTER to the 1h evaluation cycle would block nearly every entry against a 4h signal cadence — the PRD wording is what is wrong, not the constant. Both designs' proposed docs-lint tests are cut; a doc edit is reviewed, not asserted.

Also cut: A's separate pure-function slice and B's separate wiring slice are merged. A pure function with no caller is dead code for a release cycle, and these issues become GitHub issues that should each land a working behaviour change.

All three slices are fully exercisable offline against fakes. None requires live Binance, live keys, or a running freqtrade. Honest limit to state on the issue when it closes: R9 will be unit-proven and unexercised in production, because klines have been stale since 2026-07-31 and the ingestor is down.

## Grafted, and explicitly rejected

- From Design A: refactor-first ordering — collapsing the duplicated exit rule onto decision.evaluate_exit is promoted to its own slice 1, ahead of any new behaviour, instead of being bundled into the wiring slice as Design B had it. It ships alone, has an existing regression net, and guarantees the outage branch has exactly one home.
- From Design A: the structured hold-reason log in populate_exit_trend, mirroring how _entry_allowed already logs its skip reason.
- From Design A: adding "signal_outage" to the EXIT_REASONS frozenset so the reason vocabulary stays closed and greppable (Design B added the reason string without closing the vocabulary).
- From Design A: the absent-stale-key case gets its own explicit test, matching the fail-closed convention in decision.evaluate_entry where a missing stale key means stale.
- From Design A: the recommendation to keep STALE_AFTER and amend the PRD rather than narrowing the constant, with the reason stated (a window narrower than one signal interval would block nearly every entry).
- From Design A: the explicit statement that the outage grace must be large enough that a single failed fetch cannot liquidate the book — expressed here in time (3 hours) rather than in fetch counts.
- From Design A: the honesty constraint — R9 must be reported as unit-proven and unexercised in production while Binance is 451-blocked.
- Correction to Design B, not present in either: the cold-start clock is seeded from max(trade.open_date_utc, process start time), not trade.open_date_utc alone. B's seed would liquidate any position older than the grace on every restart, even with a healthy API. The corrected seed keeps fail-closed while removing the false liquidation, and is pinned by test_cold_start_does_not_exit_a_healthy_restart.
- Cut from both designs: the separate pure-function slice (B) and the separate wiring slice (A/B) are merged into one shippable behaviour change, because a pure function with no caller is dead code for a release cycle.
- Cut from both designs: any docs-linting test for the PRD wording. The doc edit is verified by review and the issue says so.

## Acceptance criteria

- [ ] A signal-API outage lasting longer than the configured grace closes open long positions with exit_reason "signal_outage", instead of holding them until the 5-day max hold.
- [ ] Both failure modes count as an outage: get_signal returning None, and get_signal returning a signal whose stale flag is true or absent (absent means stale, matching the entry-side convention in decision.evaluate_entry).
- [ ] A single fresh, non-stale signal resets the outage clock and restores normal hold behaviour.
- [ ] A freqtrade restart while the signal API is healthy never causes an exit: the cold-start clock is seeded from the later of trade.open_date_utc and the strategy's own start time, so the bot always gets a full grace period to prove reachability.
- [ ] A freqtrade restart while the signal API is down still exits, one grace period after the restart. Fail-closed survives a restart.
- [ ] The existing max_hold_5d exit still fires for old trades when the signal is healthy, and is not shadowed by the new branch.
- [ ] The outage decision is a pure function over scalars in user_data/strategies/decision.py that reads no clock and performs no I/O; the strategy owns the state and passes now in.
- [ ] custom_exit never raises: any exception in the outage path is caught and logged, leaving exits to stop-loss, trailing stop and max hold, matching the existing fail-closed posture in populate_entry_trend.
- [ ] The exit rule (confident flat) exists in exactly one place, decision.evaluate_exit, with no inline duplicate in the strategy.
- [ ] "signal_outage" is added to decision.EXIT_REASONS so the reason vocabulary stays closed and greppable.
- [ ] The freshness window is stated in hours in the PRD and in the constant's docstring, and the two agree with each other and with the pinning test.
- [ ] Every test added by these slices passes with no network access, no exchange keys, and no freqtrade process running. No new services, containers, or dependencies are introduced.
- [ ] Closing R9 is reported as unit-proven only. It must not be described as verified in production while Binance returns HTTP 451 and klines remain stale since 2026-07-31.

## Delivery slices

### 1. Slice 1: one exit brain — route populate_exit_trend through decision.evaluate_exit

user_data/strategies/EnsembleSignalStrategy.py currently re-implements inline, in populate_exit_trend, the exact rule that already lives in user_data/strategies/decision.py::evaluate_exit (signal is not None and direction == "flat" and confidence is numeric and confidence >= exit_confidence_threshold). Replace the inline condition with result = evaluate_exit(signal, self.exit_confidence_threshold) and set exit_long = 1 on the last row when result.decision == "exited". Log result.reason on the hold path the same way _entry_allowed logs its skip reason, so a non-exit is a structured record and not silence. Leave the surrounding try/except and its exit_long = 0 fallback exactly as they are.

No behaviour change is intended beyond the added log line. This slice exists so that slice 2 has exactly one place to add the outage branch, and so the two copies of the rule cannot drift. It is a refactor with a pre-existing regression net, not new capability — state that plainly on the issue.

Fully testable offline: the signal client is faked in tests/test_ensemble_strategy.py. No Binance, no keys, no freqtrade runtime.

**Acceptance**

- [ ] populate_exit_trend contains no inline direction/confidence comparison; it calls decision.evaluate_exit and branches on result.decision.
- [ ] Every pre-existing tests/test_ensemble_strategy.py::TestExit case passes with its assertions unmodified.
- [ ] A non-exit emits one INFO log carrying the pair and the machine-readable reason string.
- [ ] The try/except fail-closed fallback (exit_long = 0, exception logged, never raised) is byte-for-byte unchanged in behaviour.
- [ ] No change to decision.py in this slice.

**Tests first**

- FIRST, before any edit: run the existing tests/test_ensemble_strategy.py::TestExit suite and confirm it is green and that it covers confident-flat-exits, low-confidence-flat-holds, non-flat-holds and None-signal-holds. These are the regression net; if a case is missing, add it and watch it pass BEFORE refactoring, so the net is real.
- NEW tests/test_ensemble_strategy.py::TestExit::test_exit_delegates_to_evaluate_exit — monkeypatch the evaluate_exit symbol as imported by EnsembleSignalStrategy to return ExitDecision("exited", "exit_signal", {}), feed a signal with direction="long" (which the inline rule would never exit on), assert exit_long == 1 on the last row. Must fail first: the inline condition ignores the patched function.
- NEW tests/test_ensemble_strategy.py::TestExit::test_hold_reason_is_logged — caplog at INFO, feed a low-confidence flat, assert the pair and reason="hold" appear in the record. Must fail first: the inline path logs nothing on hold.
- All pre-existing TestExit cases must still pass unchanged after the edit, with no assertion edits. Any change needed to an existing assertion means the refactor was not behaviour-preserving and the slice is wrong.

### 2. Slice 2: exit on a sustained signal outage — the missing half of R9

Today, when the signal API is unreachable or every signal comes back stale, the strategy emits nothing and holds. custom_exit checks only the 5-day max hold, so an open position can sit for up to five days during an outage, protected only by the -5% stop and the trailing stop. This slice closes that.

Pure function, in user_data/strategies/decision.py, matching the app/services/market_data_status.py convention (pure over scalars, caller owns the query and the clock):

  evaluate_signal_outage(clock_start: datetime, now: datetime, grace: timedelta) -> ExitDecision

Returns ExitDecision("exited", "signal_outage", context) when now - clock_start > grace, otherwise ExitDecision("held", "signal_ok", context). Strictly greater than, so exactly-at-grace holds. If now < clock_start (clock skew, or a trade opened in the future by a bad fixture) it holds — skew must never liquidate. clock_start is non-optional, so the "we have never seen a good signal" case is resolved by the caller and the function stays total. context carries outage_seconds and grace_seconds so the log line alone proves the decision after the fact. Add "signal_outage" to the EXIT_REASONS frozenset.

Wiring, in user_data/strategies/EnsembleSignalStrategy.py:
- self._started_at = datetime.now(timezone.utc), set once in __init__.
- self._last_good_signal_at: Dict[str, datetime], updated in exactly one private helper called from both _entry_allowed and populate_exit_trend, set to the candle time whenever get_signal returns a non-None signal with a falsey stale flag. A None signal, or one with stale true or absent, leaves the clock untouched (absent means stale — same fail-closed convention as decision.evaluate_entry).
- signal_outage_grace: a class attribute, timedelta(hours=3), i.e. three 1-hour evaluation cycles. One greppable number, with a docstring saying why: long enough that a single failed fetch cannot liquidate the book, short enough to be well inside the 12-hour staleness window, because a persistently unreachable API is a stronger signal than an old-but-valid forecast.
- custom_exit consults evaluate_signal_outage BEFORE the max-hold check, with clock_start = self._last_good_signal_at.get(pair) or max(trade.open_date_utc, self._started_at), and returns "signal_outage" when it says exited. freqtrade records that string in trade.exit_reason, which is the durable proof.
- The whole outage branch is wrapped so it can never raise; on exception, log and fall through to the max-hold check.

The cold-start seed is the load-bearing detail. Seeding from trade.open_date_utc alone would liquidate any position older than the grace the moment the process restarts, even with a perfectly healthy API. Taking the later of trade open and process start means a restart always buys one full grace period to prove reachability, and if the API really is down, the exit still fires one grace period later. Fail-closed, without a restart-triggered false liquidation.

Honest limits, to be written into the docstring and the issue, not hidden: (a) the clock only advances while freqtrade itself is running — if the whole bot is down, nothing exits, and this slice does not and cannot fix that; (b) during a real outage this exits every open position at roughly the same moment, which is a coordinated liquidation and is the deliberate trade-off R9 asks for, which is why it gets its own exit_reason rather than reusing max_hold_5d.

Entirely offline-testable: pure function plus a stub signal client and a fake trade object. No Binance, no keys, no running freqtrade.

**Acceptance**

- [ ] evaluate_signal_outage lives in decision.py, imports stdlib only, reads no clock, performs no I/O, and is total for every input including now < clock_start.
- [ ] "signal_outage" is a member of decision.EXIT_REASONS.
- [ ] custom_exit returns "signal_outage" once the outage exceeds signal_outage_grace, and freqtrade records it in trade.exit_reason.
- [ ] None signals, stale=True signals, and signals with the stale key absent all count as an outage; only a non-None signal with a falsey stale flag resets the clock.
- [ ] The clock is reset from a single helper used by both the entry and exit paths — there is no second place that writes _last_good_signal_at.
- [ ] A restart with a healthy API never produces an exit, regardless of how old the open trade is (the cold-start seed test proves it).
- [ ] A restart with a dead API produces an exit one grace period after process start.
- [ ] The grace is one named class attribute with a docstring stating the number in hours and why it is shorter than the staleness window.
- [ ] custom_exit cannot raise; an exception in the outage path is logged and falls through to the max-hold check.
- [ ] max_hold_5d behaviour for old trades with healthy signals is unchanged.
- [ ] Every test runs green with no network, no exchange keys and no freqtrade process. No new dependency, service or container.
- [ ] The docstring states, in plain words, that this covers signal-API outage while the bot is running and does not cover the bot itself being down.

**Tests first**

- NEW tests/test_decision_evaluation.py::TestSignalOutage::test_holds_when_within_grace — clock_start 1h ago, grace 3h, decision == "held".
- NEW tests/test_decision_evaluation.py::TestSignalOutage::test_exits_when_outage_exceeds_grace — clock_start 4h ago, grace 3h, decision == "exited" and reason == "signal_outage".
- NEW tests/test_decision_evaluation.py::TestSignalOutage::test_exactly_at_grace_holds — pins the > versus >= choice explicitly.
- NEW tests/test_decision_evaluation.py::TestSignalOutage::test_clock_skew_does_not_exit — now earlier than clock_start returns "held".
- NEW tests/test_decision_evaluation.py::TestSignalOutage::test_context_reports_outage_seconds_and_grace_seconds — the returned context is sufficient to reconstruct the decision from a log line.
- NEW tests/test_decision_evaluation.py::TestSignalOutage::test_signal_outage_is_a_known_exit_reason — asserts "signal_outage" in decision.EXIT_REASONS.
- NEW tests/test_ensemble_strategy.py::TestExit::test_custom_exit_returns_signal_outage_after_grace_of_none_signals — stub client returns None; drive the strategy past the grace; custom_exit returns "signal_outage". Must fail first: custom_exit only knows max_hold.
- NEW tests/test_ensemble_strategy.py::TestExit::test_custom_exit_returns_signal_outage_after_grace_of_stale_signals — same, with signals present but stale=True; plus a case where the stale key is absent entirely, which must also count as an outage.
- NEW tests/test_ensemble_strategy.py::TestExit::test_custom_exit_holds_while_within_grace — outage shorter than the grace returns None.
- NEW tests/test_ensemble_strategy.py::TestExit::test_fresh_signal_resets_the_outage_clock — bad fetches, then one fresh non-stale signal, then custom_exit returns None.
- NEW tests/test_ensemble_strategy.py::TestExit::test_cold_start_does_not_exit_a_healthy_restart — no last-good record, trade opened 8h ago, process just started, signal healthy: custom_exit returns None. This is the test that pins the corrected seed; it fails against a naive trade.open_date_utc seed.
- NEW tests/test_ensemble_strategy.py::TestExit::test_cold_start_still_exits_after_grace_from_process_start — no last-good record, process started more than the grace ago, client dead: returns "signal_outage".
- NEW tests/test_ensemble_strategy.py::TestExit::test_outage_clock_is_per_pair — an outage on BTC/USDT does not exit ETH/USDT, whose signals are fresh.
- NEW tests/test_ensemble_strategy.py::TestExit::test_max_hold_still_fires_when_signal_is_fresh — 6-day-old trade, healthy signal, returns "max_hold_5d". Guards against the new branch shadowing the old one.
- NEW tests/test_ensemble_strategy.py::TestExit::test_custom_exit_never_raises_when_client_throws — stub client raises; custom_exit returns None or "max_hold_5d", never propagates. Fail-closed parity with the entry path.

### 3. Slice 3: reconcile the freshness contract with what R9 claims

Decision slice. Little code, one real decision, no runtime behaviour change.

app/services/signal_service.py sets INTERVAL = "4h", INTERVAL_DELTA = 4 hours, STALE_AFTER = 2 * INTERVAL_DELTA, and comments it as "older than 2 evaluation cycles". But R8 defines the evaluation cycle as the 1-hour candle, so the comment and the code disagree: the actual window is 8 hours from candle close and up to roughly 12 hours from candle open. The bot will therefore open a position on a signal up to about 12 hours old, not 2 hours as R9's wording implies. tests/test_signal_staleness.py currently pins this as an incidental multiple rather than as an intended number.

Decision: keep the constant, fix the wording. Narrowing STALE_AFTER to the 1-hour evaluation cycle would block nearly every entry, because the model only produces a signal every 4 hours — the window has to be at least a signal interval wide to be usable at all. Twelve hours is defensible against a 4-hour forecast horizon; the PRD sentence is what is wrong.

Work: correct the comment on STALE_AFTER to say "2 signal intervals (8h from candle close, up to ~12h from candle open), matched to the 4h forecast horizon — NOT the 1h evaluation cycle"; amend docs/PRD-trading-bot.md R9 to state the window in hours rather than implying the candle cadence; restate tests/test_signal_staleness.py so it asserts the intended absolute window and its boundaries rather than restating the arithmetic. Add one line to the PRD recording the interaction with slice 2: the 3-hour outage grace is deliberately shorter than the 12-hour staleness window, because an unreachable API is a stronger signal than an old-but-valid forecast.

No test is written for the PRD text. A doc edit is reviewed, not asserted — do not invent a docs-linting test to make this slice look bigger. Backend job only; no Binance, no keys, no freqtrade.

**Acceptance**

- [ ] STALE_AFTER is numerically unchanged; no entry or exit behaviour changes anywhere.
- [ ] The comment on STALE_AFTER states the window in hours from candle close and from candle open, and explicitly says it is derived from the signal interval, not the 1h evaluation cycle.
- [ ] docs/PRD-trading-bot.md R9 states the freshness window in hours and no longer implies the evaluation cycle, and records why the outage grace is shorter than the staleness window.
- [ ] tests/test_signal_staleness.py asserts the intended window and both boundaries by name, not as a bare multiple.
- [ ] The existing entry tests pass with zero assertion edits.
- [ ] No docs-linting test is added; the issue says in one line that the doc change is verified by review.

**Tests first**

- EDIT tests/test_signal_staleness.py — rename the existing pinning case to test_signal_is_fresh_for_two_signal_intervals so the test name states the contract instead of leaving a magic assertion. The rename must fail collection first (old name gone) so the change is deliberate and visible in review.
- NEW tests/test_signal_staleness.py::test_signal_one_second_inside_the_window_is_fresh — explicit lower boundary.
- NEW tests/test_signal_staleness.py::test_signal_exactly_at_the_window_is_stale — explicit upper boundary, pins the comparison operator.
- NEW tests/test_signal_staleness.py::test_freshness_window_is_two_signal_intervals_not_two_evaluation_cycles — asserts STALE_AFTER equals 2 * INTERVAL_DELTA AND that this is 8 hours, so a future edit to INTERVAL breaks a test whose name explains why it broke.
- RE-RUN the tests/test_ensemble_strategy.py entry cases unchanged, to confirm no entry behaviour moved. Expect no edits; if any assertion needs changing, the slice has silently altered behaviour and must stop.
