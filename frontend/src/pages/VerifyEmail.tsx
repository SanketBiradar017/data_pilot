import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { Loading } from "../components/ui";

export default function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { error, isLoading } = useQuery({ queryKey: ["verify", token], retry: 0, staleTime: Infinity, enabled: !!token, queryFn: () => api.post("/auth/verify", { token }) });
  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="card w-full max-w-sm p-8 text-center">
        {isLoading ? <Loading label="Verifying…" /> : !token || error ? (<><XCircle className="mx-auto h-10 w-10 text-red-500" /><h1 className="mt-3 text-lg font-semibold">Link invalid or expired</h1><p className="mt-1 text-sm text-slate-500">Sign in to request a new verification email.</p></>) : (<><CheckCircle2 className="mx-auto h-10 w-10 text-emerald-500" /><h1 className="mt-3 text-lg font-semibold">Email verified</h1><p className="mt-1 text-sm text-slate-500">Your account is ready.</p></>)}
        <Link to="/login" className="btn-primary mt-6 w-full">Go to sign in</Link>
      </div>
    </div>
  );
}
