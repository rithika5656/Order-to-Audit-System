from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _username_default(context):
    email = context.get_current_parameters().get("email", "")
    return email.split("@", 1)[0].strip().lower()[:80]


class Role(Base):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    description: Mapped[str] = mapped_column(String(160))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, default=_username_default)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(ForeignKey("roles.code"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.current_timestamp(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    customer_type: Mapped[str] = mapped_column(String(40), default="Retailer")
    state: Mapped[str] = mapped_column(String(80))
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(80), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    assigned_user: Mapped[User | None] = relationship()


class LoginActivity(Base):
    __tablename__ = "login_activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    successful: Mapped[bool] = mapped_column(Boolean)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    identifier: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    sku: Mapped[str] = mapped_column(String(60), unique=True)
    category: Mapped[str] = mapped_column(String(80), default="Snacks")
    pack_size: Mapped[str] = mapped_column(String(40), default="200 g")
    unit: Mapped[str] = mapped_column(String(24), default="packet")
    selling_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("5.00"))
    hsn_code: Mapped[str] = mapped_column(String(24), default="210690")
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    reorder_days: Mapped[int] = mapped_column(Integer, default=14)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RawMaterial(Base):
    __tablename__ = "raw_materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    unit: Mapped[str] = mapped_column(String(24))
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    reorder_days: Mapped[int] = mapped_column(Integer, default=14)
    weighted_average_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    contact: Mapped[str | None] = mapped_column(String(80), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payment_terms: Mapped[str] = mapped_column(String(80), default="Due on receipt")


class SupplierMaterial(Base):
    __tablename__ = "supplier_materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("raw_materials.id"), index=True)
    __table_args__ = (UniqueConstraint("supplier_id", "material_id"),)


class BomItem(Base):
    __tablename__ = "bom_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("raw_materials.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    per_output: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("200"))
    __table_args__ = (UniqueConstraint("product_id", "material_id"),)
    material: Mapped[RawMaterial] = relationship()


class Purchase(Base):
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("raw_materials.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(24), default="Submitted", index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    customer: Mapped[Customer] = relationship()
    product: Mapped[Product] = relationship()


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(40), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    taxable: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    cgst: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    sgst: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    igst: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    order: Mapped[Order] = relationship()


class Dispatch(Base):
    __tablename__ = "dispatches"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True)
    category: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    production_run_id: Mapped[int | None] = mapped_column(ForeignKey("production_runs.id"), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProductionRun(Base):
    __tablename__ = "production_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    expected_output: Mapped[int] = mapped_column(Integer)
    good_output: Mapped[int] = mapped_column(Integer)
    damaged: Mapped[int] = mapped_column(Integer, default=0)
    yield_variance: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    status: Mapped[str] = mapped_column(String(24), default="Completed", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProductionConsumption(Base):
    __tablename__ = "production_consumption"
    id: Mapped[int] = mapped_column(primary_key=True)
    production_run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("raw_materials.id"))
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    __table_args__ = (UniqueConstraint("production_run_id", "material_id"),)


class InventoryLot(Base):
    __tablename__ = "inventory_lots"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_type: Mapped[str] = mapped_column(String(24), index=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    batch_code: Mapped[str] = mapped_column(String(80))
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("item_type", "item_id", "batch_code"),)


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_type: Mapped[str] = mapped_column(String(24), index=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(24))
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(60))
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_lots.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("source_type", "source_id", "item_type", "item_id"),)


class InventoryLotAllocation(Base):
    __tablename__ = "inventory_lot_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    movement_id: Mapped[int] = mapped_column(ForeignKey("inventory_movements.id"), index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("inventory_lots.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    __table_args__ = (UniqueConstraint("movement_id", "lot_id"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    address: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(80))
    country: Mapped[str] = mapped_column(String(80), default="India")
    business: Mapped[str] = mapped_column(String(240))
    demo_data: Mapped[bool] = mapped_column(Boolean, default=False)


class DemoDataRecord(Base):
    __tablename__ = "demo_data_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("batch_key", "entity_type", "entity_id"),)
