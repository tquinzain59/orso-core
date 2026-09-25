export type AgentId = "jerome" | "lucas" | "clara" | "victor";

export interface AgentMeta {
  id: AgentId;
  name: string;
  role: string;
  avatar: string;
  color: string;
  badgeBg: string;
  badgeText: string;
  description: string;
}

export interface TrialConfig {
  is_trial: boolean;
  start_date?: string;
  end_date?: string;
  days_remaining?: number;
}

export interface TenantContact {
  full_name: string;
  email: string;
  phone?: string;
  role?: string;
}

export interface TenantUser {
  id: string;
  email: string;
  full_name: string;
  phone?: string;
  role: string;
  is_admin: boolean;
  is_primary_contact?: boolean;
  created_at?: string;
}

export interface TenantInstance {
  container_name: string;
  status: "ready" | "sleeping" | "not_provisioned" | "stopped" | "error" | "paused" | "not_found" | string;
}

export interface SubscriptionInfo {
  id: string;
  tier_id: "none" | "1_agent" | "2_agents" | "4_agents" | "custom" | string;
  tier_label: string;
  price_ht: number;
  status: "none" | "active" | "trialing" | "past_due" | "canceled" | string;
  current_period_start?: string;
  current_period_end?: string;
  stripe_customer_id?: string;
  payment_method?: string;
  suggested_tier?: string;
}

export interface Invoice {
  id: string;
  number: string;
  amount_ht: number;
  amount_ttc: number;
  status: "paid" | "open" | "failed" | string;
  date: string;
  pdf_url?: string;
  tenant_id?: string;
  tenant_name?: string;
  tenant_slug?: string;
}

export interface Tenant {
  id: string;
  name: string;
  siret?: string;
  slug: string;
  sector?: string;
  status: "active" | "trial" | "suspended" | "churn" | string;
  created_at: string;
  contact: TenantContact;
  users?: TenantUser[];
  instance: TenantInstance;
  agents_enabled: {
    active: AgentId[];
    trials: Record<string, TrialConfig>;
  };
  subscription: SubscriptionInfo;
  invoices?: Invoice[];
}

export interface OpsKPIs {
  total_clients: number;
  active_subscribers: number;
  trialing_clients: number;
  mrr_ht: number;
  mrr_ttc: number;
  arr_ht: number;
}

export interface OpsStats {
  kpis: OpsKPIs;
  tier_distribution: Record<string, number>;
  agent_utilization: Record<string, number>;
  pricing_catalog: Record<string, { price_ht: number; max_agents: number; label: string }>;
  timestamp: string;
}

export interface AdminUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
}

export interface LoginResponse {
  token: string;
  refresh_token?: string;
  expires_in?: number;
  user: AdminUser;
}
