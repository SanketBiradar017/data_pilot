import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, MessageSquarePlus, Send, Trash2, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { AgentTimeline } from "../components/AgentTimeline";
import { ChartRenderer } from "../components/ChartRenderer";
import { DatasetPicker } from "../components/DatasetPicker";
import { SuggestionChips } from "../components/SuggestionChips";
import { Badge, DataTable, ErrorNote, Spinner, Verified } from "../components/ui";
import { followUpChips, hasNotes } from "../lib/chatHints";
import type { Conversation, Message } from "../lib/types";

interface ConversationFull extends Conversation { messages: Message[] }

function Assistant({ m, onAsk }: { m: Message; onAsk: (q: string) => void }) {
  const [open, setOpen] = useState(false);
  const p = m.payload;
  const chips = followUpChips(p);
  return (
    <div className="space-y-3">
      {hasNotes(p) && (
        <div className="space-y-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300">
          {p.followup_note && <p><span className="font-semibold">Follow-up:</span> {p.followup_note}</p>}
          {p.interpretation && <p><span className="font-semibold">Understood as:</span> {p.interpretation}</p>}
          {(p.notes ?? []).map((n, i) => <p key={i}>• {n}</p>)}
        </div>)}
      <p className="whitespace-pre-line text-[15px] leading-relaxed">{m.content}</p>
      {p.clarification && p.clarification.columns.length > 0 && (
        <div className="flex flex-wrap gap-1.5" aria-label="Available columns">{p.clarification.columns.slice(0, 20).map((c) => <span key={c} className="rounded-full border border-slate-200 px-2 py-0.5 text-xs text-slate-600 dark:border-white/10 dark:text-slate-300">{c}</span>)}</div>)}
      {p.recommendations && p.recommendations.length > 0 && !p.clarification && (
        <div className="rounded-lg border border-brand-500/30 bg-brand-50/50 px-3 py-2 text-sm dark:bg-brand-500/5"><p className="mb-1 text-xs font-semibold uppercase text-brand-700 dark:text-brand-300">Recommendations</p>
          <ul className="list-disc space-y-1 pl-4">{p.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul></div>)}
      {p.charts?.[0] && <div className="rounded-lg border border-slate-200 p-3 dark:border-white/10"><ChartRenderer spec={p.charts[0]} height={220} /></div>}
      {p.result_rows && p.result_columns && p.result_rows.length > 1 && <DataTable columns={p.result_columns} rows={p.result_rows} maxHeight={220} />}
      {p.citations && p.citations.length > 0 && p.citations.map((c, i) => <blockquote key={i} className="border-l-4 border-brand-500 bg-brand-50/50 px-3 py-2 text-sm dark:bg-brand-500/5"><span className="mb-1 block text-xs font-medium text-brand-700 dark:text-brand-300">{c.source} · passage {c.chunk}</span>{c.snippet}</blockquote>)}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {p.validation && p.validation.total > 0 && <Badge tone={p.validation.status === "passed" ? "green" : "amber"}>{p.validation.passed}/{p.validation.total} claims verified</Badge>}
        {p.analysis_id && <Link className="text-brand-600 hover:underline" to={`/history/${p.analysis_id}`}>Open full analysis →</Link>}
        <button className="text-brand-600 hover:underline" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} evidence & agent steps</button>
      </div>
      {chips.length > 0 && <div className="flex flex-wrap gap-2">{chips.map((c) => <button key={c} type="button" className="rounded-full border border-brand-500/40 px-3 py-1 text-xs text-brand-700 hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-500/10" onClick={() => onAsk(c)}>{c}</button>)}</div>}
      {open && (
        <div className="grid gap-4 rounded-lg bg-slate-50 p-4 text-sm dark:bg-white/5 md:grid-cols-2">
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase text-slate-500">Evidence</p>
            {p.sql && <pre className="overflow-x-auto rounded bg-ink-950 p-2 font-mono text-xs text-slate-200">{p.sql}</pre>}
            {(p.evidence ?? []).map((e, i) => <p key={i} className="text-xs text-slate-600 dark:text-slate-300">• {e.text} <Verified ok={e.verified} /></p>)}
          </div>
          <div><p className="mb-1 text-xs font-semibold uppercase text-slate-500">Agents</p>{p.trace && <AgentTimeline trace={p.trace} status="completed" compact />}</div>
        </div>
      )}
    </div>
  );
}

export default function Chat() {
  const qc = useQueryClient();
  const [cid, setCid] = useState<number | null>(null);
  const [dataset, setDataset] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const convs = useQuery({ queryKey: ["conversations"], queryFn: () => api.get<Conversation[]>("/chat/conversations") });
  const conv = useQuery({ queryKey: ["conversation", cid], enabled: cid != null, queryFn: () => api.get<ConversationFull>(`/chat/conversations/${cid}`) });
  useEffect(() => { if (conv.data?.dataset_id) setDataset(conv.data.dataset_id); }, [conv.data?.dataset_id]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [conv.data?.messages.length, pending]);

  const send = useMutation({
    mutationFn: async (content: string) => {
      let id = cid;
      if (id == null) { const c = await api.post<Conversation>("/chat/conversations", { dataset_ids: dataset ? [dataset] : [] }); id = c.id; setCid(id); }
      return api.post(`/chat/conversations/${id}/messages`, { content, dataset_ids: dataset ? [dataset] : null });
    },
    onMutate: (c) => setPending(c),
    onSettled: () => { setPending(null); qc.invalidateQueries({ queryKey: ["conversation", cid] }); qc.invalidateQueries({ queryKey: ["conversations"] }); },
  });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/chat/conversations/${id}`), onSuccess: (_, id) => { if (cid === id) setCid(null); qc.invalidateQueries({ queryKey: ["conversations"] }); } });
  const submit = () => { const t = text.trim(); if (t.length < 2 || send.isPending) return; setText(""); send.mutate(t); };
  const msgs = conv.data?.messages ?? [];

  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white dark:border-white/10 dark:bg-ink-900 md:flex">
        <div className="p-3"><button className="btn-primary w-full" onClick={() => setCid(null)}><MessageSquarePlus className="h-4 w-4" /> New chat</button></div>
        <ul className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">{(convs.data ?? []).map((c) => (
          <li key={c.id} className={`group flex items-center rounded-lg ${cid === c.id ? "bg-brand-50 dark:bg-brand-500/15" : "hover:bg-slate-50 dark:hover:bg-white/5"}`}>
            <button className="min-w-0 flex-1 truncate px-3 py-2 text-left text-sm" onClick={() => setCid(c.id)}>{c.title}</button>
            <button className="p-2 text-slate-400 opacity-0 hover:text-red-600 group-hover:opacity-100" aria-label="Delete conversation" onClick={() => del.mutate(c.id)}><Trash2 className="h-3.5 w-3.5" /></button></li>))}</ul>
      </aside>
      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-5 py-3 dark:border-white/10 dark:bg-ink-900">
          <h1 className="text-lg font-semibold">Ask your data</h1><div className="ml-auto"><DatasetPicker value={dataset} onChange={setDataset} /></div>
        </div>
        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-6">
          {msgs.length === 0 && !pending && (
            <div className="mx-auto mt-16 max-w-md text-center text-slate-500"><Bot className="mx-auto mb-3 h-9 w-9 text-brand-500" /><p className="font-medium text-slate-800 dark:text-slate-100">Ask anything about your data</p>
              <p className="mt-1 text-sm">{dataset ? "Try one of these, written from your data:" : "Pick a data source and I'll suggest questions based on its columns and values."} Answers include the SQL, evidence and verification.</p>
              <SuggestionChips ids={dataset ? [dataset] : []} onPick={setText} className="mt-4 justify-center" /></div>)}
          {msgs.map((m) => (
            <div key={m.id} className={`mx-auto flex max-w-3xl gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
              {m.role === "assistant" && <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white"><Bot className="h-4 w-4" /></span>}
              <div className={m.role === "user" ? "max-w-[85%] rounded-2xl rounded-br-sm bg-brand-600 px-4 py-2.5 text-white" : "min-w-0 flex-1"}>{m.role === "user" ? m.content : <Assistant m={m} onAsk={setText} />}</div>
              {m.role === "user" && <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 dark:bg-white/10"><User className="h-4 w-4" /></span>}
            </div>))}
          {pending && <>
            <div className="mx-auto flex max-w-3xl justify-end"><div className="max-w-[85%] rounded-2xl rounded-br-sm bg-brand-600 px-4 py-2.5 text-white">{pending}</div></div>
            <div className="mx-auto flex max-w-3xl items-center gap-2 text-sm text-slate-500"><Spinner /> Agents are planning, querying and verifying…</div></>}
          <div className="mx-auto max-w-3xl"><ErrorNote error={send.error} /></div>
          <div ref={end} />
        </div>
        <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="border-t border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-ink-900">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <textarea className="input max-h-40 resize-none" rows={1} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }} placeholder={dataset ? "Ask a question about your data…" : "Select a data source first…"} aria-label="Message" />
            <button className="btn-primary h-[38px]" disabled={send.isPending || text.trim().length < 2} aria-label="Send"><Send className="h-4 w-4" /></button>
          </div>
        </form>
      </section>
    </div>
  );
}
