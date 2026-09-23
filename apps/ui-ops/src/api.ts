import { Tenant, OpsStats, Invoice, AgentId, TrialConfig, AdminUser, LoginResponse } from "./types";

const TOKEN_KEY = "orso_ops_auth_token";
const USER_KEY = "orso_ops_auth_user";

const getBaseUrl = (): string => {
  return "";
};

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): AdminUser | null {
  const raw = localStorage.getItem(USER_KEY) || sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function setStoredSession(token: string, user: AdminUser, remember: boolean = true): void {
  if (remember) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  } else {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  }
}

export function clearStoredSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

function getAuthHeaders(): HeadersInit {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

// ── Authentification Superadmin ──────────────────────────────────────────────

export async function loginAdmin(
  email: string,
  password: string,
  remember: boolean = true
): Promise<LoginResponse> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: "Erreur de connexion" }));
    throw new Error(errorData.detail || `Échec de connexion (${res.status})`);
  }

  const data: LoginResponse = await res.json();
  setStoredSession(data.token, data.user, remember);
  return data;
}

export async function fetchMe(): Promise<AdminUser> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/auth/me`, {
    headers: getAuthHeaders(),
  });

  if (!res.ok) {
    clearStoredSession();
    throw new Error(`Session expirée ou non autorisée (${res.status})`);
  }

  const data = await res.json();
  return data.user;
}

export async function logoutAdmin(): Promise<void> {
  try {
    await fetch(`${getBaseUrl()}/api/olympe/ops/auth/logout`, {
      method: "POST",
      headers: getAuthHeaders(),
    });
  } catch (e) {
    console.warn("Erreur lors de la notification de déconnexion:", e);
  } finally {
    clearStoredSession();
  }
}

// ── Endpoints Métier Ops (Protégés) ──────────────────────────────────────────

export async function fetchOpsStats(): Promise<OpsStats> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/stats`, {
    headers: getAuthHeaders(),
  });
  if (res.status === 401 || res.status === 403) {
    clearStoredSession();
    throw new Error("Session expirée. Veuillez vous reconnecter.");
  }
  if (!res.ok) {
    throw new Error(`Erreur récupération stats (${res.status})`);
  }
  return res.json();
}

export async function fetchTenants(): Promise<Tenant[]> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/tenants`, {
    headers: getAuthHeaders(),
  });
  if (res.status === 401 || res.status === 403) {
    clearStoredSession();
    throw new Error("Session expirée. Veuillez vous reconnecter.");
  }
  if (!res.ok) {
    throw new Error(`Erreur récupération clients (${res.status})`);
  }
  const data = await res.json();
  return data.tenants || [];
}

export async function fetchTenantDetail(tenantId: string): Promise<Tenant> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/tenants/${tenantId}`, {
    headers: getAuthHeaders(),
  });
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
    headers: getAuthHeaders(),
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
    headers: getAuthHeaders(),
    body: JSON.stringify({ tier_id: tierId, status }),
  });
  if (!res.ok) {
    throw new Error(`Échec mise à jour abonnement (${res.status})`);
  }
  return res.json();
}

export async function fetchInvoices(): Promise<Invoice[]> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/ops/invoices`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Erreur récupération factures (${res.status})`);
  }
  const data = await res.json();
  return data.invoices || [];
}

export async function wakeContainer(slug: string): Promise<{ success: boolean; message?: string }> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/tenants/wake/${slug}`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return res.json();
}

export async function suspendContainer(slug: string): Promise<{ success: boolean; message?: string }> {
  const res = await fetch(`${getBaseUrl()}/api/olympe/tenants/suspend/${slug}`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return res.json();
}
