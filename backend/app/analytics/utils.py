import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def jsonable(v: Any) -> Any:
    """Recursively convert numpy/pandas values into JSON-safe python values (NaN -> None)."""
    if v is None:
        return None
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return v.isoformat() if not pd.isna(v) else None
    if isinstance(v, pd.Timedelta):
        return str(v)
    if isinstance(v, np.ndarray):
        return jsonable(v.tolist())
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, str)):
        return v
    return str(v)


def frame_records(df: pd.DataFrame, n: int | None = None) -> list[dict]:
    d = df if n is None else df.head(n)
    return [jsonable(r) for r in d.to_dict(orient="records")]


def is_text(s: pd.Series) -> bool:
    """True for object/string dtypes (pandas 3 uses a dedicated `str` dtype)."""
    return not (pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s)
                or pd.api.types.is_bool_dtype(s) or isinstance(s.dtype, pd.CategoricalDtype))


def is_id_like(s: pd.Series) -> bool:
    name = str(s.name).lower()
    if name == "id" or name.endswith("_id") or name.endswith("id") and name[:-2].endswith(("_", "")) and len(name) <= 3:
        return True
    return pd.api.types.is_integer_dtype(s) and len(s) > 20 and s.nunique() == len(s) and name.endswith(("key", "code", "number", "no"))


def numeric_cols(df: pd.DataFrame) -> list[str]:
    """Numeric measure columns (booleans and identifier-like columns excluded)."""
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
            and not pd.api.types.is_bool_dtype(df[c]) and not is_id_like(df[c])]


def datetime_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]


def categorical_cols(df: pd.DataFrame, max_unique: int = 50) -> list[str]:
    out = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
            continue
        if s.nunique(dropna=True) <= max_unique:
            out.append(c)
    return out


_DMY = r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})(?:[ T].*)?$"


def parse_dates(s: pd.Series) -> pd.Series | None:
    """Parse a date column without silently swapping day and month.

    ISO dates (2025-04-03) are unambiguous. For 03/04/2025-style values the convention is decided from the WHOLE column:
    a first field > 12 proves day-first, a second field > 12 proves month-first, both would be inconsistent (left as text).
    If every value is ambiguous (all fields <= 12) day-first is used, as month-first is the rarer convention outside the US."""
    txt = s.astype(str).str.strip()
    if txt.str.match(r"^\d{4}-\d{1,2}-\d{1,2}").mean() >= 0.9:
        dt = pd.to_datetime(s, errors="coerce", format="mixed")
        return dt if dt.notna().mean() >= 0.9 else None
    parts = txt.str.extract(_DMY).apply(pd.to_numeric, errors="coerce")
    if parts[0].notna().mean() < 0.9:
        return None
    first_gt12, second_gt12 = bool((parts[0] > 12).any()), bool((parts[1] > 12).any())
    if first_gt12 and second_gt12:
        return None
    dayfirst = not second_gt12          # second field > 12 proves month-first; otherwise day-first
    dt = pd.to_datetime(s, errors="coerce", dayfirst=dayfirst, format="mixed")
    return dt if dt.notna().mean() >= 0.9 else None


def infer_types(df: pd.DataFrame) -> pd.DataFrame:
    """Best-effort coercion of object columns to datetime / numeric."""
    df = df.copy()
    for c in df.columns:
        s = df[c]
        if not is_text(s):
            continue
        nn = s.dropna()
        if nn.empty:
            continue
        sample = nn.astype(str).str.strip()
        num = pd.to_numeric(sample.str.replace(",", "", regex=False), errors="coerce")
        if num.notna().mean() >= 0.95:
            df[c] = pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")
            continue
        looks_date = sample.str.match(r"^\d{4}-\d{1,2}-\d{1,2}|^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}").mean() >= 0.9
        if looks_date:
            dt = parse_dates(s)
            if dt is not None:
                df[c] = dt
    return df


def fmtnum(v, mode: str = "standard", digits: int = 0) -> str:
    """Server-side number text. mode: standard (1,234,567) | indian (12,34,567) | inr (₹12,34,567)."""
    if v is None:
        return "n/a"
    neg = v < 0
    a = abs(float(v))
    if a != a:
        return "n/a"
    s = f"{a:,.{digits}f}"
    if mode in ("indian", "inr"):
        whole, _, frac = f"{a:.{digits}f}".partition(".")
        head, tail = whole[:-3], whole[-3:]
        if head:
            parts = []
            while len(head) > 2:
                parts.insert(0, head[-2:])
                head = head[:-2]
            if head:
                parts.insert(0, head)
            whole = ",".join(parts) + "," + tail
        s = whole + (f".{frac}" if frac else "")
    if mode == "inr":
        s = "₹" + s
    return ("-" if neg else "") + s


# ---------------------------------------------------------------------------
# Presentation helpers: plain-text numbers (never scientific notation) and histogram bins
# ---------------------------------------------------------------------------
def _half_up(f: float, digits: int) -> float:
    from decimal import ROUND_HALF_UP, Decimal

    return float(Decimal(repr(f)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def plain(v, sig: int = 4) -> str:
    """Human-readable number without scientific notation: 12600.5 -> '12,601', 4.56 -> '4.56', 0.000123456 -> '0.0001235'."""
    if v is None:
        return "n/a"
    f = float(v)
    if math.isnan(f) or math.isinf(f):
        return "n/a"
    if f == 0:
        return "0"
    a = abs(f)
    digits = 0 if a >= 1000 else 2 if a >= 1 else min(12, max(0, 3 - 1 - math.floor(math.log10(a))))   # same rule as the web UI
    s = f"{_half_up(f, digits):,.{digits}f}"     # half-up like Intl.NumberFormat (Python's default is half-even)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def pfmt(p: float | None) -> str:
    """p-values for prose: '< 0.0001' instead of 3.6e-76."""
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "n/a"
    return "< 0.0001" if p < 0.0001 else f"{p:.4f}".rstrip("0").rstrip(".") if p < 0.01 else f"{p:.3f}".rstrip("0").rstrip(".")


def pick_digits(edges) -> int:
    """One precision for all labels of a chart: the fewest decimals (0-4) whose rounding error stays under 1% of the bin width
    and keeps consecutive edges distinct (0.5, 1.25 -> 2; 10.6, 35.761 -> 1; 6340, 12600 -> 0). Mirrors histogram.ts."""
    e = [float(x) for x in edges]
    widths = [b - a for a, b in zip(e, e[1:]) if b > a]
    width = min(widths) if widths else None
    distinct = lambda r: all(b > a for a, b in zip(r, r[1:]))  # noqa: E731
    for d in range(0, 5):
        r = [round(x, d) for x in e]
        if distinct(r) and (width is None or all(abs(x - y) <= 0.01 * width + 1e-12 for x, y in zip(e, r))):
            return d
    for d in range(0, 5):
        if distinct([round(x, d) for x in e]):
            return d
    return 4


def range_label(start: float, end: float, integer: bool, last: bool, digits: int) -> str:
    """'1–13' for integer data (bins are [start, end), the last one is closed), 'a–b' with shared decimals otherwise.
    Mirrors frontend/src/lib/histogram.ts so PDF / Excel output matches the web charts."""
    if integer:
        lo = math.ceil(start - 1e-9)
        hi = math.floor(end + 1e-9) if last else math.ceil(end - 1e-9) - 1
        if hi >= lo:
            return f"{lo:,}" if lo == hi else f"{lo:,}–{hi:,}"
    fmt = lambda x: f"{x:,.{digits}f}"  # noqa: E731
    return f"{fmt(start)}–{fmt(end)}"


def hist_rows(values, bins: int) -> tuple[list[dict], bool]:
    """Histogram with real bin edges. Counts come straight from numpy; only labels are added (presentation)."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return [], False
    counts, edges = np.histogram(arr, bins=bins)
    integer = bool(np.all(np.mod(arr, 1) == 0))
    digits = pick_digits(edges)
    total = int(counts.sum())
    rows = [{"start": float(edges[i]), "end": float(edges[i + 1]), "count": int(c), "pct": (c / total * 100) if total else 0.0,
             "bin": range_label(edges[i], edges[i + 1], integer, i == len(counts) - 1, digits)} for i, c in enumerate(counts)]
    return rows, integer
