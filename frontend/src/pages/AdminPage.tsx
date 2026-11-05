import { ShieldCheck } from "lucide-react";
import { Navigate, useParams } from "react-router-dom";
import { PageHeader } from "../components/ui";
import AnalyticsPanel from "./admin/AnalyticsPanel";
import { AiPanel, FeaturesPanel, PlatformPanel } from "./admin/ConfigPanels";
import { ADMIN_NAV } from "./admin/nav";
import { ActivityPanel, DatasetsPanel, OverviewPanel, SystemPanel } from "./admin/OtherPanels";
import PaymentsPanel from "./admin/PaymentsPanel";
import PlansPanel from "./admin/PlansPanel";
import PromosPanel from "./admin/PromosPanel";
import UsersPanel from "./admin/UsersPanel";

const PANELS: Record<string, () => JSX.Element> = {
  overview: OverviewPanel, users: UsersPanel, plans: PlansPanel, promos: PromosPanel, features: FeaturesPanel, ai: AiPanel,
  payments: PaymentsPanel, datasets: DatasetsPanel, analytics: AnalyticsPanel, activity: ActivityPanel, system: SystemPanel, settings: PlatformPanel,
};

export default function AdminPage() {
  const { section = "overview" } = useParams();
  const meta = ADMIN_NAV.find((n) => n.slug === section);
  const Panel = PANELS[section];
  if (!meta || !Panel) return <Navigate to="/admin/overview" replace />;
  return (
    <>
      <PageHeader title={meta.title} subtitle={meta.subtitle} actions={<span className="hidden items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 sm:inline-flex dark:bg-brand-500/15 dark:text-brand-200"><ShieldCheck className="h-3.5 w-3.5" /> Super admin · actions are audit-logged</span>} />
      <Panel key={section} />
    </>
  );
}
