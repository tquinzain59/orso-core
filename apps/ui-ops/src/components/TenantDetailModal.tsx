import React, { useState } from "react";
import { X, Save, Clock, CheckCircle, Play, Square, ExternalLink } from "lucide-react";
import { Tenant, AgentId } from "../types";
import { AGENTS_CATALOG } from "../data";

interface TenantDetailModalProps {
  tenant: Tenant | null;
  onClose: () => void;
  onSaveAgents: (
    tenantId: string,
    activeAgents: AgentId[],
    trialsConfig: Record<string, any>
  ) => Promise<void>;
  onSaveSubscription: (tenantId: string, tierId: string) => Promise<void>;
  onWakeContainer: (slug: string) => void;
  onSuspendContainer: (slug: string) => void;
}

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

  // État local du forfait
  const [selectedTier, setSelectedTier] = useState<string>(
    tenant.subscription.tier_id
  );

  const [saving, setSaving] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Toggle agent
  const handleToggleAgent = (agentId: AgentId) => {
    if (activeAgents.includes(agentId)) {
      setActiveAgents(activeAgents.filter((a) => a !== agentId));
      const updatedTrials = { ...trials };
      delete updatedTrials[agentId];
      setTrials(updatedTrials);
    } else {
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
      if (selectedTier !== tenant.subscription.tier_id) {
        await onSaveSubscription(tenant.id, selectedTier);
      }
      setToastMessage("Modifications enregistrées avec succès !");
      setTimeout(() => setToastMessage(null), 3000);
    } catch (e: any) {
      alert("Erreur lors de l'enregistrement : " + e.message);
    } finally {
      setSaving(false);
    }
  };

  // Calcul du forfait suggéré
  const nbActivePaid = activeAgents.filter((a) => !trials[a]).length;
  let suggestedTierLabel = "Aucun";
  if (nbActivePaid === 1) {
    suggestedTierLabel = "Starter (1 agent - 99 € HT)";
  } else if (nbActivePaid === 2) {
    suggestedTierLabel = "Duo (2 agents - 169 € HT)";
  } else if (nbActivePaid >= 3) {
    suggestedTierLabel = "Flotte Complète (4 agents - 279 € HT)";
  }

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

          {/* Section 2 : Matrice d'Activation des Agents & Périodes d'Essai */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="text-base font-bold text-white">Gestion des Agents Déployés</h3>
                <p className="text-xs text-slate-400">
                  Activez ou désactivez les agents en 1-clic. Définissez une période d'essai pour les nouveaux modules.
                </p>
              </div>
              <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-slate-800 text-sky-400 border border-slate-700">
                {activeAgents.length} agent(s) activé(s)
              </span>
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

                      {/* Switch Button */}
                      <button
                        onClick={() => handleToggleAgent(agentId)}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                          isEnabled ? "bg-sky-500" : "bg-slate-700"
                        }`}
                      >
                        <span
                          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            isEnabled ? "translate-x-6" : "translate-x-1"
                          }`}
                        />
                      </button>
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

          {/* Section 3 : Forfait Stripe & Tarification */}
          <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Abonnement Stripe Associé
                </span>
                <div className="text-sm font-bold text-white mt-0.5">
                  Tarif suggéré selon sélection :{" "}
                  <span className="text-sky-400">{suggestedTierLabel}</span>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {[
                { id: "1_agent", label: "Starter (1 agent)", price: "99 € HT" },
                { id: "2_agents", label: "Duo (2 agents)", price: "169 € HT" },
                { id: "4_agents", label: "Flotte (4 agents)", price: "279 € HT" },
              ].map((tier) => (
                <button
                  key={tier.id}
                  onClick={() => setSelectedTier(tier.id)}
                  className={`p-3 rounded-xl border text-left transition-all ${
                    selectedTier === tier.id
                      ? "bg-sky-500/10 border-sky-500 text-white font-bold"
                      : "bg-slate-900 border-slate-800 text-slate-400 hover:border-slate-700"
                  }`}
                >
                  <div className="text-xs">{tier.label}</div>
                  <div className="text-base font-extrabold text-white mt-1">{tier.price}</div>
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
