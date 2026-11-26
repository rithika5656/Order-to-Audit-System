"""Safely remove only records registered by seed_demo.py."""
import argparse
import os

from sqlalchemy import delete, or_, select

from app.database import Base, SessionLocal, engine
from app.models import (
    AuditLog, BomItem, CompanyProfile, Customer, DemoDataRecord, Dispatch, Expense,
    InventoryLot, InventoryLotAllocation, InventoryMovement, Invoice, Order,
    Payment, Product, ProductionConsumption, ProductionRun, Purchase, RawMaterial,
    Supplier, SupplierMaterial, User,
)

BATCH_KEY = "sri-lakshmi-foods-demo-v1"

ENTITY_MODELS = {
    "audit_logs": AuditLog,
    "bom_items": BomItem,
    "company_profiles": CompanyProfile,
    "customers": Customer,
    "dispatches": Dispatch,
    "expenses": Expense,
    "inventory_lots": InventoryLot,
    "inventory_movements": InventoryMovement,
    "invoices": Invoice,
    "orders": Order,
    "payments": Payment,
    "products": Product,
    "production_consumptions": ProductionConsumption,
    "production_runs": ProductionRun,
    "purchases": Purchase,
    "raw_materials": RawMaterial,
    "supplier_materials": SupplierMaterial,
    "suppliers": Supplier,
    "users": User,
}

# If a real record has been created against demo master data, stop rather than
# deleting either the real record or its referenced demo parent.
DEPENDENCIES = (
    ("orders", Order, Order.customer_id, "customers"),
    ("orders", Order, Order.product_id, "products"),
    ("orders", Order, Order.created_by, "users"),
    ("invoices", Invoice, Invoice.order_id, "orders"),
    ("dispatches", Dispatch, Dispatch.invoice_id, "invoices"),
    ("payments", Payment, Payment.invoice_id, "invoices"),
    ("production_runs", ProductionRun, ProductionRun.product_id, "products"),
    ("production_consumptions", ProductionConsumption, ProductionConsumption.production_run_id, "production_runs"),
    ("production_consumptions", ProductionConsumption, ProductionConsumption.material_id, "raw_materials"),
    ("expenses", Expense, Expense.production_run_id, "production_runs"),
    ("purchases", Purchase, Purchase.supplier_id, "suppliers"),
    ("purchases", Purchase, Purchase.material_id, "raw_materials"),
    ("bom_items", BomItem, BomItem.product_id, "products"),
    ("bom_items", BomItem, BomItem.material_id, "raw_materials"),
    ("supplier_materials", SupplierMaterial, SupplierMaterial.supplier_id, "suppliers"),
    ("supplier_materials", SupplierMaterial, SupplierMaterial.material_id, "raw_materials"),
    ("audit_logs", AuditLog, AuditLog.user_id, "users"),
)

AUDIT_REFERENCES = (
    ("order", Order.reference, "orders"),
    ("invoice", Invoice.number, "invoices"),
    ("dispatch", Dispatch.reference, "dispatches"),
    ("production_run", ProductionRun.reference, "production_runs"),
    ("purchase", Purchase.reference, "purchases"),
    ("payment", Payment.reference, "payments"),
    ("product", Product.id, "products"),
    ("customer", Customer.id, "customers"),
    ("supplier", Supplier.id, "suppliers"),
    ("material", RawMaterial.id, "raw_materials"),
    ("inventory", RawMaterial.id, "raw_materials"),
)


def reset_demo(confirm: bool = False):
    if not confirm:
        raise RuntimeError("Reset requires --confirm. Only the registered Sri Lakshmi Foods demo batch is targeted.")
    if os.getenv("DEMO_MODE", "false").lower() != "true":
        raise RuntimeError("Refusing to reset demo records when DEMO_MODE is disabled.")

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        with db.begin():
            tags = list(db.scalars(select(DemoDataRecord).where(
                DemoDataRecord.batch_key == BATCH_KEY,
            )))
            if not tags:
                print("No registered Sri Lakshmi Foods demo records found; nothing removed.")
                return

            ids_by_type = {}
            for tag in tags:
                ids_by_type.setdefault(tag.entity_type, set()).add(tag.entity_id)
            for entity_type, model, foreign_key, parent_type in DEPENDENCIES:
                parent_ids = ids_by_type.get(parent_type, set())
                if not parent_ids:
                    continue
                child_ids = {
                    str(value) for value in db.scalars(
                        select(model.id).where(foreign_key.in_([int(value) for value in parent_ids]))
                    )
                }
                unregistered = child_ids - ids_by_type.get(entity_type, set())
                if unregistered:
                    raise RuntimeError(
                        f"Reset stopped: non-demo {entity_type} records reference demo {parent_type}; "
                        "preserve those records and detach them before resetting demo data."
                    )

            demo_audit_ids = ids_by_type.get("audit_logs", set())
            for audit_entity, reference_column, parent_type in AUDIT_REFERENCES:
                parent_ids = ids_by_type.get(parent_type, set())
                if not parent_ids:
                    continue
                parent_model = ENTITY_MODELS[parent_type]
                parent_values = [
                    str(value) for value in db.scalars(select(reference_column).where(
                        parent_model.id.in_([int(value) for value in parent_ids])
                    ))
                ]
                if parent_type == "raw_materials":
                    parent_values.extend(
                        str(value) for value in parent_ids
                    )
                unregistered_audit = db.scalar(select(AuditLog.id).where(
                    AuditLog.entity == audit_entity,
                    AuditLog.entity_id.in_(parent_values),
                    ~AuditLog.id.in_([int(value) for value in demo_audit_ids] or [-1]),
                ).limit(1))
                if unregistered_audit:
                    raise RuntimeError(
                        f"Reset stopped: a non-demo audit activity references demo {parent_type}."
                    )

            movement_ids = [int(value) for value in ids_by_type.get("inventory_movements", set())]
            lot_ids = [int(value) for value in ids_by_type.get("inventory_lots", set())]
            material_ids = [int(value) for value in ids_by_type.get("raw_materials", set())]
            product_ids = [int(value) for value in ids_by_type.get("products", set())]
            for item_type, item_ids in (("material", material_ids), ("finished", product_ids)):
                if not item_ids:
                    continue
                unregistered_movement = db.scalar(select(InventoryMovement.id).where(
                    InventoryMovement.item_type == item_type,
                    InventoryMovement.item_id.in_(item_ids),
                    ~InventoryMovement.id.in_(movement_ids or [-1]),
                ).limit(1))
                unregistered_lot = db.scalar(select(InventoryLot.id).where(
                    InventoryLot.item_type == item_type,
                    InventoryLot.item_id.in_(item_ids),
                    ~InventoryLot.id.in_(lot_ids or [-1]),
                ).limit(1))
                if unregistered_movement or unregistered_lot:
                    raise RuntimeError(
                        f"Reset stopped: untagged {item_type} inventory records reference demo items."
                    )

            if movement_ids or lot_ids:
                allocation_query = select(InventoryLotAllocation.id).where(
                    or_(
                        InventoryLotAllocation.movement_id.in_(movement_ids or [-1]),
                        InventoryLotAllocation.lot_id.in_(lot_ids or [-1]),
                    )
                )
                allocation_ids = list(db.scalars(allocation_query))
                for allocation in allocation_ids:
                    pair = db.execute(select(
                        InventoryLotAllocation.movement_id,
                        InventoryLotAllocation.lot_id,
                    ).where(InventoryLotAllocation.id == allocation)).one()
                    if pair.movement_id not in movement_ids or pair.lot_id not in lot_ids:
                        raise RuntimeError("Reset stopped: a stock-lot allocation links demo and non-demo records.")

            allocation_filter = []
            if movement_ids:
                allocation_filter.append(InventoryLotAllocation.movement_id.in_(movement_ids))
            if lot_ids:
                allocation_filter.append(InventoryLotAllocation.lot_id.in_(lot_ids))
            if allocation_filter:
                db.execute(delete(InventoryLotAllocation).where(or_(*allocation_filter)))

            deletion_order = (
                "payments", "dispatches", "expenses", "production_consumptions",
                "invoices", "production_runs", "purchases", "supplier_materials",
                "bom_items", "orders", "inventory_movements", "inventory_lots",
                "audit_logs", "suppliers", "customers", "products", "raw_materials",
                "users", "company_profiles",
            )
            for entity_type in deletion_order:
                ids = ids_by_type.get(entity_type, set())
                if ids:
                    model = ENTITY_MODELS[entity_type]
                    db.execute(delete(model).where(
                        model.id.in_([int(value) for value in ids])
                    ))
            db.execute(delete(DemoDataRecord).where(DemoDataRecord.batch_key == BATCH_KEY))
            print(f"Removed {len(tags)} registered demo records. Untagged application records were not targeted.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Safely reset Sri Lakshmi Foods demo data.")
    parser.add_argument("--confirm", action="store_true", help="confirm removal of the registered demo batch")
    args = parser.parse_args()
    reset_demo(confirm=args.confirm)
