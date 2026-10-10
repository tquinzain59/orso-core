export type AgentId = 'jerome' | 'lucas' | 'clara' | 'victor';

export interface Agent {
  id: AgentId;
  name: string;
  role: string;
  department: string;
  avatar: string;
  themeColor: {
    bg: string;
    border: string;
    text: string;
    accent: string;
    badge: string;
  };
  status: 'online' | 'busy' | 'offline';
  description: string;
  quickActions: {
    label: string;
    prompt: string;
    iconName?: string;
  }[];
}

export interface ActionCardData {
  id: string;
  agentId: AgentId;
  title: string;
  type: 'invoice_reminder' | 'crm_deal' | 'support_escalation' | 'tender_bid';
  recipientName: string;
  recipientContact?: string;
  amount?: number;
  dueDate?: string;
  invoiceNumber?: string;
  channel: 'email' | 'whatsapp' | 'internal';
  draftSubject?: string;
  draftContent: string;
  status: 'pending' | 'approved' | 'delayed' | 'cancelled';
  feedbackMessage?: string;
}

export interface ChatMessage {
  id: string;
  agentId: AgentId;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  actionCard?: ActionCardData;
  isStreaming?: boolean;
}

export interface ClientSession {
  session_id: string;
  tenant_id: string;
  user_id: string;
  agent_id: string;
  title: string;
  title_source: 'auto' | 'user' | string;
  dossier_metier_id?: string | null;
  created_at: number;
  last_activity_at: number;
}

export interface ClientTheme {
  theme_id: string;
  tenant_id: string;
  user_id: string;
  agent_id: string;
  title: string;
  title_source: 'auto' | 'user' | string;
  created_at: number;
  updated_at: number;
  sessions_count: number;
  sessions?: ClientSession[];
}

export interface ClientThemeContext {
  theme_id: string;
  context_text: string;
  has_context: boolean;
  length_chars: number;
  tokens_est: number;
}

export type IntegrationCategory = 'erp' | 'mail' | 'legal' | 'crm' | 'tools';

export interface Integration {
  id: string;
  name: string;
  category: IntegrationCategory;
  description: string;
  status: 'connected' | 'pending' | 'disconnected';
  lastSync?: string;
  metricLabel?: string;
  metricValue?: string;
  accountDetails?: string;
  provider: string;
  configKey?: string;
}

export type ChannelId = 'whatsapp' | 'telegram' | 'email' | 'slack' | 'discord' | string;

export interface MessagingChannel {
  id: ChannelId;
  name: string;
  tagline: string;
  description: string;
  status: 'connected' | 'disconnected' | 'configuring';
  connectedAccount?: string;
  allowedUsers: string[];
  stats?: {
    messagesToday: number;
    activeSessions: number;
  };
  configKey?: string;
  metrics?: string;
  syncStatus?: 'success' | 'idle' | 'offline' | 'error';
}

export interface ClientUser {
  id: string;
  email: string;
  full_name: string;
  role?: 'superadmin' | 'admin' | 'user' | string;
  job_title?: string;
  is_admin?: boolean;
}

export interface CompanyData {
  id: string;
  name: string;
  slug: string;
  siret?: string;
  siren?: string;
  vat_number?: string;
  legal_form?: string;
  sector?: string;
  address_line1?: string;
  address_line2?: string;
  postal_code?: string;
  city?: string;
  country?: string;
  status?: string;
  created_at?: string;
  environment?: {
    container_name?: string;
    status?: string;
    region?: string;
    dedicated_url?: string;
    isolation_type?: string;
    host?: string;
    port?: number;
  };
  agents_deployed?: string[];
}

export interface UserProfileData {
  id: string;
  email: string;
  full_name: string;
  role?: string;
  phone?: string;
  job_title?: string;
  is_admin?: boolean;
  created_at?: string;
}

export interface SubscriptionTier {
  id: string;
  name: string;
  price_ht: number;
  max_agents: number;
  description: string;
  features: string[];
  popular?: boolean;
}

export interface ClientSubscription {
  id?: string;
  tier_id: string;
  tier_label: string;
  price_ht: number;
  status: string;
  agents_count: number;
  current_period_start?: string;
  current_period_end?: string;
  trial_end?: string;
  payment_method?: string;
  stripe_customer_id?: string;
  stripe_subscription_id?: string;
  cancel_at_period_end?: boolean;
}

export interface ClientInvoice {
  id: string;
  number: string;
  date: string;
  amount_ht: number;
  amount_ttc: number;
  status: 'paid' | 'pending' | 'draft' | string;
  pdf_url?: string;
}

export interface BillingData {
  subscription: ClientSubscription;
  available_tiers: SubscriptionTier[];
  invoices: ClientInvoice[];
  has_stripe: boolean;
  stripe_portal_enabled: boolean;
}

