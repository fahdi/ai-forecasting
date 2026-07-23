# Operations Runbook — Trading Bot

Covers issues #12/#13 (PRD §4.3–§4.4, §7). Anything marked **MANUAL** needs a
human with credentials and cannot be automated from this repo.

## 1. VPS deployment (R15)

1. Provision a small VPS (2 vCPU / 4GB is plenty), install Docker + compose.
2. `git clone` the repo; `cp env.example .env` and fill real values
   (`POSTGRES_PASSWORD`, `HEALTHCHECKS_URL`, Telegram vars). No secrets in git.
3. `docker compose up -d` — brings up postgres, redis, api (signals + model
   health), ingestor (live candles + heartbeat), freqtrade (dry-run config).
4. Backfill + train once:
   `docker compose exec api python scripts/backfill_klines.py --all --interval 4h`
   then `--interval 1d`, then
   `docker compose exec api python scripts/train_ensemble.py`.
5. Dashboard: `cd frontend && npm ci && npm run build && npm run start`
   (or deploy to Vercel with `NEXT_PUBLIC_*` env set).

## 2. Binance API keys (R16) — **MANUAL**

Only needed from G2 onward (live). Dry-run/G1 needs no keys.

1. Create the API key in the Binance dashboard.
2. Permissions: **Enable Spot Trading ONLY. Disable withdrawals.** Leave
   futures/margin off.
3. Restrict the key to the VPS's IP address.
4. Put the key ONLY in `.env` on the VPS (`user_data/config.live.json` reads
   env); never in git, never in chat.
5. Verify with a read call before funding: `freqtrade balance`.

## 3. Backups (R17)

- `scripts/backup_db.sh` — pg_dump + gzip + 14-day rotation. Cron it daily.
- **Restore procedure (verified 2026-07-24 against a fresh database —
  20,452 kline rows round-tripped):**
  ```bash
  psql "$DATABASE_URL_PSQL" -c 'CREATE DATABASE restore_test'
  gunzip -c backups/ai_forecasting-<stamp>.sql.gz | \
    psql "postgresql://user:***@host:5432/restore_test"
  ```
- What's covered: klines, prediction_log (signal audit trail). Freqtrade's
  own trade DB lives in `user_data/tradesv3*.sqlite` — include that file in
  any off-VPS backup sync.

## 4. Audit trail (R13)

| What | Where |
|---|---|
| Every served signal (direction, confidence, model_version, price) | Postgres `prediction_log` (written by the signal endpoint) |
| Signal outcomes (realized vs predicted) | `prediction_log.realized`, resolved by `/api/v1/models/health` |
| Entry/skip decisions incl. blocking guard | Freqtrade log (strategy logs each fail-closed/guard-blocked decision) |
| Orders and fills | Freqtrade `tradesv3*.sqlite` + Telegram trade notifications |

## 5. Telegram control + kill switch (R12) — setup **MANUAL**, then automated

1. Create a bot via @BotFather → token into `.env` (`TELEGRAM_TOKEN`).
2. Get both stakeholders' chat ids (message the bot, then
   `https://api.telegram.org/bot<token>/getUpdates`); use a group chat that
   includes BOTH so either can halt the bot.
3. Set `TELEGRAM_ENABLED=true`; `docker compose up -d freqtrade`.
4. Commands: `/status`, `/profit`, `/stopbuy` (halt new entries),
   `/forceexit all` (flatten), `/stopbuy` + `/forceexit all` = full kill.
5. **Kill-switch drill (run once in dry-run before G1 sign-off):** send
   `/stopbuy`, confirm "no new entries" in logs; `/forceexit all`, confirm
   positions flat; document date + screenshot in docs/gates/. Last resort
   that works even if all infra is down: delete the API key at Binance.

## 6. Alerting (R14)

- **Heartbeat:** the ingestor pings `HEALTHCHECKS_URL` (healthchecks.io free
  tier) at most once/60s while consuming. Configure the check's grace period
  to 10 minutes → you get paged when the bot goes silent, covering the
  "silent > 2 cycles" PRD requirement with margin. Setup is **MANUAL**
  (create the check, paste the URL into `.env`).
- **Circuit breaker / drawdown kill trips:** Freqtrade protections log and
  (with Telegram enabled) notify when triggered.
- **Signal API failure:** surfaces three ways — strategy logs fail-closed
  no-entry lines, the dashboard SystemStatus dot goes red, and entries simply
  stop (fail-closed) rather than trading blind.

## 7. Gate status (PRD §8)

- G0 backtest: **NO-GO** as of 2026-07-24 — see docs/gates/G0-report.md.
  Model iteration required before any dry-run counts toward G1.
- G1 paper / G2 live / G3 scale: not started; each requires the prior gate's
  written pass plus stakeholder review per the PRD.
