export interface User { id: number; email: string; name: string; role: string; preferences: { theme?: "light" | "dark" | "system"; default_row_limit?: number } }
export interface ColumnProfile {
  name: string; dtype: string; type: string; missing: number; missing_pct: number; unique: number; unique_pct: number;
  min?: number | string; max?: number | string; mean?: number; median?: number; std?: number; q1?: number; q3?: number; skew?: number;
  histogram?: { bin: string; start?: number; end?: number; count: number; pct?: number }[]; integer?: boolean; top_values?: { value: string; count: number; pct: number }[];
}
export interface Profile { rows: number; columns: number; duplicate_rows: number; missing_cells: number; memory_bytes: number; numeric_columns: string[]; categorical_columns: string[]; datetime_columns: string[]; column_profiles: ColumnProfile[] }
export interface QualityIssue { severity: "high" | "medium" | "low"; column: string | null; type: string; message: string; fix: string }
export interface Quality { score: number; grade: string; dimensions: Record<string, number>; missing_cells: number; duplicate_rows: number; issues: QualityIssue[] }
export interface Dataset {
  id: number; name: string; kind: "table" | "document"; source_type: string; table_name: string; original_filename: string; status: string;
  row_count: number; column_count: number; size_bytes: number; quality_score: number | null; created_at: string; updated_at: string;
  profile?: Profile & { preview?: string; words?: number }; quality?: Quality; cleaning_log?: { op: string; message: string; column?: string }[];
}
export interface ChartSpec { type: "bar" | "line" | "pie" | "scatter" | "histogram" | "heatmap" | "pareto"; title: string; x: string; y: string[]; data: Record<string, any>[]; columns?: string[]; note?: string; signed?: boolean; line?: Record<string, any>[]; integer?: boolean; total?: number; colors?: string[] }
export interface TraceEvent { agent: string; label: string; status: "completed" | "failed"; summary: string; duration_ms: number }
export interface Evidence { type: string; text: string; verified?: boolean; sql?: string; table?: string; method?: string; source?: string; score?: number }
export interface Citation { source: string; chunk: number; score: number; snippet: string }
export interface Validation { checks: { claim: string; passed: boolean; detail: string }[]; passed: number; total: number; dropped: number; status: string }
export interface Report {
  title: string; question: string; answer: string; kpis: { label: string; value: string | number }[];
  insights: { kind: string; severity: string; text: string; verified?: boolean; verification?: string }[]; recommendations: string[];
  sql?: string; result_columns?: string[]; result_rows?: Record<string, any>[]; charts: ChartSpec[]; citations: Citation[]; evidence: Evidence[]; validation: Validation; datasets: string[];
  autopilot?: { headline: string; sections: { id: string; title: string; statements: StoryStatement[]; notes?: { kind: string; text: string; verified?: boolean }[] }[];
    steps_run: string[]; findings: number; verified: string; kpis: { label: string; value: string | number }[] } | null;
  story?: Story | null; root_cause?: RootCause | null; scenario?: ScenarioResult | null; discovery?: Discovery | null; executive?: Executive | null;
}
export interface Analysis {
  id: number; question: string; status: "queued" | "running" | "completed" | "failed"; dataset_id: number | null; created_at: string; finished_at: string | null;
  error: string; trace: TraceEvent[]; plan?: { steps: string[]; pipeline: string[]; rationale: string }; answer?: string;
  result?: { report?: Report; validation?: Validation; plan?: Analysis["plan"] };
}
export interface Message { id: number; role: "user" | "assistant"; content: string; created_at: string; payload: {
  analysis_id?: number; sql?: string; charts?: ChartSpec[]; evidence?: Evidence[]; citations?: Citation[]; trace?: TraceEvent[]; validation?: Validation;
  result_columns?: string[]; result_rows?: Record<string, any>[];
  resolved_question?: string; followup_note?: string | null; interpretation?: string | null; notes?: string[]; recommendations?: string[]; intents?: string[];
  clarification?: { message: string; missing: string[]; suggestions: Record<string, string[]>; columns: string[] } | null } }
export interface Conversation { id: number; title: string; dataset_id: number | null; created_at: string }
export interface SavedReport { id: number; title: string; format: "pdf" | "xlsx"; size_bytes: number; analysis_id: number | null; created_at: string }
export interface QueryResult { sql: string; columns: string[]; rows: Record<string, any>[]; row_count: number; truncated: boolean; elapsed_ms: number; chart: ChartSpec | null }
export interface Overview {
  kpis: { datasets: number; total_rows: number; analyses: number; completed_analyses: number; reports: number; avg_quality: number | null };
  recent_datasets: Dataset[]; recent_analyses: Analysis[]; top_issues: (QualityIssue & { dataset: string })[]; quality_by_dataset: { name: string; score: number }[];
}
export interface SchemaTable { dataset_id: number; table: string; name: string; rows: number; columns: { name: string; type: string; dtype: string }[] }
export interface Settings { user: User; system: { app_env: string; database: string; database_location: string; llm_provider: string; llm_enabled: boolean; llm_model: string | null; max_upload_mb: number; max_query_rows: number; query_timeout_seconds: number; supported_formats: string[] } }

export interface FieldMeta { name: string; kind: "numeric" | "datetime" | "category" | "text"; unique: number; values?: string[]; min?: any; max?: any; measure: boolean }
export interface FieldsResponse { columns: FieldMeta[]; rows: number }
export interface PivotResult { row_fields: string[]; column_fields: string[]; value_labels: string[]; columns: string[]; rows: Record<string, any>[]; row_count: number; source_rows: number; has_totals: boolean; chart: ChartSpec | null }
export interface Coef { name: string; coef: number; std_err: number; t: number; p_value: number; ci_low: number; ci_high: number; significant: boolean }
export interface RegressionResult {
  target: string; features: string[]; removed_by_selection: string[]; n: number; dropped_rows: number; kind: "simple" | "multiple";
  metrics: { r2: number; adj_r2: number; f_stat: number; f_p_value: number; rmse: number; mae: number; aic: number; bic: number };
  holdout: { n_train: number; n_test: number; r2: number; rmse: number; mae: number } | null; coefficients: Coef[];
  diagnostics: Record<string, number>; vif: { name: string; vif: number }[]; influential_points: { row: number; cooks_d: number; residual: number }[];
  charts: { actual_vs_predicted: { actual: number; predicted: number }[]; perfect_line: { actual: number; predicted: number }[]; residuals_vs_fitted: { fitted: number; residual: number }[]; residual_histogram: { bin: string; count: number }[]; coefficient_bars: { name: string; coef: number }[] };
  interpretation: string[]; warnings: string[];
}
export interface HypothesisResult {
  test: string; name: string; statistic: number; p_value: number; df: number | number[]; alpha: number; significant: boolean; mean_difference?: number; ci_low?: number; ci_high?: number; confidence?: number;
  effect_size: { name: string; value: number; label: string }; groups: { group: string; n: number; mean: number; std: number; median: number; ci_low: number; ci_high: number }[];
  notes: string[]; interpretation: string; chart: ChartSpec; contingency?: { rows: string[]; columns: string[]; counts: number[][] };
}
export interface ParetoRow { rank: number; category: string; value: number; share_pct: number; cum_pct: number; class: "A" | "B" | "C" }
export interface ParetoResult { category: string; measure: string; total: number; n_items: number; rows: ParetoRow[]; summary: { class: string; items: number; items_pct: number; value: number; value_pct: number }[]; items_for_80pct: number; items_for_80pct_pct: number; interpretation: string; notes: string[]; chart: ChartSpec }
export interface VarianceRow { metric: string; group: string | null; kind: string; actual: number; comparator: number; variance: number; variance_pct: number | null; status: "favourable" | "unfavourable" | "on_target" }
export interface VarianceResult { mode: "target" | "period"; rows: VarianceRow[]; summary: { favourable: number; unfavourable: number; on_target: number }; chart: ChartSpec; interpretation: string; current_period?: string; previous_period?: string; periods?: string[]; series?: { period: string; metric: string; value: number; previous: number; variance: number; variance_pct: number | null }[] }

// ---------- AI intelligence ----------
export interface Fact { id: string; label: string; value: number | null; unit: string; sql?: string | null; op?: string | null; inputs?: string[]; estimate?: boolean }
export interface Footnote { n: number; fact: string; label: string; value: number | null; unit: string; sql?: string | null; op?: string | null; inputs?: string[] | null; estimate: boolean; verified: boolean | null; detail?: string | null }
export interface StoryStatement { text: string; facts: string[]; kind: string; source?: string; verified?: boolean; refs?: number[] }
export interface Story { statements: StoryStatement[]; footnotes?: Footnote[]; text?: string; recommendations: string[]; dropped: number; headline?: string }
export interface Verification { [id: string]: { verified: boolean; detail: string } }
export interface RootCause {
  metric: string; grain: string; current: string; previous: string; direction: string; mode: string;
  totals: { current: number; previous: number; change: number; change_pct: number | null };
  dimensions: { dimension: string; n_groups: number; concentration: number; top: { group: string; previous: number; current: number; change: number; share_of_change_pct: number | null }[] }[];
  cells: { dim1: string; value1: string; dim2: string; value2: string; previous: number; current: number; change: number; share_of_change_pct: number | null }[];
  drivers: { kind: string; quantity?: string; volume_effect: number; price_mix_effect: number; mix_effect?: number; like_for_like_price_effect?: number; mix_dimension?: string; quantity_change_pct: number | null; unit_value_change_pct?: number | null } | Record<string, never>;
  seasonality: { prior_period: string; prior_previous: string; prior_change_pct: number | null; likely_seasonal: boolean } | null;
  factors: { type: string; title: string; impact: number; share_pct: number | null }[]; offsets: { group: string; change: number }[];
  facts: Fact[]; verification: Verification; charts: ChartSpec[]; reconciliation: { check: string; passed: boolean; detail: string }[]; complete_current_period: boolean; story: Story;
}
export interface Insight { id: string; type: string; severity: "high" | "medium" | "low" | "info"; title: string; text: string; facts: string[]; score: number; verified: boolean; verification_detail: string; investigate?: { tool: string; metric?: string; current?: string; grain?: string; category?: string; value?: string } | null }
export interface Discovery { insights: Insight[]; facts: Fact[]; verification: Verification; dropped_unverified: number; skipped: string[]; metric: string | null; period: { current: string | null; previous: string | null }; summary: Record<string, number> }
export interface ExecKpi { label: string; value: number | null; unit: string; period_value: number | null; change_pct: number | null; verified: boolean }
export interface Executive {
  title: string; period: string; metric: string; performance: StoryStatement[]; kpis: ExecKpi[]; findings: Insight[]; risks: Insight[]; opportunities: Insight[];
  recommendations: { text: string; insight: string | null; priority: "high" | "medium" | "low" }[]; charts: ChartSpec[];
  evidence: { id: string; label: string; value: number | null; unit: string; sql?: string | null; op?: string | null; inputs?: string[]; verified: boolean; detail: string }[];
  facts: Fact[]; verification: Verification; data_quality_score: number | null; data_notes?: string[];
}
export interface ScenarioAssumptions { price_change_pct: number; volume_change_pct: number; elasticity: number; cost_change_pct: number; fixed_cost_pct: number }
export interface ScenarioResult {
  kind: "scenario_estimate"; disclaimer: string; baseline_scope: string; observed: Record<string, string>; facts: Fact[]; verification: Verification;
  scenarios: { name: string; segment: string; assumptions: ScenarioAssumptions; facts: Record<string, string>; notes: string[]; breakdown: Record<string, any>[] }[];
  sensitivity: { price_change_pct: number; revenue: number; cost?: number; profit?: number }[];
  elasticity_hint: { available: boolean; message: string; elasticity?: number } | null; data_notes?: string[]; columns: { revenue: string; cost: string | null; quantity: string | null };
}
export interface DataRoles { revenue: string | null; cost: string | null; quantity: string | null; price: string | null; date: string | null; customer: string | null; product: string | null; dimensions: string[]; measures: string[] }

// ---------- duplicate analysis ----------
export interface DupGroup { id: number; count: number; extra: number; first_row: number; row_numbers: number[]; values: Record<string, any>; share_of_duplicates_pct: number }
export interface DupOptions { columns: string[] | null; blank_as_missing: boolean; ignore_case_space: boolean; exclude_id_like: boolean; limit: number }
export interface DupResult {
  unit: "rows" | "paragraphs"; rows: number; columns_used: string[]; all_columns: boolean; duplicate_rows: number; duplicate_pct: number; groups: number;
  rows_involved: number; rows_involved_pct: number; unique_rows: number; unique_records: number; largest_group: number; blank_cells_treated_as_missing: number;
  options: Partial<DupOptions>; groups_list: DupGroup[]; groups_returned: number;
  distribution: { label: string; groups: number; extra_rows: number; rows: number }[]; top: { label: string; count: number; id: number }[];
  composition: { label: string; value: number }[]; hint: { columns: string[]; duplicate_rows: number; groups: number; message: string } | null;
}
