# QuantPilot deployment guide

## Current status

- Vercel project: **`quantpilot`**.
- Production source: this repository root; `api/index.py` exports the FastAPI ASGI app and `vercel.json` routes API/documentation requests to it. FastAPI serves `public/` at `/`.
- OANDA practice environment variables, strict provider selection, Groq model selection, and temporary database configuration are present for production, preview, and development.
- **No deployment or public production URL exists yet.** Vercel rejected the first-deployment API request because the connector cannot supply the required `projectSettings` object or `skipAutoDetectionConfirmation=1` query option. This is a deployment-control limitation, not an application test failure.
- No live OANDA request has run. OANDA behavior is covered by mocked tests; live candles, quotes, account metadata, and deployed workflows remain to be verified after the first successful deployment.
- No Groq API key is configured. Deterministic agents work without it; the UI reports Groq as unavailable rather than generating substitute LLM output.

## Configured environment

The following names are configured in Vercel. Secret values are intentionally not recorded here.

| Variable | Configured behavior |
|---|---|
| `OANDA_API_KEY` | Sensitive practice credential |
| `OANDA_ACCOUNT_ID` | Practice account identifier |
| `OANDA_ENVIRONMENT` | `practice`; the application also forces practice in code |
| `DATA_PROVIDER` | `oanda` |
| `ALLOW_SYNTHETIC_FALLBACK` | `false`; provider failures remain explicit |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` |
| `DATABASE_URL` | Temporary SQLite under `/tmp` |
| `GROQ_API_KEY` | **Not configured** |

OANDA is used only for market data and read-only account metadata. There is no OANDA order adapter. All execution remains inside QuantPilot's simulated paper broker.

## Storage warning

**The current Vercel database is ephemeral.** SQLite files under `/tmp` can be removed when a serverless instance is replaced, and separate instances need not share state. Paper balances, orders, fills, research reports, traces, and journals can therefore disappear. This configuration is suitable only for a temporary demonstration and must not be described as production-persistent.

For durable deployment, provision a new isolated PostgreSQL/Supabase project, apply the application schema, and replace `DATABASE_URL` with its SQLAlchemy PostgreSQL connection string. Do not reuse or modify unrelated existing projects. The repeated new Supabase project request was blocked by the organization's free-project limit, so no Supabase schema has been created. The user chose to free a project slot before another creation attempt.

## Complete the first deployment

The Vercel CLI is not authenticated in the build environment. After authenticating a Vercel CLI session with access to the existing `quantpilot` project, deploy the complete repository root:

```bash
cd quantpilot
npx vercel link --project quantpilot
npx vercel --prod
```

The CLI/dashboard deployment path supports Vercel's first-deployment settings confirmation, which the API connector lacks. No source bundle, custom build script, Node frontend build, or manual file creation is required. The temporary custom build command used during connector troubleshooting has been cleared.

Alternatively, import this repository into the existing Vercel project through the dashboard and keep the settings above. Do not create a reduced static-only demo: the FastAPI backend is required.

## Post-deployment verification

Replace `$APP_URL` with the actual deployment URL, then verify:

```bash
curl -fsS "$APP_URL/health"
curl -fsS "$APP_URL/api/v1/market/integrations"
curl -fsS "$APP_URL/api/v1/market/candles/EUR_USD?timeframe=15m&rows=300"
curl -fsS "$APP_URL/api/v1/market/quote/EUR_USD"
curl -fsS "$APP_URL/api/v1/market/oanda/account"
```

Expected checks:

1. `/` loads all seven workspaces without browser JavaScript errors.
2. Integration status reports `paper_only: true`, OANDA `practice`, `MARKET_DATA_ONLY`, strict provider selection, and `EPHEMERAL_SQLITE` until PostgreSQL is configured.
3. Candles identify `oanda` as the source, contain completed bars, and include Python-calculated indicators.
4. Quotes include bid, ask, mid, spread, and a provider timestamp.
5. Account metadata is read-only and contains no credential.
6. Research returns only APPROVED, REJECTED, or NO_TRADE; provider/agent errors remain explicit.
7. Any order fill is recorded only in the internal paper account. No OANDA order endpoint exists in the source.
8. Groq remains unavailable until a key is configured; no fabricated LLM narrative appears.
9. Storage is presented as ephemeral until a durable PostgreSQL URL is installed.

## Local production-web validation

```bash
python run_api.py
# Open http://localhost:8000/
```

For an offline functional demonstration, use `DATA_PROVIDER=synthetic`. Synthetic data is prominently labelled. For strict OANDA local testing, supply practice credentials through the environment and set `DATA_PROVIDER=oanda` and `ALLOW_SYNTHETIC_FALLBACK=false`; never write real credentials into `.env.example`, documentation, screenshots, or committed source.

## Environment validation update

Vercel now explicitly configures `NEWS_PROVIDER=yfinance`, `PAPER_ONLY=true`, `TRADING_MODE=paper`, OANDA and LLM timeouts/retries, and the deterministic risk/safety thresholds. `GROQ_API_KEY` is intentionally unset for later manual configuration. The Yahoo forex-news normalization regression tests pass; a live Yahoo news request returned Yahoo's outage response and was explicitly classified unavailable.
