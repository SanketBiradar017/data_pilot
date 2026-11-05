"""Promo validation, subscription activation and manual transaction recording (gateway-agnostic)."""
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import Plan, PromoCode, PromoRedemption, Subscription, Transaction, User


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def price_cents(plan: Plan, interval: str) -> int:
    return plan.yearly_price_cents if interval == "yearly" else plan.monthly_price_cents


def find_promo(db: Session, code: str) -> PromoCode | None:
    return db.scalar(select(PromoCode).where(func.upper(PromoCode.code) == code.strip().upper()))


def evaluate_promo(db: Session, promo: PromoCode | None, user: User | None, plan: Plan, interval: str) -> int:
    """Return discount in cents or raise 400 with the reason the code can't be used."""
    bad = lambda m: HTTPException(400, m)  # noqa: E731
    if not promo or not promo.is_active:
        raise bad("Invalid or inactive promo code")
    if promo.expires_at and _aware(promo.expires_at) < datetime.now(UTC):
        raise bad("This promo code has expired")
    if promo.plan_ids and plan.id not in promo.plan_ids:
        raise bad("This promo code doesn't apply to the selected plan")
    if promo.max_uses is not None and (db.scalar(select(func.count(PromoRedemption.id)).where(PromoRedemption.promo_id == promo.id)) or 0) >= promo.max_uses:
        raise bad("This promo code has reached its usage limit")
    if user is not None:
        used = db.scalar(select(func.count(PromoRedemption.id)).where(PromoRedemption.promo_id == promo.id, PromoRedemption.user_id == user.id)) or 0
        if used >= max(1, promo.per_user_limit):
            raise bad("You've already used this promo code")
        if promo.first_time_only and db.scalar(select(func.count(Transaction.id)).where(
                Transaction.user_id == user.id, Transaction.status == "succeeded", Transaction.amount_cents > 0)):
            raise bad("This promo code is for first-time customers only")
    base = price_cents(plan, interval)
    off = base * promo.value // 100 if promo.discount_type == "percent" else promo.value
    return max(0, min(base, off))


def activate(db: Session, user: User, plan: Plan, interval: str, *, status: str = "active", period_end: datetime | None = None,
             admin_id: int | None = None, trial: bool = False) -> Subscription:
    end = period_end
    if end is None and status == "active" and price_cents(plan, interval) > 0:
        end = datetime.now(UTC) + timedelta(days=365 if interval == "yearly" else 30)
    s = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    if not s:
        s = Subscription(user_id=user.id, plan_id=plan.id)
        db.add(s)
    s.plan_id, s.status, s.interval, s.current_period_end, s.assigned_by = plan.id, status, interval, end, admin_id
    s.started_at = datetime.now(UTC)
    s.had_trial = s.had_trial or trial
    db.commit()
    return s
