from pydantic import BaseModel, Field, field_validator


class RegisterIn(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: str
    password: str


class SqlSourceIn(BaseModel):
    url: str = Field(min_length=8, description="SQLAlchemy URL, e.g. postgresql+psycopg://user:pw@host/db")
    name: str = Field(min_length=1, max_length=120)
    table: str | None = None
    query: str | None = None


class CleanIn(BaseModel):
    op: str
    column: str | None = None
    strategy: str | None = None


class SqlQueryIn(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    dataset_ids: list[int] | None = None
    max_rows: int = Field(default=1000, ge=1, le=10_000)


class SqlGenerateIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    dataset_id: int


class SavedQueryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sql: str = Field(min_length=1, max_length=20_000)


class AnalysisIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    dataset_ids: list[int] = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class ConversationIn(BaseModel):
    dataset_ids: list[int] = Field(default_factory=list)
    title: str = "New conversation"


class MessageIn(BaseModel):
    content: str = Field(min_length=2, max_length=2000)
    dataset_ids: list[int] | None = None


class ReportIn(BaseModel):
    analysis_id: int
    format: str = Field(pattern="^(pdf|xlsx)$")
    title: str | None = Field(default=None, max_length=255)


class PreferencesIn(BaseModel):
    theme: str | None = Field(default=None, pattern="^(light|dark|system)$")
    default_row_limit: int | None = Field(default=None, ge=10, le=10_000)
    name: str | None = Field(default=None, max_length=120)


# ---------- advanced analytics ----------
class FilterIn(BaseModel):
    column: str
    op: str = "eq"
    value: object = None


class ValueIn(BaseModel):
    column: str = "*"
    agg: str = "sum"


class PivotIn(BaseModel):
    dataset_id: int
    rows: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    values: list[ValueIn] = Field(min_length=1)
    filters: list[FilterIn] = Field(default_factory=list)
    totals: bool = True


class PivotExportIn(PivotIn):
    format: str = Field(default="xlsx", pattern="^(csv|xlsx)$")


class RegressionIn(BaseModel):
    dataset_id: int
    target: str
    features: list[str] = Field(min_length=1)
    auto_select: bool = False
    alpha: float = Field(default=0.05, gt=0, lt=1)


class HypothesisIn(BaseModel):
    dataset_id: int
    test: str
    value: str | None = None
    value2: str | None = None
    group: str | None = None
    groups: list[str] | None = None
    alpha: float = Field(default=0.05, gt=0, lt=1)


class ParetoIn(BaseModel):
    dataset_id: int
    category: str
    value: str | None = None
    a_cut: float = Field(default=80, gt=0, le=100)
    b_cut: float = Field(default=95, gt=0, le=100)


class VarianceMetricIn(BaseModel):
    column: str
    kind: str = "revenue"
    target_column: str | None = None
    target_value: float | None = None


class VarianceIn(BaseModel):
    dataset_id: int
    mode: str = Field(pattern="^(target|period)$")
    metrics: list[VarianceMetricIn] = Field(min_length=1)
    group_by: str | None = None
    tolerance_pct: float = Field(default=0, ge=0, le=100)
    derive_profit: dict | None = None
    date_column: str | None = None
    period: str = "month"
    current: str | None = None
    previous: str | None = None


# ---------- AI intelligence ----------
class RootCauseIn(BaseModel):
    dataset_id: int
    question: str | None = Field(default=None, max_length=2000)
    metric: str | None = None
    date_column: str | None = None
    grain: str = Field(default="month", pattern="^(day|week|month|quarter|year)$")
    current: str | None = None
    previous: str | None = None
    dimensions: list[str] | None = None
    number_mode: str = Field(default="standard", pattern="^(standard|indian|inr)$")


class ModeIn(BaseModel):
    dataset_id: int
    number_mode: str = Field(default="standard", pattern="^(standard|indian|inr)$")


class ExecExportIn(ModeIn):
    format: str = Field(default="pdf", pattern="^(pdf|xlsx)$")


class SegmentIn(BaseModel):
    column: str
    values: list[str] = Field(min_length=1)


class ScenarioItemIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    price_change_pct: float = 0
    volume_change_pct: float = 0
    cost_change_pct: float = 0
    elasticity: float = 0
    fixed_cost_pct: float = 0
    segment: SegmentIn | None = None


class ScenarioIn(BaseModel):
    dataset_id: int
    scenarios: list[ScenarioItemIn] = Field(min_length=1, max_length=5)
    revenue: str | None = None
    cost: str | None = None
    quantity: str | None = None
    date_column: str | None = None
    baseline_scope: str = Field(default="all", pattern="^(all|latest)$")
    grain: str = Field(default="month", pattern="^(week|month|quarter|year)$")
    group_by: str | None = None
    number_mode: str = Field(default="standard", pattern="^(standard|indian|inr)$")


# ---------- duplicates ----------
class DupOptionsIn(BaseModel):
    columns: list[str] | None = None
    blank_as_missing: bool = True
    ignore_case_space: bool = False
    exclude_id_like: bool = False
    limit: int = Field(default=100, ge=1, le=500)


class DupRowsIn(DupOptionsIn):
    row_numbers: list[int] = Field(min_length=1, max_length=200)


class DupExportIn(DupOptionsIn):
    format: str = Field(default="csv", pattern="^(csv|xlsx)$")
    scope: str = Field(default="groups", pattern="^(groups|rows)$")


class GeoMappingIn(BaseModel):
    country: str | None = None
    state: str | None = None
    city: str | None = None
    revenue: str | None = None
    expense: str | None = None
    loss: str | None = None
    profit: str | None = None
    date: str | None = None
    assumed_country: str | None = Field(default=None, pattern="^[A-Z0-9]{3}$")


class GeoSummaryIn(BaseModel):
    dataset_id: int
    level: str = Field(default="world", pattern="^(world|country|state|city)$")
    country: str | None = Field(default=None, pattern="^[A-Z0-9]{3}$")
    state: str | None = Field(default=None, max_length=200)
    date_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    mapping: GeoMappingIn | None = None
