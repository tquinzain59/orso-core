import React, { useState, useEffect, useCallback } from "react";
import { Navbar } from "./components/Navbar";
import { DashboardView } from "./components/DashboardView";
import { TenantsView } from "./components/TenantsView";
import { BillingView } from "./components/BillingView";
import { FleetView } from "./components/FleetView";
import { TenantDetailModal } from "./components/TenantDetailModal";
import { LoginView } from "./components/LoginView";
import { Tenant, OpsStats, Invoice, AgentId, AdminUser } from "./types";
import {
  fetchOpsStats,
  fetchTenants,
  fetchInvoices,
  updateTenantAgents,
  updateTenantSubscription,
  wakeContainer,
  suspendContainer,
  getStoredToken,
  getStoredUser,
  fetchMe,
  logoutAdmin,
} from "./api";
import { Loader2 } from "lucide-react";

export const App: React.FC = () => {
  const [adminUser, setAdminUser] = useState<AdminUser | null>(getStoredUser());
  const [checkingAuth, setCheckingAuth] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<"dashboard" | "tenants" | "billing" | "fleet">("dashboard");
  const [stats, setStats] = useState<OpsStats | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [selectedTenant, setSelectedTenant] = useState<Tenant | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statsData, tenantsData, invoicesData] = await Promise.all([
        fetchOpsStats(),
        fetchTenants(),
        fetchInvoices(),
      ]);
      setStats(statsData);
      setTenants(tenantsData);
      setInvoices(invoicesData);
    } catch (err: any) {
      console.error("Erreur de chargement des données Orso Ops:", err);
      if (err.message && err.message.includes("Session expirée")) {
        setAdminUser(null);
      } else {
        setError(err.message || "Erreur lors du chargement des données.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Vérification de la session au démarrage
  useEffect(() => {
    const initAuth = async () => {
      const token = getStoredToken();
      if (!token) {
        setAdminUser(null);
        setCheckingAuth(false);
        return;
      }

      try {
        const user = await fetchMe();
        setAdminUser(user);
        await loadData();
      } catch (err) {
        console.warn("Session invalide ou expirée:", err);
        setAdminUser(null);
      } finally {
        setCheckingAuth(false);
      }
    };

    initAuth();
  }, [loadData]);

  const handleLogout = async () => {
    await logoutAdmin();
    setAdminUser(null);
    setStats(null);
    setTenants([]);
    setInvoices([]);
  };

  const handleLoginSuccess = async (user: AdminUser) => {
    setAdminUser(user);
    await loadData();
  };

  // Sauvegarde des agents & périodes d'essai
  const handleSaveAgents = async (
    tenantId: string,
    active: AgentId[],
    trials: Record<string, any>
  ) => {
    await updateTenantAgents(tenantId, active, trials);
    await loadData();
    const updated = await fetchTenants();
    const current = updated.find((t) => t.id === tenantId) || null;
    setSelectedTenant(current);
  };

  // Sauvegarde de l'abonnement
  const handleSaveSubscription = async (tenantId: string, tierId: string, status?: string) => {
    await updateTenantSubscription(tenantId, tierId, status);
    await loadData();
    const updated = await fetchTenants();
    const current = updated.find((t) => t.id === tenantId) || null;
    setSelectedTenant(current);
  };

  // Réveil de conteneur
  const handleWakeContainer = async (slug: string) => {
    try {
      await wakeContainer(slug);
      await loadData();
    } catch (e: any) {
      setError("Erreur lors du réveil du conteneur : " + (e.message || "Échec"));
    }
  };

  // Mise en veille
  const handleSuspendContainer = async (slug: string) => {
    try {
      await suspendContainer(slug);
      await loadData();
    } catch (e: any) {
      setError("Erreur lors de la mise en veille : " + (e.message || "Échec"));
    }
  };

  // Écran d'initialisation rapide
  if (checkingAuth) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-slate-400">
        <Loader2 className="w-8 h-8 animate-spin text-sky-400 mb-3" />
        <span className="text-sm font-medium">Chargement du Cockpit Orso Ops...</span>
      </div>
    );
  }

  // Si non authentifié, afficher l'écran de Login
  if (!adminUser) {
    return <LoginView onLoginSuccess={handleLoginSuccess} />;
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onRefresh={loadData}
        loading={loading}
        totalClients={tenants.length}
        adminUser={adminUser}
        onLogout={handleLogout}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {error && (
          <div className="mb-6 p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-sm flex items-center justify-between">
            <span>{error}</span>
            <button
              onClick={loadData}
              className="text-xs underline hover:text-white font-bold ml-4 cursor-pointer"
            >
              Réessayer
            </button>
          </div>
        )}

        {activeTab === "dashboard" && (
          <DashboardView
            stats={stats}
            tenants={tenants}
            onSelectTenant={(t) => setSelectedTenant(t)}
            onGoToTenants={() => setActiveTab("tenants")}
          />
        )}

        {activeTab === "tenants" && (
          <TenantsView
            tenants={tenants}
            onSelectTenant={(t) => setSelectedTenant(t)}
            onWakeContainer={handleWakeContainer}
            onSuspendContainer={handleSuspendContainer}
          />
        )}

        {activeTab === "billing" && (
          <BillingView
            tenants={tenants}
            invoices={invoices}
            onSelectTenant={(t) => setSelectedTenant(t)}
          />
        )}

        {activeTab === "fleet" && (
          <FleetView
            tenants={tenants}
            onWakeContainer={handleWakeContainer}
            onSuspendContainer={handleSuspendContainer}
          />
        )}
      </main>

      {/* Modal Détail Client & Activation Agents */}
      <TenantDetailModal
        tenant={selectedTenant}
        onClose={() => setSelectedTenant(null)}
        onSaveAgents={handleSaveAgents}
        onSaveSubscription={handleSaveSubscription}
        onWakeContainer={handleWakeContainer}
        onSuspendContainer={handleSuspendContainer}
      />

      <footer className="border-t border-slate-900 py-6 text-center text-xs text-slate-500">
        Orso Ops Cockpit • Plateforme d'orchestration Olympe • Port 9230 • Tous droits réservés
      </footer>
    </div>
  );
};
