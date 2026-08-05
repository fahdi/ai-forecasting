# Delivery programme: finish the PRD

The objective, in the user's words: *"R5 and R13, create design docs, attack via
a council of agents, refine, write issues, acceptance criteria, start coding
TDD, then make releases every time. Repeat for all PRD items, not just these
two."*

This file is the durable record of that programme so it survives across
sessions. Update it as slices land.

## The working cycle

Every requirement goes through the same loop, and every slice ends in a release:

1. **Audit** the requirement against the code, not against the PRD or the
   comments. Cite `file:line`.
2. **Design council**: three independent designs under different lenses
   (simplest-thing, correctness-first, incremental-delivery), judged head to
   head, winner grafted with the best ideas from the runners-up.
3. **Design doc** in `docs/design/`, recording the rejected alternatives and why.
4. **Issues**, one per slice, each with behaviour, tests-to-write-first, and
   explicit acceptance criteria.
5. **TDD**: red first, and confirm it fails for the right reason. Where the
   change is a safety guard, verify by mutation rather than by going green.
6. **Ship**: full suite green, all three CI jobs green, deploy through
   `scripts/deploy_prod.sh` (which refuses commits CI did not pass), then
   `scripts/release.py` cuts the tagged release.

## Requirement status

Audited 2026-08-05 by five parallel agents reading the code. Four implemented,
thirteen partial, none entirely missing. "CI" is whether the behaviour is
covered by a test that actually runs in CI.

| ID | Status | Effort | CI | Title |
|----|--------|--------|----|-------|
| R1 | partial | medium | yes | Retrain the boosted ensemble (XGBoost/LightGBM/CatBoost) on crypto OHLCV |
| R2 | implemented | small | yes | Fixed v1 trading universe: BTC/ETH/SOL/BNB USDT, no long-tail coins |
| R3 | implemented | small | yes | GET /api/v1/signal/{pair} returning direction/confidence/horizon/model_v |
| R4 | partial | medium | **no** | Binance kline ingestion (REST backfill + websocket keep-current) into Po |
| R5 | partial | medium | **no** | Scheduled weekly retraining with walk-forward validation and promotion g |
| R6 | implemented | small | yes | Model-health metrics exposed: rolling directional accuracy, calibration  |
| R7 | partial | medium | **no** | Freqtrade hosts execution: order lifecycle, partial fills, reconnection, |
| R8 | partial | large | yes | EnsembleSignalStrategy: hourly signal fetch, confidence + trend + volati |
| R9 | partial | medium | yes | Fail-closed on unreachable or stale signal: no new entries, existing pos |
| R10 | partial | medium | **no** | Stop-losses placed on the exchange (stoploss-on-exchange) so positions s |
| R11 | partial | medium | **no** | Dashboard: open positions + live P&L, equity curve vs BTC buy-and-hold,  |
| R12 | partial | small | **no** | Telegram bot (Freqtrade native): status, daily/weekly P&L, trade notific |
| R13 | partial | medium | **no** | Audit log in PostgreSQL: every signal, every decision (entered/skipped + |
| R14 | partial | medium | yes | Alerting: heartbeat pages when the bot goes silent; alerts on circuit-br |
| R15 | implemented | small | yes | Runs on a small VPS under Docker Compose: intelligence API, Freqtrade, P |
| R16 | partial | medium | **no** | Binance API keys without withdrawal permission, IP-restricted to the VPS |
| R17 | partial | medium | yes | Automated daily backup of the database (signals, trades, audit log) |
Full evidence, gap analysis and effort notes per requirement are in the audit
output referenced from the design docs.

## Progress

| Release | Slice | Issue |
|---------|-------|-------|
| v1.0.0 | Baseline: the system as already deployed | - |
| v1.0.1 | Design docs for R5 and R13 | - |
| v1.1.0 | R5 S1: a promotion gate that is actually a comparison | #21 |
| v1.2.0 | R13 S1: guard evaluation returns structured data | #27 |
| v1.3.0 | R4 S1: kline coverage becomes a health component | #48 |

Open slices: #22-#26 (R5 S2-S6), #28-#33 (R13 S2-S7).

### Every requirement is now designed

All 17 audited. R2, R3, R6 and R15 are implemented and covered in CI, so they
need nothing. The other 13 have been through a design council, have a design
doc in `docs/design/`, and have slice issues with acceptance criteria.

| Requirement | Design doc | Slices | Shipped |
|---|---|---|---|
| R1 daily-bar model | `R1-*.md` | 4 | |
| R4 kline gap repair | `R4-kline-gap-repair.md` | 4 | S1 (v1.3.0) |
| R5 scheduled retraining | `R5-scheduled-retraining.md` | 6 | S1 (v1.1.0) |
| R7 freqtrade execution | `R7-*.md` | 4 | |
| R8 strategy guards | `R8-*.md` | 3 | |
| R9 fail-closed behaviour | `R9-*.md` | 3 | |
| R10 exchange-side stops | `R10-*.md` | 3 | |
| R11 dashboard | `R11-*.md` | 4 | |
| R12 Telegram | `R12-*.md` | 3 | |
| R13 decision audit log | `R13-decision-audit-log.md` | 7 | S1 (v1.2.0) |
| R14 alerting | `R14-*.md` | 3 | |
| R16 API key restrictions | `R16-*.md` | 3 | |
| R17 backup coverage | `R17-backup-coverage.md` | 3 | |

50 slice issues total, 3 shipped. Every remaining slice is designed to be
testable and valuable WITHOUT live Binance access, so the geo-block does not
block delivery.


**Suggested order.** R4 first: the ingestor outage left a permanent hole in the
klines table that nothing repairs, and every model slice downstream trains on
that data. Then R17 and R14 together, since a backup you are not told about
failing is the same as no backup. R11 and R12 last, as they are reporting
surfaces over work that has to exist first.

### Councils are cheap now

The first council (R5 + R13) cost ~917k subagent tokens. The second (R4 + R17)
cost ~325k for the same two-requirement output, by telling agents to read only
the named files, using two designs instead of three, and running the design
agents at low effort. Use the second shape.

### Next up: #22, R5 S2

`scripts/retrain.py`: one correct, auditable, unattended-safe retrain. Partial
work from an interrupted attempt (23 tests written, red phase confirmed, ledger
module started) was deliberately NOT committed, because it was incomplete and
half-finished tests are worse than none. Start it fresh from the issue.

## Two findings worth carrying forward

**The promotion gate was promoting on noise.** `registry.promote()` compared two
stored accuracy numbers from different walk-forward runs over different data
windows. Against the real live numbers it promotes a candidate at 0.5242 over an
incumbent at 0.5239, where one standard error is 0.0059. Fixed in v1.1.0, but
the same class of error (comparing numbers that are not comparable) is worth
looking for elsewhere.

**`scripts/train_ensemble.py` still measures one model and promotes another.**
It scores the ensemble with walk-forward folds, then promotes a model refit on
all the data. The promotion decision is not about the artifact being promoted.
This is the core of #22 and is still live.

## Blocked on decisions only the owners can make

Neither is a code problem, and both have everything ready on this side:

- **Binance geo-blocks the VPS with HTTP 451.** Market data has been stale since
  2026-07-31 and both `freqtrade` and `ingestor` are down. Needs a host in a
  permitted region. Until then several slices can be built but not exercised in
  production.
- **There is no alerting channel.** `HEALTHCHECKS_URL` is plumbed end to end
  through both compose files and the ingestor; it needs a URL in
  `/opt/ai-forecasting/.env`. `SENTRY_DSN` and the Telegram token are also empty.
  The dashboard now tells the truth, but only to someone who opens it.
