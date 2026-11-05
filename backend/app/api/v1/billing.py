"""Public/user-facing: platform info, my plan & usage, plan list, promo preview, self-service plan change."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import get_current_user, get_db
from backend.app.models import Plan, Subscription, User
from backend.app.services import appconfig, billing
from backend.app.services import entitlements as ent
from backend.app.services.datasets import audit

router = APIRouter()
public_router = APIRouter()


@public_router.get("/platform")
def platform_info():
    """Unauthenticated: branding, maintenance and signup availability (no secrets)."""
    from backend.app.config import settings

    p = appconfig.get("platform")
    return {k: p[k] for k in ("app_name", "tagline", "primary_color", "logo_url", "support_email", "maintenance_mode",
                              "maintenance_message", "announcement", "announcement_tone", "email_verification")} | {
        "registration_open": bool(p["registration_open"] and settings.allow_registration)}


@router.get("/me")
def my_billing(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    plan, sub = ent.plan_of(db, user), ent.subscription_of(db, user.id)
    usage = ent.usage_of(db, user)
    return {
        "plan": ent.plan_out(plan),
        "subscription": {"status": sub.status, "interval": sub.interval, "current_period_end": sub.current_period_end.isoformat() if sub and sub.current_period_end else None} if sub else None,
        "features": ent.feature_state(db, user),
        "usage": usage,
        "limits": {k: ent.limit_of(plan, k) for k in appconfig.LIMITS},
        "upload_limit_mb": ent.effective_upload_limit_mb(db, user),
        "allowed_formats": appconfig.get("uploads", db)["allowed_formats"],
    }


@router.get("/plans")
def public_plans(db: Session = Depends(get_db)):
    return [ent.plan_out(p) for p in db.scalars(select(Plan).where(Plan.is_active).order_by(Plan.sort_order, Plan.monthly_price_cents))]


class PromoCheckIn(BaseModel):
    code: str
    plan_id: int
    interval: str = "monthly"


@router.post("/promo/validate")
def validate_promo(body: PromoCheckIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    plan = db.get(Plan, body.plan_id)
    if not plan or not plan.is_active:
        raise HTTPException(404, "Plan not found")
    off = billing.evaluate_promo(db, billing.find_promo(db, body.code), user, plan, body.interval)
    base = billing.price_cents(plan, body.interval)
    return {"base_cents": base, "discount_cents": off, "total_cents": base - off, "currency": plan.currency}


class ChangePlanIn(BaseModel):
    plan_id: int
    interval: str = "monthly"


@router.post("/change-plan")
def change_plan(body: ChangePlanIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Self-service change: allowed for free plans and trials. Paid plans need the payment gateway (not connected) -
    an admin can assign them from the Users panel."""
    target = db.get(Plan, body.plan_id)
    if not target or not target.is_active:
        raise HTTPException(404, "Plan not found")
    current = ent.plan_of(db, user)
    if target.id == current.id:
        raise HTTPException(400, "You're already on this plan")
    ent.check_plan_change(current, target)
    price = billing.price_cents(target, body.interval)
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    if price == 0:
        billing.activate(db, user, target, body.interval, status="active", period_end=None)
        audit(db, user, "billing.change_plan", f"to={target.slug}")
    elif target.trial_days and not (sub and sub.had_trial):
        billing.activate(db, user, target, body.interval, status="trialing", period_end=ent.start_trial_end(target), trial=True)
        audit(db, user, "billing.start_trial", f"plan={target.slug} days={target.trial_days}")
    else:
        raise HTTPException(409, "Online payment isn't enabled yet. Please contact support to upgrade to this plan.")
    return my_billing(db, user)



