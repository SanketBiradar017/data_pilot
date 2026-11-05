"""Super-admin: roles, plans, promo codes, payments, runtime settings (features / AI / platform / uploads / SMTP), analytics.
Mounted under /admin; every route requires role == super_admin."""
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session

from backend.app.analytics.llm import _key, ai_runtime
from backend.app.api.v1.admin import _get_user, _iso, _like, _page, _series, _since, _user_row
from backend.app.config import settings
from backend.app.core.security import get_db, require_super_admin
from backend.app.ingestion.loaders import ALLOWED_EXT
from backend.app.models import (
    Analysis,
    ApiRequestLog,
    Dataset,
    LlmUsage,
    Plan,
    PromoCode,
    PromoRedemption,
    Subscription,
    Transaction,
    User,
)
from backend.app.services import ai_config, appconfig, billing, mailer
from backend.app.services import entitlements as ent
from backend.app.services.appconfig import FEATURES, LIMITS
from backend.app.services.datasets import audit

log = logging.getLogger("datapilot.admin")
router = APIRouter(dependencies=[Depends(require_super_admin)])


# ------------------------------------------------------------------ roles & manual plan assignment
class RoleIn(BaseModel):
    role: Literal["analyst", "admin", "super_admin"]


@router.post("/users/{uid}/role")
def change_role(uid: int, body: RoleIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    u = _get_user(db, uid)
    if u.id == admin.id:
        raise HTTPException(400, "You cannot change your own role")
    old, u.role = u.role, body.role
    db.commit()
    audit(db, admin, "admin.user.role", f"user_id={u.id} email={u.email} {old}->{body.role}")
    return _user_row(u)


class AssignPlanIn(BaseModel):
    plan_id: int
    interval: Literal["monthly", "yearly"] = "monthly"
    status: Literal["active", "trialing"] = "active"
    days: int | None = Field(default=None, ge=1, le=3650, description="Access length in days; omit for default (or no expiry on free plans)")


@router.post("/users/{uid}/subscription")
def assign_plan(uid: int, body: AssignPlanIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    u, plan = _get_user(db, uid), db.get(Plan, body.plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    end = datetime.now(UTC) + timedelta(days=body.days) if body.days else None
    billing.activate(db, u, plan, body.interval, status=body.status, period_end=end, admin_id=admin.id, trial=body.status == "trialing")
    audit(db, admin, "admin.user.assign_plan", f"user_id={u.id} email={u.email} plan={plan.slug} {body.status} days={body.days}")
    return _billing_of(db, u)


def _billing_of(db: Session, u: User) -> dict:
    sub, plan = ent.subscription_of(db, u.id), ent.plan_of(db, u)
    txs = db.scalars(select(Transaction).where(Transaction.user_id == u.id).order_by(Transaction.id.desc()).limit(20)).all()
    return {"plan": {"id": plan.id, "name": plan.name, "slug": plan.slug},
            "subscription": {"status": sub.status, "interval": sub.interval, "current_period_end": _iso(sub.current_period_end),
                             "assigned_by_admin": sub.assigned_by is not None} if sub else None,
            "usage": ent.usage_of(db, u), "limits": {k: ent.limit_of(plan, k) for k in LIMITS},
            "transactions": [_tx_out(t) for t in txs]}


@router.get("/users/{uid}/billing")
def user_billing(uid: int, db: Session = Depends(get_db)):
    return _billing_of(db, _get_user(db, uid))


# ------------------------------------------------------------------ plans
class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    monthly_price_cents: int = Field(ge=0, le=10_000_000)
    yearly_price_cents: int = Field(ge=0, le=100_000_000)
    currency: str = Field(default="INR", pattern=r"^[A-Za-z]{3}$")
    trial_days: int = Field(default=0, ge=0, le=365)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=1000)
    features: dict[str, bool] = {}
    limits: dict[str, int | None] = {}
    rules: dict = {}

    @field_validator("features")
    @classmethod
    def _f(cls, v):
        if bad := set(v) - set(FEATURES):
            raise ValueError(f"unknown feature(s): {', '.join(sorted(bad))}")
        return v

    @field_validator("limits")
    @classmethod
    def _l(cls, v):
        if bad := set(v) - set(LIMITS):
            raise ValueError(f"unknown limit(s): {', '.join(sorted(bad))}")
        if any(x is not None and x < 0 for x in v.values()):
            raise ValueError("limits must be ≥ 0 (or empty for unlimited)")
        return v

    @field_validator("rules")
    @classmethod
    def _r(cls, v):
        allowed = set(ent.DEFAULT_RULES)
        if bad := set(v) - allowed:
            raise ValueError(f"unknown rule(s): {', '.join(sorted(bad))}")
        if v.get("downgrade_timing", "period_end") not in ("immediate", "period_end"):
            raise ValueError("downgrade_timing must be immediate or period_end")
        return v


def _plan_row(db: Session, p: Plan) -> dict:
    n = db.scalar(select(func.count(Subscription.id)).where(Subscription.plan_id == p.id, Subscription.status != "canceled")) or 0
    return {**ent.plan_out(p), "subscribers": n, "is_default": p.slug == "free"}


@router.get("/plans")
def list_plans(db: Session = Depends(get_db)):
    return {"items": [_plan_row(db, p) for p in db.scalars(select(Plan).order_by(Plan.sort_order, Plan.monthly_price_cents, Plan.id))],
            "features": FEATURES, "limits": LIMITS}


def _apply_plan(p: Plan, b: PlanIn) -> None:
    p.slug, p.name, p.description = b.slug, b.name, b.description
    p.monthly_price_cents, p.yearly_price_cents, p.currency = b.monthly_price_cents, b.yearly_price_cents, b.currency.upper()
    p.trial_days, p.is_active, p.sort_order = b.trial_days, b.is_active, b.sort_order
    p.features = {k: b.features.get(k, True) for k in FEATURES}
    p.limits = {k: b.limits.get(k) for k in LIMITS}
    p.rules = {**ent.DEFAULT_RULES, **b.rules}


@router.post("/plans", status_code=201)
def create_plan(body: PlanIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    if db.scalar(select(Plan).where(Plan.slug == body.slug)):
        raise HTTPException(409, "A plan with this slug already exists")
    p = Plan()
    _apply_plan(p, body)
    db.add(p)
    db.commit()
    audit(db, admin, "admin.plan.create", f"id={p.id} slug={p.slug}")
    return _plan_row(db, p)


@router.put("/plans/{pid}")
def update_plan(pid: int, body: PlanIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    p = db.get(Plan, pid)
    if not p:
        raise HTTPException(404, "Plan not found")
    if p.slug == "free" and (body.slug != "free" or not body.is_active):
        raise HTTPException(400, "The default free plan can't be renamed or deactivated")
    if body.slug != p.slug and db.scalar(select(Plan).where(Plan.slug == body.slug)):
        raise HTTPException(409, "A plan with this slug already exists")
    _apply_plan(p, body)
    db.commit()
    audit(db, admin, "admin.plan.update", f"id={p.id} slug={p.slug}")
    return _plan_row(db, p)


@router.delete("/plans/{pid}", status_code=204)
def delete_plan(pid: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    p = db.get(Plan, pid)
    if not p:
        raise HTTPException(404, "Plan not found")
    if p.slug == "free":
        raise HTTPException(400, "The default free plan can't be deleted")
    if db.scalar(select(func.count(Subscription.id)).where(Subscription.plan_id == pid)):
        raise HTTPException(409, "This plan has subscribers. Move them to another plan or disable the plan instead.")
    db.delete(p)
    db.commit()
    audit(db, admin, "admin.plan.delete", f"id={pid} slug={p.slug}")


# ------------------------------------------------------------------ promo codes
class PromoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    description: str = Field(default="", max_length=200)
    discount_type: Literal["percent", "fixed"]
    value: int = Field(ge=1, le=10_000_000)
    expires_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)
    per_user_limit: int = Field(default=1, ge=1, le=1000)
    plan_ids: list[int] = []
    first_time_only: bool = False
    is_active: bool = True

    @field_validator("value")
    @classmethod
    def _pct(cls, v, info):
        if info.data.get("discount_type") == "percent" and v > 100:
            raise ValueError("percent discounts must be between 1 and 100")
        return v


def _promo_row(db: Session, c: PromoCode) -> dict:
    uses, disc = db.execute(select(func.count(PromoRedemption.id), func.coalesce(func.sum(PromoRedemption.discount_cents), 0))
                            .where(PromoRedemption.promo_id == c.id)).one()
    rev = db.scalar(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.promo_code == c.code, Transaction.kind != "refund", Transaction.status.in_(("succeeded", "refunded")))) or 0
    exp = c.expires_at.replace(tzinfo=c.expires_at.tzinfo or UTC) if c.expires_at else None
    return {"id": c.id, "code": c.code, "description": c.description, "discount_type": c.discount_type, "value": c.value,
            "expires_at": _iso(c.expires_at), "expired": bool(exp and exp < datetime.now(UTC)), "max_uses": c.max_uses,
            "per_user_limit": c.per_user_limit, "plan_ids": c.plan_ids or [], "first_time_only": c.first_time_only,
            "is_active": c.is_active, "uses": uses, "discount_given_cents": int(disc), "revenue_cents": int(rev), "created_at": _iso(c.created_at)}


def _check_promo_plans(db: Session, ids: list[int]) -> None:
    if ids and db.scalar(select(func.count(Plan.id)).where(Plan.id.in_(ids))) != len(set(ids)):
        raise HTTPException(400, "One or more restricted plans don't exist")


@router.get("/promos")
def list_promos(db: Session = Depends(get_db)):
    return {"items": [_promo_row(db, c) for c in db.scalars(select(PromoCode).order_by(PromoCode.id.desc()))]}


@router.post("/promos", status_code=201)
def create_promo(body: PromoIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    if billing.find_promo(db, body.code):
        raise HTTPException(409, "This promo code already exists")
    _check_promo_plans(db, body.plan_ids)
    c = PromoCode(**{**body.model_dump(), "code": body.code.upper()})
    db.add(c)
    db.commit()
    audit(db, admin, "admin.promo.create", f"code={c.code}")
    return _promo_row(db, c)


@router.put("/promos/{cid}")
def update_promo(cid: int, body: PromoIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    c = db.get(PromoCode, cid)
    if not c:
        raise HTTPException(404, "Promo code not found")
    other = billing.find_promo(db, body.code)
    if other and other.id != c.id:
        raise HTTPException(409, "This promo code already exists")
    _check_promo_plans(db, body.plan_ids)
    for k, v in {**body.model_dump(), "code": body.code.upper()}.items():
        setattr(c, k, v)
    db.commit()
    audit(db, admin, "admin.promo.update", f"code={c.code} active={c.is_active}")
    return _promo_row(db, c)


@router.delete("/promos/{cid}", status_code=204)
def delete_promo(cid: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    c = db.get(PromoCode, cid)
    if not c:
        raise HTTPException(404, "Promo code not found")
    if db.scalar(select(func.count(PromoRedemption.id)).where(PromoRedemption.promo_id == cid)):
        raise HTTPException(409, "This code has been redeemed. Disable it instead to keep revenue history.")
    db.delete(c)
    db.commit()
    audit(db, admin, "admin.promo.delete", f"code={c.code}")


# ------------------------------------------------------------------ payments & transactions
def _tx_out(t: Transaction) -> dict:
    return {"id": t.id, "user_id": t.user_id, "user_email": t.user_email, "plan_name": t.plan_name, "kind": t.kind, "status": t.status,
            "interval": t.interval, "amount_cents": t.amount_cents, "discount_cents": t.discount_cents, "currency": t.currency,
            "gateway": t.gateway, "gateway_ref": t.gateway_ref, "promo_code": t.promo_code, "refund_of": t.refund_of, "note": t.note,
            "created_at": _iso(t.created_at)}


@router.get("/transactions")
def list_transactions(q: str | None = None, status: str | None = None, kind: str | None = None, user_id: int | None = None,
                      page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    T = Transaction
    stmt = select(T)
    if q and q.strip():
        pat = _like(q)
        stmt = stmt.where(or_(func.lower(T.user_email).like(pat, escape="\\"), func.lower(T.gateway_ref).like(pat, escape="\\"),
                              func.lower(T.promo_code).like(pat, escape="\\")))
    if status in ("succeeded", "failed", "pending", "refunded"):
        stmt = stmt.where(T.status == status)
    if kind in ("subscription", "renewal", "refund"):
        stmt = stmt.where(T.kind == kind)
    if user_id:
        stmt = stmt.where(T.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(T.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    s = db.execute(select(
        func.coalesce(func.sum(case((and_ok(T), T.amount_cents), else_=0)), 0),
        func.coalesce(func.sum(case((T.kind == "refund", -T.amount_cents), else_=0)), 0),
        func.coalesce(func.sum(case((T.status == "failed", 1), else_=0)), 0),
        func.coalesce(func.sum(case((and_ok(T, "renewal"), 1), else_=0)), 0))).one()
    return {"items": [_tx_out(t) for t in rows],
            "summary": {"gross_cents": int(s[0]), "refunded_cents": int(s[1]), "net_cents": int(s[0]) - int(s[1]), "failed": int(s[2]), "renewals": int(s[3])},
            **_page(total, page, page_size)}


def and_ok(T, kind: str | None = None):
    c = and_(T.kind != "refund", T.status.in_(("succeeded", "refunded")))
    return and_(c, T.kind == kind) if kind else c


class RecordTxIn(BaseModel):
    user_id: int
    plan_id: int
    interval: Literal["monthly", "yearly"] = "monthly"
    kind: Literal["subscription", "renewal"] = "subscription"
    status: Literal["succeeded", "failed", "pending"] = "succeeded"
    promo_code: str = Field(default="", max_length=40)
    gateway_ref: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=400)
    activate: bool = True


@router.post("/transactions", status_code=201)
def record_transaction(body: RecordTxIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    """Record a payment taken outside the app (bank transfer, invoice, gateway dashboard...). Applies promo rules and, if succeeded, activates the plan."""
    u, plan = _get_user(db, body.user_id), db.get(Plan, body.plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    base, off, promo = billing.price_cents(plan, body.interval), 0, None
    if body.promo_code.strip():
        promo = billing.find_promo(db, body.promo_code)
        off = billing.evaluate_promo(db, promo, u, plan, body.interval)
    gw = appconfig.get("payments", db)["gateway"]
    t = Transaction(user_id=u.id, user_email=u.email, plan_id=plan.id, plan_name=plan.name, kind=body.kind, status=body.status,
                    interval=body.interval, amount_cents=base - off, discount_cents=off, currency=plan.currency, gateway=gw,
                    gateway_ref=body.gateway_ref, promo_code=promo.code if promo else "", note=body.note)
    db.add(t)
    db.flush()
    if promo and body.status == "succeeded":
        db.add(PromoRedemption(promo_id=promo.id, user_id=u.id, transaction_id=t.id, discount_cents=off))
    db.commit()
    if body.status == "succeeded" and body.activate:
        billing.activate(db, u, plan, body.interval, admin_id=admin.id)
    audit(db, admin, "admin.transaction.record", f"id={t.id} user={u.email} plan={plan.slug} amount={t.amount_cents} status={t.status}")
    return _tx_out(t)


class RefundIn(BaseModel):
    note: str = Field(default="", max_length=400)


@router.post("/transactions/{tid}/refund")
def refund(tid: int, body: RefundIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    """Records a full refund. If a payment gateway is connected, issue the refund there too - this only updates our books."""
    t = db.get(Transaction, tid)
    if not t:
        raise HTTPException(404, "Transaction not found")
    if t.kind == "refund" or t.status != "succeeded" or t.amount_cents <= 0:
        raise HTTPException(400, "Only succeeded payments can be refunded")
    t.status = "refunded"
    r = Transaction(user_id=t.user_id, user_email=t.user_email, plan_id=t.plan_id, plan_name=t.plan_name, kind="refund", status="succeeded",
                    interval=t.interval, amount_cents=-t.amount_cents, currency=t.currency, gateway=t.gateway, gateway_ref=t.gateway_ref,
                    refund_of=t.id, note=body.note)
    db.add(r)
    db.commit()
    audit(db, admin, "admin.transaction.refund", f"id={t.id} amount={t.amount_cents} user={t.user_email}")
    return _tx_out(r)


# ------------------------------------------------------------------ runtime settings
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _url_ok(v: str) -> str:
    if v and not re.match(r"^(https?://|/)[^\s]*$", v):
        raise ValueError("must start with http://, https:// or /")
    return v


class _Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformIn(_Patch):
    app_name: str | None = Field(default=None, min_length=1, max_length=60)
    tagline: str | None = Field(default=None, max_length=160)
    primary_color: str | None = None
    logo_url: str | None = Field(default=None, max_length=500)
    support_email: str | None = Field(default=None, max_length=255)
    public_url: str | None = Field(default=None, max_length=300)
    maintenance_mode: bool | None = None
    maintenance_message: str | None = Field(default=None, max_length=500)
    registration_open: bool | None = None
    email_verification: bool | None = None
    announcement: str | None = Field(default=None, max_length=300)
    announcement_tone: Literal["info", "warn", "success"] | None = None

    @field_validator("primary_color")
    @classmethod
    def _c(cls, v):
        if v is not None and not _HEX.match(v):
            raise ValueError("must be a hex colour like #6366f1")
        return v

    @field_validator("logo_url", "public_url")
    @classmethod
    def _u(cls, v):
        return v if v is None else _url_ok(v)

    @field_validator("support_email")
    @classmethod
    def _e(cls, v):
        if v and not _EMAIL.match(v):
            raise ValueError("invalid email")
        return v


class SmtpIn(_Patch):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    from_email: str | None = Field(default=None, max_length=255)
    from_name: str | None = Field(default=None, max_length=80)
    use_tls: bool | None = None

    @field_validator("from_email")
    @classmethod
    def _e(cls, v):
        if v and not _EMAIL.match(v):
            raise ValueError("invalid email")
        return v


class NotificationsIn(_Patch):
    verification_subject: str | None = Field(default=None, max_length=200)
    verification_body: str | None = Field(default=None, max_length=3000)
    welcome_subject: str | None = Field(default=None, max_length=200)
    welcome_body: str | None = Field(default=None, max_length=3000)
    suspended_subject: str | None = Field(default=None, max_length=200)
    suspended_body: str | None = Field(default=None, max_length=3000)


class FeaturesIn(_Patch):
    ai_chat: bool | None = None
    data_cleaning: bool | None = None
    eda: bool | None = None
    ai_agents: bool | None = None
    sql_analysis: bool | None = None
    data_visualization: bool | None = None
    pdf_reports: bool | None = None
    excel_reports: bool | None = None
    document_research: bool | None = None


class UploadsIn(_Patch):
    max_upload_mb: int | None = Field(default=None, ge=1, le=2048)
    allowed_formats: list[str] | None = None
    storage_limit_gb: float | None = Field(default=None, gt=0)

    @field_validator("allowed_formats")
    @classmethod
    def _f(cls, v):
        if v is not None:
            if bad := set(v) - ALLOWED_EXT:
                raise ValueError(f"unsupported format(s): {', '.join(sorted(bad))}")
            if not v:
                raise ValueError("at least one format is required")
        return v


class Price(BaseModel):
    input_per_m: float = Field(ge=0, le=100_000)
    output_per_m: float = Field(ge=0, le=100_000)


class AiIn(_Patch):
    provider: Literal["", "anthropic", "google"] | None = None
    model: str | None = Field(default=None, max_length=80)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=64_000)
    system_prompt: str | None = Field(default=None, max_length=4000)
    fallback_provider: Literal["", "anthropic", "google"] | None = None
    fallback_model: str | None = Field(default=None, max_length=80)
    monthly_token_cap: int | None = Field(default=None, ge=1)
    daily_call_cap: int | None = Field(default=None, ge=1)
    prices: dict[str, Price] | None = None


class PaymentsIn(_Patch):
    gateway: Literal["manual", "stripe", "paypal", "razorpay"] | None = None
    mode: Literal["test", "live"] | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    enabled: bool | None = None
    webhook_url: str | None = Field(default=None, max_length=300)
    statement_descriptor: str | None = Field(default=None, max_length=22)

    @field_validator("webhook_url")
    @classmethod
    def _u(cls, v):
        return v if v is None else _url_ok(v)


_MODELS = {"platform": PlatformIn, "smtp": SmtpIn, "notifications": NotificationsIn, "features": FeaturesIn,
           "uploads": UploadsIn, "ai": AiIn, "payments": PaymentsIn}
_NULLABLE = {"storage_limit_gb", "temperature", "max_output_tokens", "monthly_token_cap", "daily_call_cap"}


def _secrets_state() -> dict:
    return {"smtp_password_set": bool(settings.smtp_password), "payment_gateway_secret_set": bool(settings.payment_gateway_secret),
            "anthropic_key_set": ai_config.has_key("anthropic"), "google_key_set": ai_config.has_key("google")}


@router.get("/settings/{key}")
def get_setting(key: str, db: Session = Depends(get_db)):
    if key not in _MODELS:
        raise HTTPException(404, "Unknown settings group")
    out = {"values": appconfig.get(key, db), "secrets": _secrets_state()}
    if key == "ai":
        rt = ai_runtime()
        out["runtime"] = {"provider": rt["provider"], "model": rt["model"], "enabled": rt["enabled"]}
    if key == "smtp":
        out["configured"] = appconfig.smtp_configured()
    if key == "uploads":
        out["all_formats"] = sorted(ALLOWED_EXT)
    return out


@router.put("/settings/{key}")
def put_setting(key: str, body: dict, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    if key not in _MODELS:
        raise HTTPException(404, "Unknown settings group")
    try:
        model = _MODELS[key].model_validate(body)
    except ValidationError as e:  # bad values / unknown fields -> readable 422
        raise HTTPException(422, "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg'].removeprefix('Value error, ')}" for x in e.errors())) from e
    patch = model.model_dump(exclude_unset=True)
    patch = {k: v for k, v in patch.items() if v is not None or k in _NULLABLE}
    if key == "ai" and "prices" in patch:
        patch["prices"] = {m: p if isinstance(p, dict) else p.model_dump() for m, p in patch["prices"].items()}
    if key == "platform" and patch.get("email_verification") and not appconfig.smtp_configured():
        raise HTTPException(400, "Configure SMTP first - email verification would lock new users out.")
    if key == "platform" and patch.get("maintenance_mode") is True:
        log.warning("maintenance mode enabled by %s", admin.email)
    new = appconfig.put(db, key, patch)
    audit(db, admin, f"admin.settings.{key}", "changed: " + ", ".join(sorted(patch)))
    return {"values": new}


class TestMailIn(BaseModel):
    to: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/settings/smtp/test")
def smtp_test(body: TestMailIn, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    ok, err = mailer.send_mail(body.to, "DataPilot AI test email", "SMTP is configured correctly.")
    audit(db, admin, "admin.smtp.test", f"to={body.to} ok={ok}")
    return {"ok": ok, "error": err}


# ------------------------------------------------------------------ AI cost
def cost_usd(prices: dict, model: str, tin: int, tout: int) -> float:
    p = prices.get(model)
    return round((tin * p["input_per_m"] + tout * p["output_per_m"]) / 1e6, 4) if p else 0.0


@router.get("/ai/summary")
def ai_summary(db: Session = Depends(get_db)):
    prices = appconfig.get("ai", db)["prices"]
    now = datetime.now(UTC)
    ms = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(select(LlmUsage.model, func.count(), func.coalesce(func.sum(LlmUsage.input_tokens), 0), func.coalesce(func.sum(LlmUsage.output_tokens), 0))
                      .where(LlmUsage.created_at >= ms).group_by(LlmUsage.model)).all()
    by_model = [{"model": m, "calls": c, "input_tokens": int(i), "output_tokens": int(o), "cost_usd": cost_usd(prices, m, int(i), int(o)),
                 "priced": m in prices} for m, c, i, o in rows]
    cfg = appconfig.get("ai", db)
    tokens = sum(m["input_tokens"] + m["output_tokens"] for m in by_model)
    calls_24h = db.scalar(select(func.count(LlmUsage.id)).where(LlmUsage.created_at >= now - timedelta(days=1))) or 0
    return {"month_tokens": tokens, "month_cost_usd": round(sum(m["cost_usd"] for m in by_model), 2), "by_model": by_model,
            "monthly_token_cap": cfg["monthly_token_cap"], "daily_call_cap": cfg["daily_call_cap"], "calls_24h": calls_24h,
            "unpriced_models": [m["model"] for m in by_model if not m["priced"]],
            "providers": {p: bool(_key(p)) for p in ("anthropic", "google")}}


# ------------------------------------------------------------------ analytics
_FEATURE_ROUTES = (("/api/v1/chat", "AI Chat"), ("/api/v1/sql", "SQL Analysis"), ("/api/v1/advanced", "EDA / Advanced"),
                   ("/api/v1/intelligence", "AI Agents"), ("/api/v1/analyses", "AI Agents"), ("/api/v1/reports", "Reports"),
                   ("/api/v1/datasets/{dataset_id}/duplicates", "Data Cleaning"), ("/api/v1/datasets/{dataset_id}/clean", "Data Cleaning"),
                   ("/api/v1/datasets", "Datasets"))


@router.get("/analytics")
def analytics(days: int = Query(30, ge=7, le=90), db: Session = Depends(get_db)):
    R, now = ApiRequestLog, datetime.now(UTC)
    day = func.date(R.created_at)
    dau_rows = {str(d): n for d, n in db.execute(select(day, func.count(func.distinct(R.user_id))).where(R.created_at >= _since(days), R.user_id.is_not(None)).group_by(day))}
    dau = [{"date": d, "count": dau_rows.get(d, 0)} for d in (x["date"] for x in _series(db, User.created_at, days))]
    mau = db.scalar(select(func.count(func.distinct(R.user_id))).where(R.created_at >= _since(30), R.user_id.is_not(None))) or 0
    dau_today = db.scalar(select(func.count(func.distinct(R.user_id))).where(R.created_at >= _since(1), R.user_id.is_not(None))) or 0

    mrr, paying = 0.0, 0
    dist: dict[str, int] = {}
    for sub, plan in db.execute(select(Subscription, Plan).join(Plan, Plan.id == Subscription.plan_id).where(Subscription.status != "canceled")):
        end = sub.current_period_end
        if end and (end if end.tzinfo else end.replace(tzinfo=UTC)) < now:
            continue
        dist[plan.name] = dist.get(plan.name, 0) + 1
        if sub.status == "active" and (plan.monthly_price_cents or plan.yearly_price_cents):
            paying += 1
            mrr += (plan.yearly_price_cents / 12) if sub.interval == "yearly" else plan.monthly_price_cents
    on_plan = sum(dist.values())
    total_users = db.scalar(select(func.count(User.id))) or 0
    if total_users - on_plan > 0:
        dist["Free (default)"] = dist.get("Free (default)", 0) + total_users - on_plan

    T = Transaction
    month = func.coalesce(func.sum(T.amount_cents), 0)
    mkey = func.substr(cast(T.created_at, String), 1, 7)
    rev = {k: int(v) for k, v in db.execute(select(mkey, month).where(T.status.in_(("succeeded", "refunded")), T.created_at >= _since(190)).group_by(mkey))}
    months = []
    for i in range(5, -1, -1):
        y, m = now.year, now.month - i
        while m < 1:
            y, m = y - 1, m + 12
        k = f"{y}-{m:02d}"
        months.append({"month": k, "revenue_cents": rev.get(k, 0)})
    fr = db.execute(select(R.method, R.route, func.count()).where(R.created_at >= _since(30)).group_by(R.method, R.route)).all()
    usage: dict[str, int] = {}
    for method, route, n in fr:
        for prefix, label in _FEATURE_ROUTES:
            if route.startswith(prefix) and not (label == "Datasets" and method == "GET") and not (label == "AI Agents" and method == "GET"):
                usage[label] = usage.get(label, 0) + n
                break
    prices = appconfig.get("ai", db)["prices"]
    tok = db.execute(select(LlmUsage.model, func.coalesce(func.sum(LlmUsage.input_tokens), 0), func.coalesce(func.sum(LlmUsage.output_tokens), 0))
                     .where(LlmUsage.created_at >= _since(30)).group_by(LlmUsage.model)).all()
    err7 = db.execute(select(func.count(), func.coalesce(func.sum(case((R.status_code >= 500, 1), else_=0)), 0)).where(R.created_at >= _since(7))).one()
    return {
        "dau": dau, "dau_today": dau_today, "mau": mau, "total_users": total_users,
        "signups": _series(db, User.created_at, days),
        "mrr_cents": int(mrr), "arr_cents": int(mrr * 12), "paying_subscribers": paying,
        "revenue_by_month": months, "plan_distribution": [{"plan": k, "users": v} for k, v in sorted(dist.items(), key=lambda x: -x[1])],
        "feature_usage": sorted(({"feature": k, "requests": v} for k, v in usage.items()), key=lambda x: -x["requests"]),
        "ai_tokens_30d": sum(int(i) + int(o) for _, i, o in tok), "ai_cost_30d_usd": round(sum(cost_usd(prices, m, int(i), int(o)) for m, i, o in tok), 2),
        "api_requests_7d": err7[0], "api_errors_7d": int(err7[1]),
        "failed_jobs_7d": db.scalar(select(func.count(Analysis.id)).where(Analysis.status == "failed", Analysis.created_at >= _since(7))) or 0,
        "storage_bytes": db.scalar(select(func.sum(Dataset.size_bytes))) or 0,
        "storage_limit_gb": appconfig.get("uploads", db)["storage_limit_gb"],
        "currency": appconfig.get("payments", db)["currency"],
    }
