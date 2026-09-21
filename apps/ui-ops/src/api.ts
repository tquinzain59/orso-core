import { Tenant, OpsStats, Invoice, AgentId, TrialConfig } from "./types";

const getBaseUrl = (): string => {
  // En dev local ou en prod servi par Olympe
  return "";
};

export async function fetchOpsStats(): Promise<OpsStats> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/stats`);
  if (!res.ok) {
    throw new Error(`Erreur récupération stats (${res.status})`);
  }
  return res.json();
}

export async function fetchTenants(): Promise<Tenant[]> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/tenants`);
  if (!res.ok) {
    throw new Error(`Erreur récupération clients (${res.status})`);
  }
  const data = await res.json();
  return data.tenants || [];
}

export async function fetchTenantDetail(tenantId: string): Promise<Tenant> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/tenants/${tenantId}`);
  if (!res.ok) {
    throw new Error(`Erreur récupération client ${tenantId}`);
  }
  return res.json();
}

export async function updateTenantAgents(
  tenantId: string,
  active: AgentId[],
  trials: Record<string, TrialConfig>
): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/tenants/${tenantId}/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active, trials }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Erreur serveur" }));
    throw new Error(err.detail || `Échec mise à jour (${res.status})`);
  }
  return res.json();
}

export async function updateTenantSubscription(
  tenantId: string,
  tierId: string,
  status: string = "active"
): Promise<{ success: boolean }> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/tenants/${tenantId}/subscription`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tier_id: tierId, status }),
  });
  if (!res.ok) {
    throw new Error(`Échec mise à jour abonnement (${res.status})`);
  }
  return res.json();
}

export async function fetchInvoices(): Promise<Invoice[]> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/invoices`);
  if (!res.ok) {
    throw new Error(`Erreur récupération factures (${res.status})`);
  }
  const data = await res.json();
  return data.invoices || [];
}

export async function wakeContainer(slug: string): Promise<{ success: boolean; message?: string }> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/tenants/wake/${slug}`, {
    method: "POST",
  });
  return res.json();
}

export async function suspendContainer(slug: string): Promise<{ success: boolean; message?: string }> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/tenants/suspend/${slug}`, {
    method: "POST",
  });
  return res.json();
}
