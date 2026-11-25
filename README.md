# NutriLedger

Smart Manufacturing, Inventory & Audit Management for packaged-food businesses.

NutriLedger connects sales orders, GST billing, purchasing, production and stock records in one role-aware web application. The repository has a React/Vite client and FastAPI API backed by PostgreSQL (SQLite is used only as a lightweight local/test option).

## Features implemented

- JWT sign-in with salted PBKDF2 password hashes and role-gated API endpoints.
- Admin, Salesman, Production Supervisor, Accountant / Auditor and Owner demo roles.
- Live dashboard, product/customer directories and ledger-derived stock balances.
- Purchase receipts with weighted-average raw-material cost updates.
- BOM-driven production runs, actual-material issues, damaged pouch issues and yield/material variances.
- Order submission with stock warning, approval checks, GST invoicing, partial dispatch and payments.
- Invoice PDF download, GST/sales/production/receivables summaries and audit logs.
- Responsive enterprise interface using a dark-navy and royal-blue design system.
- PostgreSQL Docker Compose setup, Alembic migration entry point and automated benchmark tests.

The UI currently exposes the operational flows above, with report exports for sales, production, stock ledger and receivables.

## Technology

- Frontend: React 18, Vite 6, Tailwind CSS 3, React Router, Axios, Lucide, Recharts.
- Backend: Python 3.11, FastAPI, SQLAlchemy 2, Pydantic, PyJWT.
- Database: PostgreSQL 16; SQLite for isolated automated tests.
- PDF: ReportLab.

## Repository layout

```text
backend/
  app/                 API, SQLAlchemy models, auth and business services
  migrations/          Alembic environment and initial schema migration
  tests/               Arithmetic and end-to-end benchmark tests
  seed.py              Development-only benchmark seed
frontend/
  src/                 React application, API client and styles
docker-compose.yml     PostgreSQL, API and web containers
DESIGN.md              Architecture and business calculation notes
```

## Run locally

### Docker Compose (PostgreSQL)

1. Copy `.env.example` to `.env`. Use a unique `JWT_SECRET` and a strong local database password.
2. Run:

   ```powershell
   docker compose up --build -d
   docker compose exec api alembic -c alembic.ini upgrade head
   docker compose exec api python seed.py
   ```

3. Open `http://localhost:8080`. API docs are at `http://localhost:8000/docs`.
4. To stop the services, run `docker compose down`. The named PostgreSQL volume is retained.

For production, disable demo seeding, set long random secrets, use TLS and a managed secrets provider, and review CORS and deployment policy. The bundled demo accounts are for local development only.

### Local development

Backend (from `backend`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///./nutriledger.db"
$env:JWT_SECRET = "local-only-change-this-secret"
alembic upgrade head
python seed.py
uvicorn app.main:app --reload
```

Frontend (from `frontend`):

```powershell
npm install
npm run dev
```

Vite runs at `http://localhost:5173`. Set `VITE_API_URL` if the API is hosted elsewhere. To use PostgreSQL locally, set `DATABASE_URL` to a `postgresql+psycopg://...` connection URL before running Alembic or Uvicorn.

## Development demo credentials

All seeded users use the development-only password `NutriLedger2026!`:

| Role | Email |
|---|---|
| Admin | `admin@nutriledger.local` |
| Salesman | `sales.a@nutriledger.local` |
| Production Supervisor | `production@nutriledger.local` |
| Accountant / Auditor | `accountant@nutriledger.local` |
| Owner | `owner@nutriledger.local` |

Never use these accounts or password in a production environment.

## Benchmark data and verification

`python seed.py` creates the benchmark opening inventory, Murukku 200 g product/BOM, Retailer A (Tamil Nadu), Distributor B (Karnataka), sample supplier and five development users. Then run one purchase (60 kg flour at ₹45/kg), one production batch (200 planned, 188 good, actual oil 10.5 L, damaged 6 pouches, 9 cartons), one 150-packet Retailer A order/invoice/dispatch, a ₹4,000 payment, and finally a 120-packet Distributor B order.

Expected ledger results:

| Check | Expected |
|---|---:|
| Flour / oil / pouches closing | 120 kg / 19.5 L / 306 pieces |
| Cartons closing | 21 pieces |
| Finished goods after production / dispatch | 238 / 88 packets |
| Yield / oil consumption variance | -6% / +5% |
| Taxable / CGST / SGST / invoice total | ₹7,500 / ₹187.50 / ₹187.50 / ₹7,875 |
| Retailer A outstanding / Distributor B shortage | ₹3,875 / 32 packets |

Automated test runs the API workflow against an isolated in-memory SQLite database:

```powershell
cd backend
python -m pytest -q
```

## Security and operations notes

- Passwords are never stored in clear text. JWT tokens are signed using `JWT_SECRET`.
- Important posted transactions create audit rows. Inventory is derived from append-only source-referenced movements; application endpoints do not expose direct stock balance editing.
- Monetary calculations use Python `Decimal` and SQL `NUMERIC` columns.
- Orders can be submitted even when stock is short so the shortage is visible; approval and dispatch reject insufficient inventory.
- Invoice records are unique per order. Dispatch and payment references are unique and duplicate purchase/production references are rejected.
- Production material cost uses a weighted-average rate snapshot at issue time. Labor and utility expenses can be recorded against a run and are allocated over its good output for the cost-per-packet report.
- Schema `create_all` is currently retained for convenient development startup; use Alembic as the deployment schema authority.

## Known limitations

This is a functional implementation of the core operational workflows, not yet the full production-ready ERP described by the broader requirements. In particular:

- Credit notes/cancellations, user administration, settings, supplier screens, customer/product editing, and assignment-based customer scope remain to be built. BOM editing and expense capture are available.
- Reports cover the principal sales, GST, stock, production, costing and receivables summaries, but not every requested filtered register/analytics view.
- The PDF invoice includes core invoice/tax information but does not yet include configurable company GSTIN/address, full tax columns and legal invoice metadata.
- Frontend support for partial dispatch and payments uses simple prompts; polished validation dialogs and a dedicated mobile salesman interface remain follow-up work.
- The API lacks rate limiting, refresh/revocation tokens and a production secret manager. Review deployment security before exposing it publicly.
- Alembic currently has a baseline schema migration; future schema changes should be created as new revisions.

See [DESIGN.md](./DESIGN.md) for stock ledger, BOM, tax and costing assumptions.
