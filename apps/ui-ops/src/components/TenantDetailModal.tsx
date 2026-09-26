import React, { useState, useEffect } from "react";
import {
  X,
  Save,
  Clock,
  CheckCircle,
  Play,
  Square,
  ExternalLink,
  Users,
  UserPlus,
  Shield,
  ShieldCheck,
  UserCheck,
  Trash2,
  RefreshCw,
  AlertCircle,
  Eye,
  EyeOff,
} from "lucide-react";
import { Tenant, AgentId, TenantUser } from "../types";
import { AGENTS_CATALOG } from "../data";
import { fetchTenantUsers, createTenantUser, deleteTenantUser } from "../api";

interface TenantDetailModalProps {
  tenant: Tenant | null;
  onClose: () => void;
  onSaveAgents: (
    tenantId: string,
    activeAgents: AgentId[],
    trialsConfig: Record<string, any>
  ) => Promise<void>;
  onSaveSubscription: (tenantId: string, tierId: string, status?: string) => Promise<void>;
  onWakeContainer: (slug: string) => void;
  onSuspendContainer: (slug: string) => void;
}

export const TIER_LIMITS: Record<string, { max: number; label: string; price: string }> = {
  none: { max: 0, label: "Aucun abonnement", price: "0 € HT" },
  "1_agent": { max: 1, label: "Starter (1 agent)", price: "99 € HT" },
  "2_agents": { max: 2, label: "Duo (2 agents)", price: "169 € HT" },
  "3_agents": { max: 3, label: "Trio (3 agents)", price: "229 € HT" },
  "4_agents": { max: 4, label: "Flotte (4 agents)", price: "279 € HT" },
};

export const TenantDetailModal: React.FC<TenantDetailModalProps> = ({
  tenant,
  onClose,
  onSaveAgents,
  onSaveSubscription,
  onWakeContainer,
  onSuspendContainer,
}) => {
  if (!tenant) return null;

  // État local des agents
  const [activeAgents, setActiveAgents] = useState<AgentId[]>(
    [...tenant.agents_enabled.active]
  );
  const [trials, setTrials] = useState<Record<string, any>>(
    { ...tenant.agents_enabled.trials }
  );

  // État local du forfait et du statut commercial
  const [selectedTier, setSelectedTier] = useState<string>(
    tenant.subscription.tier_id || "none"
  );
  const [selectedStatus, setSelectedStatus] = useState<string>(
    tenant.subscription.status || (tenant.subscription.tier_id === "none" ? "none" : "active")
  );

  // État local des utilisateurs
  const [users, setUsers] = useState<TenantUser[]>(tenant.users || []);
  const [isAddingUser, setIsAddingUser] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newFullName, setNewFullName] = useState("");
  const [newRole, setNewRole] = useState("Membre");
  const [newIsAdmin, setNewIsAdmin] = useState(false);
  const [userSubmitting, setUserSubmitting] = useState(false);
  const [userError, setUserError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const [saving, setSaving] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Synchronisation des utilisateurs si nécessaire
  useEffect(() => {
    if (tenant?.id) {
      fetchTenantUsers(tenant.id)
        .then((res) => {
          if (res && res.length > 0) setUsers(res);
        })
        .catch((err) => console.warn("Erreur chargement utilisateurs tenant:", err));
    }
  }, [tenant?.id]);

  const generatePassword = () => {
    const chars = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%";
    let pass = "Orso26!";
    for (let i = 0; i < 6; i++) {
      pass += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    setNewPassword(pass);
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newEmail || !newFullName) {
      setUserError("L'adresse email et le nom complet sont obligatoires.");
      return;
    }
    setUserSubmitting(true);
    setUserError(null);
    try {
      const created = await createTenantUser(tenant.id, {
        email: newEmail.trim(),
        password: newPassword.trim() || undefined,
        full_name: newFullName.trim(),
        role: newRole.trim() || "Membre",
        is_admin: newIsAdmin,
      });
      setUsers((prev) => [...prev, created]);
      setIsAddingUser(false);
      setNewEmail("");
      setNewPassword("");
      setNewFullName("");
      setNewRole("Membre");
      setNewIsAdmin(false);
      setToastMessage(`Utilisateur ${created.email} créé avec succès !`);
      setTimeout(() => setToastMessage(null), 3000);
    } catch (err: any) {
      setUserError(err?.message || "Erreur lors de la création de l'utilisateur.");
    } finally {
      setUserSubmitting(false);
    }
  };

  const handleDeleteUser = async (user: TenantUser) => {
    if (user.is_primary_contact) {
      alert("Le contact principal ne peut pas être supprimé directement.");
      return;
    }
    if (!window.confirm(`Confirmez-vous la révocation du compte de ${user.full_name} (${user.email}) ?`)) {
      return;
    }
    try {
      await deleteTenantUser(tenant.id, user.id);
      setUsers((prev) => prev.filter((u) => u.id !== user.id));
      setToastMessage(`Utilisateur ${user.email} révoqué.`);
      setTimeout(() => setToastMessage(null), 3000);
    } catch (err: any) {
      alert("Erreur suppression: " + err.message);
    }
  };

  const maxQuota = TIER_LIMITS[selectedTier]?.max ?? 0;
  const isSubscriptionInactive =
    selectedTier === "none" || selectedStatus === "none" || selectedStatus === "canceled";

  // Sélection du forfait avec réajustement automatique des agents si quota dépassé
  const handleSelectTier = (tierId: string) => {
    setSelectedTier(tierId);
    if (tierId === "none") {
      setActiveAgents([]);
      setTrials({});
      if (selectedStatus === "active") {
        setSelectedStatus("none");
      }
      return;
    }
    if (selectedStatus === "none" || selectedStatus === "canceled") {
      setSelectedStatus("active");
    }
    const maxAllowed = TIER_LIMITS[tierId]?.max ?? 0;
    if (activeAgents.length > maxAllowed) {
      const trimmed = activeAgents.slice(0, maxAllowed);
      setActiveAgents(trimmed);
      const updatedTrials = { ...trials };
      for (const a of activeAgents) {
        if (!trimmed.includes(a)) {
          delete updatedTrials[a];
        }
      }
      setTrials(updatedTrials);
    }
  };

  // Toggle agent avec verrou strict sur le quota du forfait sélectionné
  const handleToggleAgent = (agentId: AgentId) => {
    if (activeAgents.includes(agentId)) {
      setActiveAgents(activeAgents.filter((a) => a !== agentId));
      const updatedTrials = { ...trials };
      delete updatedTrials[agentId];
      setTrials(updatedTrials);
    } else {
      if (isSubscriptionInactive || maxQuota === 0) {
        alert(
          "Impossible d'activer un agent sans forfait actif.\nVeuillez sélectionner un forfait (1, 2, 3 ou 4 agents) ci-dessous."
        );
        return;
      }
      if (activeAgents.length >= maxQuota) {
        alert(
          `Quota atteint : le forfait ${TIER_LIMITS[selectedTier]?.label || selectedTier} est limité à ${maxQuota} agent(s).\nPour activer un agent supplémentaire, sélectionnez d'abord un forfait supérieur (ex: ${
            maxQuota < 4 ? maxQuota + 1 : 4
          } agents) ci-dessous.`
        );
        return;
      }
      setActiveAgents([...activeAgents, agentId]);
    }
  };

  // Switch mode : Abonnement permanent vs Période d'essai
  const handleSetTrialMode = (agentId: AgentId, isTrial: boolean, days: number = 14) => {
    const updatedTrials = { ...trials };
    if (isTrial) {
      const now = new Date();
      const end = new Date(now.getTime() + days * 24 * 60 * 60 * 1000);
      updatedTrials[agentId] = {
        is_trial: true,
        start_date: now.toISOString(),
        end_date: end.toISOString(),
        days_remaining: days,
      };
    } else {
      delete updatedTrials[agentId];
    }
    setTrials(updatedTrials);
  };

  // Enregistrement
  const handleSave = async () => {
    setSaving(true);
    try {
      await onSaveAgents(tenant.id, activeAgents, trials);
      if (
        selectedTier !== tenant.subscription.tier_id ||
        selectedStatus !== tenant.subscription.status
      ) {
        await onSaveSubscription(tenant.id, selectedTier, selectedStatus);
      }
      setToastMessage("Modifications enregistrées avec succès !");
      setTimeout(() => setToastMessage(null), 3000);
    } catch (e: any) {
      alert("Erreur lors de l'enregistrement : " + e.message);
    } finally {
      setSaving(false);
    }
  };


  const isReady = tenant.instance?.status === "ready";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/80 backdrop-blur-sm overflow-y-auto">
      <div className="relative w-full max-w-4xl bg-slate-900 border border-slate-800 rounded-3xl shadow-2xl overflow-hidden my-8">
        {/* Header Modal */}
        <div className="flex items-center justify-between p-6 border-b border-slate-800 bg-slate-950/60">
          <div>
            <div className="flex items-center space-x-3">
              <h2 className="text-xl font-bold text-white tracking-tight">{tenant.name}</h2>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/30">
                {tenant.slug}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              SIRET : {tenant.siret || "Non renseigné"} • Secteur : {tenant.sector || "Services"} • Inscrit le{" "}
              {new Date(tenant.created_at).toLocaleDateString("fr-FR")}
            </p>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 border border-transparent hover:border-slate-700 transition-all"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-8 max-h-[75vh] overflow-y-auto">
          {/* Toast de succès */}
          {toastMessage && (
            <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 rounded-xl text-sm font-medium flex items-center space-x-2">
              <CheckCircle className="w-4 h-4" />
              <span>{toastMessage}</span>
            </div>
          )}

          {/* Section 1 : Contact & Conteneur Docker */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Contact */}
            <div className="p-4 rounded-2xl bg-slate-950/60 border border-slate-800/80">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Contact & Facturation
              </span>
              <div className="mt-2 text-sm text-white font-bold">{tenant.contact.full_name}</div>
              <div className="text-xs text-slate-400">{tenant.contact.email}</div>
              <div className="text-xs text-slate-400 mt-0.5">{tenant.contact.phone || "Téléphone non renseigné"}</div>
              <div className="text-xs text-slate-500 mt-1">Rôle : {tenant.contact.role || "Dirigeant"}</div>
            </div>

            {/* Conteneur Olympe */}
            <div className="p-4 rounded-2xl bg-slate-950/60 border border-slate-800/80 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Conteneur Dédié (Olympe)
                  </span>
                  <span
                    className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-xs font-mono font-medium ${
                      isReady ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${isReady ? "bg-emerald-400 animate-pulse" : "bg-slate-500"}`}></span>
                    <span>{isReady ? "En ligne (9119)" : "En veille (Éteint)"}</span>
                  </span>
                </div>
                <div className="text-xs font-mono text-slate-300 mt-2">
                  {tenant.instance?.container_name || `orso_client_${tenant.slug}`}
                </div>
              </div>

              <div className="flex items-center space-x-2 mt-3 pt-3 border-t border-slate-800/80">
                {!isReady ? (
                  <button
                    onClick={() => onWakeContainer(tenant.slug)}
                    className="flex-1 py-1.5 px-3 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 rounded-xl text-xs font-bold border border-emerald-500/30 flex items-center justify-center space-x-1.5 transition-all"
                  >
                    <Play className="w-3.5 h-3.5" />
                    <span>Réveiller le conteneur</span>
                  </button>
                ) : (
                  <button
                    onClick={() => onSuspendContainer(tenant.slug)}
                    className="flex-1 py-1.5 px-3 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-bold border border-slate-700 flex items-center justify-center space-x-1.5 transition-all"
                  >
                    <Square className="w-3.5 h-3.5" />
                    <span>Suspendre (Économie RAM)</span>
                  </button>
                )}

                <a
                  href={`https://app.orso-agents.fr/t/${tenant.slug}`}
                  target="_blank"
                  rel="noreferrer"
                  className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white border border-slate-700 transition-all"
                  title="Ouvrir l'espace client"
                >
                  <ExternalLink className="w-4 h-4" />
                </a>
              </div>
            </div>
          </div>

          {/* Section : Collaborateurs & Droits d'Accès */}
          <div className="p-5 rounded-3xl bg-slate-950/70 border border-slate-800 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <div className="flex items-center space-x-2">
                  <Users className="w-4 h-4 text-sky-400" />
                  <h3 className="text-base font-bold text-white">Collaborateurs & Accès Entreprise</h3>
                  <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20">
                    {users.length} utilisateur{users.length > 1 ? "s" : ""}
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  Gérez les utilisateurs autorisés à se connecter sur l'espace client. Le rôle Administrateur débloque les onglets Interfaces, ERP et Canaux.
                </p>
              </div>

              {!isAddingUser && (
                <button
                  type="button"
                  onClick={() => {
                    setIsAddingUser(true);
                    generatePassword();
                  }}
                  className="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-sky-500 hover:bg-sky-400 text-slate-950 flex items-center space-x-1.5 transition-all self-start sm:self-auto shadow-md shadow-sky-500/10"
                >
                  <UserPlus className="w-3.5 h-3.5" />
                  <span>+ Nouvel utilisateur</span>
                </button>
              )}
            </div>

            {/* Formulaire d'ajout d'utilisateur */}
            {isAddingUser && (
              <form onSubmit={handleCreateUser} className="p-4 rounded-2xl bg-slate-900 border border-sky-500/30 space-y-4">
                <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                  <span className="text-xs font-bold text-white uppercase tracking-wider flex items-center space-x-1.5">
                    <UserPlus className="w-3.5 h-3.5 text-sky-400" />
                    <span>Créer un nouvel accès utilisateur</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setIsAddingUser(false);
                      setUserError(null);
                    }}
                    className="text-slate-400 hover:text-white text-xs"
                  >
                    Fermer
                  </button>
                </div>

                {userError && (
                  <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-center space-x-2">
                    <AlertCircle className="w-4 h-4 shrink-0" />
                    <span>{userError}</span>
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* Email */}
                  <div>
                    <label className="block text-xs font-medium text-slate-400 mb-1">
                      Adresse email (Identifiant de login) *
                    </label>
                    <input
                      type="email"
                      required
                      placeholder="nom.prenom@entreprise.fr"
                      value={newEmail}
                      onChange={(e) => setNewEmail(e.target.value)}
                      className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-xl text-xs text-white placeholder:text-slate-600 focus:outline-none focus:border-sky-500"
                    />
                  </div>

                  {/* Mot de passe */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-medium text-slate-400">Mot de passe de connexion</label>
                      <button
                        type="button"
                        onClick={generatePassword}
                        className="text-[10px] text-sky-400 hover:text-sky-300 flex items-center space-x-1"
                      >
                        <RefreshCw className="w-2.5 h-2.5" />
                        <span>Générer</span>
                      </button>
                    </div>
                    <div className="relative">
                      <input
                        type={showPassword ? "text" : "password"}
                        placeholder="Mot de passe sécurisé"
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        className="w-full px-3 py-1.5 pr-8 bg-slate-950 border border-slate-800 rounded-xl text-xs text-white placeholder:text-slate-600 font-mono focus:outline-none focus:border-sky-500"
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                      >
                        {showPassword ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                      </button>
                    </div>
                  </div>

                  {/* Nom complet */}
                  <div>
                    <label className="block text-xs font-medium text-slate-400 mb-1">Nom et Prénom *</label>
                    <input
                      type="text"
                      required
                      placeholder="Marc Dupont"
                      value={newFullName}
                      onChange={(e) => setNewFullName(e.target.value)}
                      className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-xl text-xs text-white placeholder:text-slate-600 focus:outline-none focus:border-sky-500"
                    />
                  </div>

                  {/* Rôle dans la société */}
                  <div>
                    <label className="block text-xs font-medium text-slate-400 mb-1">Rôle dans la société</label>
                    <input
                      type="text"
                      placeholder="ex: DAF, Commercial, Comptable, Assistant"
                      value={newRole}
                      onChange={(e) => setNewRole(e.target.value)}
                      className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-xl text-xs text-white placeholder:text-slate-600 focus:outline-none focus:border-sky-500"
                    />
                  </div>
                </div>

                {/* Switch Admin */}
                <div className="p-3 rounded-xl bg-slate-950 border border-slate-800/80 flex items-center justify-between">
                  <div className="pr-4">
                    <div className="text-xs font-bold text-white flex items-center space-x-1.5">
                      <Shield className="w-3.5 h-3.5 text-amber-400" />
                      <span>Droits Administrateur Client</span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      Permet d'afficher et de paramétrer les onglets Interfaces, ERP et Canaux de discussion dans l'interface client. (Les utilisateurs standards accèdent uniquement à la Discussion).
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setNewIsAdmin(!newIsAdmin)}
                    className={`w-11 h-6 flex items-center rounded-full p-1 transition-colors shrink-0 ${
                      newIsAdmin ? "bg-emerald-500" : "bg-slate-800"
                    }`}
                  >
                    <div
                      className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                        newIsAdmin ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>

                <div className="flex items-center justify-end space-x-2 pt-2">
                  <button
                    type="button"
                    onClick={() => {
                      setIsAddingUser(false);
                      setUserError(null);
                    }}
                    className="px-3 py-1.5 rounded-xl text-xs text-slate-400 hover:text-white hover:bg-slate-800"
                  >
                    Annuler
                  </button>
                  <button
                    type="submit"
                    disabled={userSubmitting}
                    className="px-4 py-1.5 rounded-xl text-xs font-bold bg-sky-500 hover:bg-sky-400 text-slate-950 flex items-center space-x-1.5 disabled:opacity-50"
                  >
                    {userSubmitting ? "Création en cours..." : "Créer le collaborateur"}
                  </button>
                </div>
              </form>
            )}

            {/* Liste des utilisateurs */}
            <div className="space-y-2">
              {users.map((u) => (
                <div
                  key={u.id || u.email}
                  className="p-3 rounded-2xl bg-slate-900/90 border border-slate-800/80 flex items-center justify-between gap-3 hover:border-slate-700 transition-colors"
                >
                  <div className="flex items-center space-x-3 min-w-0">
                    <div className="w-8 h-8 rounded-xl bg-slate-800 text-sky-400 border border-slate-700 font-bold text-xs flex items-center justify-center shrink-0">
                      {u.full_name ? u.full_name[0].toUpperCase() : "U"}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center space-x-2">
                        <span className="text-xs font-bold text-white truncate">{u.full_name}</span>
                        {u.is_primary_contact && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/20 shrink-0">
                            Contact Principal
                          </span>
                        )}
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-300 border border-slate-700 truncate">
                          {u.role || "Membre"}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-400 truncate mt-0.5">{u.email}</div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-2 shrink-0">
                    {u.is_admin ? (
                      <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        <ShieldCheck className="w-3 h-3" />
                        <span>Admin (Tous onglets)</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-800 text-slate-400 border border-slate-700">
                        <UserCheck className="w-3 h-3" />
                        <span>Discussion seule</span>
                      </span>
                    )}

                    {!u.is_primary_contact && (
                      <button
                        type="button"
                        onClick={() => handleDeleteUser(u)}
                        title="Révoquer l'accès"
                        className="p-1.5 text-slate-500 hover:text-rose-400 hover:bg-slate-800 rounded-lg transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Section 2 : Matrice d'Activation des Agents & Périodes d'Essai */}
          <div>
            <div className="flex flex-col mb-3 space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-base font-bold text-white">Gestion des Agents Déployés</h3>
                  <p className="text-xs text-slate-400">
                    Activez ou désactivez les agents selon la capacité du forfait sélectionné ({maxQuota} max).
                  </p>
                </div>
                <span
                  className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
                    activeAgents.length >= maxQuota && maxQuota > 0
                      ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                      : "bg-slate-800 text-sky-400 border-slate-700"
                  }`}
                >
                  {activeAgents.length} / {maxQuota} agent(s) activé(s)
                </span>
              </div>

              {isSubscriptionInactive ? (
                <div className="p-3 bg-amber-500/10 border border-amber-500/30 text-amber-400 rounded-xl text-xs font-medium flex items-center space-x-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>
                    Ce client est en statut{" "}
                    <strong>
                      {selectedStatus === "none"
                        ? "Prospect (aucun abonnement)"
                        : selectedStatus === "canceled"
                        ? "Résilié"
                        : "Inactif"}
                    </strong>
                    . Sélectionnez un forfait (1, 2, 3 ou 4 agents) ci-dessous pour débloquer l'activation des agents.
                  </span>
                </div>
              ) : activeAgents.length >= maxQuota ? (
                <div className="p-2.5 bg-slate-900 border border-slate-800 text-slate-300 rounded-xl text-xs font-medium flex items-center justify-between">
                  <span>Quota maximal atteint pour ce forfait ({maxQuota} agent{maxQuota > 1 ? "s" : ""}).</span>
                  {maxQuota < 4 && (
                    <span className="text-sky-400 font-semibold text-[11px]">
                      Sélectionnez un forfait supérieur ci-dessous pour activer plus d'agents.
                    </span>
                  )}
                </div>
              ) : null}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {(Object.keys(AGENTS_CATALOG) as AgentId[]).map((agentId) => {
                const meta = AGENTS_CATALOG[agentId];
                const isEnabled = activeAgents.includes(agentId);
                const trialInfo = trials[agentId];
                const isTrial = Boolean(trialInfo);

                return (
                  <div
                    key={agentId}
                    className={`p-4 rounded-2xl border transition-all ${
                      isEnabled
                        ? "bg-slate-950/80 border-slate-700 shadow-md"
                        : "bg-slate-950/30 border-slate-800/60 opacity-60 hover:opacity-80"
                    }`}
                  >
                    {/* Top Row : Avatar & Toggle */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-3">
                        <div
                          className={`w-9 h-9 rounded-xl bg-gradient-to-tr ${meta.color} flex items-center justify-center text-white font-extrabold text-sm shadow-md`}
                        >
                          {meta.name[0]}
                        </div>
                        <div>
                          <div className="text-sm font-bold text-white">{meta.name}</div>
                          <div className="text-xs text-slate-400">{meta.role}</div>
                        </div>
                      </div>

                      {/* Switch Button avec Quota Lock */}
                      {(() => {
                        const isAtQuota = !isEnabled && activeAgents.length >= maxQuota;
                        const isDisabled = (isSubscriptionInactive && !isEnabled) || isAtQuota;
                        return (
                          <button
                            type="button"
                            onClick={() => handleToggleAgent(agentId)}
                            disabled={isDisabled}
                            title={
                              isDisabled
                                ? isSubscriptionInactive
                                  ? "Sélectionnez un forfait payant pour activer un agent"
                                  : `Quota atteint (${maxQuota} max). Choisissez un forfait supérieur ci-dessous.`
                                : isEnabled
                                ? "Désactiver cet agent"
                                : "Activer cet agent"
                            }
                            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                              isEnabled ? "bg-sky-500" : "bg-slate-700"
                            } ${isDisabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
                          >
                            <span
                              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                isEnabled ? "translate-x-6" : "translate-x-1"
                              }`}
                            />
                          </button>
                        );
                      })()}
                    </div>

                    <p className="text-xs text-slate-400 mt-3 line-clamp-2">{meta.description}</p>

                    {/* Paramétrage de la période d'essai si actif */}
                    {isEnabled && (
                      <div className="mt-3 pt-3 border-t border-slate-800/80 space-y-2">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-slate-400 font-medium">Type d'accès :</span>
                          <div className="flex space-x-1">
                            <button
                              onClick={() => handleSetTrialMode(agentId, false)}
                              className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-all ${
                                !isTrial
                                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                  : "text-slate-500 hover:text-slate-300"
                              }`}
                            >
                              Abonnement
                            </button>
                            <button
                              onClick={() => handleSetTrialMode(agentId, true, 14)}
                              className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-all ${
                                isTrial
                                  ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                                  : "text-slate-500 hover:text-slate-300"
                              }`}
                            >
                              Essai gratuit
                            </button>
                          </div>
                        </div>

                        {isTrial && (
                          <div className="flex items-center justify-between p-2 rounded-xl bg-amber-500/5 border border-amber-500/20 text-xs">
                            <div className="flex items-center space-x-1.5 text-amber-300">
                              <Clock className="w-3.5 h-3.5" />
                              <span>Fin de l'essai :</span>
                            </div>
                            <div className="flex space-x-1">
                              {[7, 14, 30].map((d) => (
                                <button
                                  key={d}
                                  onClick={() => handleSetTrialMode(agentId, true, d)}
                                  className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                    trialInfo.days_remaining === d
                                      ? "bg-amber-500 text-slate-950"
                                      : "bg-slate-800 text-slate-400 hover:text-white"
                                  }`}
                                >
                                  {d}j
                                </button>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Section 3 : Forfait Stripe & Statut Commercial */}
          <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Abonnement Stripe & Statut Commercial
                </span>
                <div className="text-sm font-bold text-white mt-0.5">
                  Forfait sélectionné :{" "}
                  <span className="text-sky-400 font-mono">
                    {TIER_LIMITS[selectedTier]?.label || selectedTier} ({TIER_LIMITS[selectedTier]?.price})
                  </span>
                </div>
              </div>

              {/* Sélecteur de Statut Commercial */}
              <div className="flex items-center space-x-1 bg-slate-900 p-1 rounded-xl border border-slate-800 text-xs">
                {[
                  { id: "active", label: "Abonné", color: "text-emerald-400" },
                  { id: "none", label: "Prospect", color: "text-sky-400" },
                  { id: "canceling", label: "En résiliation", color: "text-amber-400" },
                  { id: "canceled", label: "Résilié", color: "text-rose-400" },
                ].map((st) => (
                  <button
                    key={st.id}
                    type="button"
                    onClick={() => {
                      setSelectedStatus(st.id);
                      if (st.id === "none" || st.id === "canceled") {
                        setSelectedTier("none");
                        setActiveAgents([]);
                        setTrials({});
                      } else if (selectedTier === "none" && st.id === "active") {
                        setSelectedTier("1_agent");
                      }
                    }}
                    className={`px-2.5 py-1 rounded-lg font-medium transition-all ${
                      selectedStatus === st.id
                        ? "bg-slate-800 text-white shadow-sm font-bold border border-slate-700"
                        : "text-slate-400 hover:text-white"
                    }`}
                  >
                    <span className={st.color}>•</span> {st.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Grille des 5 Forfaits */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
              {[
                { id: "none", label: "Aucun", quota: "0 agent", price: "0 € HT" },
                { id: "1_agent", label: "Starter", quota: "1 agent", price: "99 € HT" },
                { id: "2_agents", label: "Duo", quota: "2 agents", price: "169 € HT" },
                { id: "3_agents", label: "Trio", quota: "3 agents", price: "229 € HT" },
                { id: "4_agents", label: "Flotte", quota: "4 agents", price: "279 € HT" },
              ].map((tier) => (
                <button
                  key={tier.id}
                  type="button"
                  onClick={() => handleSelectTier(tier.id)}
                  className={`p-3 rounded-xl border text-left transition-all ${
                    selectedTier === tier.id
                      ? "bg-sky-500/10 border-sky-500 text-white font-bold ring-1 ring-sky-500/50 shadow-md"
                      : "bg-slate-900 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-300"
                  }`}
                >
                  <div className="flex items-center justify-between text-xs font-semibold">
                    <span>{tier.label}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60 font-mono">
                      {tier.quota}
                    </span>
                  </div>
                  <div className="text-sm font-extrabold text-white mt-1.5">{tier.price}</div>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="p-6 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between">
          <div className="text-xs text-slate-400">
            Propagation immédiate sur Supabase & Guard JWT sans coupure de service.
          </div>

          <div className="flex space-x-3">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-all"
            >
              Annuler
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-5 py-2 rounded-xl text-sm font-bold bg-sky-500 hover:bg-sky-400 text-slate-950 shadow-lg shadow-sky-500/20 flex items-center space-x-2 transition-all disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              <span>{saving ? "Sauvegarde en cours..." : "Enregistrer les modifications"}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
