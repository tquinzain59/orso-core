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

export type IntegrationCategory = 'erp' | 'mail' | 'legal' | 'crm';

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
}

export type ChannelId = 'whatsapp' | 'telegram' | 'email';

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
}
