from datetime import date
from decimal import Decimal
import re

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    remember_me: bool = False

    @field_validator("email")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().lower()


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    token: str = Field(min_length=32, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[a-z]", value) or not re.search(r"[A-Z]", value) or not re.search(r"\d", value):
            raise ValueError("Password must include uppercase, lowercase, and numeric characters")
        return value


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[a-z]", value) or not re.search(r"[A-Z]", value) or not re.search(r"\d", value):
            raise ValueError("Password must include uppercase, lowercase, and numeric characters")
        return value


class UserCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=80)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=128)
    role: str = Field(min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=40)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]+", value):
            raise ValueError("Username may contain letters, numbers, dots, underscores, and hyphens")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[a-z]", value) or not re.search(r"[A-Z]", value) or not re.search(r"\d", value):
            raise ValueError("Password must include uppercase, lowercase, and numeric characters")
        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        from .roles import ROLES

        if value not in ROLES:
            raise ValueError("Select one of the supported user roles")
        return value


class UserUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=80)
    active: bool | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str | None) -> str | None:
        if value is not None:
            from .roles import ROLES

            if value not in ROLES:
                raise ValueError("Select one of the supported user roles")
        return value


class AdminPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[a-z]", value) or not re.search(r"[A-Z]", value) or not re.search(r"\d", value):
            raise ValueError("Password must include uppercase, lowercase, and numeric characters")
        return value


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


class OrderEditRequest(BaseModel):
    customer_id: int | None = None
    product_id: int | None = None
    quantity: int | None = Field(default=None, gt=0)


class CustomerAssignmentRequest(BaseModel):
    user_id: int | None = None


class ProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    sku: str | None = Field(default=None, min_length=1, max_length=60)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    pack_size: str | None = Field(default=None, min_length=1, max_length=40)
    selling_price: Decimal | None = Field(default=None, ge=0)
    gst_rate: Decimal | None = Field(default=None, ge=0, le=100)
    hsn_code: str | None = Field(default=None, min_length=1, max_length=24)


class PaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    reference: str


class ReorderPolicyRequest(BaseModel):
    minimum_stock: Decimal = Field(ge=0)
    target_coverage_days: int = Field(ge=1, le=365)
