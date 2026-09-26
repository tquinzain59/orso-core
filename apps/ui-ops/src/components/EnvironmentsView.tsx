import React, { useState, useEffect } from "react";
import {
  Activity,
  Server,
  Cpu,
  Layers,
  Search,
  Filter,
  AlertTriangle,
  Clock,
  ExternalLink,
  RefreshCw,
  Building2,
  ShieldCheck,
  ChevronLeft,
  ChevronRight,
  X,
  TrendingUp,
  Zap,
  Loader2,
} from "lucide-react";
import {
  TelemetrySummary,
  TelemetryEnvironment,
  TelemetrySnapshot,
  TelemetryAlert,
  Tenant,
} from "../types";
import {
  fetchTelemetrySummary,
  fetchTelemetryEnvironments,
  fetchAgentHistory,
  fetchTelemetryAlerts,
} from "../api";

interface EnvironmentsViewProps {
  tenants: Tenant[];
  onSelectTenant?: (tenant: Tenant) => void;
}

export const EnvironmentsView: React.FC<EnvironmentsViewProps> = ({
  tenants,
  onSelectTenant,
}) => {
  const [summary, setSummary] = useState<TelemetrySummary | null>(null);
  const [environments, setEnvironments] = useState<TelemetryEnvironment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchTerm, setSearchTerm] = useState("");
  const [filterType, setFilterType] = useState<"all" | "clients" | "system" | "active" | "idle">("all");

  // État de la modale de détails
  const [selectedEnv, setSelectedEnv] = useState<TelemetryEnvironment | null>(null);
  const [snapshots, setSnapshots] = useState<TelemetrySnapshot[]>([]);
  const [envAlerts, setEnvAlerts] = useState<TelemetryAlert[]>([]);
  const [loadingModal, setLoadingModal] = useState(false);
  const [modalPage, setModalPage] = useState(1);
  const modalPageLimit = 5;

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [sum, envs] = await Promise.all([
        fetchTelemetrySummary(),
        fetchTelemetryEnvironments(),
      ]);
      setSummary(sum);
      setEnvironments(envs);
    } catch (err: any) {
      setError(err.message || "Erreur de chargement de la télémétrie");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    // Rafraîchissement automatique toutes les 30 secondes
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, []);

  // Chargement des données détaillées de la modale au clic
  const handleOpenModal = async (env: TelemetryEnvironment) => {
    setSelectedEnv(env);
    setModalPage(1);
    setLoadingModal(true);
    try {
      const [hist, alerts] = await Promise.all([
        fetchAgentHistory(env.agent_id, 25),
        fetchTelemetryAlerts(env.agent_id),
      ]);
      setSnapshots(hist.snapshots || []);
      setEnvAlerts(alerts || []);
    } catch (e: any) {
      console.error("Erreur chargement détails agent:", e);
    } finally {
      setLoadingModal(false);
    }
  };

  const handleCloseModal = () => {
    setSelectedEnv(null);
    setSnapshots([]);
    setEnvAlerts([]);
  };

  // Filtrage
  const filteredEnvironments = environments.filter((env) => {
    const search = searchTerm.toLowerCase();
    const matchesSearch =
      env.display_name.toLowerCase().includes(search) ||
      env.module.toLowerCase().includes(search) ||
      env.container_id.toLowerCase().includes(search) ||
      env.server_ip.toLowerCase().includes(search) ||
      (env.tenant?.name && env.tenant.name.toLowerCase().includes(search)) ||
      (env.tenant?.slug && env.tenant.slug.toLowerCase().includes(search));

    if (!matchesSearch) return false;

    if (filterType === "clients") return !env.tenant?.is_system;
    if (filterType === "system") return Boolean(env.tenant?.is_system);
    if (filterType === "active") return env.status === "active";
    if (filterType === "idle") return env.status === "idle" || env.status === "error";

    return true;
  });

  const formatNumber = (num: number): string => {
    return new Intl.NumberFormat("fr-FR").format(num);
  };

  const formatTokens = (tokens: number): string => {
    if (tokens >= 1_000_000) {
      return (tokens / 1_000_000).toFixed(1) + " M";
    }
    if (tokens >= 1_000) {
      return (tokens / 1_000).toFixed(1) + " k";
    }
    return tokens.toString();
  };

  // Pagination de la modale
  const totalSnapshots = snapshots.length;
  const totalPages = Math.ceil(totalSnapshots / modalPageLimit) || 1;
  const paginatedSnapshots = snapshots.slice(
    (modalPage - 1) * modalPageLimit,
    modalPage * modalPageLimit
  );

  return (
    <div className="space-y-8">
      {/* Header & Titre */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2.5">
            <div className="p-2 rounded-xl bg-sky-500/10 border border-sky-500/20 text-sky-400">
              <Activity className="w-5 h-5" />
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight">
              Environnements Docker & Télémétrie
            </h1>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Supervision temps réel des conteneurs, consommation de jetons, signes vitaux Docker et clients rattachés.
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={loadData}
            disabled={loading}
            className="flex items-center space-x-2 px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800 text-xs font-semibold text-slate-300 hover:text-white hover:border-slate-700 transition-all disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin text-sky-400" : ""}`} />
            <span>Actualiser</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-sm flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            onClick={loadData}
            className="text-xs underline hover:text-white font-bold ml-4 cursor-pointer"
          >
            Réessayer
          </button>
        </div>
      )}

      {/* Bannière KPIs Globaux */}
      {summary && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Tokens Totaux */}
          <div className="p-5 rounded-2xl bg-slate-900/80 border border-slate-800 backdrop-blur-md relative overflow-hidden group hover:border-slate-700 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Jetons Consommés
              </span>
              <div className="p-2 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
                <Zap className="w-4 h-4" />
              </div>
            </div>
            <div className="text-2xl font-extrabold text-white mt-2">
              {formatTokens(summary.total_tokens)}
            </div>
            <div className="flex items-center space-x-2 text-xs text-slate-400 mt-1 font-mono">
              <span className="text-blue-400">In: {formatTokens(summary.total_input_tokens)}</span>
              <span>•</span>
              <span className="text-emerald-400">Out: {formatTokens(summary.total_output_tokens)}</span>
            </div>
          </div>

          {/* Coût Total */}
          <div className="p-5 rounded-2xl bg-slate-900/80 border border-slate-800 backdrop-blur-md relative overflow-hidden group hover:border-slate-700 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Dépenses LLM ($)
              </span>
              <div className="p-2 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
                <TrendingUp className="w-4 h-4" />
              </div>
            </div>
            <div className="text-2xl font-extrabold text-white mt-2">
              {summary.total_cost_usd.toFixed(2)} $
            </div>
            <div className="text-xs text-slate-400 mt-1">
              Soit environ {(summary.total_cost_usd * 0.92).toFixed(2)} € HT
            </div>
          </div>

          {/* Appels API */}
          <div className="p-5 rounded-2xl bg-slate-900/80 border border-slate-800 backdrop-blur-md relative overflow-hidden group hover:border-slate-700 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Requêtes & Appels API
              </span>
              <div className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <Layers className="w-4 h-4" />
              </div>
            </div>
            <div className="text-2xl font-extrabold text-white mt-2">
              {formatNumber(summary.total_api_calls)}
            </div>
            <div className="text-xs text-slate-400 mt-1">
              Sur {summary.agents_count} environnements actifs
            </div>
          </div>

          {/* Alertes Actives */}
          <div className="p-5 rounded-2xl bg-slate-900/80 border border-slate-800 backdrop-blur-md relative overflow-hidden group hover:border-slate-700 transition-all">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Alertes & Incidents
              </span>
              <div
                className={`p-2 rounded-xl border ${
                  summary.alerts_active > 0
                    ? "bg-rose-500/10 text-rose-400 border-rose-500/20 animate-pulse"
                    : "bg-slate-800 text-slate-400 border-slate-700"
                }`}
              >
                <AlertTriangle className="w-4 h-4" />
              </div>
            </div>
            <div className="text-2xl font-extrabold text-white mt-2">
              {summary.alerts_active}
            </div>
            <div className="text-xs text-slate-400 mt-1">
              {summary.alerts_active > 0 ? "Surveillance active requise" : "Aucun incident détecté"}
            </div>
          </div>
        </div>
      )}

      {/* Barre de Recherche et Filtres */}
      <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 bg-slate-900/90 border border-slate-800 p-4 rounded-2xl">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Rechercher un environnement, un client, un module ou un conteneur..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-slate-950/80 border border-slate-800 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-sky-500 transition-all"
          />
        </div>

        <div className="flex items-center space-x-2">
          <Filter className="w-4 h-4 text-slate-400 shrink-0" />
          <div className="flex flex-wrap rounded-xl bg-slate-950 p-1 border border-slate-800 text-xs font-medium gap-0.5">
            <button
              onClick={() => setFilterType("all")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                filterType === "all" ? "bg-sky-500 text-slate-950 font-bold" : "text-slate-400 hover:text-white"
              }`}
            >
              Tous ({environments.length})
            </button>
            <button
              onClick={() => setFilterType("clients")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                filterType === "clients" ? "bg-emerald-500 text-slate-950 font-bold" : "text-slate-400 hover:text-white"
              }`}
            >
              Clients
            </button>
            <button
              onClick={() => setFilterType("system")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                filterType === "system" ? "bg-indigo-500 text-white font-bold" : "text-slate-400 hover:text-white"
              }`}
            >
              Supervision
            </button>
            <button
              onClick={() => setFilterType("active")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                filterType === "active" ? "bg-emerald-500 text-slate-950 font-bold" : "text-slate-400 hover:text-white"
              }`}
            >
              Actifs
            </button>
            <button
              onClick={() => setFilterType("idle")}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                filterType === "idle" ? "bg-amber-500 text-slate-950 font-bold" : "text-slate-400 hover:text-white"
              }`}
            >
              En veille
            </button>
          </div>
        </div>
      </div>

      {/* Grille des Environnements */}
      {filteredEnvironments.length === 0 ? (
        <div className="py-16 text-center text-slate-400 bg-slate-900/50 rounded-2xl border border-slate-800">
          Aucun environnement Docker ne correspond à votre recherche.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredEnvironments.map((env) => {
            const isSystem = Boolean(env.tenant?.is_system);
            const isActive = env.status === "active";
            const isError = env.status === "error";

            // Glow couleur selon le module
            let glowGradient = "from-blue-600/10";
            let accentBorder = "hover:border-blue-500/40";
            if (env.module === "supervision" || isSystem) {
              glowGradient = "from-indigo-600/10";
              accentBorder = "hover:border-indigo-500/40";
            } else if (env.module === "commercial") {
              glowGradient = "from-purple-600/10";
              accentBorder = "hover:border-purple-500/40";
            } else if (env.module === "support") {
              glowGradient = "from-emerald-600/10";
              accentBorder = "hover:border-emerald-500/40";
            }

            return (
              <div
                key={env.agent_id}
                onClick={() => handleOpenModal(env)}
                className={`group relative bg-slate-900/80 hover:bg-slate-900 border border-slate-800 ${accentBorder} rounded-3xl p-6 transition-all duration-300 shadow-xl overflow-hidden backdrop-blur-md cursor-pointer flex flex-col justify-between`}
              >
                {/* Glow effect */}
                <div
                  className={`absolute inset-0 bg-gradient-to-b ${glowGradient} to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none`}
                />

                <div>
                  {/* Top Bar: Nom & Statut */}
                  <div className="flex items-start justify-between mb-4">
                    <div>
                      <div className="flex items-center space-x-2">
                        <h3 className="text-base font-bold text-white group-hover:text-sky-400 transition-colors">
                          {env.display_name}
                        </h3>
                      </div>
                      <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold block mt-0.5 font-mono">
                        Module : {env.module}
                      </span>
                    </div>

                    <span
                      className={`inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
                        isActive
                          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                          : isError
                          ? "bg-rose-500/10 text-rose-400 border-rose-500/20"
                          : "bg-amber-500/10 text-amber-400 border-amber-500/20"
                      }`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          isActive
                            ? "bg-emerald-400 animate-pulse"
                            : isError
                            ? "bg-rose-400"
                            : "bg-amber-400"
                        }`}
                      />
                      <span>{isActive ? "Actif" : isError ? "Erreur" : "En veille"}</span>
                    </span>
                  </div>

                  {/* BLOC CLIENT ASSOCIÉ (Mise en avant) */}
                  <div className="p-3 rounded-2xl bg-slate-950/80 border border-slate-800/80 mb-4 group-hover:border-slate-700/80 transition-colors">
                    <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider flex items-center justify-between">
                      <span>Client Associé</span>
                      {isSystem ? (
                        <span className="px-1.5 py-0.2 rounded text-[9px] font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                          Infrastructure
                        </span>
                      ) : (
                        <span className="px-1.5 py-0.2 rounded text-[9px] font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20">
                          Client Déployé
                        </span>
                      )}
                    </div>

                    <div className="flex items-center justify-between mt-2">
                      <div className="flex items-center space-x-2.5 truncate">
                        <div
                          className={`w-8 h-8 rounded-xl flex items-center justify-center font-bold text-xs shrink-0 ${
                            isSystem
                              ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                              : "bg-sky-500/20 text-sky-300 border border-sky-500/30"
                          }`}
                        >
                          {isSystem ? <ShieldCheck className="w-4 h-4" /> : <Building2 className="w-4 h-4" />}
                        </div>
                        <div className="truncate">
                          <div className="text-sm font-bold text-white truncate">
                            {env.tenant?.name || "Client non renseigné"}
                          </div>
                          <div className="text-[11px] text-slate-400 font-mono truncate">
                            {env.tenant?.slug || "system"}
                          </div>
                        </div>
                      </div>
                      {!isSystem && onSelectTenant && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            const matched = tenants.find(
                              (t) => t.id === env.tenant?.id || t.slug === env.tenant?.slug
                            );
                            if (matched) {
                              onSelectTenant(matched);
                            }
                          }}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-sky-300 hover:bg-sky-500/10 transition-all cursor-pointer shrink-0"
                          title="Accéder à la fiche client"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Données Techniques Conteneur */}
                  <div className="space-y-2 text-xs text-slate-400 border-t border-slate-800/80 pt-3">
                    <div className="flex items-center justify-between">
                      <span className="text-slate-500">Conteneur Docker</span>
                      <span className="font-mono text-slate-300 text-[11px] truncate max-w-[150px]">
                        {env.container_id || "n/a"}
                      </span>
                    </div>

                    <div className="flex items-center justify-between">
                      <span className="text-slate-500">Hôte / IP Serveur</span>
                      <span className="font-mono text-slate-300">{env.server_ip}</span>
                    </div>

                    {/* Signes Vitaux (CPU / RAM) */}
                    <div className="pt-2 border-t border-slate-800/60 space-y-2">
                      <div>
                        <div className="flex justify-between text-[11px] mb-1">
                          <span className="text-slate-500 flex items-center space-x-1">
                            <Cpu className="w-3 h-3" />
                            <span>Charge CPU</span>
                          </span>
                          <span className="font-mono font-bold text-slate-300">
                            {env.vitals.cpu_percent.toFixed(2)} %
                          </span>
                        </div>
                        <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${
                              env.vitals.cpu_percent > 80
                                ? "bg-rose-500"
                                : env.vitals.cpu_percent > 40
                                ? "bg-amber-500"
                                : "bg-sky-500"
                            }`}
                            style={{ width: `${Math.min(env.vitals.cpu_percent, 100)}%` }}
                          />
                        </div>
                      </div>

                      <div>
                        <div className="flex justify-between text-[11px] mb-1">
                          <span className="text-slate-500 flex items-center space-x-1">
                            <Server className="w-3 h-3" />
                            <span>Mémoire RAM</span>
                          </span>
                          <span className="font-mono font-bold text-slate-300">
                            {env.vitals.memory_usage_mb.toFixed(0)} MB ({env.vitals.memory_percent.toFixed(1)}%)
                          </span>
                        </div>
                        <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-emerald-500 rounded-full transition-all"
                            style={{ width: `${Math.min(env.vitals.memory_percent, 100)}%` }}
                          />
                        </div>
                      </div>
                    </div>

                    {/* Télémétrie Tokens / Coût */}
                    <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between">
                      <span className="text-slate-500">Tokens / Dépense</span>
                      <span className="font-semibold text-slate-200">
                        {formatTokens(env.total_tokens)} •{" "}
                        <span className="text-amber-400 font-bold">{env.cost_usd.toFixed(2)} $</span>
                      </span>
                    </div>
                  </div>
                </div>

                {/* Footer Carte */}
                <div className="mt-4 pt-3 border-t border-slate-800/60 flex items-center justify-between text-[11px] text-slate-500">
                  <div className="flex items-center space-x-1">
                    <Clock className="w-3.5 h-3.5" />
                    <span>Vu : {env.last_seen_at ? new Date(env.last_seen_at).toLocaleTimeString("fr-FR") : "n/a"}</span>
                  </div>
                  <span className="text-sky-400 group-hover:translate-x-0.5 transition-transform font-medium flex items-center space-x-0.5">
                    <span>Inspecter</span>
                    <ExternalLink className="w-3 h-3" />
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* MODALE DÉTAILLÉE DE TÉLÉMÉTRIE (Inspirée du commit abe482d) */}
      {selectedEnv && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm overflow-y-auto">
          <div className="relative w-full max-w-3xl bg-slate-900 border border-slate-800 rounded-3xl shadow-2xl overflow-hidden my-8">
            {/* Header Modal */}
            <div className="flex items-center justify-between p-6 border-b border-slate-800 bg-slate-950/60">
              <div className="flex items-center space-x-3">
                <div className="w-10 h-10 rounded-2xl bg-sky-500/10 border border-sky-500/20 text-sky-400 flex items-center justify-center font-bold">
                  <Activity className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <h2 className="text-lg font-bold text-white">{selectedEnv.display_name}</h2>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
                      {selectedEnv.module}
                    </span>
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5">
                    Conteneur : <span className="font-mono text-slate-300">{selectedEnv.container_id}</span> • IP :{" "}
                    <span className="font-mono text-slate-300">{selectedEnv.server_ip}</span>
                  </div>
                </div>
              </div>

              <button
                onClick={handleCloseModal}
                className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-xl transition-all cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Corps de la modale */}
            <div className="p-6 space-y-6 max-h-[75vh] overflow-y-auto">
              {/* Client associé & KPIs immédiats */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="p-4 rounded-2xl bg-slate-950/60 border border-slate-800">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">
                      Client Associé
                    </span>
                    {!selectedEnv.tenant?.is_system && onSelectTenant && (
                      <button
                        type="button"
                        onClick={() => {
                          const matched = tenants.find(
                            (t) =>
                              t.id === selectedEnv.tenant?.id ||
                              t.slug === selectedEnv.tenant?.slug
                          );
                          if (matched) {
                            handleCloseModal();
                            onSelectTenant(matched);
                          }
                        }}
                        className="text-[11px] text-sky-400 hover:text-sky-300 flex items-center space-x-1 font-medium cursor-pointer"
                        title="Accéder à la fiche client"
                      >
                        <ExternalLink className="w-3 h-3" />
                        <span>Fiche</span>
                      </button>
                    )}
                  </div>
                  <div className="text-base font-bold text-white mt-1">
                    {selectedEnv.tenant?.name || "Plateforme Système"}
                  </div>
                  <div className="text-xs text-slate-500 font-mono mt-0.5">
                    {selectedEnv.tenant?.slug || "system"}
                  </div>
                </div>

                <div className="p-4 rounded-2xl bg-slate-950/60 border border-slate-800">
                  <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">
                    Tokens (In / Out)
                  </span>
                  <div className="text-base font-bold text-white mt-1">
                    {formatNumber(selectedEnv.total_tokens)}
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5 flex space-x-2 font-mono">
                    <span className="text-blue-400">In: {formatNumber(selectedEnv.input_tokens)}</span>
                    <span className="text-emerald-400">Out: {formatNumber(selectedEnv.output_tokens)}</span>
                  </div>
                </div>

                <div className="p-4 rounded-2xl bg-slate-950/60 border border-slate-800">
                  <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">
                    Coût Estimé & Appels
                  </span>
                  <div className="text-base font-bold text-amber-400 mt-1">
                    {selectedEnv.cost_usd.toFixed(4)} $
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5 font-mono">
                    {formatNumber(selectedEnv.api_calls)} requêtes API
                  </div>
                </div>
              </div>

              {/* Alertes Actives de l'Environnement */}
              {envAlerts.length > 0 && (
                <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 space-y-2">
                  <div className="flex items-center space-x-2 text-rose-400 text-xs font-bold uppercase tracking-wider">
                    <AlertTriangle className="w-4 h-4" />
                    <span>Alertes Télémétriques Actives ({envAlerts.length})</span>
                  </div>
                  <div className="space-y-1.5 mt-2">
                    {envAlerts.map((al) => (
                      <div
                        key={al.id}
                        className="flex items-start justify-between text-xs bg-slate-950/80 p-2.5 rounded-xl border border-rose-500/30"
                      >
                        <div className="space-y-0.5">
                          <span className="font-semibold text-rose-300">[{al.level}]</span>{" "}
                          <span className="text-white">{al.message}</span>
                          <div className="text-[10px] text-slate-500 font-mono">
                            Détecté le : {new Date(al.detected_at).toLocaleString("fr-FR")}
                          </div>
                        </div>
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40">
                          {al.category}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Tableau Historique Paginé des Snapshots */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-sm font-bold text-white flex items-center space-x-2">
                    <Clock className="w-4 h-4 text-sky-400" />
                    <span>Historique des Snapshots de Télémétrie</span>
                  </h4>
                  <span className="text-xs text-slate-400 font-mono">
                    Page {modalPage} sur {totalPages} ({totalSnapshots} enregistrés)
                  </span>
                </div>

                <div className="bg-slate-950 rounded-2xl border border-slate-800 overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-800 bg-slate-900/60 text-slate-400 uppercase tracking-wider font-semibold">
                        <th className="py-2.5 px-4">Horodatage</th>
                        <th className="py-2.5 px-4 text-right">Appels API</th>
                        <th className="py-2.5 px-4 text-right text-blue-400">Tokens In</th>
                        <th className="py-2.5 px-4 text-right text-emerald-400">Tokens Out</th>
                        <th className="py-2.5 px-4 text-right text-amber-400">Coût ($)</th>
                        <th className="py-2.5 px-4 text-center">État</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono">
                      {loadingModal ? (
                        <tr>
                          <td colSpan={6} className="py-8 text-center text-slate-400 font-sans">
                            <div className="flex items-center justify-center space-x-2">
                              <Loader2 className="w-4 h-4 animate-spin text-sky-400" />
                              <span>Chargement des métriques...</span>
                            </div>
                          </td>
                        </tr>
                      ) : paginatedSnapshots.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="py-6 text-center text-slate-500 font-sans">
                            Aucun snapshot d'activité enregistré pour cet environnement.
                          </td>
                        </tr>
                      ) : (
                        paginatedSnapshots.map((s) => (
                          <tr key={s.id} className="hover:bg-slate-900/40 transition-colors">
                            <td className="py-2.5 px-4 text-slate-300 font-sans">
                              {new Date(s.snapshot_at).toLocaleString("fr-FR")}
                            </td>
                            <td className="py-2.5 px-4 text-right text-white font-bold">
                              {formatNumber(s.api_calls)}
                            </td>
                            <td className="py-2.5 px-4 text-right text-blue-300">
                              {formatNumber(s.input_tokens)}
                            </td>
                            <td className="py-2.5 px-4 text-right text-emerald-300">
                              {formatNumber(s.output_tokens)}
                            </td>
                            <td className="py-2.5 px-4 text-right text-amber-300 font-bold">
                              {s.cost_usd.toFixed(4)} $
                            </td>
                            <td className="py-2.5 px-4 text-center font-sans">
                              <span
                                className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                                  s.status === "active"
                                    ? "bg-emerald-500/10 text-emerald-400"
                                    : "bg-slate-800 text-slate-400"
                                }`}
                              >
                                {s.status}
                              </span>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Pagination Controls */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between mt-3 px-1 text-xs">
                    <button
                      onClick={() => setModalPage((p) => Math.max(p - 1, 1))}
                      disabled={modalPage === 1}
                      className="px-3 py-1.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-400 hover:text-white disabled:opacity-40 transition-all flex items-center space-x-1 cursor-pointer"
                    >
                      <ChevronLeft className="w-3.5 h-3.5" />
                      <span>Précédent</span>
                    </button>

                    <span className="text-slate-500">
                      Affichage de {(modalPage - 1) * modalPageLimit + 1} à{" "}
                      {Math.min(modalPage * modalPageLimit, totalSnapshots)} sur {totalSnapshots}
                    </span>

                    <button
                      onClick={() => setModalPage((p) => Math.min(p + 1, totalPages))}
                      disabled={modalPage === totalPages}
                      className="px-3 py-1.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-400 hover:text-white disabled:opacity-40 transition-all flex items-center space-x-1 cursor-pointer"
                    >
                      <span>Suivant</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Footer Modal */}
            <div className="p-4 px-6 border-t border-slate-800 bg-slate-950/60 flex items-center justify-end">
              <button
                onClick={handleCloseModal}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl text-xs font-bold transition-all cursor-pointer"
              >
                Fermer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
