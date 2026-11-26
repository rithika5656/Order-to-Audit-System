from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .models import (
    BomItem, Customer, Dispatch, InventoryLot, InventoryLotAllocation,
    InventoryMovement, Invoice, Order, Payment, Product, RawMaterial,
)


CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def balance(db: Session, item_type: str, item_id: int) -> Decimal:
    value = db.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity), 0)).where(
            InventoryMovement.item_type == item_type,
            InventoryMovement.item_id == item_id,
        )
    )
    return Decimal(value)


def lot_balance(db: Session, lot_id: int) -> Decimal:
    received = db.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity), 0)).where(
            InventoryMovement.lot_id == lot_id,
        )
    )
    allocated = db.scalar(
        select(func.coalesce(func.sum(InventoryLotAllocation.quantity), 0)).where(
            InventoryLotAllocation.lot_id == lot_id,
        )
    )
    return Decimal(received) - Decimal(allocated)


def create_lot(
    db: Session,
    item_type: str,
    item_id: int,
    batch_code: str,
    expiry_date: date | None = None,
    created_at: datetime | None = None,
) -> InventoryLot:
    batch_code = batch_code.strip()
    if not batch_code:
        raise HTTPException(status_code=422, detail="Batch code must not be empty")
    existing = db.scalar(select(InventoryLot).where(
        InventoryLot.item_type == item_type,
        InventoryLot.item_id == item_id,
        InventoryLot.batch_code == batch_code,
    ))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Batch code already exists for this inventory item")
    lot = InventoryLot(
        item_type=item_type, item_id=item_id, batch_code=batch_code,
        expiry_date=expiry_date, created_at=created_at or datetime.utcnow(),
    )
    db.add(lot)
    db.flush()
    return lot


def add_movement(
    db: Session,
    item_type: str,
    item_id: int,
    qty: Decimal,
    unit: str,
    source: str,
    source_id: str,
    lot_id: int | None = None,
    created_at: datetime | None = None,
):
    allocations: list[tuple[int, Decimal]] = []
    new_balance = balance(db, item_type, item_id) + qty
    if new_balance < 0:
        raise HTTPException(status_code=409, detail=f"Insufficient {item_type} inventory (available {new_balance - qty})")
    if qty > 0 and lot_id is not None:
        lot = db.get(InventoryLot, lot_id)
        if lot is None or lot.item_type != item_type or lot.item_id != item_id:
            raise HTTPException(status_code=422, detail="Inventory lot does not match the movement item")
    if qty < 0 and lot_id is None:
        required = -qty
        legacy_balance = db.scalar(select(func.coalesce(func.sum(InventoryMovement.quantity), 0)).where(
            InventoryMovement.item_type == item_type,
            InventoryMovement.item_id == item_id,
            InventoryMovement.lot_id.is_(None),
        ))
        allocated_from_legacy_movements = db.scalar(
            select(func.coalesce(func.sum(InventoryLotAllocation.quantity), 0))
            .join(InventoryMovement, InventoryMovement.id == InventoryLotAllocation.movement_id)
            .where(
                InventoryMovement.item_type == item_type,
                InventoryMovement.item_id == item_id,
                InventoryMovement.lot_id.is_(None),
            )
        )
        available_legacy = max(
            Decimal("0"), Decimal(legacy_balance) + Decimal(allocated_from_legacy_movements),
        )
        lots = list(db.scalars(
            select(InventoryLot).where(
                InventoryLot.item_type == item_type,
                InventoryLot.item_id == item_id,
            ).order_by(
                case((InventoryLot.expiry_date.is_(None), 1), else_=0),
                InventoryLot.expiry_date,
                InventoryLot.created_at,
                InventoryLot.id,
            )
        ))
        available_lots = []
        for lot in lots:
            if lot.expiry_date is not None and lot.expiry_date < date.today():
                continue
            available = lot_balance(db, lot.id)
            if available > 0:
                available_lots.append((lot.id, available))
        eligible = available_legacy + sum((quantity for _, quantity in available_lots), Decimal("0"))
        if required > eligible:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient non-expired {item_type} stock (available {eligible})",
            )
        remaining = required
        for current_lot_id, available in available_lots:
            if remaining <= 0:
                break
            take = min(available, remaining)
            if take > 0:
                allocations.append((current_lot_id, take))
                remaining -= take
    movement = InventoryMovement(
        item_type=item_type, item_id=item_id, quantity=qty, unit=unit,
        source_type=source, source_id=source_id, lot_id=lot_id,
        created_at=created_at or datetime.utcnow(),
    )
    db.add(movement)
    db.flush()
    for allocated_lot_id, allocated_quantity in allocations:
        db.add(InventoryLotAllocation(
            movement_id=movement.id,
            lot_id=allocated_lot_id,
            quantity=allocated_quantity,
        ))
    db.flush()
    return movement


def stock_intelligence(db: Session, item_type: str, item, window_days: int = 30) -> dict:
    item_id = item.id
    current = balance(db, item_type, item_id)
    expired_lots = list(db.scalars(select(InventoryLot).where(
        InventoryLot.item_type == item_type,
        InventoryLot.item_id == item_id,
        InventoryLot.expiry_date < date.today(),
    )))
    expired_quantity = sum(
        (max(Decimal("0"), lot_balance(db, lot.id)) for lot in expired_lots),
        Decimal("0"),
    )
    available = max(Decimal("0"), current - expired_quantity)
    minimum = Decimal(item.reorder_level)
    target_days = item.reorder_days
    usage_sources = ("production", "production-damage") if item_type == "material" else ("dispatch",)
    start = datetime.utcnow() - timedelta(days=window_days)
    consumed = db.scalar(select(func.coalesce(func.sum(-InventoryMovement.quantity), 0)).where(
        InventoryMovement.item_type == item_type,
        InventoryMovement.item_id == item_id,
        InventoryMovement.quantity < 0,
        InventoryMovement.source_type.in_(usage_sources),
        InventoryMovement.created_at >= start,
    ))
    average_daily_usage = Decimal(consumed) / Decimal(window_days)
    coverage_days = available / average_daily_usage if average_daily_usage > 0 else None
    target_stock = max(minimum, average_daily_usage * Decimal(target_days))
    suggested = max(Decimal("0"), target_stock - available)
    if average_daily_usage == 0 and available <= minimum:
        suggested = max(Decimal("0"), minimum * 2 - available)
    low = available <= minimum or (coverage_days is not None and coverage_days <= Decimal(target_days))
    return {
        "id": item_id,
        "name": item.name,
        "item_type": item_type,
        "quantity": str(current),
        "available_quantity": str(available),
        "expired_quantity": str(expired_quantity),
        "unit": item.unit,
        "minimum_stock": str(minimum),
        "target_coverage_days": target_days,
        "usage_window_days": window_days,
        "consumed_in_window": str(Decimal(consumed)),
        "average_daily_usage": str(average_daily_usage.quantize(Decimal("0.001"))),
        "estimated_days_remaining": (
            str(coverage_days.quantize(Decimal("0.1"))) if coverage_days is not None else None
        ),
        "suggested_reorder_quantity": str(suggested.quantize(Decimal("0.001"))),
        "low_stock": low,
    }


def lot_summary(db: Session, item_type: str, item_id: int) -> list[dict]:
    lots = db.scalars(select(InventoryLot).where(
        InventoryLot.item_type == item_type,
        InventoryLot.item_id == item_id,
    ).order_by(InventoryLot.expiry_date, InventoryLot.created_at))
    rows = []
    for lot in lots:
        quantity = lot_balance(db, lot.id)
        if quantity <= 0:
            continue
        rows.append({
            "id": lot.id, "batch_code": lot.batch_code,
            "expiry_date": lot.expiry_date.isoformat() if lot.expiry_date else None,
            "quantity": str(quantity),
            "expired": lot.expiry_date is not None and lot.expiry_date < date.today(),
            "expiring_soon": (
                lot.expiry_date is not None
                and date.today() <= lot.expiry_date <= date.today() + timedelta(days=30)
            ),
        })
    return rows


def available_for_order(db: Session, product_id: int) -> Decimal:
    total = balance(db, "finished", product_id)
    expired = Decimal("0")
    for lot in db.scalars(select(InventoryLot).where(
        InventoryLot.item_type == "finished",
        InventoryLot.item_id == product_id,
        InventoryLot.expiry_date < date.today(),
    )):
        expired += max(Decimal("0"), lot_balance(db, lot.id))
    return max(Decimal("0"), total - expired)


def build_invoice(db: Session, order: Order) -> Invoice:
    customer = db.get(Customer, order.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    taxable = money(order.unit_price * order.quantity)
    rate = order.product.gst_rate / Decimal("100")
    if customer.state.strip().casefold() == "tamil nadu":
        cgst = money(taxable * rate / 2)
        sgst = cgst
        igst = Decimal("0.00")
    else:
        cgst = sgst = Decimal("0.00")
        igst = money(taxable * rate)
    invoice = Invoice(
        number=f"NL-{order.reference}", order_id=order.id,
        taxable=taxable, cgst=cgst, sgst=sgst, igst=igst,
        total=taxable + cgst + sgst + igst,
    )
    return invoice


def outstanding(db: Session, invoice_id: int) -> Decimal:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    paid = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.invoice_id == invoice_id))
    return money(invoice.total - Decimal(paid))


def dispatched(db: Session, invoice_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(Dispatch.quantity), 0)).where(Dispatch.invoice_id == invoice_id)))


def bom_expected(db: Session, product_id: int, output: int) -> dict[int, Decimal]:
    result = {}
    for item in db.scalars(select(BomItem).where(BomItem.product_id == product_id)):
        result[item.material_id] = item.quantity * Decimal(output) / item.per_output
    return result
