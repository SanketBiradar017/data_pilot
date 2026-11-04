# Accuracy: how Phase 2 results are checked

## Three independent layers
1. **Fact verification (runtime).** Every number an agent shows is a *fact*. Base facts carry the SQL that produces them and are re-executed in a sandboxed DuckDB; derived facts name an operation and are re-evaluated from verified inputs. A statement is shown only if every fact it cites verified.
2. **Exact reconciliation (runtime).** Breakdowns must add up to the total: dimension contributions, volume + mix + price (+ any change from rows without a quantity), and the scenario group breakdown. A failed check is shown to the user.
3. **Differential tests (CI).** `backend/tests/accuracy/` recomputes results with a deliberately naive oracle (plain Python loops, no pandas `groupby`, no SQL, no shared helpers) on randomly generated messy data: blank labels, missing values, negative revenue (refunds), timestamps with a time part, duplicate rows, groups that appear or disappear, week / month / quarter grains. About 280 random datasets were also run as a one-off soak test.

## Definitions (so numbers can be reproduced)
* Totals use `SUM` over rows where the metric is known. Missing values are skipped, never counted as 0.
* **Profit** = Σ(revenue − cost) over rows where *both* are known; rows missing either are excluded and disclosed (`data_notes`).
* Blank labels form an explicit `(blank)` group (SQL: `IS NULL`) so no row silently drops out of a breakdown.
* Volume / mix / price are computed on rows with both metric and quantity known; the remainder is reported as "unattributed".
* Period change % = (current − previous) / |previous|; undefined (n/a) when previous is 0.
* Percent shares can exceed 100 % when other groups move the opposite way; the text says so.
* Cost-like metrics treat an *increase* as the adverse direction when wording recommendations.
* Numbers keep decimals when small (4.56 is never shown as 5).
* Data is analysed **as stored**. Nothing is cleaned or merged silently, so the SQL shown reproduces the numbers in the SQL editor. Label variants (`' north '` vs `North`) are reported as a data-quality insight instead.
* Ambiguous dates (`03/04/2025`): the convention is decided from the whole column (a field > 12 proves day- or month-first); a fully ambiguous column is read day-first; an inconsistent column is left as text.

## Guard rails against answering the wrong question
* "Why did *profit* fall?" with no profit column uses revenue − cost; it never substitutes revenue silently.
* Metrics that are not additive (prices, rates, margins, percentages) or not available (orders, customers, churn) produce a clear error instead of a misleading sum.
* "May" is read as a month only after a preposition ("in May"); "last year" does not change the comparison grain.
* If you ask about a *decrease* but the metric actually increased, the answer says so first.
* Groups backed by fewer than 5 rows are not called "performers" or "declining".

## Known limits
* Scenarios are **linear estimates** (price × volume × elasticity). They are not forecasts and ignore competitors, seasonality and capacity.
* Discovery thresholds (3 % share, 10 % change, 5 rows, top-20 % customers) are fixed heuristics, not statistical tests.
* A fact check proves a number matches the data, not that the *business interpretation* is right. Correlation and drivers are descriptive, not causal.
* The optional LLM can only reword text; it is rejected if it introduces a number that is not in the verified text.


## Chat answers

`backend/tests/accuracy/test_chat_accuracy.py` runs about 700 phrasings (5 aggregations × 3 measures × 5 groupings, rankings, distinct counts, 9 filter styles) against data with missing measures and blank labels. For each one the generated DuckDB result is compared with an independent pandas computation (`verify_spec`), and the question is rewritten to canonical wording and parsed back to confirm follow-up merging cannot change its meaning.

Rules the chat follows so that it never answers a different question than the one asked:

- A measure or column the data does not have (`headcount`, `churn`) stops the run with an explanation and the real column list. Typos (`revnue`) are repaired and synonyms (`sales` → `revenue`) mapped, each with a note.
- A capitalised name after “for/in/of” that is not a value in the data (`for Furniture`) is reported, not ignored.
- Codes such as `order_id` are counted (`COUNT(DISTINCT …)`), never summed. “Profit” is calculated as revenue − cost only when both columns exist.
- A filter that matches no rows says why and shows the real range of values; it never falls back to sample rows.
- Relative dates (“last month”) are not guessed; the answer says all periods were used.
- Forecasts use only complete periods, pick the best of several models by backtest on the latest periods, show an approximate 80% range and a confidence label, and are marked ESTIMATE. History is re-summed with SQL and the forecast is reproduced from it during validation. Fewer than 8 periods are refused.
