"""Generate deterministic demo data in data/samples (sales.csv, customers.csv, sales_policy.txt)."""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "samples"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    n = 1200
    dates = pd.date_range("2024-01-01", "2025-12-31", periods=n).normalize()
    region = rng.choice(["North", "South", "East", "West"], n, p=[.3, .25, .25, .2])
    category = rng.choice(["Electronics", "Furniture", "Office Supplies", "Apparel"], n, p=[.35, .2, .3, .15])
    qty = rng.integers(1, 12, n)
    price = np.round(rng.gamma(4, 30, n) + np.where(category == "Electronics", 150, 0), 2)
    growth = 1 + np.linspace(0, .6, n)  # upward trend over time
    discount = np.round(rng.choice([0, .05, .1, .2], n), 2)
    revenue = np.round(qty * price * (1 - discount) * growth, 2)
    margin = pd.Series(category).map({"Electronics": 0.72, "Furniture": 0.6, "Office Supplies": 0.5, "Apparel": 0.55}).to_numpy()
    df = pd.DataFrame({"order_id": np.arange(1000, 1000 + n), "order_date": dates, "region": region,
                       "category": category, "quantity": qty, "unit_price": price, "discount": discount,
                       "revenue": revenue, "cost": np.round(revenue * margin * rng.uniform(0.9, 1.1, n), 2), "customer_id": rng.integers(1, 301, n)})
    df.loc[rng.choice(n, 40, replace=False), "discount"] = np.nan          # missing values
    df.loc[rng.choice(n, 6, replace=False), "revenue"] *= 25               # anomalies
    df.loc[rng.choice(n, 30, replace=False), "region"] = " north "         # messy text
    df = pd.concat([df, df.sample(12, random_state=1)], ignore_index=True)  # duplicates
    df.to_csv(OUT / "sales.csv", index=False)

    cust = pd.DataFrame({"customer_id": np.arange(1, 301),
                         "segment": rng.choice(["Consumer", "Corporate", "Small Business"], 300),
                         "country": rng.choice(["US", "UK", "DE", "IN", "BR"], 300),
                         "lifetime_value": np.round(rng.gamma(3, 400, 300), 2)})
    cust.to_csv(OUT / "customers.csv", index=False)

    (OUT / "sales_policy.txt").write_text(
        "Discount Policy\n\nSales representatives may grant discounts of up to 10% without approval. "
        "Discounts above 10% require written approval from the regional sales manager.\n\n"
        "Returns Policy\n\nElectronics may be returned within 30 days of delivery. Furniture returns are accepted "
        "within 14 days and incur a restocking fee of 15%.\n\n"
        "Regional Targets\n\nThe North region target for 2025 is 15% revenue growth. The West region is "
        "expected to expand into two new markets during the second half of the year.\n", encoding="utf-8")
    print(f"Wrote demo data to {OUT}")


if __name__ == "__main__":
    main()
