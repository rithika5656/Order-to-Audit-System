from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    BomItem, Customer, Dispatch, InventoryMovement, Invoice, Order, Payment,
    Product, RawMaterial,
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


def add_movement(db: Session, item_type: str, item_id: int, qty: Decimal, unit: str, source: str, source_id: str):
    new_balance = balance(db, item_type, item_id) + qty
    if new_balance < 0:
        raise HTTPException(status_code=409, detail=f"Insufficient {item_type} inventory (available {new_balance - qty})")
    movement = InventoryMovement(
        item_type=item_type, item_id=item_id, quantity=qty, unit=unit,
        source_type=source, source_id=source_id,
    )
    db.add(movement)
    db.flush()


def available_for_order(db: Session, product_id: int) -> Decimal:
    return balance(db, "finished", product_id)


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
