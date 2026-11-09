# QuantPilot — complete Vercel setup

This guide deploys the **full FastAPI backend and seven-workspace web application** from `quantpilot-vercel.zip`.

> **Paper trading only.** OANDA is read-only practice market data. QuantPilot has no real-money broker or OANDA order adapter. Never put credentials in source, Git, screenshots, or this guide.

## 1. What you need

1. A Vercel account with permission to create deployments.
2. The supplied OANDA **practice/demo** access token and account ID.
3. For the CLI method: Node.js and npm. Use a current Node.js LTS release supported by the latest Vercel CLI.
4. Optional: a Groq API key. The application works deterministically without it.
5. Optional for durable storage: a new PostgreSQL database. Without it, the instructions below use temporary SQLite storage that can lose data.

No frontend build, Node package installation inside the project, Docker, or manually created source files is required.

## 2. Extract and inspect the ZIP

### macOS / Linux

```bash
unzip quantpilot-vercel.zip -d quantpilot-deploy
cd quantpilot-deploy/quantpilot
```

### Windows PowerShell

```powershell
Expand-Archive -Path .\quantpilot-vercel.zip -DestinationPath .\quantpilot-deploy
cd .\quantpilot-deploy\quantpilot
```

Confirm these files are at the directory root:

```text
api/index.py
api/main.py
public/index.html
config/risk_config.yaml
config/strategy_config.yaml
requirements.txt
requirements-dev.txt
vercel.json
VERCEL_SETUP.md
```

`requirements.txt` contains production web/API dependencies. `requirements-dev.txt` additionally contains Streamlit, Plotly, and Pytest for local development. Vercel should use `requirements.txt`.

The ZIP deliberately excludes `.env`, databases, caches, Git metadata, and credentials. `.env.example` contains empty placeholders only.

## 3. Recommended method: deploy with the Vercel CLI

This is the shortest way to complete Vercel's first-deployment confirmation.

### Step 3.1 — Authenticate

From the extracted project directory:

```bash
npx vercel@latest login
npx vercel@latest whoami
```

Complete the login flow in your browser. `whoami` must return the Vercel account that owns or can access the target project.

If you prefer a global installation:

```bash
npm install --global vercel
vercel login
vercel whoami
```

### Step 3.2 — Link the existing project

The existing project is named **`quantpilot`** and already has the OANDA environment configuration in the account used to create it:

```bash
npx vercel@latest link --project quantpilot
```

Answer the prompts as follows:

- **Set up and deploy?** Yes.
- **Which scope?** Select the account/team containing `quantpilot`.
- **Link to existing project?** Yes, if asked separately.
- **Project name:** `quantpilot`.

If that account cannot find the project, either choose the correct scope or create a new project instead:

```bash
npx vercel@latest link
```

Choose **No** when asked to link an existing project, then enter a unique name such as `quantpilot`. A new project needs every environment variable in section 5.

### Step 3.3 — Check project settings

In the Vercel dashboard, open **Project → Settings → General → Build & Development Settings** and use:

| Setting | Value |
|---|---|
| Framework Preset | **FastAPI** |
| Root Directory | Repository/ZIP root (`./`) |
| Build Command | Empty / default |
| Output Directory | Empty / default |
| Install Command | Empty / default; Vercel installs `requirements.txt` |

Do **not** set `python3 build_source.py`, do not deploy only `public/`, and do not configure a static-site output directory. `api/index.py` exports the ASGI app and `public/` is mounted by FastAPI.

### Step 3.4 — Add or verify environment variables

If you linked the original `quantpilot` project, verify the existing values using section 5. If you created a new project, add them before deployment.

Secret values are most safely entered in **Project → Settings → Environment Variables**, rather than typed into a terminal where they can enter shell history.

### Step 3.5 — Deploy production

From the project root:

```bash
npx vercel@latest --prod
```

If the CLI asks to confirm detected settings, choose **FastAPI** and accept the defaults in Step 3.3. Do not add a custom build command.

The command should eventually print a production URL. Open that URL only after the deployment reaches **READY**. A building, queued, or error deployment is not a working release.

For a non-production test first:

```bash
npx vercel@latest
```

Then promote the tested deployment from the dashboard or run `npx vercel@latest --prod`.

## 4. Alternative method: GitHub/GitLab + Vercel dashboard

Vercel's dashboard does not turn this ZIP directly into a deployment. For a dashboard deployment, first place the extracted source in a Git repository.

### Step 4.1 — Create and push a private repository

From the extracted project root:

```bash
git init
git add .
git commit -m "Deploy QuantPilot paper-trading platform"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_PRIVATE_REPOSITORY.git
git push -u origin main
```

Use your actual repository URL. Before committing, verify:

```bash
git status --short
```

There must be no `.env`, real credential, `quantpilot.db`, or other secret file.

### Step 4.2 — Import into Vercel

1. Open the Vercel dashboard.
2. Select **Add New → Project**.
3. Import the repository.
4. Set **Framework Preset** to **FastAPI**.
5. Leave Root Directory at the repository root unless the project is inside a subdirectory; if it is, select that subdirectory.
6. Leave Build Command, Output Directory, and Install Command at their defaults.
7. Add every required variable from section 5.
8. Select **Deploy**.
9. Wait for **READY**, then open the generated domain.

For the existing `quantpilot` project, connect the repository under **Project → Settings → Git** instead of creating a duplicate project.

## 5. Required environment variables

Configure these for **Production**, **Preview**, and **Development** unless you intentionally use different providers per environment.

| Name | Required value / action | Secret? |
|---|---|---|
| `OANDA_API_KEY` | Your OANDA **practice** access token | **Yes — Sensitive** |
| `OANDA_ACCOUNT_ID` | Your OANDA practice account ID | **Yes — Sensitive/Encrypted** |
| `OANDA_ENVIRONMENT` | `practice` | No |
| `DATA_PROVIDER` | `oanda` | No |
| `ALLOW_SYNTHETIC_FALLBACK` | `false` | No |
| `DATABASE_URL` | Temporary: `sqlite:////tmp/quantpilot.db` | Treat as Sensitive |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | No |
| `GROQ_API_KEY` | Optional Groq key; leave unset for deterministic mode | **Yes — Sensitive** |
| `NEWS_PROVIDER` | Configured: `yfinance` | No |
| `NEWS_API_KEY` | Only if a supported news provider is configured | **Yes — Sensitive** |

Important behavior:

- The application forces `OANDA_ENVIRONMENT=practice` in code even if a different value is supplied.
- Strict `DATA_PROVIDER=oanda` does not fall back to fabricated/synthetic candles during an outage.
- `NEWS_PROVIDER=yfinance` uses Yahoo Finance news, including `EUR_USD` → `EURUSD=X` normalization. Provider outages produce explicit UNAVAILABLE news, not invented news. No Yahoo API key is required.
- Without `GROQ_API_KEY`, agents still run deterministically and the integration endpoint reports Groq as unavailable.
- After adding or changing an environment variable, **redeploy** so existing serverless instances use it.

## 6. Storage: temporary versus persistent

### Temporary demonstration storage

```dotenv
DATABASE_URL=sqlite:////tmp/quantpilot.db
```

**This is ephemeral on Vercel.** Serverless instances can be replaced and need not share `/tmp`. Paper balances, orders, fills, reports, traces, and journals can disappear. The UI reports `EPHEMERAL_SQLITE`.

### Durable PostgreSQL storage

Create a new isolated PostgreSQL/Supabase database that you are authorized to use, then set:

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require
```

Replace the placeholders with the database's actual connection details. Keep the value Sensitive and redeploy. SQLAlchemy creates the application's current schema on startup; there is no Alembic migration history for complex future upgrades.

Do not reuse, pause, delete, or upgrade unrelated existing Supabase projects. The original attempt to create a new isolated Supabase project was blocked by the account's free-project limit, so this remains your infrastructure decision.

## 7. Verify the deployed application

Set the real URL printed by Vercel—do not assume a domain exists before deployment:

```bash
export APP_URL="https://YOUR-REAL-DEPLOYMENT.vercel.app"
```

Windows PowerShell:

```powershell
$APP_URL = "https://YOUR-REAL-DEPLOYMENT.vercel.app"
```

Check the browser pages:

1. `$APP_URL/` — all seven web workspaces should load.
2. `$APP_URL/docs` — interactive FastAPI documentation.
3. `$APP_URL/health` — paper-only and integration health.

Check API responses:

```bash
curl -fsS "$APP_URL/health"
curl -fsS "$APP_URL/api/v1/market/integrations"
curl -fsS "$APP_URL/api/v1/market/candles/EUR_USD?timeframe=15m&rows=300"
curl -fsS "$APP_URL/api/v1/market/quote/EUR_USD"
curl -fsS "$APP_URL/api/v1/market/oanda/account"
```

Expected results:

- `paper_only` is `true`.
- OANDA reports `practice` and `MARKET_DATA_ONLY`.
- Candles identify `oanda`, contain completed bars, and include Python indicators.
- Quotes expose bid, ask, mid, spread, and a timestamp.
- Account metadata is readable but contains no token.
- Research outcomes are only APPROVED, REJECTED, or NO_TRADE; errors fail closed.
- Any execution appears only in the internal paper account.
- Storage says `EPHEMERAL_SQLITE` until PostgreSQL is configured.

## 8. Run locally before or after deployment

Python 3.11+ is recommended:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
cp .env.example .env               # Windows: copy .env.example .env
```

For an offline demonstration, set this in `.env`:

```dotenv
DATA_PROVIDER=synthetic
ALLOW_SYNTHETIC_FALLBACK=true
DATABASE_URL=sqlite:///./quantpilot.db
```

For actual OANDA practice data, enter credentials only in your local untracked `.env` and use:

```dotenv
DATA_PROVIDER=oanda
ALLOW_SYNTHETIC_FALLBACK=false
OANDA_ENVIRONMENT=practice
DATABASE_URL=sqlite:///./quantpilot.db
```

Start the production web app and API:

```bash
python run_api.py
```

Open `http://localhost:8000/`. Run tests with `pytest -q`; the current suite contains 55 tests. The optional Streamlit dashboard starts with `streamlit run app.py`.

## 9. Troubleshooting and what to fix

### `The projectSettings object is required for new projects`

This was the connector's first-deployment blocker. Use the latest authenticated CLI in section 3 or the dashboard in section 4. Set **Framework Preset = FastAPI**. The connector used by the assistant cannot supply Vercel's required first-deployment confirmation parameter.

### `files[n].data should be string` or `Missing files`

These were API connector upload errors, not application errors. Deploy the extracted directory with the CLI instead of using the connector's inline-file payload.

### `No matching distribution` or dependency installation fails

- Use Python **3.11** in `vercel.json`.
- Keep `requirements.txt` at the project root.
- Redeploy the complete extracted project, not only `public/`.
- Production intentionally excludes Streamlit, Plotly, and Pytest to reduce serverless size. Install `requirements-dev.txt` if running those locally.

### `/` returns 404 or only API JSON appears

- Confirm `public/index.html`, `public/styles.css`, and `public/app.js` were uploaded.
- Confirm `api/main.py` mounts `public/` after the API routes.
- Do not set an Output Directory or deploy a static-only subset.

### `/api/v1/market/quote/...` returns 503

- Add `OANDA_API_KEY` and `OANDA_ACCOUNT_ID` to the same environment as the deployment.
- Ensure the token is for a **practice** account and has not expired.
- Verify `OANDA_ACCOUNT_ID` belongs to that same practice environment.
- Redeploy after correcting variables.
- Keep `ALLOW_SYNTHETIC_FALLBACK=false`; do not conceal provider failures with synthetic data.

### OANDA returns 401/403

The token/account combination or permissions are wrong. Use valid practice credentials. QuantPilot intentionally rejects live OANDA endpoints.

### Groq is unavailable

Add `GROQ_API_KEY` as a Sensitive variable and redeploy. Check that the configured model is active for the account. This is optional and does not prevent deterministic research.

### Paper state disappears

This is expected with `/tmp` SQLite. Configure durable PostgreSQL as shown in section 6 and redeploy.

### Function timeout

- Check OANDA/Groq provider status and networking.
- Try fewer candles and disable automatic execution during diagnosis.
- Optional Groq should not be required for deterministic operation.
- Inspect **Vercel → Project → Deployments → Functions/Logs** for the actual exception.

### Deployment still fails

Copy the first red error from the Vercel build log, plus the deployment URL/ID. Do not copy environment-variable values or the OANDA token. The exact build error is needed for a responsible source-level fix.
