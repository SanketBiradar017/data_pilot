import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./lib/auth";
import { NumFmtProvider } from "./lib/numfmt";
import { initTheme } from "./lib/theme";
import "./index.css";

initTheme();

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 } } });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter><AuthProvider><NumFmtProvider><App /></NumFmtProvider></AuthProvider></BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
