import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, tokenStore } from "../api/client";
import { setTheme, type ThemePref } from "./theme";
import type { User } from "./types";

interface AuthCtx { user: User | null; loading: boolean; login: (email: string, password: string, register?: { name: string }) => Promise<void>; logout: () => void; setUser: (u: User) => void }
const Ctx = createContext<AuthCtx>(null!);
export const useAuth = () => useContext(Ctx);


export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!tokenStore.get());

  const logout = useCallback(() => { tokenStore.clear(); setUser(null); }, []);
  useEffect(() => {
    if (!tokenStore.get()) return;
    api.get<User>("/auth/me").then(setUser).catch(() => tokenStore.clear()).finally(() => setLoading(false));
  }, []);
  useEffect(() => { window.addEventListener("datapilot:logout", logout); return () => window.removeEventListener("datapilot:logout", logout); }, [logout]);
  const uid = user?.id;
  useEffect(() => { if (uid && user?.preferences?.theme) setTheme(user.preferences.theme as ThemePref); /* eslint-disable-next-line */ }, [uid]);

  const login: AuthCtx["login"] = async (email, password, register) => {
    const res = await (register ? api.post<{ token: string; user: User }>("/auth/register", { email, password, name: register.name })
      : api.post<{ token: string; user: User }>("/auth/login", { email, password }));
    tokenStore.set(res.token);
    setUser(res.user);
  };
  return <Ctx.Provider value={{ user, loading, login, logout, setUser }}>{children}</Ctx.Provider>;
}
