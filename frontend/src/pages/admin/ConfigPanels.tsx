import { useMutation, useQuery } from "@tanstack/react-query";
import { Mail, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { Badge, Card, ErrorNote, Spinner, Stat } from "../../components/ui";
import { Field, NumInput, SecretBadge, SettingsCard, Toggle, money } from "./forms";
import { TableWrap, fmtNum } from "./common";

const FEATURE_LABELS: [string, string, string][] = [
  ["ai_chat", "AI Chat", "Ask-your-data conversations"], ["data_cleaning", "Data Cleaning", "Cleaning operations and duplicate detection"], ["eda", "EDA", "Advanced analytics tools"],
  ["ai_agents", "AI Agents", "Multi-agent analysis workspace and intelligence"], ["sql_analysis", "SQL Analysis", "SQL editor and NL→SQL"], ["data_visualization", "Data Visualization", "Charts in analyses and chat"],
  ["pdf_reports", "PDF Reports", "PDF report generation"], ["excel_reports", "Excel Reports", "Excel report generation"], ["document_research", "Document Research", "Uploading and querying PDFs/Word/text"],
];

export function FeaturesPanel() {
  return (
    <div className="space-y-6">
      <SettingsCard<Record<string, boolean>> group="features" title="Platform-wide feature switches">{(f) => (
        <div className="divide-y divide-slate-100 dark:divide-white/5">
          <p className="pb-3 text-xs text-slate-500">Switching a feature off disables it for <b>everyone</b>, including via the API. Per-plan access and usage limits are set under Subscriptions &amp; Pricing.</p>
          {FEATURE_LABELS.map(([k, label, hint]) => <Toggle key={k} label={label} hint={hint} checked={f.draft![k] !== false} onChange={(v) => f.set(k, v)} />)}
        </div>)}</SettingsCard>
      <UploadSettings />
    </div>
  );
}

export function UploadSettings() {
  return (
    <SettingsCard<{ max_upload_mb: number; allowed_formats: string[]; storage_limit_gb: number | null }> group="uploads" title="Upload limits & allowed formats">{(f) => {
      const all: string[] = f.q.data?.all_formats ?? [];
      const on = new Set(f.draft!.allowed_formats);
      return (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Maximum upload size (MB)" hint="Applies to everyone; a plan can set a lower file-size limit."><NumInput min={1} value={f.draft!.max_upload_mb} onChange={(v) => f.set("max_upload_mb", v ?? 1)} placeholder="100" /></Field>
            <Field label="Total storage limit (GB)" hint="Platform-wide cap across all datasets. Empty = unlimited."><NumInput step={0.5} min={0.1} value={f.draft!.storage_limit_gb} onChange={(v) => f.set("storage_limit_gb", v)} /></Field>
          </div>
          <div><p className="label">Allowed file formats</p><div className="flex flex-wrap gap-2">{all.map((e) => (
            <button key={e} type="button" aria-pressed={on.has(e)} onClick={() => { const n = new Set(on); n.has(e) ? n.delete(e) : n.add(e); f.set("allowed_formats", all.filter((x) => n.has(x))); }}
              className={`rounded-full border px-3 py-1 font-mono text-xs ${on.has(e) ? "border-brand-600 bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200" : "border-slate-200 text-slate-400 line-through dark:border-white/10"}`}>{e}</button>))}</div></div>
        </div>);
    }}</SettingsCard>
  );
}

interface AiVals { provider: string; model: string; temperature: number | null; max_output_tokens: number | null; system_prompt: string; fallback_provider: string; fallback_model: string; monthly_token_cap: number | null; daily_call_cap: number | null; prices: Record<string, { input_per_m: number; output_per_m: number }> }
interface AiSummary { month_tokens: number; month_cost_usd: number; by_model: { model: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number; priced: boolean }[]; monthly_token_cap: number | null; daily_call_cap: number | null; calls_24h: number; unpriced_models: string[]; providers: Record<string, boolean> }

export function AiPanel() {
  const sum = useQuery({ queryKey: ["admin", "ai-summary"], queryFn: () => api.get<AiSummary>("/admin/ai/summary") });
  return (
    <div className="space-y-6">
      {sum.data && (<>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat label="Tokens this month" value={fmtNum(sum.data.month_tokens)} hint={sum.data.monthly_token_cap ? `cap ${fmtNum(sum.data.monthly_token_cap)}` : "no cap"} />
          <Stat label="Estimated cost (month)" value={`$${sum.data.month_cost_usd.toFixed(2)}`} tone="amber" hint={sum.data.unpriced_models.length ? "some models unpriced" : "from price table"} />
          <Stat label="Calls (24h)" value={sum.data.calls_24h} tone="green" hint={sum.data.daily_call_cap ? `cap ${sum.data.daily_call_cap}` : "no cap"} />
          <div className="card p-5"><p className="text-sm text-slate-500">Provider keys</p><div className="mt-2 flex gap-2">{Object.entries(sum.data.providers).map(([p, ok]) => <Badge key={p} tone={ok ? "green" : "slate"}>{p}: {ok ? "set" : "missing"}</Badge>)}</div></div>
        </div>
        {sum.data.by_model.length > 0 && <Card title="Cost by model (this month)" pad={false}><TableWrap><thead><tr><th className="th">Model</th><th className="th text-right">Calls</th><th className="th text-right">In</th><th className="th text-right">Out</th><th className="th text-right">Cost</th></tr></thead>
          <tbody>{sum.data.by_model.map((m) => <tr key={m.model}><td className="td">{m.model || "—"}</td><td className="td text-right tabular-nums">{m.calls}</td><td className="td text-right tabular-nums">{fmtNum(m.input_tokens)}</td><td className="td text-right tabular-nums">{fmtNum(m.output_tokens)}</td><td className="td text-right tabular-nums">{m.priced ? `$${m.cost_usd.toFixed(4)}` : <span className="text-amber-600">set price</span>}</td></tr>)}</tbody></TableWrap></Card>}
      </>)}
      <SettingsCard<AiVals> group="ai" title="Model & generation">{(f) => (
        <div className="space-y-4">
          <p className="text-xs text-slate-500">Active now: <b>{f.q.data?.runtime?.provider || "none"}</b> / <b>{f.q.data?.runtime?.model || "—"}</b> ({f.q.data?.runtime?.enabled ? "key present" : "no API key — running deterministic mode"}). Leave provider/model blank to use the server's <code>LLM_PROVIDER</code> / <code>LLM_MODEL</code>.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Provider"><select className="input" value={f.draft!.provider} onChange={(e) => f.set("provider", e.target.value)}><option value="">Server default</option><option value="anthropic">Anthropic</option><option value="google">Google</option></select></Field>
            <Field label="Model"><input className="input" value={f.draft!.model} onChange={(e) => f.set("model", e.target.value)} placeholder="Provider default" /></Field>
            <Field label="Temperature (0–2)" hint="Empty = server default"><NumInput step={0.1} value={f.draft!.temperature} onChange={(v) => f.set("temperature", v)} placeholder="default" /></Field>
            <Field label="Max output tokens per call" hint="Caps every request. Empty = per-call defaults."><NumInput min={1} value={f.draft!.max_output_tokens} onChange={(v) => f.set("max_output_tokens", v)} /></Field>
            <Field label="Fallback provider"><select className="input" value={f.draft!.fallback_provider} onChange={(e) => f.set("fallback_provider", e.target.value)}><option value="">None</option><option value="anthropic">Anthropic</option><option value="google">Google</option></select></Field>
            <Field label="Fallback model" hint="Used when the primary call fails"><input className="input" value={f.draft!.fallback_model} onChange={(e) => f.set("fallback_model", e.target.value)} placeholder="Provider default" /></Field>
          </div>
          <Field label="System prompt (appended to every agent prompt)" hint="Tone, policies or company context. Max 4000 characters."><textarea rows={4} className="input" maxLength={4000} value={f.draft!.system_prompt} onChange={(e) => f.set("system_prompt", e.target.value)} /></Field>
          <SecretBadge name="ANTHROPIC_API_KEY / GOOGLE_API_KEY" set={f.q.data?.secrets?.anthropic_key_set || f.q.data?.secrets?.google_key_set} />
        </div>)}</SettingsCard>
      <SettingsCard<AiVals> group="ai" title="Usage limits (all users)" keys={["monthly_token_cap", "daily_call_cap"]}>{(f) => (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Monthly token cap" hint="When reached, AI wording is skipped and analyses use deterministic logic."><NumInput min={1} value={f.draft!.monthly_token_cap} onChange={(v) => f.set("monthly_token_cap", v)} /></Field>
          <Field label="Daily call cap (rolling 24h)"><NumInput min={1} value={f.draft!.daily_call_cap} onChange={(v) => f.set("daily_call_cap", v)} /></Field>
        </div>)}</SettingsCard>
      <SettingsCard<AiVals> group="ai" title="Price table (for cost estimates)" keys={["prices"]}>{(f) => <PriceEditor prices={f.draft!.prices} onChange={(p) => f.set("prices", p)} />}</SettingsCard>
    </div>
  );
}

function PriceEditor({ prices, onChange }: { prices: AiVals["prices"]; onChange: (p: AiVals["prices"]) => void }) {
  const [name, setName] = useState("");
  const upd = (m: string, k: "input_per_m" | "output_per_m", v: number) => onChange({ ...prices, [m]: { ...prices[m], [k]: v } });
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">USD per 1M tokens. Costs shown across the panel are estimates from these numbers — check your provider's current pricing.</p>
      {Object.entries(prices).map(([m, p]) => (
        <div key={m} className="grid grid-cols-[1fr_90px_90px_auto] items-end gap-2"><Field label="Model"><input className="input" value={m} readOnly /></Field>
          <Field label="Input"><NumInput step={0.01} value={p.input_per_m} onChange={(v) => upd(m, "input_per_m", v ?? 0)} placeholder="0" /></Field><Field label="Output"><NumInput step={0.01} value={p.output_per_m} onChange={(v) => upd(m, "output_per_m", v ?? 0)} placeholder="0" /></Field>
          <button className="btn-ghost mb-0.5 !px-2" aria-label={`Remove ${m}`} onClick={() => { const n = { ...prices }; delete n[m]; onChange(n); }}><Trash2 className="h-4 w-4" /></button></div>))}
      <div className="flex gap-2"><input className="input" placeholder="model name, e.g. claude-sonnet-5-5" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn-ghost shrink-0" disabled={!name.trim() || name in prices} onClick={() => { onChange({ ...prices, [name.trim()]: { input_per_m: 0, output_per_m: 0 } }); setName(""); }}><Plus className="h-4 w-4" /> Add</button></div>
    </div>
  );
}

// ---------------------------------------------------------------- platform settings
interface PlatVals { app_name: string; tagline: string; primary_color: string; logo_url: string; support_email: string; public_url: string; maintenance_mode: boolean; maintenance_message: string; registration_open: boolean; email_verification: boolean; announcement: string; announcement_tone: string }
interface SmtpVals { host: string; port: number; username: string; from_email: string; from_name: string; use_tls: boolean }
interface NotifVals { verification_subject: string; verification_body: string; welcome_subject: string; welcome_body: string; suspended_subject: string; suspended_body: string }

export function PlatformPanel() {
  const [to, setTo] = useState("");
  const test = useMutation({ mutationFn: () => api.post<{ ok: boolean; error: string }>("/admin/settings/smtp/test", { to }) });
  return (
    <div className="space-y-6">
      <SettingsCard<PlatVals> group="platform" title="Branding" keys={["app_name", "tagline", "primary_color", "logo_url", "support_email", "public_url"]}>{(f) => (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Application name"><input className="input" maxLength={60} value={f.draft!.app_name} onChange={(e) => f.set("app_name", e.target.value)} /></Field>
          <Field label="Tagline"><input className="input" maxLength={160} value={f.draft!.tagline} onChange={(e) => f.set("tagline", e.target.value)} /></Field>
          <Field label="Primary colour" hint="Empty = built-in theme"><div className="flex gap-2"><input type="color" aria-label="Pick colour" className="h-10 w-12 shrink-0 cursor-pointer rounded border border-slate-300 bg-transparent p-1 dark:border-white/15" value={/^#[0-9a-f]{6}$/i.test(f.draft!.primary_color) ? f.draft!.primary_color : "#6366f1"} onChange={(e) => f.set("primary_color", e.target.value)} />
            <input className="input font-mono" value={f.draft!.primary_color} placeholder="#6366f1" onChange={(e) => f.set("primary_color", e.target.value)} />{f.draft!.primary_color && <button className="btn-ghost" onClick={() => f.set("primary_color", "")}>Reset</button>}</div></Field>
          <Field label="Logo URL" hint="https://… or /path (square, ≥64px)"><input className="input" value={f.draft!.logo_url} onChange={(e) => f.set("logo_url", e.target.value)} placeholder="https://…" /></Field>
          <Field label="Support email"><input className="input" type="email" value={f.draft!.support_email} onChange={(e) => f.set("support_email", e.target.value)} /></Field>
          <Field label="Public app URL" hint="Used in email links"><input className="input" value={f.draft!.public_url} onChange={(e) => f.set("public_url", e.target.value)} /></Field>
        </div>)}</SettingsCard>

      <SettingsCard<PlatVals> group="platform" title="Access & availability" keys={["maintenance_mode", "maintenance_message", "registration_open", "email_verification"]}>{(f) => (
        <div className="space-y-2">
          <Toggle label="Maintenance mode" hint="Blocks the app API for everyone with a 503 and your message. The admin panel and sign-in stay reachable." checked={f.draft!.maintenance_mode} onChange={(v) => f.set("maintenance_mode", v)} />
          {f.draft!.maintenance_mode && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">Saving will take the app offline for all non-admin users.</p>}
          <Field label="Maintenance message"><input className="input" maxLength={500} value={f.draft!.maintenance_message} onChange={(e) => f.set("maintenance_message", e.target.value)} /></Field>
          <Toggle label="Registration open" hint="When off, new sign-ups are rejected." checked={f.draft!.registration_open} onChange={(v) => f.set("registration_open", v)} />
          <Toggle label="Require email verification" hint="New users must click an emailed link before signing in. Requires working SMTP." checked={f.draft!.email_verification} onChange={(v) => f.set("email_verification", v)} />
        </div>)}</SettingsCard>

      <SettingsCard<PlatVals> group="platform" title="Announcement banner" keys={["announcement", "announcement_tone"]}>{(f) => (
        <div className="grid gap-3 sm:grid-cols-[1fr_160px]">
          <Field label="Message" hint="Shown at the top of the app for all users. Empty = hidden."><input className="input" maxLength={300} value={f.draft!.announcement} onChange={(e) => f.set("announcement", e.target.value)} /></Field>
          <Field label="Style"><select className="input" value={f.draft!.announcement_tone} onChange={(e) => f.set("announcement_tone", e.target.value)}><option value="info">Info</option><option value="warn">Warning</option><option value="success">Success</option></select></Field>
        </div>)}</SettingsCard>

      <SettingsCard<SmtpVals> group="smtp" title="Email (SMTP)">{(f) => (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Host"><input className="input" value={f.draft!.host} onChange={(e) => f.set("host", e.target.value)} placeholder="smtp.example.com" /></Field>
            <Field label="Port"><NumInput min={1} value={f.draft!.port} onChange={(v) => f.set("port", v ?? 587)} placeholder="587" /></Field>
            <Field label="Username"><input className="input" value={f.draft!.username} autoComplete="off" onChange={(e) => f.set("username", e.target.value)} /></Field>
            <Field label="From address"><input className="input" type="email" value={f.draft!.from_email} onChange={(e) => f.set("from_email", e.target.value)} /></Field>
            <Field label="From name"><input className="input" value={f.draft!.from_name} onChange={(e) => f.set("from_name", e.target.value)} /></Field>
          </div>
          <Toggle label="Use STARTTLS" checked={f.draft!.use_tls} onChange={(v) => f.set("use_tls", v)} />
          <SecretBadge name="SMTP_PASSWORD" set={f.q.data?.secrets?.smtp_password_set} />
          <div className="flex flex-wrap items-end gap-2 border-t border-slate-100 pt-4 dark:border-white/5">
            <Field label="Send a test email to" className="min-w-[240px] flex-1"><input className="input" type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="you@example.com" /></Field>
            <button className="btn-ghost" disabled={!to || test.isPending || f.dirty} title={f.dirty ? "Save first" : ""} onClick={() => test.mutate()}>{test.isPending ? <Spinner /> : <Mail className="h-4 w-4" />} Send test</button>
          </div>
          {test.data && <p className={`text-sm ${test.data.ok ? "text-emerald-600" : "text-red-600"}`}>{test.data.ok ? "Test email sent." : `Failed: ${test.data.error}`}</p>}
          <ErrorNote error={test.error} />
        </div>)}</SettingsCard>

      <SettingsCard<NotifVals> group="notifications" title="Notification messages">{(f) => (
        <div className="space-y-5">
          <p className="text-xs text-slate-500">Placeholders: <code>{"{name}"}</code> <code>{"{app}"}</code> <code>{"{url}"}</code> <code>{"{support}"}</code>; verification also has <code>{"{link}"}</code>.</p>
          {([["verification", "Email verification"], ["welcome", "Welcome"], ["suspended", "Account suspended"]] as const).map(([k, label]) => (
            <div key={k} className="space-y-2"><h4 className="text-sm font-semibold">{label}</h4>
              <input className="input" aria-label={`${label} subject`} value={f.draft![`${k}_subject`]} onChange={(e) => f.set(`${k}_subject`, e.target.value)} />
              <textarea rows={4} className="input" aria-label={`${label} body`} value={f.draft![`${k}_body`]} onChange={(e) => f.set(`${k}_body`, e.target.value)} /></div>))}
        </div>)}</SettingsCard>
    </div>
  );
}

export { money };
