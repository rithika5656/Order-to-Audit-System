import os
import csv
import hashlib
import secrets
import smtplib
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from io import BytesIO, StringIO
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import (
    AuditLog, BomItem, CompanyProfile, Customer, Dispatch, Expense, InventoryLot,
    InventoryLotAllocation, InventoryMovement, Invoice, LoginActivity, LoginAttempt,
    Order, PasswordResetToken, Payment, Product, ProductionConsumption, ProductionRun,
    Purchase, RawMaterial, Role, Supplier, SupplierMaterial, User,
)
from .schemas import (
    AdminPasswordResetRequest, CustomerAssignmentRequest, ForgotPasswordRequest,
    LoginRequest, OrderEditRequest, OrderRequest, PasswordChangeRequest,
    PasswordResetRequest, PaymentRequest, ProductUpdateRequest, ProductionRequest,
    PurchaseRequest, ReorderPolicyRequest, UserCreateRequest, UserUpdateRequest,
)
from .security import (
    DEMO_MODE, create_token, current_user, hash_password, password_hasher,
    require_roles, verify_password,
)
from .roles import (
    ACCOUNTANT_AUDITOR, FACTORY_ADMIN, OWNER, PRODUCTION_SUPERVISOR, ROLES,
    SALESMAN, canonical_role,
)
from .services import (
    add_movement, available_for_order, balance, bom_expected, build_invoice, create_lot,
    dispatched, lot_balance, lot_summary, money, outstanding, stock_intelligence,
)


app = FastAPI(title="NutriLedger API", version="1.0.0")
origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:8080,http://127.0.0.1:8080",
)
origins = [origin.strip() for origin in origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)
Base.metadata.create_all(bind=engine)

ADMIN = (FACTORY_ADMIN,)
PRODUCTION = (FACTORY_ADMIN, PRODUCTION_SUPERVISOR)
SALES = (FACTORY_ADMIN, SALESMAN)
FINANCE = (FACTORY_ADMIN, ACCOUNTANT_AUDITOR, OWNER)
USER_MANAGERS = (FACTORY_ADMIN, OWNER)
COOKIE_NAME = "nutriledger_access"
CSRF_COOKIE_NAME = "nutriledger_csrf"
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT = timedelta(minutes=15)
RESET_TOKEN_LIFETIME = timedelta(hours=1)
_dummy_password_hash = hash_password("not-a-real-user-password")


def audit(db: Session, user: User | None, action: str, entity: str, entity_id: str):
    db.add(AuditLog(user_id=user.id if user else None, action=action, entity=entity, entity_id=entity_id))


def reference(prefix: str, value: str):
    return f"{prefix}-{value.strip()}"


def _secure_cookie():
    return os.getenv("COOKIE_SECURE", "false" if DEMO_MODE else "true").lower() == "true"


def _set_session_cookies(response: Response, user: User, remember_me: bool = False):
    lifetime = (
        int(os.getenv("JWT_REMEMBER_EXPIRE_DAYS", "14")) * 24 * 60 * 60
        if remember_me else int(os.getenv("JWT_EXPIRE_MINUTES", "60")) * 60
    )
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_token(user, remember_me=remember_me),
        max_age=lifetime if remember_me else None,
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=lifetime if remember_me else None,
        httponly=False,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
    )
    return csrf_token


@app.middleware("http")
async def protect_cookie_authenticated_requests(request: Request, call_next):
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.cookies.get(COOKIE_NAME)
        and request.url.path != "/api/auth/login"
    ):
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        header_token = request.headers.get("X-CSRF-Token", "")
        if not cookie_token or not secrets.compare_digest(cookie_token, header_token):
            return JSONResponse(status_code=403, content={"detail": "CSRF token is missing or invalid."})
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "NutriLedger"}


@app.post("/api/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    remote = request.client.host if request.client else "unknown"
    throttle_key = hashlib.sha256(f"{remote}:{payload.email}".encode()).hexdigest()
    attempt = db.get(LoginAttempt, throttle_key)
    if attempt and attempt.locked_until and attempt.locked_until > now:
        db.add(LoginActivity(
            user_id=None, email=payload.email, successful=False, ip_address=remote, created_at=now,
        ))
        db.commit()
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in 15 minutes.")
    if attempt and now - attempt.updated_at > LOGIN_LOCKOUT:
        attempt.failed_attempts = 0
        attempt.locked_until = None
    elif attempt and attempt.locked_until:
        attempt.failed_attempts = 0
        attempt.locked_until = None

    user = db.scalar(select(User).where(or_(
        func.lower(User.email) == payload.email,
        func.lower(User.username) == payload.email,
    )))
    password_ok = verify_password(payload.password, user.password_hash if user else _dummy_password_hash)
    if user is None or not user.active or not password_ok:
        if attempt is None:
            attempt = LoginAttempt(identifier=throttle_key, failed_attempts=0)
            db.add(attempt)
        attempt.failed_attempts += 1
        attempt.updated_at = now
        if attempt.failed_attempts >= LOGIN_MAX_ATTEMPTS:
            attempt.locked_until = now + LOGIN_LOCKOUT
        db.add(LoginActivity(
            user_id=user.id if user else None,
            email=payload.email,
            successful=False,
            ip_address=remote,
            created_at=now,
        ))
        db.commit()
        if attempt.locked_until:
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again in 15 minutes.")
        raise HTTPException(status_code=401, detail="Invalid username/email or password")

    if not user.password_hash.startswith("$argon2") or password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    user.last_login_at = now
    if attempt:
        db.delete(attempt)
    db.add(LoginActivity(
        user_id=user.id, email=user.email, successful=True, ip_address=remote, created_at=now,
    ))
    db.commit()
    csrf_token = _set_session_cookies(response, user, remember_me=payload.remember_me)
    return {"csrf_token": csrf_token, "user": {
        "id": user.id, "name": user.name, "username": user.username,
        "email": user.email, "role": canonical_role(user.role),
        "must_change_password": user.must_change_password,
    }}


@app.get("/api/auth/me")
def me(request: Request, user: User = Depends(current_user)):
    return {
        "id": user.id, "name": user.name, "username": user.username,
        "email": user.email, "role": canonical_role(user.role),
        "must_change_password": user.must_change_password,
        "csrf_token": request.cookies.get(CSRF_COOKIE_NAME),
    }


@app.post("/api/auth/logout")
def logout(response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    user.token_version += 1
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", samesite="lax")
    return {"message": "Signed out"}


def _send_password_reset(email: str, token: str):
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        raise HTTPException(status_code=503, detail="Password reset email is not configured.")
    port = int(os.getenv("SMTP_PORT", "587"))
    base_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
    reset_link = f"{base_url}/reset-password?email={quote(email)}&token={quote(token)}"
    message = EmailMessage()
    message["Subject"] = "Reset your NutriLedger password"
    message["From"] = sender
    message["To"] = email
    message.set_content(f"Use this link within one hour to reset your NutriLedger password:\n\n{reset_link}")
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if os.getenv("SMTP_USE_TLS", "true").lower() == "true":
            smtp.starttls()
        username = os.getenv("SMTP_USERNAME")
        password = os.getenv("SMTP_PASSWORD")
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


@app.post("/api/auth/password-reset/request")
def request_password_reset(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    if not DEMO_MODE and (not os.getenv("SMTP_HOST") or not os.getenv("SMTP_FROM")):
        raise HTTPException(status_code=503, detail="Password reset email is not configured.")
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    result = {"message": "If that account exists, password reset instructions have been sent."}
    if user is None or not user.active:
        if DEMO_MODE:
            result["development_token"] = None
        return result
    now = datetime.utcnow()
    for existing in db.scalars(select(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None),
    )):
        existing.used_at = now
    token = secrets.token_urlsafe(32)
    reset_record = PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        created_at=now,
        expires_at=now + RESET_TOKEN_LIFETIME,
    )
    db.add(reset_record)
    if DEMO_MODE and (not os.getenv("SMTP_HOST") or not os.getenv("SMTP_FROM")):
        db.commit()
        result["development_token"] = token
        return result
    try:
        _send_password_reset(user.email, token)
    except (OSError, smtplib.SMTPException) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Password reset email could not be sent.") from exc
    db.commit()
    return result


@app.post("/api/auth/password-reset")
def reset_password(
    payload: PasswordResetRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    reset_record = db.scalar(select(PasswordResetToken).where(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > datetime.utcnow(),
    ))
    user = db.get(User, reset_record.user_id) if reset_record else None
    if user is None or not user.active or user.email.lower() != payload.email:
        raise HTTPException(status_code=400, detail="Invalid or expired password reset token.")
    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    user.must_change_password = False
    reset_record.used_at = datetime.utcnow()
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", samesite="lax")
    return {"message": "Password reset successfully. Sign in with your new password."}


@app.post("/api/auth/password-change")
def change_password(
    payload: PasswordChangeRequest,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    user.must_change_password = False
    db.commit()
    csrf_token = _set_session_cookies(response, user)
    return {"message": "Password changed successfully.", "csrf_token": csrf_token}


def _user_record(user: User):
    return {
        "id": user.id, "name": user.name, "username": user.username,
        "email": user.email, "role": canonical_role(user.role), "phone": user.phone,
        "active": user.active, "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "must_change_password": user.must_change_password,
    }


def _may_manage_target(actor: User, target: User):
    if canonical_role(actor.role) == FACTORY_ADMIN and canonical_role(target.role) in (OWNER, FACTORY_ADMIN):
        raise HTTPException(status_code=403, detail="Factory Admin cannot manage Owner or Factory Admin accounts.")


@app.get("/api/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(require_roles(*USER_MANAGERS))):
    records = list(db.scalars(select(User).order_by(User.name, User.id)))
    if canonical_role(user.role) == FACTORY_ADMIN:
        records = [record for record in records if canonical_role(record.role) not in (OWNER, FACTORY_ADMIN)]
    return [_user_record(record) for record in records]


@app.post("/api/users")
def create_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*USER_MANAGERS)),
):
    requested_role = canonical_role(payload.role)
    if canonical_role(user.role) == FACTORY_ADMIN and requested_role not in (
        SALESMAN, PRODUCTION_SUPERVISOR, ACCOUNTANT_AUDITOR,
    ):
        raise HTTPException(status_code=403, detail="Factory Admin may only assign operational roles.")
    if db.scalar(select(User.id).where(or_(
        func.lower(User.email) == payload.email,
        func.lower(User.username) == payload.username,
    ))):
        raise HTTPException(status_code=409, detail="Username or email is already in use.")
    if db.get(Role, requested_role) is None:
        raise HTTPException(status_code=422, detail="The selected role is not configured.")
    record = User(
        name=payload.name.strip(), username=payload.username, email=payload.email,
        password_hash=hash_password(payload.password), role=requested_role,
        phone=payload.phone, active=True, must_change_password=True,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username or email is already in use.") from exc
    db.refresh(record)
    audit(db, user, "created", "user", str(record.id))
    db.commit()
    return _user_record(record)


@app.patch("/api/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*USER_MANAGERS)),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id != target.id:
        _may_manage_target(user, target)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one user field to update.")
    if user.id == target.id and (changes.get("active") is False or "role" in changes):
        raise HTTPException(status_code=400, detail="You cannot deactivate or change your own role.")
    if ("name" in changes and changes["name"] is None) or (
        "active" in changes and changes["active"] is None
    ):
        raise HTTPException(status_code=422, detail="Name and account status cannot be empty.")
    if "role" in changes and changes["role"] is None:
        raise HTTPException(status_code=422, detail="Role cannot be empty.")
    next_role = canonical_role(changes.get("role", target.role))
    if "role" in changes and canonical_role(user.role) == FACTORY_ADMIN and next_role in (OWNER, FACTORY_ADMIN):
        raise HTTPException(status_code=403, detail="Factory Admin may not assign privileged roles.")
    previous_role = canonical_role(target.role)
    next_active = changes.get("active", target.active)
    if previous_role == FACTORY_ADMIN and target.active and (
        next_role != FACTORY_ADMIN or not next_active
    ):
        active_admins = db.scalar(select(func.count(User.id)).where(
            User.id != target.id, User.active.is_(True), User.role.in_(("Admin", FACTORY_ADMIN)),
        )) or 0
        if active_admins == 0:
            raise HTTPException(status_code=409, detail="At least one active Factory Admin account must remain.")
    if previous_role == OWNER and target.active and (next_role != OWNER or not next_active):
        active_owners = db.scalar(select(func.count(User.id)).where(
            User.id != target.id, User.active.is_(True), User.role == OWNER,
        )) or 0
        if active_owners == 0:
            raise HTTPException(status_code=409, detail="At least one active Owner account must remain.")
    if any(changes.get(key) != getattr(target, key) for key in ("role", "active") if key in changes):
        target.token_version += 1
    for key in ("name", "phone", "active"):
        if key in changes:
            setattr(target, key, changes[key])
    if "role" in changes:
        target.role = next_role
    audit(db, user, "updated", "user", str(target.id))
    db.commit()
    return _user_record(target)


@app.post("/api/users/{user_id}/reset-password")
def admin_reset_user_password(
    user_id: int,
    payload: AdminPasswordResetRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*USER_MANAGERS)),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    _may_manage_target(user, target)
    target.password_hash = hash_password(payload.new_password)
    target.token_version += 1
    target.must_change_password = True
    audit(db, user, "password_reset", "user", str(target.id))
    db.commit()
    return {"message": "Password reset. The user must change it at next login."}


@app.get("/api/users/{user_id}/login-activity")
def user_login_activity(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*USER_MANAGERS)),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    _may_manage_target(user, target)
    records = db.scalars(
        select(LoginActivity).where(LoginActivity.user_id == target.id)
        .order_by(LoginActivity.created_at.desc()).limit(100)
    )
    return [{
        "created_at": row.created_at.isoformat(),
        "successful": row.successful,
        "ip_address": row.ip_address,
    } for row in records]


@app.get("/api/dashboard")
def dashboard(
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*FINANCE)),
):
    today = date.today()
    chart_start = from_date or today - timedelta(days=29)
    chart_end = to_date or today
    if chart_start > chart_end:
        raise HTTPException(status_code=422, detail="Start date must be on or before end date")
    if (chart_end - chart_start).days > 365:
        raise HTTPException(status_code=422, detail="Dashboard date range cannot exceed 366 days")
    today_orders = db.scalar(select(func.count(Order.id)).where(func.date(Order.created_at) == today.isoformat())) or 0
    pending = db.scalar(select(func.count(Order.id)).where(Order.status == "Submitted")) or 0
    products = list(db.scalars(select(Product).where(Product.active.is_(True))))
    finished = []
    stock_alerts = []
    for product in products:
        product_stock = stock_intelligence(db, "finished", product)
        finished.append({
            "id": product.id, "product": product.name, "quantity": product_stock["quantity"],
            "available_quantity": product_stock["available_quantity"],
            "unit": product.unit, "low": product_stock["low_stock"],
            "reorder_level": product_stock["minimum_stock"],
            "estimated_days_remaining": product_stock["estimated_days_remaining"],
        })
        if product_stock["low_stock"]:
            stock_alerts.append({
                "type": "low_stock", "severity": "warning",
                "title": f"Low finished stock: {product.name}",
                "detail": f"{product_stock['available_quantity']} usable of {product_stock['quantity']} {product.unit} on hand; minimum is {product_stock['minimum_stock']}.",
                "href": "/inventory",
            })
    materials = list(db.scalars(select(RawMaterial)))
    raw_stock = []
    for material in materials:
        material_stock = stock_intelligence(db, "material", material)
        raw_stock.append({
            "id": material.id, "material": material.name, "quantity": material_stock["quantity"],
            "available_quantity": material_stock["available_quantity"],
            "unit": material.unit, "low": material_stock["low_stock"],
            "reorder_level": material_stock["minimum_stock"],
            "estimated_days_remaining": material_stock["estimated_days_remaining"],
            "suggested_reorder_quantity": material_stock["suggested_reorder_quantity"],
        })
        if material_stock["low_stock"]:
            remaining = material_stock["estimated_days_remaining"]
            detail = f"{material_stock['available_quantity']} usable of {material_stock['quantity']} {material.unit} on hand; minimum is {material_stock['minimum_stock']}."
            if remaining is not None:
                detail += f" Estimated coverage: {remaining} days."
            stock_alerts.append({
                "type": "low_stock", "severity": "warning",
                "title": f"Low raw material: {material.name}",
                "detail": detail, "href": "/inventory",
            })
    invoices = list(db.scalars(select(Invoice)))
    sales = sum((i.taxable for i in invoices), Decimal("0"))
    open_receivables = sum((outstanding(db, invoice.id) for invoice in invoices), Decimal("0"))
    total_orders = db.scalar(select(func.count(Order.id))) or 0
    completed_runs = list(db.scalars(
        select(ProductionRun).where(ProductionRun.status == "Completed")
    ))
    expected_output_total = sum((run.expected_output for run in completed_runs), 0)
    good_output_total = sum((run.good_output for run in completed_runs), 0)
    production_efficiency = (
        Decimal(good_output_total) / Decimal(expected_output_total) * Decimal("100")
        if expected_output_total else Decimal("0")
    )
    run_costs = defaultdict(lambda: Decimal("0"))
    run_outputs = defaultdict(lambda: Decimal("0"))
    for run in completed_runs:
        consumptions = list(db.scalars(select(ProductionConsumption).where(
            ProductionConsumption.production_run_id == run.id,
        )))
        direct_cost = sum((row.quantity * row.unit_cost for row in consumptions), Decimal("0"))
        overhead = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.production_run_id == run.id,
        ))
        run_costs[run.product_id] += direct_cost + Decimal(overhead)
        run_outputs[run.product_id] += Decimal(run.good_output)
    raw_inventory_value = sum(
        (balance(db, "material", material.id) * material.weighted_average_cost for material in materials),
        Decimal("0"),
    )
    products_for_valuation = list(db.scalars(select(Product)))
    bom_rows = list(db.scalars(select(BomItem)))
    material_costs = {material.id: material.weighted_average_cost for material in materials}
    standard_costs = defaultdict(lambda: Decimal("0"))
    for bom in bom_rows:
        if bom.per_output:
            standard_costs[bom.product_id] += (
                bom.quantity / bom.per_output * material_costs.get(bom.material_id, Decimal("0"))
            )
    finished_inventory_value = Decimal("0")
    for product in products_for_valuation:
        unit_cost = (
            run_costs[product.id] / run_outputs[product.id]
            if run_outputs[product.id]
            else standard_costs[product.id]
        )
        finished_inventory_value += balance(db, "finished", product.id) * unit_cost
    inventory_value = money(raw_inventory_value + finished_inventory_value)
    month = date(today.year, today.month, 1)
    months = []
    for offset in range(5, -1, -1):
        index = month.year * 12 + month.month - 1 - offset
        year, month_index = divmod(index, 12)
        month_start = date(year, month_index + 1, 1)
        months.append(month_start)
    monthly_sales = []
    monthly_production = []
    monthly_payments = []
    monthly_wastage = []
    all_payments = list(db.scalars(select(Payment)))
    runs_by_month = defaultdict(list)
    for run in completed_runs:
        runs_by_month[(run.created_at.year, run.created_at.month)].append(run)
    payments_by_month = defaultdict(lambda: Decimal("0"))
    for payment in all_payments:
        payments_by_month[(payment.created_at.year, payment.created_at.month)] += payment.amount
    for month_start in months:
        next_month = date(month_start.year + (1 if month_start.month == 12 else 0),
                          1 if month_start.month == 12 else month_start.month + 1, 1)
        month_runs = runs_by_month[(month_start.year, month_start.month)]
        monthly_sales.append({
            "month": month_start.strftime("%b %y"),
            "sales": str(money(sum((
                invoice.taxable for invoice in invoices
                if month_start <= invoice.created_at.date() < next_month
            ), Decimal("0")))),
        })
        monthly_production.append({
            "month": month_start.strftime("%b %y"),
            "expected": sum(run.expected_output for run in month_runs),
            "actual": sum(run.good_output for run in month_runs),
        })
        monthly_wastage.append({
            "month": month_start.strftime("%b %y"),
            "damaged": sum(run.damaged for run in month_runs),
            "yield_shortfall": sum(max(0, run.expected_output - run.good_output) for run in month_runs),
        })
        monthly_payments.append({
            "month": month_start.strftime("%b %y"),
            "collected": str(money(payments_by_month[(month_start.year, month_start.month)])),
        })
    product_sales_rows = db.execute(
        select(
            Product.id, Product.name, func.coalesce(func.sum(Order.quantity), 0),
            func.coalesce(func.sum(Invoice.taxable), 0),
        )
        .join(Order, Order.product_id == Product.id)
        .join(Invoice, Invoice.order_id == Order.id)
        .group_by(Product.id, Product.name)
        .order_by(func.sum(Order.quantity).desc(), Product.name)
        .limit(5)
    ).all()
    top_selling_products = [{
        "product_id": product_id, "product": name,
        "units_sold": int(quantity), "revenue": str(money(Decimal(revenue))),
    } for product_id, name, quantity, revenue in product_sales_rows]
    top_customer_rows = db.execute(
        select(
            Customer.id, Customer.name, func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.taxable), 0),
        )
        .join(Order, Order.customer_id == Customer.id)
        .join(Invoice, Invoice.order_id == Order.id)
        .group_by(Customer.id, Customer.name)
        .order_by(func.sum(Invoice.taxable).desc(), Customer.name)
        .limit(5)
    ).all()
    top_customers = [{
        "customer_id": customer_id, "customer": name,
        "invoices": int(invoice_count), "revenue": str(money(Decimal(revenue))),
    } for customer_id, name, invoice_count, revenue in top_customer_rows]
    pending_customer_payments = []
    for invoice in sorted(
        (item for item in invoices if outstanding(db, item.id) > 0),
        key=lambda item: outstanding(db, item.id), reverse=True,
    )[:6]:
        pending_customer_payments.append({
            "invoice": invoice.number, "customer": invoice.order.customer.name,
            "amount_due": str(money(outstanding(db, invoice.id))),
            "created_at": invoice.created_at.isoformat(),
        })
    recent = list(db.scalars(select(Order).order_by(Order.created_at.desc()).limit(6)))
    month_start = datetime(today.year, today.month, 1)
    runs_this_month = list(db.scalars(select(ProductionRun).where(
        ProductionRun.created_at >= month_start, ProductionRun.status == "Completed",
    )))
    active_runs = db.scalar(select(func.count(ProductionRun.id)).where(
        ProductionRun.status.in_(("Planned", "In Progress")),
    )) or 0
    today_dispatches = db.scalar(select(func.count(Dispatch.id)).where(
        func.date(Dispatch.created_at) == today.isoformat(),
    )) or 0
    today_payments = sum((
        payment.amount for payment in all_payments
        if payment.created_at.date() == today
    ), Decimal("0"))
    pending_dispatches = []
    for invoice in invoices:
        remaining = invoice.order.quantity - dispatched(db, invoice.id)
        if remaining > 0:
            pending_dispatches.append({
                "invoice": invoice.number, "order": invoice.order.reference,
                "customer": invoice.order.customer.name, "remaining": remaining,
            })
    revenue_rows = db.execute(
        select(func.date(Invoice.created_at), func.sum(Invoice.taxable))
        .where(
            Invoice.created_at >= datetime.combine(chart_start, datetime.min.time()),
            Invoice.created_at < datetime.combine(chart_end + timedelta(days=1), datetime.min.time()),
        )
        .group_by(func.date(Invoice.created_at))
        .order_by(func.date(Invoice.created_at))
    ).all()
    revenue_by_day = {str(day): Decimal(value) for day, value in revenue_rows}
    revenue_series = []
    for offset in range((chart_end - chart_start).days + 1):
        current_date = chart_start + timedelta(days=offset)
        revenue_series.append({
            "date": current_date.isoformat(),
            "revenue": str(money(revenue_by_day.get(current_date.isoformat(), Decimal("0")))),
        })
    recent_batches = list(db.scalars(
        select(ProductionRun).order_by(ProductionRun.created_at.desc()).limit(6)
    ))
    production_runs = list(db.scalars(
        select(ProductionRun).where(ProductionRun.status == "Completed")
        .order_by(ProductionRun.created_at.desc()).limit(8)
    ))
    production_performance = [{
        "reference": run.reference, "date": run.created_at.date().isoformat(),
        "expected": run.expected_output, "actual": run.good_output,
    } for run in reversed(production_runs)]
    attention = list(stock_alerts)
    if pending:
        attention.append({
            "type": "pending_orders", "severity": "information",
            "title": f"{pending} order{'s' if pending != 1 else ''} awaiting verification",
            "detail": "Review submitted orders before invoicing.",
            "href": "/orders",
        })
    if pending_dispatches:
        attention.append({
            "type": "pending_dispatch", "severity": "information",
            "title": f"{len(pending_dispatches)} invoice{'s' if len(pending_dispatches) != 1 else ''} awaiting dispatch",
            "detail": f"{sum(row['remaining'] for row in pending_dispatches)} units remain to be dispatched.",
            "href": "/invoices",
        })
    for invoice in sorted(
        (invoice for invoice in invoices if outstanding(db, invoice.id) > 0),
        key=lambda item: item.created_at,
    )[:3]:
        due = outstanding(db, invoice.id)
        attention.append({
            "type": "receivable", "severity": "warning",
            "title": f"Payment pending: {invoice.order.customer.name}",
            "detail": f"{invoice.number} has {money(due)} outstanding.",
            "href": "/invoices",
        })
    expiring_before = today + timedelta(days=30)
    lots = db.scalars(select(InventoryLot).where(
        InventoryLot.expiry_date.is_not(None),
        InventoryLot.expiry_date <= expiring_before,
    ))
    for lot in lots:
        quantity = lot_balance(db, lot.id)
        if quantity <= 0:
            continue
        item = db.get(RawMaterial if lot.item_type == "material" else Product, lot.item_id)
        item_name = item.name if item else f"{lot.item_type} #{lot.item_id}"
        is_expired = lot.expiry_date < today
        attention.append({
            "type": "expiry", "severity": "critical" if is_expired else "warning",
            "title": f"{'Expired' if is_expired else 'Expiring soon'} batch: {lot.batch_code}",
            "detail": f"{item_name} · {quantity} on hand · expiry {lot.expiry_date.isoformat()}.",
            "href": "/inventory",
        })
    raw_stock_alert_count = sum(1 for item in raw_stock if item["low"])
    activities = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(8)))
    company_profile = db.scalar(select(CompanyProfile).order_by(CompanyProfile.id).limit(1))
    return {
        "today_orders": today_orders, "pending_orders": pending,
        "total_orders": total_orders,
        "total_sales": str(money(sales)), "finished_goods": finished,
        "raw_materials": raw_stock,
        "outstanding_receivables": str(money(open_receivables)),
        "inventory_valuation": str(inventory_value),
        "raw_material_inventory_valuation": str(money(raw_inventory_value)),
        "finished_goods_inventory_valuation": str(money(finished_inventory_value)),
        "production_output": good_output_total,
        "production_efficiency_percent": str(production_efficiency.quantize(Decimal("0.1"))),
        "active_production_runs": active_runs,
        "pending_dispatch_count": len(pending_dispatches),
        "raw_material_alert_count": raw_stock_alert_count,
        "pending_dispatches": pending_dispatches,
        "production_this_month": {
            "runs": len(runs_this_month),
            "good_output": sum(run.good_output for run in runs_this_month),
        },
        "today_operations": {
            "orders_received": today_orders,
            "production_batches": sum(1 for run in completed_runs if run.created_at.date() == today),
            "units_produced": sum(run.good_output for run in completed_runs if run.created_at.date() == today),
            "dispatches": today_dispatches,
            "payments_collected": str(money(today_payments)),
        },
        "monthly_sales": monthly_sales,
        "monthly_production": monthly_production,
        "monthly_payments": monthly_payments,
        "monthly_wastage": monthly_wastage,
        "top_selling_products": top_selling_products,
        "top_customers": top_customers,
        "pending_customer_payments": pending_customer_payments,
        "recent_production_batches": [{
            "id": run.id, "reference": run.reference,
            "product": db.get(Product, run.product_id).name,
            "expected_output": run.expected_output, "good_output": run.good_output,
            "damaged": run.damaged, "yield_variance_percent": str(run.yield_variance),
            "status": run.status, "created_at": run.created_at.isoformat(),
        } for run in recent_batches],
        "revenue_analytics": {
            "from_date": chart_start.isoformat(), "to_date": chart_end.isoformat(),
            "series": revenue_series,
        },
        "production_performance": production_performance,
        "stock_alerts": stock_alerts,
        "attention": attention,
        "recent_activities": [{
            "id": row.id, "action": row.action, "entity": row.entity,
            "entity_id": row.entity_id,
            "user": db.get(User, row.user_id).name if row.user_id and db.get(User, row.user_id) else "System",
            "created_at": row.created_at.isoformat(),
        } for row in activities],
        "company": ({
            "name": company_profile.name, "city": company_profile.city,
            "state": company_profile.state, "business": company_profile.business,
            "demo_data": company_profile.demo_data,
        } if company_profile else None),
        "recent_orders": [{"reference": o.reference, "customer": o.customer.name,
                           "product": o.product.name, "quantity": o.quantity,
                           "status": o.status, "created_at": o.created_at.isoformat()} for o in recent],
    }


@app.get("/api/products")
def products(db: Session = Depends(get_db), user: User = Depends(current_user)):
    confidential_price = canonical_role(user.role) == PRODUCTION_SUPERVISOR
    return [{"id": p.id, "name": p.name, "sku": p.sku, "category": p.category,
             "pack_size": p.pack_size, "unit": p.unit,
             "selling_price": None if confidential_price else str(p.selling_price),
             "gst_rate": str(p.gst_rate), "hsn_code": p.hsn_code, "active": p.active,
             "reorder_level": str(p.reorder_level),
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


@app.patch("/api/products/{product_id}")
def update_product(
    product_id: int,
    payload: ProductUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN)),
):
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one product field to update.")
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Product fields cannot be empty.")
    for key, value in changes.items():
        setattr(product, key, value.strip() if isinstance(value, str) else value)
    audit(db, user, "updated", "product", str(product.id))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Product name or SKU already exists.") from exc
    return {"id": product.id, "name": product.name, "sku": product.sku, "selling_price": str(product.selling_price)}


@app.get("/api/customers")
def customers(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SALES, OWNER)),
):
    result = []
    query = select(Customer).order_by(Customer.name)
    if canonical_role(user.role) == SALESMAN:
        query = query.where(Customer.assigned_user_id == user.id)
    for customer in db.scalars(query).all():
        customer_invoices = list(db.scalars(
            select(Invoice).join(Order, Invoice.order_id == Order.id)
            .where(Order.customer_id == customer.id)
        ))
        due = sum((outstanding(db, invoice.id) for invoice in customer_invoices), Decimal("0"))
        result.append({
            "id": customer.id, "name": customer.name,
            "customer_type": customer.customer_type, "state": customer.state,
            "gstin": customer.gstin, "contact": customer.contact,
            "billing_address": customer.billing_address,
            "credit_limit": str(customer.credit_limit),
            "outstanding_balance": str(money(due)),
            "assigned_user_id": customer.assigned_user_id,
            "assigned_user": customer.assigned_user.name if customer.assigned_user else None,
        })
    return result


@app.get("/api/suppliers")
def suppliers(db: Session = Depends(get_db), user: User = Depends(require_roles(*FINANCE))):
    result = []
    for supplier in db.scalars(select(Supplier).order_by(Supplier.name)).all():
        supplied = list(db.scalars(
            select(RawMaterial.name)
            .join(SupplierMaterial, SupplierMaterial.material_id == RawMaterial.id)
            .where(SupplierMaterial.supplier_id == supplier.id)
            .order_by(RawMaterial.name)
        ))
        result.append({
            "id": supplier.id, "name": supplier.name,
            "contact": supplier.contact, "gstin": supplier.gstin,
            "payment_terms": supplier.payment_terms,
            "materials": supplied,
        })
    return result


@app.get("/api/company")
def company(db: Session = Depends(get_db), user: User = Depends(current_user)):
    profile = db.scalar(select(CompanyProfile).order_by(CompanyProfile.id).limit(1))
    if profile is None:
        return None
    return {
        "name": profile.name, "address": profile.address,
        "city": profile.city, "state": profile.state,
        "country": profile.country, "business": profile.business,
        "demo_data": profile.demo_data,
    }


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


@app.put("/api/customers/{customer_id}/assignment")
def assign_customer(
    customer_id: int,
    payload: CustomerAssignmentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN, OWNER)),
):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    assigned_user_id = payload.user_id
    if assigned_user_id is not None:
        assigned_user = db.get(User, assigned_user_id)
        if assigned_user is None or not assigned_user.active or canonical_role(assigned_user.role) != SALESMAN:
            raise HTTPException(status_code=422, detail="Assign the customer to an active Salesman account.")
    customer.assigned_user_id = assigned_user_id
    audit(db, user, "assigned", "customer", str(customer.id))
    db.commit()
    return {
        "id": customer.id,
        "assigned_user_id": customer.assigned_user_id,
        "assigned_user": customer.assigned_user.name if customer.assigned_user else None,
    }


@app.get("/api/inventory")
def inventory(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PRODUCTION, *FINANCE)),
):
    materials = list(db.scalars(select(RawMaterial).order_by(RawMaterial.name)))
    products = list(db.scalars(select(Product).order_by(Product.name)))
    may_view_costs = canonical_role(user.role) != PRODUCTION_SUPERVISOR
    return {
        "materials": [{
            **stock_intelligence(db, "material", material),
            **({"weighted_average_cost": str(material.weighted_average_cost)} if may_view_costs else {}),
            "lots": lot_summary(db, "material", material.id),
        } for material in materials],
        "finished_goods": [{
            **stock_intelligence(db, "finished", product),
            "lots": lot_summary(db, "finished", product.id),
        } for product in products],
    }


@app.put("/api/inventory/{item_type}/{item_id}/policy")
def update_reorder_policy(
    item_type: str,
    item_id: int,
    payload: ReorderPolicyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN)),
):
    model = RawMaterial if item_type == "material" else Product if item_type == "finished" else None
    if model is None:
        raise HTTPException(status_code=422, detail="Inventory type must be material or finished")
    item = db.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    item.reorder_level = payload.minimum_stock
    item.reorder_days = payload.target_coverage_days
    audit(db, user, "updated reorder policy", item_type, str(item_id))
    db.commit()
    return stock_intelligence(db, item_type, item)


@app.get("/api/inventory/ledger")
def ledger(db: Session = Depends(get_db), user: User = Depends(require_roles(*PRODUCTION, *FINANCE))):
    rows = list(db.scalars(
        select(InventoryMovement).order_by(InventoryMovement.created_at.desc()).limit(500)
    ))
    result = []
    for row in rows:
        lot = db.get(InventoryLot, row.lot_id) if row.lot_id else None
        allocations = db.execute(
            select(InventoryLotAllocation.quantity, InventoryLot.batch_code)
            .join(InventoryLot, InventoryLot.id == InventoryLotAllocation.lot_id)
            .where(InventoryLotAllocation.movement_id == row.id)
        ).all()
        result.append({
            "id": row.id, "item_type": row.item_type, "item_id": row.item_id,
            "quantity": str(row.quantity), "unit": row.unit, "source_type": row.source_type,
            "source_id": row.source_id, "lot_id": row.lot_id,
            "batch_code": lot.batch_code if lot else None,
            "expiry_date": lot.expiry_date.isoformat() if lot and lot.expiry_date else None,
            "allocations": [{
                "batch_code": batch_code, "quantity": str(quantity),
            } for quantity, batch_code in allocations],
            "created_at": row.created_at.isoformat(),
        })
    return result


@app.post("/api/purchases")
def create_purchase(payload: PurchaseRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*ADMIN))):
    material = db.get(RawMaterial, payload.material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Raw material not found")
    if db.scalar(select(Purchase).where(Purchase.reference == payload.reference)):
        raise HTTPException(status_code=409, detail="Purchase reference already processed")
    if payload.expiry_date and not payload.batch_code:
        raise HTTPException(status_code=422, detail="A batch code is required when an expiry date is provided")
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
    lot = create_lot(
        db, "material", material.id, payload.batch_code, payload.expiry_date,
    ) if payload.batch_code else None
    add_movement(
        db, "material", material.id, payload.quantity, material.unit,
        "purchase", purchase.reference, lot_id=lot.id if lot else None,
    )
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
    finished_lot = create_lot(
        db, "finished", product.id, run.reference, payload.finished_expiry_date,
    )
    add_movement(
        db, "finished", product.id, Decimal(payload.good_output), product.unit,
        "production", run.reference, lot_id=finished_lot.id,
    )
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
def list_production_runs(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PRODUCTION, *FINANCE)),
):
    runs = db.scalars(select(ProductionRun).order_by(ProductionRun.created_at.desc()))
    result = []
    for run in runs:
        expected = bom_expected(db, run.product_id, run.expected_output)
        actual = {
            row.material_id: row.quantity for row in db.scalars(
                select(ProductionConsumption).where(ProductionConsumption.production_run_id == run.id)
            )
        }
        variances = []
        for material_id, planned_quantity in expected.items():
            actual_quantity = actual.get(material_id, Decimal("0"))
            variances.append({
                "material": db.get(RawMaterial, material_id).name,
                "expected": str(planned_quantity),
                "actual": str(actual_quantity),
                "variance_percent": str(
                    ((actual_quantity - planned_quantity) / planned_quantity * Decimal("100")).quantize(Decimal("0.1"))
                    if planned_quantity else Decimal("0")
                ),
            })
        result.append({
            "id": run.id, "reference": run.reference,
            "product": db.get(Product, run.product_id).name,
            "expected_output": run.expected_output, "good_output": run.good_output,
            "damaged": run.damaged, "yield_variance_percent": str(run.yield_variance),
            "variance_alert": abs(run.yield_variance) > Decimal("3"),
            "status": run.status,
            "material_variance": variances,
            "created_at": run.created_at.isoformat(),
        })
    return result


@app.get("/api/production-schedule")
def production_schedule(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PRODUCTION)),
):
    orders = db.scalars(select(Order).where(Order.status == "Approved").order_by(Order.created_at))
    schedule = []
    for order in orders:
        requirements = []
        for item in db.scalars(select(BomItem).where(BomItem.product_id == order.product_id)):
            required = item.quantity * Decimal(order.quantity) / item.per_output
            available = balance(db, "material", item.material_id)
            requirements.append({
                "material": item.material.name,
                "required": str(required),
                "available": str(available),
                "shortage": str(max(Decimal("0"), required - available)),
                "unit": item.material.unit,
            })
        schedule.append({
            "order_id": order.id,
            "order_reference": order.reference,
            "customer": order.customer.name,
            "product": order.product.name,
            "quantity": order.quantity,
            "created_at": order.created_at.isoformat(),
            "material_requirements": requirements,
        })
    return schedule


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
def get_bom(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PRODUCTION, OWNER)),
):
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
    if canonical_role(user.role) == SALESMAN and customer.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="You may only place orders for assigned customers.")
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


@app.put("/api/orders/{order_id}")
def edit_order(
    order_id: int,
    payload: OrderEditRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN)),
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.status != "Submitted":
        raise HTTPException(status_code=409, detail="Only submitted orders can be edited.")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one order field to update.")
    if "customer_id" in changes:
        customer = db.get(Customer, changes["customer_id"])
        if customer is None:
            raise HTTPException(status_code=404, detail="Customer not found.")
        order.customer_id = customer.id
    if "product_id" in changes:
        product = db.get(Product, changes["product_id"])
        if product is None or not product.active:
            raise HTTPException(status_code=404, detail="Active product not found.")
        order.product_id = product.id
        order.unit_price = product.selling_price
    if "quantity" in changes:
        order.quantity = changes["quantity"]
    audit(db, user, "edited", "order", order.reference)
    db.commit()
    return {"id": order.id, "reference": order.reference, "status": order.status}


@app.get("/api/orders")
def list_orders(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SALES, OWNER)),
):
    query = select(Order).order_by(Order.created_at.desc())
    if canonical_role(user.role) == SALESMAN:
        query = query.where(Order.created_by == user.id)
    result = []
    for order in db.scalars(query).all():
        invoice = db.scalar(select(Invoice).where(Invoice.order_id == order.id))
        invoice_due = outstanding(db, invoice.id) if invoice else Decimal("0")
        shipped = dispatched(db, invoice.id) if invoice else 0
        if invoice is None:
            fulfillment_stage = "Awaiting verification" if order.status == "Submitted" else order.status
            payment_status = "Not invoiced"
            invoice_total = None
            invoice_number = None
            pending_action = (
                "Review order" if order.status == "Submitted"
                else "Generate invoice" if order.status == "Approved"
                else "No action" if order.status == "Rejected"
                else "Review order"
            )
        else:
            fulfillment_stage = (
                "Completed" if shipped >= order.quantity and order.status == "Completed"
                else "Dispatched" if shipped >= order.quantity
                else "Partially dispatched" if shipped
                else "Ready for dispatch"
            )
            payment_status = (
                "Paid" if invoice_due <= 0
                else "Partially paid" if invoice_due < invoice.total
                else "Unpaid"
            )
            invoice_total = str(invoice.total)
            invoice_number = invoice.number
            pending_action = (
                "Dispatch remaining units" if shipped < order.quantity
                else "Collect payment" if invoice_due > 0
                else "Complete"
            )
        result.append({
            "id": order.id, "reference": order.reference,
            "customer": order.customer.name, "state": order.customer.state,
            "product": order.product.name, "product_id": order.product_id,
            "customer_id": order.customer_id, "quantity": order.quantity,
            "unit_price": str(order.unit_price),
            "available_stock": str(available_for_order(db, order.product_id)),
            "status": order.status, "fulfillment_stage": fulfillment_stage,
            "approval_status": (
                "Pending approval" if order.status == "Submitted"
                else "Rejected" if order.status == "Rejected"
                else "Approved"
            ),
            "payment_status": payment_status, "invoice_number": invoice_number,
            "invoice_total": invoice_total, "amount_due": str(money(invoice_due)),
            "pending_action": pending_action,
            "dispatched_quantity": shipped,
            "remaining_quantity": max(0, order.quantity - shipped),
            "created_at": order.created_at.isoformat(),
        })
    return result


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
def list_invoices(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*FINANCE, SALESMAN)),
):
    query = select(Invoice).join(Order, Invoice.order_id == Order.id).order_by(Invoice.created_at.desc())
    if canonical_role(user.role) == SALESMAN:
        query = query.where(Order.created_by == user.id)
    invoices = db.scalars(query)
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
def record_payment(
    invoice_id: int,
    payload: PaymentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ADMIN)),
):
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
def invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*FINANCE, SALESMAN)),
):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if canonical_role(user.role) == SALESMAN and invoice.order.created_by != user.id:
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
