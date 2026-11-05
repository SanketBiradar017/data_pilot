import { Activity, BarChart3, BrainCircuit, CreditCard, Database, LayoutDashboard, Receipt, Server, Settings, SlidersHorizontal, Tag, Users, type LucideIcon } from "lucide-react";

export const ADMIN_NAV: { slug: string; label: string; icon: LucideIcon; title: string; subtitle: string }[] = [
  { slug: "overview", label: "Overview", icon: LayoutDashboard, title: "Overview", subtitle: "Users, datasets and analyses across the platform." },
  { slug: "users", label: "User Management", icon: Users, title: "User management", subtitle: "Accounts, roles, status and subscriptions." },
  { slug: "plans", label: "Subscriptions & Pricing", icon: CreditCard, title: "Subscriptions & pricing", subtitle: "Plans, pricing, trials, limits and upgrade rules." },
  { slug: "promos", label: "Promo Codes", icon: Tag, title: "Promo codes", subtitle: "Discounts, limits, restrictions and revenue impact." },
  { slug: "features", label: "Feature & Usage Control", icon: SlidersHorizontal, title: "Feature & usage control", subtitle: "Turn features on or off and set upload limits." },
  { slug: "ai", label: "AI Configuration", icon: BrainCircuit, title: "AI configuration", subtitle: "Provider, model, prompts, caps, fallback and cost." },
  { slug: "payments", label: "Payments & Transactions", icon: Receipt, title: "Payments & transactions", subtitle: "Payments, refunds, renewals and gateway settings." },
  { slug: "datasets", label: "Dataset Management", icon: Database, title: "Dataset management", subtitle: "All uploaded datasets, storage and upload rules." },
  { slug: "analytics", label: "Analytics & Reports", icon: BarChart3, title: "Analytics & reports", subtitle: "Growth, revenue, feature usage, AI cost and errors." },
  { slug: "activity", label: "Activity & Audit Logs", icon: Activity, title: "Activity & audit logs", subtitle: "Everything users and admins have done." },
  { slug: "system", label: "System Monitoring", icon: Server, title: "System monitoring", subtitle: "Health of the database, disk, API and workers." },
  { slug: "settings", label: "Platform Settings", icon: Settings, title: "Platform settings", subtitle: "Branding, availability, email and notifications." },
];
