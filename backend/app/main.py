import os
import csv
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO, StringIO

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import (
    AuditLog, BomItem, Customer, Dispatch, Expense, InventoryMovement, Invoice,
    Order, Payment, Product, ProductionConsumption, ProductionRun, Purchase,
    RawMaterial, Supplier, User,
)
from .schemas import LoginRequest, OrderRequest, PaymentRequest, ProductionRequest, PurchaseRequest
from .security import create_token, current_user, hash_password, require_roles, verify_password
from .services import add_movement, available_for_order, balance, bom_expected, build_invoice, dispatched, money, outstanding


app = FastAPI(title="NutriLedger API", version="1.0.0")
origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:8080,http://127.0.0.1:8080",
).split(",")
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)
Base.metadata.create_all(bind=engine)

ADMIN = ("Admin",)
PRODUCTION = ("Admin", "Production Supervisor")
SALES = ("Admin", "Salesman")
FINANCE = ("Admin", "Accountant / Auditor", "Owner")


def audit(db: Session, user: User | None, action: str, entity: str, entity_id: str):
    db.add(AuditLog(user_id=user.id if user else None, action=action, entity=entity, entity_id=entity_id))


def reference(prefix: str, value: str):
    return f"{prefix}-{value.strip()}"


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "NutriLedger"}


@app.post("/api/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"access_token": create_token(user), "token_type": "bearer", "user": {
        "id": user.id, "name": user.name, "email": user.email, "role": user.role,
    }}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    today = date.today()
    today_orders = db.scalar(select(func.count(Order.id)).where(func.date(Order.created_at) == today.isoformat())) or 0
    pending = db.scalar(select(func.count(Order.id)).where(Order.status == "Submitted")) or 0
    products = list(db.scalars(select(Product).where(Product.active.is_(True))))
    finished = [{"product": p.name, "quantity": str(balance(db, "finished", p.id)), "unit": p.unit} for p in products]
    materials = list(db.scalars(select(RawMaterial)))
    raw_stock = [{"material": m.name, "quantity": str(balance(db, "material", m.id)), "unit": m.unit,
                  "low": balance(db, "material", m.id) <= m.reorder_level} for m in materials]
    invoices = list(db.scalars(select(Invoice)))
    sales = sum((i.taxable for i in invoices), Decimal("0"))
    open_receivables = sum((outstanding(db, invoice.id) for invoice in invoices), Decimal("0"))
    month = date(today.year, today.month, 1)
    months = []
    for offset in range(5, -1, -1):
        index = month.year * 12 + month.month - 1 - offset
        year, month_index = divmod(index, 12)
        month_start = date(year, month_index + 1, 1)
        months.append(month_start)
    monthly_sales = []
    for month_start in months:
        next_month = date(month_start.year + (1 if month_start.month == 12 else 0),
                          1 if month_start.month == 12 else month_start.month + 1, 1)
        monthly_sales.append({
            "month": month_start.strftime("%b %y"),
            "sales": str(money(sum((
                invoice.taxable for invoice in invoices
                if month_start <= invoice.created_at.date() < next_month
            ), Decimal("0")))),
        })
    recent = list(db.scalars(select(Order).order_by(Order.created_at.desc()).limit(6)))
    month_start = datetime(today.year, today.month, 1)
    runs_this_month = list(db.scalars(select(ProductionRun).where(ProductionRun.created_at >= month_start)))
    return {
        "today_orders": today_orders, "pending_orders": pending,
        "total_sales": str(money(sales)), "finished_goods": finished,
        "raw_materials": raw_stock,
        "outstanding_receivables": str(money(open_receivables)),
        "production_this_month": {
            "runs": len(runs_this_month),
            "good_output": sum(run.good_output for run in runs_this_month),
        },
        "monthly_sales": monthly_sales,
        "recent_orders": [{"reference": o.reference, "customer": o.customer.name,
                           "product": o.product.name, "quantity": o.quantity,
                           "status": o.status, "created_at": o.created_at.isoformat()} for o in recent],
    }


@app.get("/api/products")
def products(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id": p.id, "name": p.name, "sku": p.sku, "category": p.category,
             "pack_size": p.pack_size, "unit": p.unit, "selling_price": str(p.selling_price),
             "gst_rate": str(p.gst_rate), "hsn_code": p.hsn_code, "active": p.active,
             "stock": str(balance(db, "finished", p.id))}
            for p in db.scalars(select(Product).order_by(Product.name))]


@app.post("/api/products")
def create_product(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    try:
        product = Product(
            name=payload["name"].strip(), sku=payload["sku"].strip(),
            category=payload.get("category", "Snacks"), pack_size=payload.get("pack_size", "200 g"),
            unit=payload.get("unit", "packet"), selling_price=Decimal(str(payload["selling_price"])),
            gst_rate=Decimal(str(payload.get("gst_rate", 5))), hsn_code=payload.get("hsn_code", "210690"),
        )
    except (KeyError, ValueError):
        raise HTTPException(status_code=422, detail="Product name, SKU and valid selling price are required")
    db.add(product)
    try:
        db.flush()
        audit(db, user, "created", "product", str(product.id))
        db.commit()
    except Exception as exc:
        db.rollback()
        if "UNIQUE" in str(exc).upper() or "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Product name or SKU already exists")
        raise
    return {"id": product.id, "name": product.name, "sku": product.sku}


@app.get("/api/customers")
def customers(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id": c.id, "name": c.name, "customer_type": c.customer_type,
             "state": c.state, "gstin": c.gstin, "contact": c.contact}
            for c in db.scalars(select(Customer).order_by(Customer.name))]


@app.post("/api/customers")
def create_customer(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    if not payload.get("name") or not payload.get("state"):
        raise HTTPException(status_code=422, detail="Customer name and state are required")
    customer = Customer(
        name=payload["name"].strip(), state=payload["state"].strip(),
        customer_type=payload.get("customer_type", "Retailer"),
        gstin=payload.get("gstin"), contact=payload.get("contact"),
        billing_address=payload.get("billing_address"),
    )
    db.add(customer)
    db.flush()
    audit(db, user, "created", "customer", str(customer.id))
    db.commit()
    return {"id": customer.id, "name": customer.name}


@app.get("/api/inventory")
def inventory(db: Session = Depends(get_db), user: User = Depends(current_user)):
    materials = list(db.scalars(select(RawMaterial).order_by(RawMaterial.name)))
    products = list(db.scalars(select(Product).order_by(Product.name)))
    return {
        "materials": [{"id": m.id, "name": m.name, "unit": m.unit,
                       "quantity": str(balance(db, "material", m.id)),
                       "reorder_level": str(m.reorder_level),
                       "weighted_average_cost": str(m.weighted_average_cost)} for m in materials],
        "finished_goods": [{"id": p.id, "name": p.name, "unit": p.unit,
                            "quantity": str(balance(db, "finished", p.id))} for p in products],
    }


@app.get("/api/inventory/ledger")
def ledger(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(InventoryMovement).order_by(InventoryMovement.created_at.desc()).limit(500))
    return [{"id": r.id, "item_type": r.item_type, "item_id": r.item_id,
             "quantity": str(r.quantity), "unit": r.unit, "source_type": r.source_type,
             "source_id": r.source_id, "created_at": r.created_at.isoformat()} for r in rows]


@app.post("/api/purchases")
def create_purchase(payload: PurchaseRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    material = db.get(RawMaterial, payload.material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Raw material not found")
    if db.scalar(select(Purchase).where(Purchase.reference == payload.reference)):
        raise HTTPException(status_code=409, detail="Purchase reference already processed")
    purchase = Purchase(
        reference=payload.reference, material_id=material.id,
        quantity=payload.quantity, unit_rate=payload.unit_rate,
        total=money(payload.quantity * payload.unit_rate),
    )
    previous_qty = balance(db, "material", material.id)
    previous_cost = material.weighted_average_cost
    new_qty = previous_qty + payload.quantity
    material.weighted_average_cost = (
        (previous_qty * previous_cost + payload.quantity * payload.unit_rate) / new_qty
        if new_qty else payload.unit_rate
    )
    db.add(purchase)
    db.flush()
    add_movement(db, "material", material.id, payload.quantity, material.unit, "purchase", purchase.reference)
    audit(db, user, "recorded", "purchase", purchase.reference)
    db.commit()
    return {"id": purchase.id, "reference": purchase.reference, "total": str(purchase.total)}


@app.get("/api/purchases")
def list_purchases(db: Session = Depends(get_db), user: User = Depends(require_roles(*FINANCE))):
    purchases = db.scalars(select(Purchase).order_by(Purchase.created_at.desc()))
    return [{
        "id": p.id, "reference": p.reference, "material": db.get(RawMaterial, p.material_id).name,
        "quantity": str(p.quantity), "unit_rate": str(p.unit_rate), "total": str(p.total),
        "created_at": p.created_at.isoformat(),
    } for p in purchases]


@app.post("/api/production-runs")
def create_production(payload: ProductionRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*PRODUCTION))):
    product = db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if db.scalar(select(ProductionRun).where(ProductionRun.reference == payload.reference)):
        raise HTTPException(status_code=409, detail="Production reference already processed")
    planned = bom_expected(db, product.id, payload.expected_output)
    if not planned:
        raise HTTPException(status_code=422, detail="Product has no bill of materials")
    if set(payload.actual_consumption) != set(planned):
        raise HTTPException(status_code=422, detail="Actual consumption must include every BOM material exactly once")
    for material_id, qty in payload.actual_consumption.items():
        if material_id not in planned or Decimal(qty) < 0:
            raise HTTPException(status_code=422, detail="Consumption must reference BOM materials and be non-negative")
    yield_variance = (Decimal(payload.good_output - payload.expected_output) / Decimal(payload.expected_output)) * Decimal("100")
    run = ProductionRun(
        reference=payload.reference, product_id=product.id,
        expected_output=payload.expected_output, good_output=payload.good_output,
        damaged=payload.damaged, yield_variance=yield_variance,
    )
    db.add(run)
    db.flush()
    for material_id, actual in payload.actual_consumption.items():
        material = db.get(RawMaterial, material_id)
        add_movement(db, "material", material_id, -Decimal(actual), material.unit, "production", run.reference)
        consumption_qty = Decimal(actual)
        if material.name == "200 g pouch":
            consumption_qty += Decimal(payload.damaged)
        db.add(ProductionConsumption(
            production_run_id=run.id, material_id=material_id,
            quantity=consumption_qty, unit_cost=material.weighted_average_cost,
        ))
    if payload.damaged:
        pouch = db.scalar(select(RawMaterial).where(RawMaterial.name == "200 g pouch"))
        if pouch:
            add_movement(db, "material", pouch.id, -Decimal(payload.damaged), pouch.unit, "production-damage", run.reference)
            if pouch.id not in payload.actual_consumption:
                db.add(ProductionConsumption(
                    production_run_id=run.id, material_id=pouch.id,
                    quantity=Decimal(payload.damaged), unit_cost=pouch.weighted_average_cost,
                ))
    add_movement(db, "finished", product.id, Decimal(payload.good_output), product.unit, "production", run.reference)
    audit(db, user, "completed", "production_run", run.reference)
    db.commit()
    return {
        "id": run.id, "reference": run.reference, "expected_output": run.expected_output,
        "good_output": run.good_output, "yield_variance_percent": str(run.yield_variance),
        "variance_alert": abs(run.yield_variance) > Decimal("3") or any(
            expected and abs((Decimal(actual) - expected) / expected * Decimal("100")) > Decimal("3")
            for material_id, actual in payload.actual_consumption.items()
            if (expected := planned.get(material_id))
        ),
        "consumption_variance": {
            str(material_id): str((Decimal(actual) - expected) / expected * Decimal("100"))
            for material_id, actual in payload.actual_consumption.items()
            if (expected := planned.get(material_id)) and expected != 0
        },
        "finished_stock": str(available_for_order(db, product.id)),
    }


@app.get("/api/production-runs")
def list_production_runs(db: Session = Depends(get_db), user: User = Depends(current_user)):
    runs = db.scalars(select(ProductionRun).order_by(ProductionRun.created_at.desc()))
    return [{
        "id": run.id, "reference": run.reference,
        "product": db.get(Product, run.product_id).name,
        "expected_output": run.expected_output, "good_output": run.good_output,
        "damaged": run.damaged, "yield_variance_percent": str(run.yield_variance),
        "variance_alert": abs(run.yield_variance) > Decimal("3"),
        "created_at": run.created_at.isoformat(),
    } for run in runs]


@app.post("/api/production-runs/{run_id}/expenses")
def record_production_expense(
    run_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN)),
):
    run = db.get(ProductionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Production run not found")
    reference_value = str(payload.get("reference", "")).strip()
    category = str(payload.get("category", "")).strip()
    try:
        amount = Decimal(str(payload["amount"]))
    except (KeyError, ArithmeticError, ValueError):
        raise HTTPException(status_code=422, detail="A valid expense amount is required")
    if not reference_value or not category or amount < 0:
        raise HTTPException(status_code=422, detail="Reference, category and non-negative amount are required")
    if db.scalar(select(Expense).where(Expense.reference == reference_value)):
        raise HTTPException(status_code=409, detail="Expense reference already processed")
    expense = Expense(reference=reference_value, category=category, amount=money(amount),
                      production_run_id=run.id, note=payload.get("note"))
    db.add(expense)
    audit(db, user, "recorded", "expense", reference_value)
    db.commit()
    return {"reference": expense.reference, "amount": str(expense.amount)}


@app.get("/api/production-runs/{run_id}/costing")
def production_costing(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*FINANCE))):
    run = db.get(ProductionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Production run not found")
    rows = list(db.scalars(select(ProductionConsumption).where(ProductionConsumption.production_run_id == run.id)))
    raw_cost = sum((row.quantity * row.unit_cost for row in rows), Decimal("0"))
    expenses = list(db.scalars(select(Expense).where(Expense.production_run_id == run.id)))
    overhead = sum((expense.amount for expense in expenses), Decimal("0"))
    total = money(raw_cost + overhead)
    per_packet = money(total / Decimal(run.good_output)) if run.good_output else Decimal("0.00")
    product = db.get(Product, run.product_id)
    gross_margin = money(product.selling_price - per_packet)
    margin_percent = (gross_margin / product.selling_price * Decimal("100")) if product.selling_price else Decimal("0")
    return {
        "reference": run.reference, "raw_material_cost": str(money(raw_cost)),
        "overhead_cost": str(money(overhead)), "total_cost": str(total),
        "good_output": run.good_output, "cost_per_packet": str(per_packet),
        "selling_price": str(product.selling_price), "gross_margin_per_packet": str(gross_margin),
        "gross_margin_percent": str(margin_percent),
    }


@app.get("/api/bom/{product_id}")
def get_bom(product_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"material_id": item.material_id, "material": item.material.name,
             "quantity": str(item.quantity), "unit": item.material.unit,
             "per_output": str(item.per_output)}
            for item in db.scalars(select(BomItem).where(BomItem.product_id == product_id))]


@app.put("/api/bom/{product_id}")
def replace_bom(
    product_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN)),
):
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=422, detail="BOM must contain at least one material")
    seen = set()
    validated = []
    for row in items:
        try:
            material_id = int(row["material_id"])
            quantity = Decimal(str(row["quantity"]))
            per_output = Decimal(str(row.get("per_output", 200)))
        except (KeyError, ArithmeticError, ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Each BOM item needs material_id, quantity and valid per_output")
        if material_id in seen or quantity <= 0 or per_output <= 0 or db.get(RawMaterial, material_id) is None:
            raise HTTPException(status_code=422, detail="BOM materials must be unique and quantities must be positive")
        seen.add(material_id)
        validated.append(BomItem(product_id=product_id, material_id=material_id,
                                  quantity=quantity, per_output=per_output))
    db.query(BomItem).filter(BomItem.product_id == product_id).delete(synchronize_session=False)
    db.add_all(validated)
    audit(db, user, "updated", "bom", str(product_id))
    db.commit()
    return {"product_id": product_id, "items_saved": len(validated)}


@app.post("/api/orders")
def create_order(payload: OrderRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*SALES))):
    customer, product = db.get(Customer, payload.customer_id), db.get(Product, payload.product_id)
    if customer is None or product is None:
        raise HTTPException(status_code=404, detail="Customer or product not found")
    ref = reference("ORD", f"{datetime.utcnow():%Y%m%d%H%M%S%f}")
    order = Order(reference=ref, customer_id=customer.id, product_id=product.id,
                  quantity=payload.quantity, unit_price=product.selling_price,
                  created_by=user.id)
    db.add(order)
    db.flush()
    audit(db, user, "submitted", "order", order.reference)
    db.commit()
    stock = int(available_for_order(db, product.id))
    return {"id": order.id, "reference": order.reference, "status": order.status,
            "available_stock": stock, "shortage": str(max(0, payload.quantity - stock))}


@app.get("/api/orders")
def list_orders(db: Session = Depends(get_db), user: User = Depends(current_user)):
    query = select(Order).order_by(Order.created_at.desc())
    if user.role == "Salesman":
        query = query.where(Order.created_by == user.id)
    return [{"id": o.id, "reference": o.reference, "customer": o.customer.name,
             "state": o.customer.state, "product": o.product.name, "product_id": o.product_id,
             "customer_id": o.customer_id, "quantity": o.quantity, "unit_price": str(o.unit_price),
             "available_stock": str(available_for_order(db, o.product_id)),
             "status": o.status, "created_at": o.created_at.isoformat()} for o in db.scalars(query)]


@app.post("/api/orders/{order_id}/approve")
def approve_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "Submitted":
        raise HTTPException(status_code=409, detail=f"Cannot approve order in {order.status} status")
    available = available_for_order(db, order.product_id)
    if available < order.quantity:
        raise HTTPException(status_code=409, detail=f"Insufficient finished goods: {order.quantity - int(available)} packet shortage")
    order.status = "Approved"
    audit(db, user, "approved", "order", order.reference)
    db.commit()
    return {"status": order.status}


@app.post("/api/orders/{order_id}/invoice")
def invoice_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "Approved":
        raise HTTPException(status_code=409, detail="Only approved orders can be invoiced")
    if db.scalar(select(Invoice).where(Invoice.order_id == order.id)):
        raise HTTPException(status_code=409, detail="Order already invoiced")
    invoice = build_invoice(db, order)
    today = datetime.utcnow()
    fy_start = today.year if today.month >= 4 else today.year - 1
    count = db.scalar(select(func.count(Invoice.id)).where(
        Invoice.created_at >= datetime(fy_start, 4, 1),
        Invoice.created_at < datetime(fy_start + 1, 4, 1),
    )) or 0
    invoice.number = f"NL/{fy_start}-{str(fy_start + 1)[-2:]}/{count + 1:04d}"
    db.add(invoice)
    order.status = "Invoiced"
    db.flush()
    audit(db, user, "generated", "invoice", invoice.number)
    db.commit()
    return {"id": invoice.id, "number": invoice.number, "taxable": str(invoice.taxable),
            "cgst": str(invoice.cgst), "sgst": str(invoice.sgst), "igst": str(invoice.igst),
            "total": str(invoice.total)}


@app.get("/api/invoices")
def list_invoices(db: Session = Depends(get_db), user: User = Depends(require_roles(*FINANCE))):
    invoices = db.scalars(select(Invoice).order_by(Invoice.created_at.desc()))
    return [{"id": i.id, "number": i.number, "customer": i.order.customer.name,
             "order_reference": i.order.reference, "taxable": str(i.taxable),
             "cgst": str(i.cgst), "sgst": str(i.sgst), "igst": str(i.igst),
             "total": str(i.total), "outstanding": str(outstanding(db, i.id)),
             "remaining": i.order.quantity - dispatched(db, i.id),
             "created_at": i.created_at.isoformat()} for i in invoices]


@app.post("/api/invoices/{invoice_id}/dispatch")
def create_dispatch(invoice_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    qty = int(payload.get("quantity", 0))
    already = dispatched(db, invoice_id)
    if qty <= 0 or already + qty > invoice.order.quantity:
        raise HTTPException(status_code=422, detail="Dispatch quantity must be positive and no greater than the unshipped quantity")
    if available_for_order(db, invoice.order.product_id) < qty:
        raise HTTPException(status_code=409, detail="Insufficient finished goods for dispatch")
    ref = payload.get("reference") or f"DSP-{invoice.number}-{already + qty}"
    if db.scalar(select(Dispatch).where(Dispatch.reference == ref)):
        raise HTTPException(status_code=409, detail="Dispatch reference already processed")
    dispatch = Dispatch(reference=ref, invoice_id=invoice_id, quantity=qty)
    db.add(dispatch)
    add_movement(db, "finished", invoice.order.product_id, Decimal(-qty),
                 invoice.order.product.unit, "dispatch", ref)
    invoice.order.status = "Dispatched" if already + qty == invoice.order.quantity else "Invoiced"
    audit(db, user, "dispatched", "dispatch", ref)
    db.commit()
    return {"reference": ref, "dispatched": qty, "remaining": invoice.order.quantity - already - qty}


@app.post("/api/invoices/{invoice_id}/payments")
def record_payment(invoice_id: int, payload: PaymentRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*FINANCE))):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if db.scalar(select(Payment).where(Payment.reference == payload.reference)):
        raise HTTPException(status_code=409, detail="Payment reference already processed")
    if payload.amount > outstanding(db, invoice_id):
        raise HTTPException(status_code=422, detail="Payment exceeds invoice outstanding")
    payment = Payment(reference=payload.reference, invoice_id=invoice_id, amount=money(payload.amount))
    db.add(payment)
    audit(db, user, "recorded", "payment", payload.reference)
    db.commit()
    return {"reference": payment.reference, "amount": str(payment.amount),
            "outstanding": str(outstanding(db, invoice_id))}


@app.get("/api/reports/summary")
def report_summary(db: Session = Depends(get_db), user: User = Depends(require_roles(*FINANCE))):
    invoices = list(db.scalars(select(Invoice)))
    runs = list(db.scalars(select(ProductionRun)))
    purchases = list(db.scalars(select(Purchase).order_by(Purchase.created_at.desc())))
    materials = list(db.scalars(select(RawMaterial)))
    products = list(db.scalars(select(Product)))
    payments = list(db.scalars(select(Payment).order_by(Payment.created_at.desc())))
    ageing = {"current": Decimal("0"), "1_30_days": Decimal("0"), "31_60_days": Decimal("0"),
              "61_90_days": Decimal("0"), "over_90_days": Decimal("0")}
    today = date.today()
    for invoice in invoices:
        due = outstanding(db, invoice.id)
        age_days = (today - invoice.created_at.date()).days
        bucket = ("current" if age_days <= 0 else "1_30_days" if age_days <= 30
                  else "31_60_days" if age_days <= 60 else "61_90_days" if age_days <= 90 else "over_90_days")
        ageing[bucket] += due
    costing_rows = []
    for run in runs:
        consumptions = list(db.scalars(select(ProductionConsumption).where(
            ProductionConsumption.production_run_id == run.id
        )))
        raw_cost = sum((row.quantity * row.unit_cost for row in consumptions), Decimal("0"))
        overhead = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.production_run_id == run.id
        ))
        total_cost = money(raw_cost + Decimal(overhead))
        costing_rows.append({
            "reference": run.reference, "good_output": run.good_output,
            "raw_material_cost": str(money(raw_cost)), "overhead_cost": str(money(Decimal(overhead))),
            "total_cost": str(total_cost),
            "cost_per_packet": str(money(total_cost / run.good_output)) if run.good_output else "0.00",
        })
    return {
        "sales_register": [{"invoice": i.number, "customer": i.order.customer.name,
                            "taxable": str(i.taxable), "gst": str(i.cgst + i.sgst + i.igst),
                            "total": str(i.total)} for i in invoices],
        "customer_sales": [{"customer": customer, "taxable": str(money(sum(
            (i.taxable for i in invoices if i.order.customer.name == customer), Decimal("0")
        )))} for customer in sorted({i.order.customer.name for i in invoices})],
        "product_sales": [{"product": product, "quantity": sum(
            i.order.quantity for i in invoices if i.order.product.name == product
        ), "taxable": str(money(sum(
            (i.taxable for i in invoices if i.order.product.name == product), Decimal("0")
        )))} for product in sorted({i.order.product.name for i in invoices})],
        "gst_summary": {"taxable": str(money(sum((i.taxable for i in invoices), Decimal("0")))),
                        "cgst": str(money(sum((i.cgst for i in invoices), Decimal("0")))),
                        "sgst": str(money(sum((i.sgst for i in invoices), Decimal("0")))),
                        "igst": str(money(sum((i.igst for i in invoices), Decimal("0"))))},
        "purchase_register": [{"reference": p.reference, "material": db.get(RawMaterial, p.material_id).name,
                               "quantity": str(p.quantity), "unit_rate": str(p.unit_rate), "total": str(p.total)}
                              for p in purchases],
        "raw_material_stock": [{"material": m.name, "quantity": str(balance(db, "material", m.id)), "unit": m.unit}
                               for m in materials],
        "finished_goods_stock": [{"product": p.name, "quantity": str(balance(db, "finished", p.id)), "unit": p.unit}
                                 for p in products],
        "stock_ledger": [{"item_type": m.item_type, "item_id": m.item_id, "quantity": str(m.quantity),
                          "unit": m.unit, "source_type": m.source_type, "source_id": m.source_id,
                          "created_at": m.created_at.isoformat()}
                         for m in db.scalars(select(InventoryMovement).order_by(InventoryMovement.created_at.desc()))],
        "production": [{"reference": r.reference, "expected": r.expected_output,
                        "good_output": r.good_output, "damaged": r.damaged,
                        "yield_variance_percent": str(r.yield_variance)} for r in runs],
        "cost_per_packet": costing_rows,
        "payment_collection": [{"reference": p.reference, "invoice": db.get(Invoice, p.invoice_id).number,
                                "customer": db.get(Invoice, p.invoice_id).order.customer.name,
                                "amount": str(p.amount), "date": p.created_at.date().isoformat()}
                               for p in payments],
        "receivables": [{"invoice": i.number, "customer": i.order.customer.name,
                         "amount": str(outstanding(db, i.id))} for i in invoices],
        "receivables_ageing": {key: str(money(value)) for key, value in ageing.items()},
    }


@app.get("/api/reports/export/{report_name}")
def export_report(
    report_name: str,
    format: str = "csv",
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*FINANCE)),
):
    report_builders = {
        "sales-register": lambda: [
            {"invoice": i.number, "date": i.created_at.date().isoformat(),
             "customer": i.order.customer.name, "taxable": str(i.taxable),
             "cgst": str(i.cgst), "sgst": str(i.sgst), "igst": str(i.igst),
             "total": str(i.total)}
            for i in db.scalars(select(Invoice).order_by(Invoice.created_at))
            if (from_date is None or i.created_at.date() >= from_date)
            and (to_date is None or i.created_at.date() <= to_date)
        ],
        "stock-ledger": lambda: [
            {"date": m.created_at.isoformat(), "item_type": m.item_type, "item_id": m.item_id,
             "quantity": str(m.quantity), "unit": m.unit, "source_type": m.source_type, "source_id": m.source_id}
            for m in db.scalars(select(InventoryMovement).order_by(InventoryMovement.created_at))
            if (from_date is None or m.created_at.date() >= from_date)
            and (to_date is None or m.created_at.date() <= to_date)
        ],
        "production": lambda: [
            {"batch": r.reference, "date": r.created_at.date().isoformat(), "expected": r.expected_output,
             "good_output": r.good_output, "damaged": r.damaged, "yield_variance_percent": str(r.yield_variance)}
            for r in db.scalars(select(ProductionRun).order_by(ProductionRun.created_at))
            if (from_date is None or r.created_at.date() >= from_date)
            and (to_date is None or r.created_at.date() <= to_date)
        ],
        "receivables": lambda: [
            {"invoice": i.number, "date": i.created_at.date().isoformat(), "customer": i.order.customer.name,
             "invoice_total": str(i.total), "outstanding": str(outstanding(db, i.id))}
            for i in db.scalars(select(Invoice).order_by(Invoice.created_at))
            if (from_date is None or i.created_at.date() >= from_date)
            and (to_date is None or i.created_at.date() <= to_date)
        ],
    }
    if report_name not in report_builders:
        raise HTTPException(status_code=404, detail="Unknown report")
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date must not be after to_date")
    if format not in ("csv", "xlsx", "pdf"):
        raise HTTPException(status_code=422, detail="format must be csv, xlsx or pdf")
    rows = report_builders[report_name]()
    headers = list(rows[0].keys()) if rows else ["No records"]
    output = BytesIO()
    if format == "csv":
        text = StringIO()
        writer = csv.DictWriter(text, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        output.write(text.getvalue().encode("utf-8-sig"))
        media_type = "text/csv"
    elif format == "xlsx":
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = report_name[:31]
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(header, "") for header in headers])
        workbook.save(output)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfgen import canvas
        pdf = canvas.Canvas(output, pagesize=landscape(A4))
        pdf.setTitle(f"NutriLedger {report_name}")
        pdf.setFont("Helvetica-Bold", 15)
        pdf.drawString(36, 560, f"NutriLedger - {report_name.replace('-', ' ').title()}")
        pdf.setFont("Helvetica", 8)
        y = 535
        pdf.drawString(36, y, " | ".join(headers)[:180])
        for row in rows:
            y -= 16
            if y < 36:
                pdf.showPage()
                pdf.setFont("Helvetica", 8)
                y = 560
            pdf.drawString(36, y, " | ".join(str(row.get(header, "")) for header in headers)[:180])
        pdf.save()
        media_type = "application/pdf"
    output.seek(0)
    return StreamingResponse(
        output, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{report_name}.{format}"'},
    )


@app.get("/api/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*FINANCE))):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    pdf.setTitle(f"NutriLedger invoice {invoice.number}")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(48, 790, "NutriLedger | GST TAX INVOICE")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(48, 755, f"Invoice: {invoice.number}")
    pdf.drawString(48, 735, f"Customer: {invoice.order.customer.name}")
    pdf.drawString(48, 715, f"State: {invoice.order.customer.state}")
    pdf.drawString(48, 680, f"{invoice.order.product.name} ({invoice.order.product.hsn_code})")
    pdf.drawString(48, 660, f"{invoice.order.quantity} x Rs {invoice.order.unit_price} = Rs {invoice.taxable}")
    pdf.drawString(48, 630, f"CGST: Rs {invoice.cgst}    SGST: Rs {invoice.sgst}    IGST: Rs {invoice.igst}")
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(48, 600, f"Invoice total: Rs {invoice.total}")
    pdf.save()
    output.seek(0)
    return StreamingResponse(output, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{invoice.number.replace("/", "-")}.pdf"'})


@app.get("/api/audit-logs")
def audit_logs(db: Session = Depends(get_db), user: User = Depends(require_roles(*FINANCE))):
    logs = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200))
    return [{"id": log.id, "user_id": log.user_id, "action": log.action,
             "entity": log.entity, "entity_id": log.entity_id,
             "created_at": log.created_at.isoformat()} for log in logs]
