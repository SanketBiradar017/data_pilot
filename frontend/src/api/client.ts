const BASE = "/api/v1";
const TOKEN_KEY = "datapilot.token";

export const tokenStore = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string) => { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* ignore */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function errorMessage(body: any, status: number): string {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`).join("; ");
  return `Request failed (${status})`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const t = tokenStore.get();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(BASE + path, { ...init, headers });
  if (res.status === 401 && !path.startsWith("/auth/")) { tokenStore.clear(); window.dispatchEvent(new Event("datapilot:logout")); }
  if (!res.ok) throw new ApiError(res.status, errorMessage(await res.json().catch(() => null), res.status));
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  get: <T>(p: string) => request<T>(p),
  post: <T>(p: string, body?: unknown) => request<T>(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(p: string, body: unknown) => request<T>(p, { method: "PUT", body: JSON.stringify(body) }),
  del: <T = void>(p: string) => request<T>(p, { method: "DELETE" }),
  upload: <T>(p: string, file: File) => { const f = new FormData(); f.append("file", file); return request<T>(p, { method: "POST", body: f }); },
  /** Authenticated file download (reports, CSV). Pass `body` to POST. */
  async download(path: string, fallbackName: string, body?: unknown) {
    const res = await fetch(BASE + path, { method: body ? "POST" : "GET", headers: { Authorization: `Bearer ${tokenStore.get() ?? ""}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined });
    if (!res.ok) throw new ApiError(res.status, errorMessage(await res.json().catch(() => null), res.status));
    const cd = res.headers.get("content-disposition") ?? "";
    const name = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd)?.[1] ?? fallbackName;
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: decodeURIComponent(name) });
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  },
};
