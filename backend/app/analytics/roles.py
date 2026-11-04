"""Guess the business meaning of columns (revenue, cost, quantity, price, date, customer, product)."""
import re

import pandas as pd

from backend.app.analytics.utils import datetime_cols, infer_types, is_id_like, numeric_cols

_REV = ("revenue", "sales", "turnover", "income", "amount", "total")
_COST = ("cost", "expense", "cogs", "spend")
_QTY = ("quantity", "qty", "units", "volume")
_PRICE = ("unit_price", "price", "rate")
_PRODUCT = ("product", "item", "sku", "category", "brand")
_CUSTOMER = re.compile(r"customer|client|user|account|buyer|member", re.I)


def _pick(cols: list[str], hints: tuple[str, ...]) -> str | None:
    for h in hints:
        for c in cols:
            if h in c.lower():
                return c
    return None


_NON_ADDITIVE = re.compile(r"price|rate|ratio|pct|percent|margin|discount|score|average|avg|age\b|share", re.I)


def is_additive(col: str) -> bool:
    """False for columns where summing across rows is meaningless (prices, rates, percentages)."""
    return not _NON_ADDITIVE.search(col)


def detect_roles(df: pd.DataFrame) -> dict:
    df = infer_types(df)
    nums = numeric_cols(df)
    dts = datetime_cols(df)
    cost = _pick([c for c in nums], _COST)
    rev = _pick([c for c in nums if c != cost and is_additive(c)], _REV)
    qty = _pick(nums, _QTY)
    price = _pick([c for c in nums if c not in (rev, cost, qty)], _PRICE)
    customer = next((c for c in df.columns if _CUSTOMER.search(c) and c not in nums and df[c].nunique() > 1), None)
    dims = []
    for c in df.columns:
        if c in nums or c in dts or c == customer:
            continue
        n = df[c].nunique(dropna=True)
        if 2 <= n <= 60 and n < len(df) * 0.5:
            dims.append(c)
    product = next((c for h in _PRODUCT for c in dims if h in c.lower()), None)
    return {"additive": [c for c in nums if is_additive(c)], "revenue": rev, "cost": cost, "quantity": qty, "price": price, "date": dts[0] if dts else None,
            "customer": customer, "product": product, "dimensions": dims, "measures": nums}


__all__ = ["detect_roles", "is_id_like"]
