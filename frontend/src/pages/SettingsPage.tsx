import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, ErrorNote, Loading, PageHeader, Spinner } from "../components/ui";
import { useAuth } from "../lib/auth";
import { setTheme, storedTheme, type ThemePref } from "../lib/theme";
import type { Settings, User } from "../lib/types";

export default function SettingsPage() {
  const { setUser } = useAuth();
  const { data, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/settings") });
  const [name, setName] = useState("");
  const [theme, setThemeState] = useState<ThemePref>(storedTheme());
  useEffect(() => { if (data) { setName(data.user.name); setThemeState(storedTheme()); } }, [data]);
  useEffect(() => { const f = () => setThemeState(storedTheme()); window.addEventListener("datapilot:theme", f); return () => window.removeEventListener("datapilot:theme", f); }, []);   // sidebar toggle keeps the dropdown in sync
  const choose = (t: ThemePref) => { setThemeState(t); setTheme(t); };   // applies immediately and remembers it
  const save = useMutation({ mutationFn: () => api.put<User>("/settings", { name, theme }), onSuccess: (u) => { setUser(u); setTheme(theme); } });
  if (isLoading) return <Loading />;
  if (!data) return <ErrorNote error={error} />;
  const s = data.system;
  const row = (k: string, v: React.ReactNode) => <div className="flex justify-between gap-4 border-b border-slate-100 py-2.5 text-sm last:border-0 dark:border-white/5"><dt className="text-slate-500">{k}</dt><dd className="text-right font-medium">{v}</dd></div>;
  return (
    <>
      <PageHeader title="Settings" subtitle="Profile, appearance and system configuration." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Profile & appearance">
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <div><label className="label" htmlFor="nm">Display name</label><input id="nm" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></div>
            <div><label className="label">Email</label><input className="input" value={data.user.email} disabled /></div>
            <div><label className="label" htmlFor="th">Theme</label><select id="th" className="input" value={theme} onChange={(e) => choose(e.target.value as ThemePref)}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></div>
            <ErrorNote error={save.error} />
            <button className="btn-primary" disabled={save.isPending}>{save.isPending && <Spinner />} {save.isSuccess ? "Saved ✓" : "Save changes"}</button>
          </form>
        </Card>
        <Card title="System">
          <dl>
            {row("Role", <Badge tone="brand">{data.user.role}</Badge>)}
            {row("Environment", s.app_env)}
            {row("Application database", <span className="break-all font-mono text-xs">{s.database} · {s.database_location}</span>)}
            {row("AI language model", s.llm_enabled ? <Badge tone="green">{s.llm_provider} {s.llm_model ?? ""}</Badge> : <Badge>deterministic mode (no API key)</Badge>)}
            {row("Max upload size", `${s.max_upload_mb} MB`)}
            {row("Max query rows", s.max_query_rows.toLocaleString())}
            {row("Query timeout", `${s.query_timeout_seconds}s`)}
            {row("Supported formats", <span className="flex flex-wrap justify-end gap-1">{s.supported_formats.map((f) => <Badge key={f}>{f}</Badge>)}</span>)}
          </dl>
          {!s.llm_enabled && <p className="mt-3 text-xs text-slate-500">Set <code>LLM_PROVIDER</code> and the matching API key in <code>.env</code> to enable LLM-assisted routing, SQL generation and narrative. All analysis remains verified against raw data either way.</p>}
        </Card>
      </div>
    </>
  );
}
