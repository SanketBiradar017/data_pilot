import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import { useAuth } from "./lib/auth";
import AdminPage from "./pages/AdminPage";
import Advanced from "./pages/Advanced";
import Billing from "./pages/Billing";
import Chat from "./pages/Chat";
import DatasetDetail from "./pages/DatasetDetail";
import Datasets from "./pages/Datasets";
import GeoRevenue from "./pages/GeoRevenue";
import History, { HistoryDetail } from "./pages/History";
import Landing from "./pages/Landing";
import Intelligence from "./pages/Intelligence";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Reports from "./pages/Reports";
import SettingsPage from "./pages/SettingsPage";
import SqlEditor from "./pages/SqlEditor";
import VerifyEmail from "./pages/VerifyEmail";
import Workspace from "./pages/Workspace";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  if (!user) return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/verify" element={<VerifyEmail />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
  return (
    <Routes>
      <Route path="/verify" element={<VerifyEmail />} />
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="datasets" element={<Datasets />} />
        <Route path="datasets/:id" element={<DatasetDetail />} />
        <Route path="workspace" element={<Workspace />} />
        <Route path="advanced" element={<Advanced />} />
        <Route path="intelligence" element={<Intelligence />} />
        <Route path="geo-revenue" element={<GeoRevenue />} />
        <Route path="chat" element={<Chat />} />
        <Route path="sql" element={<SqlEditor />} />
        <Route path="reports" element={<Reports />} />
        <Route path="history" element={<History />} />
        <Route path="history/:id" element={<HistoryDetail />} />
        <Route path="admin" element={user.role === "super_admin" ? <Navigate to="/admin/overview" replace /> : <Navigate to="/" replace />} />
        <Route path="admin/:section" element={user.role === "super_admin" ? <AdminPage /> : <Navigate to="/" replace />} />
        <Route path="billing" element={<Billing />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
