"""Create a deterministic, fully linked Sri Lakshmi Foods demo dataset."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import os

from sqlalchemy import func, select

from app.database import Base, SessionLocal, engine
from app.models import (
    AuditLog, BomItem, CompanyProfile, Customer, DemoDataRecord, Dispatch, Expense,
    InventoryLot, InventoryMovement, Invoice, Order, Payment, Product,
    ProductionConsumption, ProductionRun, Purchase, RawMaterial, Role, Supplier,
    SupplierMaterial, User,
)
from app.security import hash_password
from app.services import add_movement, build_invoice, create_lot, dispatched, money, outstanding


BATCH_KEY = "sri-lakshmi-foods-demo-v1"
CENT = Decimal("0.01")
QTY = Decimal("0.001")
NOW = datetime.utcnow().replace(microsecond=0)

ROLE_NAMES = ("Admin", "Salesman", "Production Supervisor", "Accountant / Auditor", "Owner")
USER_ROWS = (
    ("Demo Admin", "demo.admin@srilakshmifoods.example.test", "Admin"),
    ("Demo Sales Lead", "demo.sales@srilakshmifoods.example.test", "Salesman"),
    ("Demo Production Supervisor", "demo.production@srilakshmifoods.example.test", "Production Supervisor"),
    ("Demo Accountant", "demo.accounts@srilakshmifoods.example.test", "Accountant / Auditor"),
    ("Demo Owner", "demo.owner@srilakshmifoods.example.test", "Owner"),
)

PRODUCT_ROWS = (
    ("Murukku 200 g", "MUR-200", "Traditional Snacks", "200 g", "50.00", True),
    ("Mixture 200 g", "MIX-200", "Traditional Snacks", "200 g", "55.00", True),
    ("Banana Chips 200 g", "BAN-200", "Chips", "200 g", "80.00", True),
    ("Ribbon Pakoda 200 g", "RIB-200", "Traditional Snacks", "200 g", "60.00", True),
    ("Thattai 200 g", "THA-200", "Traditional Snacks", "200 g", "65.00", True),
    ("Adhirasam 200 g", "ADH-200", "Traditional Sweets", "200 g", "75.00", True),
    ("Garlic Murukku 200 g", "GAR-200", "Traditional Snacks", "200 g", "60.00", True),
    ("Spicy Mixture 200 g", "SPM-200", "Traditional Snacks", "200 g", "60.00", True),
    ("Tapioca Chips 200 g", "TAP-200", "Chips", "200 g", "75.00", True),
    ("Peanut Candy 200 g", "PEA-200", "Traditional Sweets", "200 g", "70.00", False),
)

MATERIAL_ROWS = (
    ("Rice Flour", "kg", "42.00", "100"),
    ("Besan Flour", "kg", "58.00", "45"),
    ("Urad Dal Flour", "kg", "92.00", "25"),
    ("Plantain", "kg", "38.00", "70"),
    ("Tapioca", "kg", "32.00", "60"),
    ("Groundnut Oil", "litre", "148.00", "45"),
    ("Palmolein Oil", "litre", "122.00", "50"),
    ("Peanuts", "kg", "112.00", "35"),
    ("Jaggery", "kg", "54.00", "30"),
    ("Sesame Seeds", "kg", "158.00", "15"),
    ("Chilli Powder", "kg", "245.00", "8"),
    ("Salt & Spice Mix", "kg", "185.00", "12"),
    ("Garlic Powder", "kg", "310.00", "5"),
    ("200 g Laminated Pouch", "pieces", "2.40", "500"),
    ("Corrugated Carton", "pieces", "16.00", "40"),
)

# Each recipe quantity is for a 200-packet batch.
RECIPES = (
    (("Rice Flour", "35"), ("Urad Dal Flour", "3"), ("Palmolein Oil", "4"),
     ("Salt & Spice Mix", "0.5"), ("200 g Laminated Pouch", "200"), ("Corrugated Carton", "10")),
    (("Besan Flour", "18"), ("Rice Flour", "12"), ("Groundnut Oil", "5"),
     ("Peanuts", "8"), ("Salt & Spice Mix", "1"), ("200 g Laminated Pouch", "200"),
     ("Corrugated Carton", "10")),
    (("Plantain", "45"), ("Palmolein Oil", "8"), ("Salt & Spice Mix", "0.8"),
     ("200 g Laminated Pouch", "200"), ("Corrugated Carton", "10")),
    (("Rice Flour", "20"), ("Besan Flour", "12"), ("Palmolein Oil", "4"),
     ("Chilli Powder", "0.4"), ("Salt & Spice Mix", "0.4"),
     ("200 g Laminated Pouch", "200"), ("Corrugated Carton", "10")),
    (("Rice Flour", "30"), ("Urad Dal Flour", "4"), ("Sesame Seeds", "3"),
     ("Groundnut Oil", "3"), ("Salt & Spice Mix", "0.6"),
     ("200 g Laminated Pouch", "200"), ("Corrugated Carton", "10")),
    (("Rice Flour", "18"), ("Jaggery", "15"), ("Sesame Seeds", "1"),
     ("Groundnut Oil", "3"), ("200 g Laminated Pouch", "200"), ("Corrugated Carton", "10")),
    (("Rice Flour", "30"), ("Urad Dal Flour", "3"), ("Garlic Powder", "0.8"),
     ("Palmolein Oil", "4"), ("Salt & Spice Mix", "0.5"),
     ("200 g Laminated Pouch", "200"), ("Corrugated Carton", "10")),
    (("Besan Flour", "16"), ("Rice Flour", "10"), ("Peanuts", "10"),
     ("Groundnut Oil", "4"), ("Chilli Powder", "0.8"), ("Salt & Spice Mix", "0.8"),
     ("200 g Laminated Pouch", "200"), ("Corrugated Carton", "10")),
    (("Tapioca", "45"), ("Palmolein Oil", "8"), ("Salt & Spice Mix", "0.8"),
     ("200 g Laminated Pouch", "200"), ("Corrugated Carton", "10")),
    (("Peanuts", "22"), ("Jaggery", "15"), ("Sesame Seeds", "2"),
     ("200 g Laminated Pouch", "200"), ("Corrugated Carton", "10")),
)

CUSTOMER_ROWS = (
    ("Kovai Fresh Mart", "Retailer", "Tamil Nadu", "DEMO-GST-33-0001", "Coimbatore"),
    ("Annamalai Wholesale Foods", "Distributor", "Tamil Nadu", "DEMO-GST-33-0002", "Erode"),
    ("Malabar Taste Stores", "Distributor", "Kerala", "DEMO-GST-32-0003", "Palakkad"),
    ("Mysuru South Market", "Retailer", "Karnataka", "DEMO-GST-29-0004", "Mysuru"),
    ("Andhra Pantry Network", "Distributor", "Andhra Pradesh", "DEMO-GST-37-0005", "Tirupati"),
    ("Hyderabad Heritage Bazaar", "Retailer", "Telangana", "DEMO-GST-36-0006", "Hyderabad"),
    ("Nilgiri Provision House", "Retailer", "Tamil Nadu", None, "Ooty"),
    ("Kongu Retail Collective", "Distributor", "Tamil Nadu", "DEMO-GST-33-0008", "Tiruppur"),
)

SUPPLIER_ROWS = (
    ("Kaveri Grain Traders", "Rice Flour", "DEMO-GST-33-S001", "Net 15 days"),
    ("Coimbatore Pulse Mills", "Besan Flour", "DEMO-GST-33-S002", "Net 30 days"),
    ("Thanjavur Dal Products", "Urad Dal Flour", "DEMO-GST-33-S003", "Net 15 days"),
    ("Western Ghats Produce", "Plantain", "DEMO-GST-32-S004", "Net 7 days"),
    ("Salem Root Crop Supply", "Tapioca", "DEMO-GST-33-S005", "Net 15 days"),
    ("Kongu Oil Distributors", "Groundnut Oil", "DEMO-GST-33-S006", "Net 30 days"),
    ("Southern Edible Oils", "Palmolein Oil", "DEMO-GST-33-S007", "Net 30 days"),
    ("Erode Nut & Seed Co", "Peanuts", "DEMO-GST-33-S008", "Net 15 days"),
    ("Amaravati Sweeteners", "Jaggery", "DEMO-GST-37-S009", "Net 15 days"),
    ("Nilgiri Packaging Works", "200 g Laminated Pouch", "DEMO-GST-33-S010", "Net 30 days"),
)

SUPPLIER_MATERIALS = {
    "Kaveri Grain Traders": ("Rice Flour", "Sesame Seeds"),
    "Coimbatore Pulse Mills": ("Besan Flour", "Urad Dal Flour"),
    "Thanjavur Dal Products": ("Urad Dal Flour",),
    "Western Ghats Produce": ("Plantain",),
    "Salem Root Crop Supply": ("Tapioca",),
    "Kongu Oil Distributors": ("Groundnut Oil",),
    "Southern Edible Oils": ("Palmolein Oil",),
    "Erode Nut & Seed Co": ("Peanuts", "Sesame Seeds"),
    "Amaravati Sweeteners": ("Jaggery",),
    "Nilgiri Packaging Works": ("200 g Laminated Pouch", "Corrugated Carton"),
}

DEMO_PASSWORD = os.getenv("DEMO_SEED_PASSWORD", "SriLakshmiDemo2026!")


def d(value) -> Decimal:
    return Decimal(str(value))


def add_tag(db, entity_type: str, obj):
    db.add(DemoDataRecord(
        batch_key=BATCH_KEY, entity_type=entity_type, entity_id=str(obj.id),
    ))
    return obj


def add_row(db, entity_type: str, obj):
    db.add(obj)
    db.flush()
    add_tag(db, entity_type, obj)
    return obj


def record_movement(db, *args, **kwargs):
    movement = add_movement(db, *args, **kwargs)
    add_tag(db, "inventory_movements", movement)
    return movement


def add_audit(db, actor: User, action: str, entity: str, entity_id: str, created_at: datetime):
    row = add_row(db, "audit_logs", AuditLog(
        user_id=actor.id, action=f"DEMO DATA · {action}",
        entity=entity, entity_id=entity_id, created_at=created_at,
    ))
    return row


def seed_demo():
    if os.getenv("DEMO_MODE", "true").lower() != "true":
        raise RuntimeError("Refusing to seed demo records when DEMO_MODE is disabled.")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing_demo = db.scalar(select(DemoDataRecord.id).where(
            DemoDataRecord.batch_key == BATCH_KEY,
        ).limit(1))
        if existing_demo:
            print(f"Demo batch {BATCH_KEY} already exists; no changes made.")
            return
        existing_company = db.scalar(select(CompanyProfile.id).limit(1))
        if existing_company:
            raise RuntimeError("A company profile already exists; refusing to overwrite it.")

        db.rollback()
        with db.begin():
            for role_name in ROLE_NAMES:
                if db.get(Role, role_name) is None:
                    db.add(Role(code=role_name, description=f"{role_name} application role"))
            db.flush()

            company = add_row(db, "company_profiles", CompanyProfile(
                name="Sri Lakshmi Foods",
                address="18, Avinashi Road, Peelamedu",
                city="Coimbatore", state="Tamil Nadu", country="India",
                business="Manufacturing and distribution of traditional South Indian snacks",
                demo_data=True,
            ))

            users = {}
            for name, email, role in USER_ROWS:
                if db.scalar(select(User.id).where(User.email == email)):
                    raise RuntimeError(f"Demo user email already exists but is not registered: {email}")
                user = add_row(db, "users", User(
                    name=name, email=email, role=role,
                    password_hash=hash_password(DEMO_PASSWORD),
                ))
                users[role] = user

            materials = {}
            for index, (name, unit, cost, reorder) in enumerate(MATERIAL_ROWS):
                material = add_row(db, "raw_materials", RawMaterial(
                    name=f"{name} (DEMO DATA)", unit=unit,
                    reorder_level=d(reorder), reorder_days=14 + (index % 3) * 7,
                    weighted_average_cost=d(cost),
                ))
                materials[name] = material

            products = []
            for index, (name, sku, category, pack, price, active) in enumerate(PRODUCT_ROWS):
                products.append(add_row(db, "products", Product(
                    name=f"{name} (DEMO DATA)", sku=f"DEMO-{sku}",
                    category=category, pack_size=pack, unit="packet",
                    selling_price=d(price), gst_rate=d("5.00"),
                    hsn_code="210690", reorder_level=d(80 + index * 10),
                    reorder_days=14 + index % 4 * 7, active=active,
                )))

            bom_by_product = defaultdict(list)
            for product, recipe in zip(products, RECIPES):
                for material_name, quantity in recipe:
                    bom = add_row(db, "bom_items", BomItem(
                        product_id=product.id, material_id=materials[material_name].id,
                        quantity=d(quantity), per_output=d("200"),
                    ))
                    bom_by_product[product.id].append(bom)

            customers = []
            for index, (name, kind, state, gstin, city) in enumerate(CUSTOMER_ROWS):
                customers.append(add_row(db, "customers", Customer(
                    name=f"{name} (DEMO DATA)", customer_type=kind, state=state,
                    gstin=gstin, contact=f"DEMO ONLY +91 90000 10{index:03d}",
                    billing_address=f"{index + 1}, Market Road, {city}, {state}, India",
                    credit_limit=d(50000 + index * 25000),
                )))

            suppliers = {}
            for index, (name, material_name, gstin, terms) in enumerate(SUPPLIER_ROWS):
                supplier = add_row(db, "suppliers", Supplier(
                    name=f"{name} (DEMO DATA)",
                    contact=f"DEMO ONLY +91 90000 20{index:03d}",
                    gstin=gstin, payment_terms=terms,
                ))
                suppliers[name] = supplier
            for supplier_name, material_names in SUPPLIER_MATERIALS.items():
                for material_name in material_names:
                    add_row(db, "supplier_materials", SupplierMaterial(
                        supplier_id=suppliers[supplier_name].id,
                        material_id=materials[material_name].id,
                    ))

            batch_plans = []
            total_consumption = defaultdict(lambda: d(0))
            yield_losses = (0, 5, 12, 22, 10, 0)
            usage_factors = (d("0.98"), d("1.00"), d("1.06"), d("0.95"), d("1.03"), d("1.00"))
            for index in range(18):
                product = products[index % len(products)]
                product_index = index % len(products)
                expected_output = 200 * (1 + index % 3)
                good_output = expected_output - yield_losses[index % len(yield_losses)]
                damaged = index % 4
                planned = {
                    row.material_id: row.quantity * d(expected_output) / row.per_output
                    for row in bom_by_product[product.id]
                }
                actual = {}
                for row in bom_by_product[product.id]:
                    material = db.get(RawMaterial, row.material_id)
                    if material.name.startswith("200 g Laminated Pouch"):
                        actual[row.material_id] = d(good_output)
                    elif material.name.startswith("Corrugated Carton"):
                        actual[row.material_id] = planned[row.material_id]
                    else:
                        factor = usage_factors[(index + product_index) % len(usage_factors)]
                        actual[row.material_id] = (planned[row.material_id] * factor).quantize(QTY, rounding=ROUND_HALF_UP)
                    total_consumption[row.material_id] += actual[row.material_id]
                pouch = next(
                    (row for row in bom_by_product[product.id]
                     if db.get(RawMaterial, row.material_id).name.startswith("200 g Laminated Pouch")),
                    None,
                )
                if pouch and damaged:
                    total_consumption[pouch.material_id] += d(damaged)
                batch_plans.append({
                    "index": index, "product": product, "expected": expected_output,
                    "good": good_output, "damaged": damaged, "planned": planned,
                    "actual": actual, "created_at": NOW - timedelta(days=120 - index * 6),
                })

            opening_date = NOW - timedelta(days=240)
            for name, material in materials.items():
                estimated = total_consumption[material.id]
                opening_quantity = max(d("20"), estimated * d("1.10") + d("20"))
                record_movement(
                    db, "material", material.id, opening_quantity, material.unit,
                    "opening_balance", f"DEMO-OPEN-MAT-{material.id}",
                    created_at=opening_date,
                )
            for product in products:
                record_movement(
                    db, "finished", product.id, d("25"), product.unit,
                    "opening_balance", f"DEMO-OPEN-FIN-{product.sku}",
                    created_at=opening_date,
                )

            purchase_material_names = (
                "Rice Flour", "Besan Flour", "Urad Dal Flour", "Plantain", "Tapioca",
                "Groundnut Oil", "Palmolein Oil", "Peanuts", "Jaggery", "Sesame Seeds",
                "200 g Laminated Pouch", "Corrugated Carton",
            )
            for index, material_name in enumerate(purchase_material_names):
                material = materials[material_name]
                quantity = max(d("15"), total_consumption[material.id] * d("0.12"))
                supplier_for_material = {
                    material_name: supplier_name
                    for supplier_name, supplied in SUPPLIER_MATERIALS.items()
                    for material_name in supplied
                }
                supplier = suppliers[supplier_for_material[material_name]]
                rate = material.weighted_average_cost * d("1.02" if index % 2 else "0.98")
                created_at = NOW - timedelta(days=190 - index * 5)
                reference = f"DEMO-PUR-{index + 1:03d}"
                purchase = add_row(db, "purchases", Purchase(
                    reference=reference, supplier_id=supplier.id,
                    material_id=material.id, quantity=quantity, unit_rate=rate,
                    total=money(quantity * rate), created_at=created_at,
                ))
                lot = create_lot(
                    db, "material", material.id, f"DEMO-LOT-PUR-{index + 1:03d}",
                    (created_at + timedelta(days=365)).date(), created_at=created_at,
                )
                add_row(db, "inventory_lots", lot)
                old_quantity = sum(
                    (movement.quantity for movement in db.scalars(select(InventoryMovement).where(
                        InventoryMovement.item_type == "material",
                        InventoryMovement.item_id == material.id,
                    ))),
                    d(0),
                )
                # The receipt is appended to the ledger before the weighted cost update.
                material.weighted_average_cost = (
                    old_quantity * material.weighted_average_cost + quantity * rate
                ) / (old_quantity + quantity)
                record_movement(
                    db, "material", material.id, quantity, material.unit,
                    "purchase", reference, lot_id=lot.id, created_at=created_at,
                )
                add_audit(db, users["Accountant / Auditor"], "recorded purchase", "purchase", reference, created_at)

            for plan in batch_plans:
                index = plan["index"]
                product = plan["product"]
                run_ref = f"DEMO-RUN-{index + 1:03d}"
                run_date = plan["created_at"]
                run = add_row(db, "production_runs", ProductionRun(
                    reference=run_ref, product_id=product.id,
                    expected_output=plan["expected"], good_output=plan["good"],
                    damaged=plan["damaged"],
                    yield_variance=d(plan["good"] - plan["expected"]) / d(plan["expected"]) * d(100),
                    status="Completed", created_at=run_date,
                ))
                for bom in bom_by_product[product.id]:
                    material = db.get(RawMaterial, bom.material_id)
                    actual = plan["actual"][material.id]
                    record_movement(
                        db, "material", material.id, -actual, material.unit,
                        "production", run_ref, created_at=run_date,
                    )
                    consumption_qty = actual + d(plan["damaged"]) if material.name.startswith("200 g Laminated Pouch") else actual
                    add_row(db, "production_consumptions", ProductionConsumption(
                        production_run_id=run.id, material_id=material.id,
                        expected_quantity=plan["planned"][material.id],
                        quantity=consumption_qty, unit_cost=material.weighted_average_cost,
                    ))
                pouch = next(
                    (material for material in materials.values()
                     if material.name.startswith("200 g Laminated Pouch")),
                    None,
                )
                if pouch and plan["damaged"]:
                    record_movement(
                        db, "material", pouch.id, -d(plan["damaged"]), pouch.unit,
                        "production-damage", run_ref, created_at=run_date,
                    )
                finished_lot = create_lot(
                    db, "finished", product.id, run_ref,
                    (run_date + timedelta(days=180)).date(), created_at=run_date,
                )
                add_row(db, "inventory_lots", finished_lot)
                record_movement(
                    db, "finished", product.id, d(plan["good"]), product.unit,
                    "production", run_ref, lot_id=finished_lot.id, created_at=run_date,
                )
                for category, amount in (
                    ("Labour", d(750 + index * 45)),
                    ("Gas and power", d(260 + index * 20)),
                ):
                    expense_ref = f"DEMO-EXP-{index + 1:03d}-{category[:2].upper()}"
                    add_row(db, "expenses", Expense(
                        reference=expense_ref, category=category, amount=amount,
                        production_run_id=run.id, note="DEMO DATA - batch operating cost",
                        created_at=run_date,
                    ))
                add_audit(db, users["Production Supervisor"], "completed production", "production_run", run_ref, run_date)

            for index, material in enumerate(materials.values()):
                ledger_balance = sum(
                    (movement.quantity for movement in db.scalars(select(InventoryMovement).where(
                        InventoryMovement.item_type == "material",
                        InventoryMovement.item_id == material.id,
                    ))),
                    d(0),
                )
                material.reorder_level = max(
                    d("5"), ledger_balance + d("5") if index in (0, 5) else ledger_balance * d("0.45"),
                )

            orders = []
            invoices = []
            salesperson = users["Salesman"]
            rejected_indexes = {33, 34}
            submitted_indexes = {28, 29, 30, 31}
            approved_index = 32
            for index in range(35):
                customer = customers[(index * 3 + index // 5) % len(customers)]
                product = products[index % len(products)]
                qty = 60 + (index % 6) * 20
                created_at = NOW - timedelta(days=55 - index * 1.5)
                if index in rejected_indexes:
                    status = "Rejected"
                elif index in submitted_indexes:
                    status = "Submitted"
                elif index == approved_index:
                    status = "Approved"
                else:
                    status = "Approved"
                order = add_row(db, "orders", Order(
                    reference=f"DEMO-ORD-{index + 1:03d}",
                    customer_id=customer.id, product_id=product.id,
                    quantity=qty, unit_price=product.selling_price,
                    status=status, created_by=salesperson.id, created_at=created_at,
                ))
                orders.append(order)
                add_audit(db, salesperson, "submitted order", "order", order.reference, created_at)
                if index in rejected_indexes:
                    order.status = "Rejected"
                    add_audit(db, users["Admin"], "rejected order", "order", order.reference, created_at + timedelta(hours=1))
                    continue
                if index >= 28:
                    continue
                order.status = "Approved"
                invoice = build_invoice(db, order)
                invoice.number = f"DEMO/26-27/{index + 1:04d}"
                invoice.created_at = created_at + timedelta(hours=2)
                db.add(invoice)
                db.flush()
                add_tag(db, "invoices", invoice)
                invoices.append(invoice)
                add_audit(db, users["Admin"], "generated invoice", "invoice", invoice.number, invoice.created_at)

                if index < 10:
                    dispatch_qty = order.quantity
                elif index < 18:
                    dispatch_qty = max(1, order.quantity // 2)
                else:
                    dispatch_qty = 0
                if dispatch_qty:
                    dispatch_ref = f"DEMO-DSP-{index + 1:03d}"
                    dispatch_date = invoice.created_at + timedelta(days=1)
                    dispatch = add_row(db, "dispatches", Dispatch(
                        reference=dispatch_ref, invoice_id=invoice.id,
                        quantity=dispatch_qty, created_at=dispatch_date,
                    ))
                    record_movement(
                        db, "finished", product.id, -d(dispatch_qty), product.unit,
                        "dispatch", dispatch_ref, created_at=dispatch_date,
                    )
                    add_audit(db, users["Admin"], "dispatched order", "dispatch", dispatch.reference, dispatch_date)
                if index < 10:
                    order.status = "Dispatched"
                elif index < 18:
                    order.status = "Invoiced"
                else:
                    order.status = "Ready for dispatch"

            for index in range(15):
                invoice = invoices[index]
                amount = invoice.total if index < 6 else money(invoice.total * d("0.42"))
                payment_date = invoice.created_at + timedelta(days=4 + index % 5)
                payment_ref = f"DEMO-PAY-{index + 1:03d}"
                payment = add_row(db, "payments", Payment(
                    reference=payment_ref, invoice_id=invoice.id,
                    amount=amount, created_at=payment_date,
                ))
                add_audit(db, users["Accountant / Auditor"], "recorded payment", "payment", payment_ref, payment_date)
                if index < 6 and dispatched(db, invoice.id) == invoice.order.quantity:
                    invoice.order.status = "Completed"

            for product in products:
                available = sum(
                    (movement.quantity for movement in db.scalars(select(InventoryMovement).where(
                        InventoryMovement.item_type == "finished",
                        InventoryMovement.item_id == product.id,
                    ))),
                    d(0),
                )
                product.reorder_level = max(
                    d("40"), available + d("10") if product.id == products[2].id else d("80"),
                )

            # Add explicit adjustment movements for realistic cycle-count records.
            for index, material_name in enumerate(("Chilli Powder", "Salt & Spice Mix")):
                material = materials[material_name]
                adjustment_date = NOW - timedelta(days=12 - index)
                record_movement(
                    db, "material", material.id, d("2.5"), material.unit,
                    "adjustment", f"DEMO-ADJ-{index + 1:03d}", created_at=adjustment_date,
                )
                add_audit(db, users["Admin"], "posted stock adjustment", "inventory", str(material.id), adjustment_date)

            db.flush()
            registered = db.scalar(select(func.count(DemoDataRecord.id)).where(
                DemoDataRecord.batch_key == BATCH_KEY,
            ))
            movements = db.scalar(select(func.count(DemoDataRecord.id)).where(
                DemoDataRecord.batch_key == BATCH_KEY,
                DemoDataRecord.entity_type == "inventory_movements",
            ))
            audit_rows = db.scalar(select(func.count(DemoDataRecord.id)).where(
                DemoDataRecord.batch_key == BATCH_KEY,
                DemoDataRecord.entity_type == "audit_logs",
            ))
            print(f"Created Sri Lakshmi Foods demo dataset ({BATCH_KEY}).")
            print(f"Company profile: {company.name}, Coimbatore, Tamil Nadu, India.")
            print("Created: 10 products, 15 raw materials, 8 customers, 10 suppliers, 5 users, 10 recipes.")
            print("Created: 35 orders, 18 production batches, 12 purchases, 28 invoices, 15 payments.")
            print(f"Tagged demo records: {registered} total, {movements} stock movements, {audit_rows} audit activities.")
            print(f"Orders: {Counter(order.status for order in orders)}")
            print(f"Outstanding on demo invoices: INR {money(sum((outstanding(db, invoice.id) for invoice in invoices), d(0)))}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo()
