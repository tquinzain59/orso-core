import React from "react";
import { Server, Play, Square, Activity, ShieldCheck } from "lucide-react";
import { Tenant } from "../types";

interface FleetViewProps {
  tenants: Tenant[];
  onWakeContainer: (slug: string) => void;
  onSuspendContainer: (slug: string) => void;
}

export const FleetView: React.FC<FleetViewProps> = ({
  tenants,
  onWakeContainer,
  onSuspendContainer,
}) => {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Supervision Flotte Olympe & Ingress</h1>
        <p className="text-sm text-slate-400 mt-1">
          Orchestration physique des conteneurs isolés, réseau interne <code>orso_network</code> et routage Nginx.
        </p>
      </div>

      {/* Network Overview Card */}
      <div className="bg-slate-900/80 border border-slate-800 p-6 rounded-3xl grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="flex items-start space-x-4">
          <div className="p-3 rounded-2xl bg-sky-500/10 border border-sky-500/20 text-sky-400">
            <Server className="w-6 h-6" />
          </div>
          <div>
            <div className="text-xs uppercase font-semibold text-slate-400">Passerelle Ingress</div>
            <div className="text-lg font-bold text-white mt-0.5">Nginx Zero-Reload</div>
            <p className="text-xs text-slate-400 mt-1">Résolveur Docker DNS <code>127.0.0.11</code> actif</p>
          </div>
        </div>

        <div className="flex items-start space-x-4">
          <div className="p-3 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <ShieldCheck className="w-6 h-6" />
          </div>
          <div>
            <div className="text-xs uppercase font-semibold text-slate-400">Réseau d'Isolation</div>
            <div className="text-lg font-bold text-white mt-0.5">orso_network (Bridge)</div>
            <p className="text-xs text-slate-400 mt-1">Ports 9119 internes étanches par client</p>
          </div>
        </div>

        <div className="flex items-start space-x-4">
          <div className="p-3 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
            <Activity className="w-6 h-6" />
          </div>
          <div>
            <div className="text-xs uppercase font-semibold text-slate-400">Superviseur Olympe</div>
            <div className="text-lg font-bold text-white mt-0.5">Port 9230 (Healthy)</div>
            <p className="text-xs text-slate-400 mt-1">Gestionnaire Wake-on-Demand prêt</p>
          </div>
        </div>
      </div>

      {/* Fleet Containers Table */}
      <div className="bg-slate-900/80 border border-slate-800 p-6 rounded-3xl">
        <h2 className="text-lg font-bold text-white mb-4">Conteneurs Clients Déployés</h2>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                <th className="pb-3 font-semibold">Conteneur Docker</th>
                <th className="pb-3 font-semibold">Client Assigné</th>
                <th className="pb-3 font-semibold">Route Ingress</th>
                <th className="pb-3 font-semibold">Port Interne</th>
                <th className="pb-3 font-semibold">État Réel</th>
                <th className="pb-3 font-semibold text-right">Cycle de Vie</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {tenants.map((t) => {
                const isReady = t.instance?.status === "ready";
                const containerName = t.instance?.container_name || `orso_client_${t.slug}`;

                return (
                  <tr key={t.id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="py-3 font-mono font-bold text-white flex items-center space-x-2">
                      <span className={`w-2 h-2 rounded-full ${isReady ? "bg-emerald-400 animate-pulse" : "bg-slate-600"}`}></span>
                      <span>{containerName}</span>
                    </td>
                    <td className="py-3 text-slate-300 font-medium">{t.name}</td>
                    <td className="py-3 font-mono text-xs text-sky-400">/t/{t.slug}/api/*</td>
                    <td className="py-3 font-mono text-xs text-slate-400">9119 (interne)</td>
                    <td className="py-3">
                      <span
                        className={`text-xs px-2.5 py-1 rounded-full font-mono font-medium ${
                          isReady ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {isReady ? "running (ready)" : "exited (sleeping)"}
                      </span>
                    </td>
                    <td className="py-3 text-right">
                      {!isReady ? (
                        <button
                          onClick={() => onWakeContainer(t.slug)}
                          className="px-3 py-1 bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-400 rounded-lg text-xs font-bold border border-emerald-500/30 inline-flex items-center space-x-1.5 transition-all"
                        >
                          <Play className="w-3 h-3" />
                          <span>Wake-on-Demand</span>
                        </button>
                      ) : (
                        <button
                          onClick={() => onSuspendContainer(t.slug)}
                          className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white rounded-lg text-xs font-bold border border-slate-700 inline-flex items-center space-x-1.5 transition-all"
                        >
                          <Square className="w-3 h-3" />
                          <span>Mettre en veille</span>
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
