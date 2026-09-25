import React, { useState } from "react";
import { Search, Filter, SlidersHorizontal, CheckCircle2, Clock, AlertTriangle, Play, Square } from "lucide-react";
import { Tenant } from "../types";
import { AGENTS_CATALOG } from "../data";

interface TenantsViewProps {
  tenants: Tenant[];
  onSelectTenant: (t: Tenant) => void;
  onWakeContainer: (slug: string) => void;
  onSuspendContainer: (slug: string) => void;
}

export const TenantsView: React.FC<TenantsViewProps> = ({
  tenants,
  onSelectTenant,
  onWakeContainer,
  onSuspendContainer,
}) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const filteredTenants = tenants.filter((t) => {
    const matchesUser = t.users?.some(
      (u) =>
        u.full_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        u.email.toLowerCase().includes(searchTerm.toLowerCase())
    );
    const matchesSearch =
      t.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.slug.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (t.siret && t.siret.includes(searchTerm)) ||
      t.contact.full_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.contact.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
      Boolean(matchesUser);

    if (!matchesSearch) return false;
    if (statusFilter === "all") return true;
    if (statusFilter === "active") return t.status === "active";
    if (statusFilter === "trial") return t.status === "trial" || Object.keys(t.agents_enabled.trials).length > 0;
    if (statusFilter === "suspended") return t.status === "suspended";
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Annuaire des Entreprises & Clients</h1>
          <p className="text-sm text-slate-400 mt-1">
            Activez/désactivez des agents, gérez les durées d'essai et surveillez les conteneurs clients.
          </p>
        </div>
      </div>

      {/* Filters & Search */}
      <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 bg-slate-900/90 border border-slate-800 p-4 rounded-2xl">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Rechercher une entreprise, un SIRET, un contact ou un email..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-slate-950/80 border border-slate-800 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-sky-500 transition-all"
          />
        </div>

        <div className="flex items-center space-x-2">
          <Filter className="w-4 h-4 text-slate-400" />
          <div className="flex rounded-xl bg-slate-950 p-1 border border-slate-800 text-xs font-medium">
            <button
              onClick={() => setStatusFilter("all")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                statusFilter === "all" ? "bg-sky-500 text-slate-950 font-bold" : "text-slate-400 hover:text-white"
              }`}
            >
              Tous ({tenants.length})
            </button>
            <button
              onClick={() => setStatusFilter("active")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                statusFilter === "active" ? "bg-emerald-500 text-slate-950 font-bold" : "text-slate-400 hover:text-white"
              }`}
            >
              Abonnés
            </button>
            <button
              onClick={() => setStatusFilter("trial")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                statusFilter === "trial" ? "bg-amber-500 text-slate-950 font-bold" : "text-slate-400 hover:text-white"
              }`}
            >
              Essais
            </button>
          </div>
        </div>
      </div>

      {/* Tenants Table */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-slate-950/70 border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                <th className="py-3.5 px-4 font-semibold">Entreprise & SIRET</th>
                <th className="py-3.5 px-4 font-semibold">Contact DAF / Dirigeant</th>
                <th className="py-3.5 px-4 font-semibold">Statut Commercial</th>
                <th className="py-3.5 px-4 font-semibold">Forfait Facturé</th>
                <th className="py-3.5 px-4 font-semibold">Agents Déployés</th>
                <th className="py-3.5 px-4 font-semibold">Conteneur Olympe</th>
                <th className="py-3.5 px-4 font-semibold text-right">Pilotage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {filteredTenants.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-400">
                    Aucun client ne correspond à votre recherche.
                  </td>
                </tr>
              ) : (
                filteredTenants.map((t) => {
                  const hasTrials = Object.keys(t.agents_enabled.trials).length > 0;
                  const isContainerReady = t.instance?.status === "ready";
                  const isNotProvisioned = t.instance?.status === "not_provisioned" || !t.instance?.status;
                  const hasNoSubscription = t.subscription.status === "none" || t.subscription.status === "inactive" || t.subscription.tier_id === "none";

                  return (
                    <tr key={t.id} className="hover:bg-slate-800/40 transition-colors">
                      {/* Entreprise */}
                      <td className="py-4 px-4 font-medium text-white">
                        <div className="text-base font-bold">{t.name}</div>
                        <div className="flex items-center space-x-2 text-xs text-slate-400 font-mono mt-0.5">
                          <span>{t.siret || "SIRET non renseigné"}</span>
                          <span>•</span>
                          <span className="text-slate-500">{t.slug}</span>
                        </div>
                      </td>

                      {/* Contact */}
                      <td className="py-4 px-4 text-slate-300">
                        <div className="flex items-center space-x-2">
                          <span className="font-semibold">{t.contact.full_name}</span>
                          {t.users && t.users.length > 1 && (
                            <span
                              className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20"
                              title={`${t.users.length} collaborateurs enregistrés pour ce client`}
                            >
                              +{t.users.length - 1}
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-slate-400">{t.contact.email}</div>
                        {t.contact.phone && (
                          <div className="text-xs text-slate-500 font-mono">{t.contact.phone}</div>
                        )}
                      </td>

                      {/* Statut Commercial */}
                      <td className="py-4 px-4">
                        {t.status === "active" && !hasTrials && !hasNoSubscription && (
                          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span>Client Actif</span>
                          </span>
                        )}
                        {hasNoSubscription && (
                          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20">
                            <AlertTriangle className="w-3.5 h-3.5" />
                            <span>Sans abonnement</span>
                          </span>
                        )}
                        {hasTrials && (
                          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                            <Clock className="w-3.5 h-3.5" />
                            <span>Essai en cours</span>
                          </span>
                        )}
                        {t.status === "suspended" && (
                          <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                            <AlertTriangle className="w-3.5 h-3.5" />
                            <span>Suspendu</span>
                          </span>
                        )}
                      </td>

                      {/* Forfait */}
                      <td className="py-4 px-4">
                        <div className="font-bold text-white text-sm">
                          {hasNoSubscription ? "0 € HT/m" : (t.subscription.price_ht > 0 ? `${t.subscription.price_ht} € HT/m` : "Gratuit (Essai)")}
                        </div>
                        <div className="text-xs text-slate-400">{t.subscription.tier_label}</div>
                      </td>

                      {/* Agents Déployés */}
                      <td className="py-4 px-4">
                        <div className="flex flex-wrap gap-1.5 max-w-xs">
                          {t.agents_enabled.active.length === 0 && (
                            <span className="text-xs px-2.5 py-1 rounded-lg border font-medium bg-slate-800 border-slate-700 text-slate-400">Aucun agent activé</span>
                          )}
                          {t.agents_enabled.active.map((agentId) => {
                            const meta = AGENTS_CATALOG[agentId];
                            const trialInfo = t.agents_enabled.trials[agentId];

                            return (
                              <span
                                key={agentId}
                                className={`text-xs px-2.5 py-1 rounded-lg border font-medium flex items-center space-x-1 ${
                                  trialInfo
                                    ? "bg-amber-500/15 border-amber-500/40 text-amber-300"
                                    : meta?.badgeBg || "bg-slate-800 text-slate-200"
                                }`}
                              >
                                <span>{meta?.name || agentId}</span>
                                {trialInfo && (
                                  <span className="text-[10px] font-bold px-1 rounded bg-amber-400/20 text-amber-200">
                                    {trialInfo.days_remaining ? `${trialInfo.days_remaining}j` : "Essai"}
                                  </span>
                                )}
                              </span>
                            );
                          })}
                        </div>
                      </td>

                      {/* Conteneur Olympe */}
                      <td className="py-4 px-4">
                        <div className="flex items-center space-x-2">
                          <span
                            className={`w-2.5 h-2.5 rounded-full ${
                              isContainerReady ? "bg-emerald-400 animate-pulse" : (isNotProvisioned ? "bg-slate-700" : "bg-amber-400")
                            }`}
                          ></span>
                          <span className="text-xs font-mono font-medium text-slate-300">
                            {isContainerReady ? "En ligne" : (isNotProvisioned ? "Non provisionné" : "En veille")}
                          </span>
                        </div>
                        {!isNotProvisioned && (
                          <div className="flex space-x-1 mt-1.5">
                            {!isContainerReady ? (
                              <button
                                onClick={() => onWakeContainer(t.slug)}
                                title="Réveiller le conteneur"
                                className="px-2 py-0.5 rounded bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-[10px] font-bold border border-emerald-500/20 flex items-center space-x-1"
                              >
                                <Play className="w-2.5 h-2.5" />
                                <span>Wake</span>
                              </button>
                            ) : (
                              <button
                                onClick={() => onSuspendContainer(t.slug)}
                                title="Mettre en veille (Stop)"
                                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 text-[10px] font-bold border border-slate-700 flex items-center space-x-1"
                              >
                                <Square className="w-2.5 h-2.5" />
                                <span>Stop</span>
                              </button>
                            )}
                          </div>
                        )}
                      </td>

                      {/* Bouton Action */}
                      <td className="py-4 px-4 text-right">
                        <button
                          onClick={() => onSelectTenant(t)}
                          className="px-3.5 py-1.5 bg-sky-500/10 hover:bg-sky-500/20 text-sky-400 hover:text-sky-300 rounded-xl text-xs font-bold border border-sky-500/30 flex items-center space-x-1.5 ml-auto transition-all shadow-sm"
                        >
                          <SlidersHorizontal className="w-3.5 h-3.5" />
                          <span>Gérer</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
