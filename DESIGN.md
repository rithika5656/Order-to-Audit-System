# NutriLedger design notes

## Architecture

The React application calls a FastAPI JSON API over HTTP. FastAPI validates request bodies, applies role dependencies and uses SQLAlchemy sessions to perform business operations. PostgreSQL is the deployment database; tests use an isolated SQLite database. SQLAlchemy models live in `backend/app/models.py`, HTTP routes in `backend/app/main.py`, and calculation helpers in `backend/app/services.py`.

## Visual system

The shared interface uses dark navy (`#101D38`) and midnight blue (`#172B4D`) for navigation and primary text, royal blue (`#2864B4`) for actions and active navigation, steel blue (`#3979C9`) and light blue (`#83B5FF`) for accents, and off-white/white surfaces. Amber and red are reserved for warning and critical statuses. Green and teal accents are intentionally excluded.

## Core relationships

- A customer places orders; each order refers to one customer and product.
- An order can have one posted invoice. Invoice tax amounts and taxable totals are stored as `NUMERIC`.
- One invoice can have multiple dispatches and payments for partial fulfillment/settlement.
- BOM items join a finished product to raw materials and provide required quantity per output quantity.
- Purchases refer to a raw material; production runs refer to a product.
- Each inventory movement stores an item type/id, signed quantity, unit, optional inventory-lot reference and unique source type/id pair per item. Lot allocations connect a single issue movement to one or more received/produced lots without changing the existing movement uniqueness rule. Audit rows record actor, operation, entity and timestamp.

## Inventory ledger

Balances are calculated as `SUM(inventory_movements.quantity)` grouped by item. Opening balances are positive movements; receipts are positive; production issues and dispatches are negative; production output is positive. This is equivalent to:

`Closing stock = opening balance + receipts - issues - dispatches + adjustments`

Stock is never directly edited. Purchase, production and dispatch endpoints record source documents and reject movements that result in a negative balance. When lots are tracked, production issues and dispatches use earliest-expiry-first allocation, skip expired lots and then consume legacy/untracked balances. Batch receipts and issues remain signed ledger movements; lot-allocation rows only identify which batch supplied a posted issue. Inventory usage and coverage use the latest 30 days of production issues or dispatches. Reorder suggestions target the greater of minimum stock and average daily usage multiplied by configured target coverage days; where there is no usage history, a low item is suggested back to twice its minimum. For high-concurrency deployment, inventory-changing operations should additionally use database-level serialization/locking or a materialized balance row with guarded updates; current request transactions provide atomic multi-row writes but not a full concurrent reservation system.

The benchmark treats pouches used for good output (188) as an actual production issue and damaged pouches (6) as a separate production-damage issue. Cartons are consumed as entered (9). Finished inventory increases only by good output, not expected output or damaged units.

## BOM and variances

BOM requirement for an output quantity is `BOM quantity × actual planned output / BOM per_output`. For 200 Murukku packets the benchmark plan is 40 kg flour, 10 L oil, 1.2 kg spice, 200 pouches and 10 cartons. Actual oil consumption variance is `(10.5 - 10) / 10 × 100 = +5%`. Yield variance is `(188 - 200) / 200 × 100 = -6%`. A variance alert threshold is 3%; reporting currently displays yield and consumption variance data but does not yet implement configurable alert delivery.

## Costing

Raw-material weighted-average rate is maintained on purchase: `(old quantity × old rate + receipt quantity × receipt rate) / new quantity`. A production run snapshots each material's rate when consumption is posted. Labour and utilities are recorded as run-linked expenses; the allocation rule is to divide batch direct-material cost plus batch overhead by good packets (damaged output does not absorb overhead). For the benchmark, flour is valued at ₹43.125/kg after the 60 kg receipt, total direct material cost including damaged pouches is ₹4,055, and ₹1,800 overhead yields ₹31.14 per good packet (₹5,855 / 188). Financial calculations use `Decimal`/SQL `NUMERIC`, not binary floats.

## GST and invoice identifiers

The current invoice flow applies the product's GST rate (benchmark 5%). Tamil Nadu customer invoices split tax equally between CGST and SGST; other customer states use IGST. Invoice numbers use `NL/{financial-year}/{sequence}` where the Indian financial year starts April 1. Posted invoices are not deleted; a credit-note cancellation flow remains to be implemented.

## Authentication and authorization

Passwords use salted PBKDF2-HMAC-SHA256. Signed JWT access tokens include user id, role and expiry. Dependencies protect endpoints and check role membership. The current demo implementation does not include refresh tokens, revocation lists, account lockout, password reset or deployment-grade secret management.
