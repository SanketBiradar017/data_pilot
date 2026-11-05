"""Plans, feature flags and usage limits: who may do what, and how much."""
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.security import SUPER_ADMIN, get_current_user, get_db
from backend.app.models import Analysis, Conversation, Dataset, Message, Plan, Report, Subscription, User
from backend.app.services import appconfig
from backend.app.services.appconfig import FEATURES, LIMITS

DEFAULT_RULES = {"allow_upgrade": True, "allow_downgrade": True, "downgrade_timing": "period_end", "prorate_upgrades": True,
                 "allowed_upgrade_to": [], "allowed_downgrade_to": []}  # empty list = any plan


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def month_start() -> datetime:
    n = datetime.now(UTC)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def seed_plans(db: Session) -> None:
    """Make sure a default free plan exists. Seeded unrestricted so existing behaviour is unchanged until an admin sets limits."""
    if db.scalar(select(Plan).where(Plan.slug == "free")):
        return
    db.add(Plan(slug="free", name="Free", description="Default plan", features={k: True for k in FEATURES},
                limits={k: None for k in LIMITS}, rules=dict(DEFAULT_RULES)))
    db.commit()


def default_plan(db: Session) -> Plan:
    p = db.scalar(select(Plan).where(Plan.slug == "free"))
    if not p:
        seed_plans(db)
        p = db.scalar(select(Plan).where(Plan.slug == "free"))
    return p


def subscription_of(db: Session, user_id: int) -> Subscription | None:
    s = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if not s or s.status == "canceled":
        return None
    end = _aware(s.current_period_end)
    if end and end < datetime.now(UTC):
        return None  # expired trial / lapsed period -> falls back to the free plan
    return s


def plan_of(db: Session, user: User) -> Plan:
    s = subscription_of(db, user.id)
    return (db.get(Plan, s.plan_id) if s else None) or default_plan(db)


def limit_of(plan: Plan, key: str) -> int | None:
    return (plan.limits or {}).get(key)


def usage_of(db: Session, user: User) -> dict:
    ms = month_start()
    return {
        "max_datasets": db.scalar(select(func.count(Dataset.id)).where(Dataset.owner_id == user.id)) or 0,
        "storage_mb": round((db.scalar(select(func.sum(Dataset.size_bytes)).where(Dataset.owner_id == user.id)) or 0) / 1048576, 2),
        "ai_analyses_per_month": db.scalar(select(func.count(Analysis.id)).where(Analysis.owner_id == user.id, Analysis.created_at >= ms)) or 0,
        "reports_per_month": db.scalar(select(func.count(Report.id)).where(Report.owner_id == user.id, Report.created_at >= ms)) or 0,
        "chat_messages_per_month": db.scalar(select(func.count(Message.id)).join(Conversation, Conversation.id == Message.conversation_id)
                                             .where(Conversation.owner_id == user.id, Message.role == "user", Message.created_at >= ms)) or 0,
    }


def feature_state(db: Session, user: User) -> dict[str, bool]:
    g, plan = appconfig.get("features", db), plan_of(db, user)
    return {k: bool(g.get(k, True)) and bool((plan.features or {}).get(k, True)) for k in FEATURES}


def check_feature(db: Session, user: User, feat: str) -> None:
    if not appconfig.get("features", db).get(feat, True):
        raise HTTPException(403, f"{FEATURES[feat]} is currently disabled by the administrator")
    if user.role == SUPER_ADMIN:
        return
    if not (plan_of(db, user).features or {}).get(feat, True):
        raise HTTPException(403, f"{FEATURES[feat]} is not included in your plan. Upgrade to use it.")


def check_limit(db: Session, user: User, key: str, adding: float = 1) -> None:
    if user.role == SUPER_ADMIN:
        return
    plan = plan_of(db, user)
    lim = limit_of(plan, key)
    if lim is not None and usage_of(db, user)[key] + adding > lim:
        raise HTTPException(402, f"Your {plan.name} plan allows {lim} for “{LIMITS[key]}”. Upgrade to continue.")


def effective_upload_limit_mb(db: Session, user: User) -> int:
    cap = int(appconfig.get("uploads", db)["max_upload_mb"])
    if user.role == SUPER_ADMIN:
        return cap
    lim = limit_of(plan_of(db, user), "max_file_mb")
    return min(cap, lim) if lim else cap


def require_feature(feat: str):
    def dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
        check_feature(db, user, feat)
    return dep


def check_plan_change(current: Plan, target: Plan) -> None:
    """Enforce the *current* plan's upgrade/downgrade rules for user-initiated changes."""
    rules = {**DEFAULT_RULES, **(current.rules or {})}
    up = (target.monthly_price_cents, target.sort_order) > (current.monthly_price_cents, current.sort_order)
    kind, allowed = ("upgrade", rules["allowed_upgrade_to"]) if up else ("downgrade", rules["allowed_downgrade_to"])
    if not rules[f"allow_{kind}"]:
        raise HTTPException(409, f"{kind.title()}s are not allowed from the {current.name} plan")
    if allowed and target.id not in allowed:
        raise HTTPException(409, f"You can't {kind} from {current.name} to {target.name}")


def plan_out(p: Plan) -> dict:
    return {"id": p.id, "slug": p.slug, "name": p.name, "description": p.description, "monthly_price_cents": p.monthly_price_cents,
            "yearly_price_cents": p.yearly_price_cents, "currency": p.currency, "trial_days": p.trial_days, "is_active": p.is_active,
            "sort_order": p.sort_order, "features": {k: (p.features or {}).get(k, True) for k in FEATURES},
            "limits": {k: (p.limits or {}).get(k) for k in LIMITS}, "rules": {**DEFAULT_RULES, **(p.rules or {})}}


def start_trial_end(plan: Plan) -> datetime:
    return datetime.now(UTC) + timedelta(days=plan.trial_days)


def strip_charts(obj):
    """Data Visualization switched off: drop chart specs from a result payload (recursive, copy)."""
    if isinstance(obj, dict):
        return {k: strip_charts(v) for k, v in obj.items() if k not in ("charts", "chart")}
    if isinstance(obj, list):
        return [strip_charts(v) for v in obj]
    return obj
