# Hisaab

An accounting application for Nepal’s trading and wholesale businesses, built with React + TypeScript + Vite, FastAPI, and PostgreSQL.

**This is an operational MVP for evaluation and a supervised pilot. It is not IRD-approved billing software. Live VAT/tax invoices and CBMS submission are disabled.** Enabling `TAX_BILLING_ENABLED` deliberately fails startup until a verified implementation is released.

## Quick start with Docker

Requires Git and Docker Desktop (or Docker Engine with the Compose v2 plugin). Start Docker before running these commands. Python and Node are needed only for native development and the host-side verification/backup scripts.

```sh
git clone https://github.com/baduneev/Hisaab.git
cd Hisaab
```

Copy the example environment file:

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```sh
# macOS / Linux
cp .env.example .env
```

Build and start the application:

```sh
docker compose up -d --build --wait api
docker compose --profile operations up -d worker
```

Open **http://127.0.0.1:8008**. API documentation is at **http://127.0.0.1:8008/docs**. Database migrations and sample-data setup run automatically. The worker processes queued PDFs, imports, and insight jobs.

The sample owner login is **`owner@hisaab.demo` / `Hisaab-demo-2026!`**. `.env.example` enables this demo and HTTP cookies for local use. Self-service registration creates an empty, isolated company. Every dashboard figure is derived from posted transactions. For real deployments, use a clean database and `DEMO_MODE=false`; changing the flag does not delete an existing demo account.

Database files persist in the `hisaab_data` Docker volume. Stop all services while keeping the data with `docker compose --profile operations stop`. Inspect startup problems with `docker compose logs --tail=100 api database`; ports **8008** and **55438** must be available on the host.

## Native development on Windows

Requires Python 3.11+, Node 22+, and Docker Desktop. Clone the repository as above, then run from its root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

The script installs locked dependencies, builds the interface, starts the dedicated PostgreSQL container on **55438**, migrates the database, and serves the application at **http://127.0.0.1:8008**. It uses one API worker. Existing installations can use `scripts/start.ps1 -NoInstall` after building updated source.

For frontend development, after the initial setup, start the API in one terminal:

```powershell
.venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8008 --reload --reload-dir api
```

Start Vite in a second terminal:

```powershell
npm run dev
```

Open **http://127.0.0.1:5188**. API documentation: **http://127.0.0.1:8008/docs**.

If the Docker API is already running, stop it before starting a development API on the same port: `docker compose --profile operations stop api worker`. To stop the complete local deployment while keeping its database volume, run `docker compose --profile operations stop`.

For native development on macOS/Linux, use `python3 -m venv .venv`, activate it with `source .venv/bin/activate`, then run `pip install -r requirements.lock.txt`, `npm ci`, `npm run build`, `docker compose up -d --wait database`, and `python -m alembic upgrade head`. Start `python -m uvicorn api.main:app --host 127.0.0.1 --port 8008 --reload --reload-dir api` and `npm run dev` in separate terminals. Copy `.env.example` to `.env` first. Run `python -m api.worker` in a third terminal when testing queued jobs.

## Configuration

Keep local settings and secrets in `.env`, which Git ignores. Use server-side secrets in a hosted deployment.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Native API database connection; defaults to the local database on port 55438. Compose supplies its own internal database address. |
| `POSTGRES_PASSWORD` | Compose database password; the example value is for local development. If changed, also update the password in `DATABASE_URL` for native tools. Changing it does not reset a password in an existing database volume. |
| `DEMO_MODE` | `true` creates the labeled sample company; use `false` with a clean database for real businesses. |
| `COOKIE_SECURE` | `false` for local HTTP; `true` behind HTTPS. |
| `ENCRYPTION_KEY` | Fernet key required by backup creation and restoration; see the backup instructions below. |
| `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL` | Optional HTTPS OpenAI-compatible provider URL, server-side credential, and model identifier. Leave blank to use deterministic insights. |
| `AI_DAILY_LIMIT` | Maximum AI requests per tenant per day; defaults to 25. |
| `TAX_BILLING_ENABLED` | Must remain `false`; live tax billing is not implemented. Compose enforces `false`. |

After changing Docker environment settings, rerun `docker compose up -d api` and `docker compose --profile operations up -d worker` so the containers are recreated with the new configuration. Never put AI keys in `VITE_*` variables or frontend code.

## Repository layout

| Path | Contents |
| --- | --- |
| `web/` | React interface and generated API types |
| `api/` | FastAPI routes, accounting engine, reports, jobs, and insights |
| `migrations/` | Alembic database migrations |
| `tests/`, `e2e/` | Accounting/API acceptance tests and Playwright browser tests |
| `scripts/` | Setup, API type generation, reconciliation, and encrypted backups |
| `docs/` | Verification evidence and launch-readiness requirements |

## Implemented workflows

- Company registration, hashed passwords, expiring HttpOnly sessions, five server-enforced roles, multiple branches/warehouses, fiscal-period locks, and append-only audit history.
- Customer/supplier records, PAN validation, credit terms, invoice history, running statements, aging, partial payments, invoice allocations, and unallocated advances.
- Quotations, sales, cash sales, discounts, purchase orders, goods receipts, supplier bills, original-document-linked returns, expenses, balanced journals, and exact manual journal reversals.
- Perpetual inventory, decimal quantities, pack conversion, moving weighted-average cost, original sale-cost restoration on returns, stock transfers, adjustments, and opening stock.
- Profit/loss, balance sheet, trial balance, cash movement summary, aging, historical inventory valuation, product margins, printable reports, CSV exports, and bilingual PDF transaction records.
- English/Nepali navigation and primary workflows; BS/AD transaction-date input and display, NPR grouping, Nepal time and BS fiscal-year numbering. Some accountant-facing account names and technical CSV headers remain English. Supported calendar range comes from the pinned `nepali-datetime` library.
- CSV templates, full-file validation, preview and atomic commit for products, contacts, opening stock, and balanced opening journals. Opening journals must exclude inventory; opening-stock entries create the inventory control balance.
- Manual CSV bank reconciliation against the same account, exact signed amount, and transaction date. Optional bank-provided reference distinguishes otherwise identical statement rows.
- Evidence-linked insights for collections, reorder thresholds, no recorded sales for 60 days, product margin changes, customer concentration, and comparable-period gross profit.
- Optional AI explanations through an HTTPS OpenAI-compatible provider. The model receives aggregate figures and a classified topic, never raw user questions, customer identities, credentials, arbitrary SQL, or write tools. Provider failure keeps deterministic explanations and evidence available; daily request caps apply.
- Durable jobs for imports, PDF generation, and insight snapshots. Run `.venv/Scripts/python.exe -m api.worker` in a separate process, or `docker compose --profile operations up -d worker` after building the image. Workers recheck tenant and user access before execution. A crashed worker transaction rolls back so a pending job can be picked up again; completed/failed jobs remain inspectable through the API.

## Accounting guarantees and intentional limits

Posting requires an `Idempotency-Key`. PostgreSQL serializes each company’s posting operations, so numbering, allocations, and stock changes are atomic. Concurrent duplicate requests return the same posted result. Posted documents, journals, ledger lines, stock movements, allocations, and audit entries cannot be edited or deleted by application operations. PostgreSQL triggers also reject mutation of these records and enforce balanced journals and inventory/control-account reconciliation at commit.

The stock ledger rejects negative quantities, negative values, future postings, and stock dates before the company’s latest posted stock date. Returns cannot exceed the original quantity. Supplier billing consumes a full goods receipt once and creates no additional stock movement. In v1, supplier billing after an unbilled purchase return is blocked for accountant review. Purchase-return cost differences are booked explicitly as stock adjustment expense.

Draft updates use `If-Match` versions; posting is always online. On-device drafts are keyed by company and user and are removed after successful server saving. The most recent 200 transactions load in the main transaction list; the API supports `limit` and `offset`. Reports use posted records, with current operational stock alerts labeled separately from historical financial figures. The cash flow report is a cash movement summary, not a statutory cash flow classification. Accounting corrections beyond linked returns and manual-journal reversals need an accountant-guided workflow.

Deferred: payroll, fixed-asset schedules, manufacturing, batch/expiry or serial tracking, foreign currency, intercompany consolidation, OCR, demand forecasting, payment-provider integrations, tax return filing, and production IRD/CBMS connectivity.

## Verification

```powershell
# Fast SQLite acceptance suite (PostgreSQL-specific cases skip explicitly)
.venv/Scripts/python.exe -m pytest -q

# Full PostgreSQL suite: creates and removes disposable hisaab_test_* databases
$env:HISAAB_TEST_DATABASE_URL = $env:DATABASE_URL
# If DATABASE_URL is in .env rather than shell environment, use the local URL:
$env:HISAAB_TEST_DATABASE_URL = 'postgresql+psycopg://hisaab:hisaab-local-only@127.0.0.1:55438/hisaab'
.venv/Scripts/python.exe -m pytest -q

npm run build
npx playwright install chromium
npm test
.venv/Scripts/python.exe scripts/check_books.py
```

The PostgreSQL test account needs database-creation privileges because each test receives an isolated disposable database. CI runs against PostgreSQL and checks generated API types. API contract regeneration: `npm run api:types` with the API running. `web/generated/api.ts` and `openapi.json` are generated artifacts.

Browser tests cover contact creation, invoice draft recovery and posting, English/Nepali mobile navigation, report and insight evidence links, offline behavior, and desktop/mobile screenshots. PDF QA: `python scripts/render_sample_pdf.py`, then render `artifacts/pdf/bilingual-invoice.pdf` with Poppler. The Noto fonts are distributed under the included OFL license.

To run the same browser suite against the built Docker application, set `$env:HISAAB_WEB_URL='http://127.0.0.1:8008'` before `npm test`. Latest observed results are recorded in [verification](docs/verification.md).

## Backups and deployment

Generate a backup encryption key and store it in a secret manager or the ignored local `.env`:

```powershell
.venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.venv/Scripts/python.exe scripts/backup.py create
.venv/Scripts/python.exe scripts/backup.py verify-restore backups/<backup>.enc --database hisaab_restore_<unique_suffix>
```

Backups use a consistent exported PostgreSQL snapshot and Fernet authenticated encryption. Restore drills require a new `hisaab_restore_*` database and compare checksums, record counts, journal balances, and inventory reconciliation. They never overwrite the application database. Keep the encryption key separately from the backup. The backup helper targets the local Compose database; hosted database deployments should run equivalent `pg_dump`/restore operations against the hosting provider’s approved backup facility. Backups currently encrypt in memory, so very large databases need a streaming backup service.

`scripts/backup-daily.ps1` is suitable for a daily Windows Task Scheduler job. No operating-system task or future schedule is installed automatically. Configure off-device encrypted storage, retention, alerts, and regular restore drills before real data is stored.

`docker compose up --build api` builds the complete application. The API and database bind to loopback. `Caddyfile.example` provides the HTTPS reverse-proxy configuration: replace the example domain and set `COOKIE_SECURE=true`, `DEMO_MODE=false`, a strong database password, and a separate encryption key. Allow only the actual proxy address for forwarded headers. Use a non-superuser database runtime role and a separate migration role; the included local Compose account is for development. One API worker is intentional because the local login rate limiter is process-local; a scaled deployment needs a shared gateway limiter. Pin infrastructure images to reviewed digests when deploying.

Operational probes: `/api/v1/health` for readiness, `scripts/check_books.py` for per-company reconciliation, structured API failure logs, and `/api/v1/jobs/{id}` for job failures. Credentials and request bodies are excluded from application failure logs. Store AI credentials only in server-side environment secrets. No public deployment or production account changes are made by local setup.

## Before production tax billing

See [launch readiness](docs/launch-readiness.md) for the remaining IRD, accountant, customer-validation, and pilot requirements. Completion of automated tests does not establish statutory compliance or substitute for a reconciled monthly pilot close.
