import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, Plug, Power, Replace, ShieldAlert, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { Badge, Card, ErrorNote, Loading, Spinner, Stat } from "../../components/ui";
import { Modal, TableWrap, fmtDateTime, fmtNum } from "./common";
import { Field, Toggle } from "./forms";


interface Usage { calls: number; input_tokens: number; output_tokens: number; failures: number; last_used_at: string | null }
interface KeyRow { id: number; provider: string; label: string; masked: string; is_active: boolean; status: "untested" | "valid" | "invalid"; status_message: string; last_tested_at: string | null; created_at: string; updated_at: string; activated_at: string | null; usage: Usage }
interface Overview {
  keys: KeyRow[]; env: Record<string, { configured: boolean; masked: string }>;
  effective: { provider: string; model: string; enabled: boolean; key_source: "admin" | "env" | "none"; masked: string };
  env_usage: Usage | null; model_suggestions: Record<string, string[]>; encryption: { ok: boolean; detail: string }; sync_note: string;
}
interface Event { id: number; api_key_id: number | null; provider: string; action: string; actor: string; detail: string; created_at: string }

const SOURCE = { admin: ["Admin-managed key", "green"], env: ["Environment fallback (.env)", "amber"], none: ["No key — deterministic mode", "slate"] } as const;
const statusTone = (s: KeyRow["status"]) => (s === "valid" ? "green" : s === "invalid" ? "red" : "slate");
const ACTION: Record<string, string> = { create: "Added", update: "Updated", test: "Tested", activate: "Activated", activate_failed: "Activation failed", deactivate: "Deactivated", delete: "Deleted", model_changed: "Model changed" };

export default function ApiKeysPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "ai-keys"], queryFn: () => api.get<Overview>("/admin/ai-keys"), refetchInterval: 30_000 });
  const hist = useQuery({ queryKey: ["admin", "ai-keys", "history"], queryFn: () => api.get<Event[]>("/admin/ai-keys/history?limit=50") });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["admin", "ai-keys"] }); qc.invalidateQueries({ queryKey: ["admin", "ai-summary"] }); };
  const [adding, setAdding] = useState(false);
  const [replacing, setReplacing] = useState<KeyRow | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const act = useMutation({
    mutationFn: ({ id, op }: { id: number; op: "test" | "activate" | "deactivate" | "delete" }) =>
      op === "delete" ? api.del(`/admin/ai-keys/${id}`) : api.post<any>(`/admin/ai-keys/${id}/${op}`),
    onSuccess: (r: any, v) => { setNotice({ ok: v.op !== "test" || r?.ok, text: r?.message ?? (v.op === "activate" ? "Key activated. Requests use it immediately." : v.op === "delete" ? "Key deleted." : "Done.") }); refresh(); },
    onError: (e: Error) => { setNotice({ ok: false, text: e.message }); refresh(); },
  });

  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <ErrorNote error={q.error} />;
  const d = q.data, [srcLabel, srcTone] = SOURCE[d.effective.key_source];
  const google = d.keys.filter((k) => k.provider === "google");
  return (
    <div className="space-y-6">
      {!d.encryption.ok && <p role="alert" className="flex gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300"><ShieldAlert className="h-4 w-4 shrink-0" />{d.encryption.detail}</p>}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="card p-5"><p className="text-sm text-slate-500">Connection</p><div className="mt-2"><Badge tone={d.effective.enabled ? srcTone : "slate"}>{d.effective.enabled ? srcLabel : SOURCE.none[0]}</Badge></div>
          <p className="mt-2 font-mono text-xs text-slate-500">{d.effective.masked || "—"}</p></div>
        <Stat label="Provider / model" value={<span className="text-xl">{d.effective.provider || "none"}</span>} hint={d.effective.model || "default"} icon={Plug} />
        <Stat label="Calls (admin keys)" value={fmtNum(d.keys.reduce((n, k) => n + k.usage.calls, 0))} hint={`${d.keys.reduce((n, k) => n + k.usage.failures, 0)} failed`} tone="green" />
        <Stat label="Calls (.env key)" value={fmtNum(d.env_usage?.calls ?? 0)} hint={d.env.google.configured ? `GOOGLE_API_KEY ${d.env.google.masked}` : "GOOGLE_API_KEY not set"} tone="amber" />
      </div>
      {notice && <p role="status" className={`rounded-lg p-3 text-sm ${notice.ok ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300" : "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300"}`}>{notice.text}</p>}

      <Card title="Google Gemini API keys" action={<button className="btn-primary !py-1.5" onClick={() => setAdding(true)} disabled={!d.encryption.ok}><KeyRound className="h-4 w-4" /> Add key</button>} pad={false}>
        <TableWrap>
          <thead><tr><th className="th">Label</th><th className="th">Key</th><th className="th">Status</th><th className="th">Last tested</th><th className="th">Updated</th><th className="th text-right">Calls</th><th className="th text-right">Tokens</th><th className="th text-right">Actions</th></tr></thead>
          <tbody>
            {d.env.google.configured && (
              <tr className="bg-slate-50/60 dark:bg-white/[0.02]"><td className="td">Environment <span className="text-xs text-slate-500">(GOOGLE_API_KEY)</span></td><td className="td font-mono text-xs">{d.env.google.masked}</td>
                <td className="td">{d.effective.key_source === "env" ? <Badge tone="amber">In use · fallback</Badge> : <Badge>Standby</Badge>}</td><td className="td text-slate-400">—</td><td className="td text-slate-400">—</td>
                <td className="td text-right tabular-nums">{fmtNum(d.env_usage?.calls ?? 0)}</td><td className="td text-right tabular-nums">{fmtNum((d.env_usage?.input_tokens ?? 0) + (d.env_usage?.output_tokens ?? 0))}</td><td className="td text-right text-xs text-slate-400">managed in .env</td></tr>)}
            {google.length === 0 && <tr><td className="td text-slate-500" colSpan={8}>No admin-managed key yet. {d.env.google.configured ? "The .env key is used until you activate one here." : "Add one to enable AI features."}</td></tr>}
            {google.map((k) => (
              <tr key={k.id}>
                <td className="td font-medium">{k.label}</td>
                <td className="td font-mono text-xs">{k.masked}</td>
                <td className="td"><div className="flex flex-wrap items-center gap-1">{k.is_active && <Badge tone="green"><CheckCircle2 className="h-3 w-3" /> Active</Badge>}<Badge tone={statusTone(k.status)}>{k.status === "untested" ? "Not tested" : k.status === "valid" ? "Connected" : "Failed"}</Badge></div>
                  {k.status === "invalid" && <p className="mt-0.5 max-w-[16rem] text-[11px] text-red-600">{k.status_message}</p>}</td>
                <td className="td text-xs text-slate-500">{fmtDateTime(k.last_tested_at)}</td><td className="td text-xs text-slate-500">{fmtDateTime(k.updated_at)}</td>
                <td className="td text-right tabular-nums">{fmtNum(k.usage.calls)}{k.usage.failures > 0 && <span className="text-xs text-red-500"> ({k.usage.failures} failed)</span>}</td>
                <td className="td text-right tabular-nums" title={k.usage.last_used_at ? `Last used ${fmtDateTime(k.usage.last_used_at)}` : "Never used"}>{fmtNum(k.usage.input_tokens + k.usage.output_tokens)}</td>
                <td className="td"><div className="flex justify-end gap-1">
                  <button className="btn-ghost !px-2 !py-1 text-xs" disabled={act.isPending} onClick={() => act.mutate({ id: k.id, op: "test" })}><Plug className="h-3.5 w-3.5" /> Test</button>
                  {k.is_active ? <button className="btn-ghost !px-2 !py-1 text-xs" disabled={act.isPending} onClick={() => confirm("Deactivate this key? The app falls back to the .env key, or deterministic mode if none.") && act.mutate({ id: k.id, op: "deactivate" })}><Power className="h-3.5 w-3.5" /> Deactivate</button>
                    : <button className="btn-ghost !px-2 !py-1 text-xs" disabled={act.isPending} onClick={() => act.mutate({ id: k.id, op: "activate" })}><Power className="h-3.5 w-3.5" /> Activate</button>}
                  <button className="btn-ghost !px-2 !py-1 text-xs" aria-label={`Replace key ${k.label}`} onClick={() => setReplacing(k)}><Replace className="h-3.5 w-3.5" /></button>
                  {!k.is_active && <button className="btn-danger !px-2 !py-1" aria-label={`Delete key ${k.label}`} disabled={act.isPending} onClick={() => confirm(`Delete “${k.label}”? This cannot be undone.`) && act.mutate({ id: k.id, op: "delete" })}><Trash2 className="h-3.5 w-3.5" /></button>}
                </div></td>
              </tr>))}
          </tbody>
        </TableWrap>
        <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500 dark:border-white/5">Keys are encrypted at rest ({d.encryption.detail}) and shown only as masked values. {d.sync_note} Activation always tests the key first; an admin key outranks the .env key.</p>
      </Card>

      <ModelCard o={d} onDone={(t) => { setNotice({ ok: true, text: t }); refresh(); }} onError={(t) => setNotice({ ok: false, text: t })} />

      <Card title="Change history" pad={false}>
        {hist.data?.length ? <TableWrap><thead><tr><th className="th">When</th><th className="th">Action</th><th className="th">By</th><th className="th">Details</th></tr></thead>
          <tbody>{hist.data.map((e) => <tr key={e.id}><td className="td whitespace-nowrap text-xs text-slate-500">{fmtDateTime(e.created_at)}</td><td className="td">{ACTION[e.action] ?? e.action}</td><td className="td text-xs">{e.actor}</td><td className="td text-xs text-slate-500">{e.api_key_id ? `key #${e.api_key_id} · ` : ""}{e.detail}</td></tr>)}</tbody></TableWrap>
          : <p className="p-5 text-sm text-slate-500">No changes yet.</p>}
      </Card>

      {adding && <KeyDialog title="Add Google API key" onClose={() => setAdding(false)} onDone={(t) => { setAdding(false); setNotice({ ok: true, text: t }); refresh(); }} />}
      {replacing && <KeyDialog title={`Replace key “${replacing.label}”`} existing={replacing} onClose={() => setReplacing(null)} onDone={(t) => { setReplacing(null); setNotice({ ok: true, text: t }); refresh(); }} />}
    </div>
  );
}

function KeyDialog({ title, existing, onClose, onDone }: { title: string; existing?: KeyRow; onClose: () => void; onDone: (msg: string) => void }) {
  const [label, setLabel] = useState(existing?.label ?? "");
  const [secret, setSecret] = useState("");
  const [activate, setActivate] = useState(true);
  const m = useMutation({
    mutationFn: () => existing
      ? api.put(`/admin/ai-keys/${existing.id}`, { ...(label && label !== existing.label ? { label } : {}), ...(secret ? { api_key: secret } : {}) })
      : api.post("/admin/ai-keys", { provider: "google", label, api_key: secret, activate }),
    onSuccess: () => { setSecret(""); onDone(existing ? "Key updated." : activate ? "Key added, verified and activated. It is in use now." : "Key added. Test and activate it when ready."); },
    onSettled: () => setSecret(""),   // the secret never lingers in component state
  });
  return (
    <Modal title={title} onClose={onClose}>
      <form className="space-y-4" autoComplete="off" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <Field label="Label"><input className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Production" maxLength={80} /></Field>
        <Field label={existing ? "New API key" : "API key"} hint="Stored encrypted. It cannot be viewed again after saving.">
          <input className="input font-mono" type="password" autoComplete="new-password" spellCheck={false} value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="AIza…" required={!existing} />
        </Field>
        {!existing && <Toggle checked={activate} onChange={setActivate} label="Test and activate now" hint="Verifies the key with Google, then makes it the key used for all requests." />}
        {existing?.is_active && <p className="text-xs text-slate-500">This key is active: the new key is tested first and only replaces it if the test passes.</p>}
        <ErrorNote error={m.error} />
        <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={m.isPending || (!existing && !secret) || (!!existing && !secret && label === existing.label)}>{m.isPending && <Spinner />} {existing ? "Save" : activate ? "Add & activate" : "Add key"}</button></div>
      </form>
    </Modal>
  );
}

function ModelCard({ o, onDone, onError }: { o: Overview; onDone: (m: string) => void; onError: (m: string) => void }) {
  const provider = "google";
  const current = o.effective.provider === provider ? o.effective.model : "";
  const [model, setModel] = useState(current);
  const [verify, setVerify] = useState(true);
  const m = useMutation({
    mutationFn: () => api.put<{ model: string }>("/admin/ai-keys/model", { provider, model, verify }),
    onSuccess: (r) => onDone(`Model set to ${r.model}. New requests use it immediately.`), onError: (e: Error) => onError(e.message),
  });
  const suggestions = o.model_suggestions[provider];
  return (
    <Card title="Gemini model">
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <Field label="Choose a model"><select className="input" value={suggestions.includes(model) ? model : ""} onChange={(e) => e.target.value && setModel(e.target.value)}><option value="">Custom…</option>{suggestions.map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Model name" hint={current ? `Currently ${current}` : "Currently the server default"}><input className="input font-mono" value={model} onChange={(e) => setModel(e.target.value)} placeholder="gemini-2.5-flash" maxLength={80} /></Field>
        <button className="btn-primary mb-0.5" disabled={m.isPending || !model.trim() || model === current} onClick={() => m.mutate()}>{m.isPending && <Spinner />} Apply</button>
      </div>
      <div className="mt-3"><Toggle checked={verify} onChange={setVerify} label="Verify the model with the active key before applying" /></div>
    </Card>
  );
}
