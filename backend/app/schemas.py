from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class PurchaseRequest(BaseModel):
    material_id: int
    quantity: Decimal = Field(gt=0)
    unit_rate: Decimal = Field(ge=0)
    reference: str
    batch_code: str | None = Field(default=None, max_length=80)
    expiry_date: date | None = None


class ProductionRequest(BaseModel):
    product_id: int
    expected_output: int = Field(gt=0)
    good_output: int = Field(ge=0)
    damaged: int = Field(ge=0, default=0)
    actual_consumption: dict[int, Decimal]
    reference: str
    finished_expiry_date: date | None = None


class OrderRequest(BaseModel):
    customer_id: int
    product_id: int
    quantity: int = Field(gt=0)


class PaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    reference: str


class ReorderPolicyRequest(BaseModel):
    minimum_stock: Decimal = Field(ge=0)
    target_coverage_days: int = Field(ge=1, le=365)
