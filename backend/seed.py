from decimal import Decimal
import os

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import BomItem, Customer, InventoryMovement, Product, RawMaterial, Role, Supplier, User
from app.security import hash_password


def seed():
    if os.getenv("DEMO_MODE", "true").lower() != "true":
        raise RuntimeError("Refusing to seed demo accounts when DEMO_MODE is disabled.")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.scalar(select(User.id).limit(1)):
            print("Seed data already exists; no changes made.")
            return

        roles = ["Admin", "Salesman", "Production Supervisor", "Accountant / Auditor", "Owner"]
        db.add_all([Role(code=role, description=f"{role} application role") for role in roles])
        db.flush()
        users = [
            ("NutriLedger Admin", "admin@nutriledger.local", "Admin"),
            ("Salesman A", "sales.a@nutriledger.local", "Salesman"),
            ("Production Supervisor", "production@nutriledger.local", "Production Supervisor"),
            ("Accountant", "accountant@nutriledger.local", "Accountant / Auditor"),
            ("Business Owner", "owner@nutriledger.local", "Owner"),
        ]
        for name, email, role in users:
            db.add(User(name=name, email=email, role=role, password_hash=hash_password("NutriLedger2026!")))

        product = Product(name="Murukku 200 g", sku="MUR-200", category="Traditional Snacks",
                          pack_size="200 g", selling_price=Decimal("50.00"),
                          gst_rate=Decimal("5.00"), hsn_code="210690")
        db.add(product)
        db.add_all([
            Customer(name="Retailer A", customer_type="Retailer", state="Tamil Nadu", gstin="33ABCDE1234F1Z5"),
            Customer(name="Distributor B", customer_type="Distributor", state="Karnataka", gstin="29ABCDE1234F1Z2"),
        ])
        supplier = Supplier(name="South Foods Supply", contact="+91 90000 00000")
        db.add(supplier)
        materials_data = [
            ("Flour", "kg", Decimal("20"), Decimal("42")),
            ("Cooking oil", "litre", Decimal("10"), Decimal("140")),
            ("Salt and spice mix", "kg", Decimal("2"), Decimal("200")),
            ("200 g pouch", "pieces", Decimal("100"), Decimal("2.50")),
            ("Carton", "pieces", Decimal("10"), Decimal("15")),
        ]
        materials = {}
        for name, unit, reorder, cost in materials_data:
            material = RawMaterial(name=name, unit=unit, reorder_level=reorder, weighted_average_cost=cost)
            db.add(material)
            materials[name] = material
        db.flush()
        db.add_all([
            BomItem(product_id=product.id, material_id=materials["Flour"].id, quantity=Decimal("40"), per_output=Decimal("200")),
            BomItem(product_id=product.id, material_id=materials["Cooking oil"].id, quantity=Decimal("10"), per_output=Decimal("200")),
            BomItem(product_id=product.id, material_id=materials["Salt and spice mix"].id, quantity=Decimal("1.2"), per_output=Decimal("200")),
            BomItem(product_id=product.id, material_id=materials["200 g pouch"].id, quantity=Decimal("200"), per_output=Decimal("200")),
            BomItem(product_id=product.id, material_id=materials["Carton"].id, quantity=Decimal("10"), per_output=Decimal("200")),
        ])
        opening = {"Flour": Decimal("100"), "Cooking oil": Decimal("30"),
                   "Salt and spice mix": Decimal("5"), "200 g pouch": Decimal("500"),
                   "Carton": Decimal("30")}
        for name, qty in opening.items():
            db.add(InventoryMovement(item_type="material", item_id=materials[name].id,
                                    quantity=qty, unit=materials[name].unit,
                                    source_type="opening_balance", source_id=f"OPEN-{name}"))
        db.add(InventoryMovement(item_type="finished", item_id=product.id,
                                quantity=Decimal("50"), unit=product.unit,
                                source_type="opening_balance", source_id="OPEN-MUR-200"))
        db.commit()
        print("Created benchmark data and five demo users (development only).")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
