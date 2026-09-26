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
  tier_id: "none" | "1_agent" | "2_agents" | "3_agents" | "4_agents" | "custom" | string;
  tier_label: string;
  price_ht: number;
  status: "none" | "active" | "trialing" | "past_due" | "canceling" | "canceled" | string;
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

export interface TelemetrySummary {
  agents_count: number;
  snapshots_count: number;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_api_calls: number;
  total_cost_usd: number;
  last_snapshot_at: string;
  agents_registered?: number;
  alerts_active: number;
  simulated?: boolean;
}

export interface TelemetryEnvironment {
  agent_id: number;
  display_name: string;
  module: string;
  container_id: string;
  server_ip: string;
  dashboard_url: string;
  status: "active" | "idle" | "error" | string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  api_calls: number;
  cost_usd: number;
  error_count: number;
  last_seen_at: string;
  vitals: {
    cpu_percent: number;
    memory_usage_mb: number;
    memory_limit_mb: number;
    memory_percent: number;
    docker_status: string;
  };
  tenant?: {
    id?: string;
    name: string;
    slug?: string;
    sector?: string;
    is_system?: boolean;
    status?: string;
    tier_label?: string;
  } | null;
}

export interface TelemetrySnapshot {
  id: number;
  snapshot_at: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  api_calls: number;
  cost_usd: number;
  status: string;
  error_count: number;
}

export interface TelemetryAlert {
  id: number;
  agent_id: number;
  level: "INFO" | "WARNING" | "CRITICAL" | string;
  category: string;
  message: string;
  detected_at: string;
  resolved_at?: string | null;
  agent_name?: string;
  tenant_id?: string;
}

