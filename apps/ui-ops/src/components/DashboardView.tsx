import React from "react";
import { Users, CreditCard, Sparkles, TrendingUp, CheckCircle, Clock } from "lucide-react";
import { OpsStats, Tenant } from "../types";
import { AGENTS_CATALOG } from "../data";

interface DashboardViewProps {
  stats: OpsStats | null;
  tenants: Tenant[];
  onSelectTenant: (t: Tenant) => void;
  onGoToTenants: () => void;
}

export const DashboardView: React.FC<DashboardViewProps> = ({
  stats,
  tenants,
  onSelectTenant,
  onGoToTenants,
}) => {
  if (!stats) {
    return (
      <div className="py-20 text-center text-slate-400">
        Chargement des métriques opérationnelles...
      </div>
    );
  }

  const kpis = stats.kpis;

  return (
    <div className="space-y-8">
      {/* Hero Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-gradient-to-r from-slate-900 via-slate-900 to-sky-950/40 p-6 rounded-2xl border border-slate-800 shadow-xl">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Tableau de Bord Opérations</h1>
          <p className="text-sm text-slate-400 mt-1">
            Supervision commerciale, revenus récurrents et pilotage de la flotte multi-agents.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={onGoToTenants}
            className="px-4 py-2 bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold rounded-xl text-sm transition-all shadow-lg shadow-sky-500/20"
          >
            Gérer les Clients & Agents
          </button>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {/* MRR */}
        <div className="bg-slate-900/90 border border-slate-800 p-5 rounded-2xl relative overflow-hidden group hover:border-slate-700 transition-all">
          <div className="absolute top-0 right-0 w-24 h-24 bg-sky-500/5 rounded-full blur-xl group-hover:bg-sky-500/10 transition-all"></div>
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-sky-400 tracking-wider uppercase">Revenus Récurrents</span>
            <div className="p-2 rounded-xl bg-sky-500/10 border border-sky-500/20 text-sky-400">
              <CreditCard className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-3xl font-extrabold text-white tracking-tight">
              {kpis.mrr_ht.toLocaleString("fr-FR")} € <span className="text-xs font-normal text-slate-400">HT / mois</span>
            </div>
            <div className="flex items-center justify-between text-xs text-slate-400 mt-2 pt-2 border-t border-slate-800/80">
              <span>TTC : {kpis.mrr_ttc.toLocaleString("fr-FR")} €</span>
              <span className="text-emerald-400 font-medium">ARR : {kpis.arr_ht.toLocaleString("fr-FR")} €</span>
            </div>
          </div>
        </div>

        {/* Abonnés Actifs */}
        <div className="bg-slate-900/90 border border-slate-800 p-5 rounded-2xl relative overflow-hidden group hover:border-slate-700 transition-all">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-emerald-400 tracking-wider uppercase">Abonnés Payants</span>
            <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <CheckCircle className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-3xl font-extrabold text-white tracking-tight">
              {kpis.active_subscribers}
            </div>
            <div className="text-xs text-slate-400 mt-2 pt-2 border-t border-slate-800/80">
              Sur {kpis.total_clients} entreprises enregistrées
            </div>
          </div>
        </div>

        {/* En Période d'Essai */}
        <div className="bg-slate-900/90 border border-slate-800 p-5 rounded-2xl relative overflow-hidden group hover:border-slate-700 transition-all">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-amber-400 tracking-wider uppercase">En Période d'Essai</span>
            <div className="p-2 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400">
              <Clock className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-3xl font-extrabold text-white tracking-tight">
              {kpis.trialing_clients}
            </div>
            <div className="text-xs text-slate-400 mt-2 pt-2 border-t border-slate-800/80">
              Prospects testant 1 ou plusieurs agents
            </div>
          </div>
        </div>

        {/* Total Inscrits */}
        <div className="bg-slate-900/90 border border-slate-800 p-5 rounded-2xl relative overflow-hidden group hover:border-slate-700 transition-all">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-indigo-400 tracking-wider uppercase">Total Clients Inscrits</span>
            <div className="p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <Users className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-3xl font-extrabold text-white tracking-tight">
              {kpis.total_clients}
            </div>
            <div className="text-xs text-slate-400 mt-2 pt-2 border-t border-slate-800/80">
              Inscriptions via orso-agents.fr
            </div>
          </div>
        </div>
      </div>

      {/* Pricing Tiers & Agents Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Grille Tarifaire Officielle */}
        <div className="lg:col-span-2 bg-slate-900/80 border border-slate-800 p-6 rounded-2xl">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-lg font-bold text-white">Forfaits & Abonnements Stripe</h2>
              <p className="text-xs text-slate-400">Grille tarifaire validée et répartition des clients actifs</p>
            </div>
            <TrendingUp className="w-5 h-5 text-sky-400" />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {/* 1 Agent */}
            <div className="bg-slate-950/60 border border-slate-800/90 p-4 rounded-xl relative">
              <div className="flex justify-between items-start">
                <span className="text-xs font-semibold px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  Starter
                </span>
                <span className="text-xs font-bold text-slate-400">
                  {stats.tier_distribution["1_agent"] || 0} abonné(s)
                </span>
              </div>
              <div className="mt-3">
                <div className="text-2xl font-extrabold text-white">99 € <span className="text-xs font-normal text-slate-400">HT/m</span></div>
                <div className="text-xs text-slate-400 mt-1">1 agent au choix (ex: Jérôme)</div>
              </div>
            </div>

            {/* 2 Agents */}
            <div className="bg-slate-950/60 border border-purple-500/30 p-4 rounded-xl relative shadow-lg shadow-purple-500/5">
              <div className="flex justify-between items-start">
                <span className="text-xs font-semibold px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20">
                  Duo
                </span>
                <span className="text-xs font-bold text-purple-300">
                  {stats.tier_distribution["2_agents"] || 0} abonné(s)
                </span>
              </div>
              <div className="mt-3">
                <div className="text-2xl font-extrabold text-white">169 € <span className="text-xs font-normal text-slate-400">HT/m</span></div>
                <div className="text-xs text-slate-400 mt-1">2 agents (ex: Jérôme + Lucas)</div>
              </div>
            </div>

            {/* 4 Agents */}
            <div className="bg-slate-950/60 border border-amber-500/30 p-4 rounded-xl relative shadow-lg shadow-amber-500/5">
              <div className="flex justify-between items-start">
                <span className="text-xs font-semibold px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  Flotte Complète
                </span>
                <span className="text-xs font-bold text-amber-300">
                  {stats.tier_distribution["4_agents"] || 0} abonné(s)
                </span>
              </div>
              <div className="mt-3">
                <div className="text-2xl font-extrabold text-white">279 € <span className="text-xs font-normal text-slate-400">HT/m</span></div>
                <div className="text-xs text-slate-400 mt-1">Les 4 agents activés</div>
              </div>
            </div>
          </div>
        </div>

        {/* Adoption des Agents */}
        <div className="bg-slate-900/80 border border-slate-800 p-6 rounded-2xl">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-lg font-bold text-white">Déploiement des Agents</h2>
              <p className="text-xs text-slate-400">Nombre d'entreprises ayant activé chaque agent</p>
            </div>
            <Sparkles className="w-5 h-5 text-amber-400" />
          </div>

          <div className="space-y-4">
            {(Object.keys(AGENTS_CATALOG) as Array<keyof typeof AGENTS_CATALOG>).map((agentKey) => {
              const meta = AGENTS_CATALOG[agentKey];
              const count = stats.agent_utilization[agentKey] || 0;
              const pct = kpis.total_clients > 0 ? Math.round((count / kpis.total_clients) * 100) : 0;

              return (
                <div key={agentKey} className="space-y-1.5">
                  <div className="flex justify-between items-center text-xs">
                    <span className="font-semibold text-slate-200">{meta.name} ({meta.role})</span>
                    <span className="text-slate-400 font-mono">{count} clients ({pct}%)</span>
                  </div>
                  <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full bg-gradient-to-r ${meta.color}`}
                      style={{ width: `${Math.max(pct, 5)}%` }}
                    ></div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Quick Clients Table */}
      <div className="bg-slate-900/80 border border-slate-800 p-6 rounded-2xl">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-bold text-white">Clients Récents</h2>
            <p className="text-xs text-slate-400">Derniers comptes configurés sur la plateforme</p>
          </div>
          <button
            onClick={onGoToTenants}
            className="text-xs text-sky-400 hover:text-sky-300 font-medium"
          >
            Voir tous les clients ({tenants.length}) &rarr;
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                <th className="pb-3 font-semibold">Entreprise</th>
                <th className="pb-3 font-semibold">Contact DAF / Dirigeant</th>
                <th className="pb-3 font-semibold">Forfait</th>
                <th className="pb-3 font-semibold">Agents Activés</th>
                <th className="pb-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {tenants.slice(0, 5).map((t) => (
                <tr key={t.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="py-3 font-medium text-white">
                    {t.name}
                    <div className="text-xs text-slate-400 font-mono">{t.siret || t.slug}</div>
                  </td>
                  <td className="py-3 text-slate-300">
                    {t.contact.full_name}
                    <div className="text-xs text-slate-400">{t.contact.email}</div>
                  </td>
                  <td className="py-3">
                    <span className="text-xs font-semibold px-2 py-0.5 rounded bg-slate-800 text-slate-200 border border-slate-700">
                      {t.subscription.tier_label} ({t.subscription.price_ht} € HT)
                    </span>
                  </td>
                  <td className="py-3">
                    <div className="flex space-x-1.5">
                      {t.agents_enabled.active.map((a) => {
                        const meta = AGENTS_CATALOG[a];
                        const isTrial = Boolean(t.agents_enabled.trials[a]);
                        return (
                          <span
                            key={a}
                            className={`text-xs px-2 py-0.5 rounded-full border ${
                              isTrial
                                ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
                                : meta?.badgeBg || "bg-slate-800 text-slate-300"
                            }`}
                            title={isTrial ? "Période d'essai active" : "Abonnement actif"}
                          >
                            {meta?.name || a} {isTrial && "⏳"}
                          </span>
                        );
                      })}
                    </div>
                  </td>
                  <td className="py-3 text-right">
                    <button
                      onClick={() => onSelectTenant(t)}
                      className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-sky-400 hover:text-sky-300 text-xs font-medium rounded-lg border border-slate-700 transition-all"
                    >
                      Piloter
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
