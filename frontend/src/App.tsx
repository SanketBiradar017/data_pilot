import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import { useAuth } from "./lib/auth";
import Advanced from "./pages/Advanced";
import Chat from "./pages/Chat";
import DatasetDetail from "./pages/DatasetDetail";
import Datasets from "./pages/Datasets";
import History, { HistoryDetail } from "./pages/History";
import Landing from "./pages/Landing";
import Intelligence from "./pages/Intelligence";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Reports from "./pages/Reports";
import SettingsPage from "./pages/SettingsPage";
import SqlEditor from "./pages/SqlEditor";
import Workspace from "./pages/Workspace";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  if (!user) return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="datasets" element={<Datasets />} />
        <Route path="datasets/:id" element={<DatasetDetail />} />
        <Route path="workspace" element={<Workspace />} />
        <Route path="advanced" element={<Advanced />} />
        <Route path="intelligence" element={<Intelligence />} />
        <Route path="chat" element={<Chat />} />
        <Route path="sql" element={<SqlEditor />} />
        <Route path="reports" element={<Reports />} />
        <Route path="history" element={<History />} />
        <Route path="history/:id" element={<HistoryDetail />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
