import React, { useState } from "react";
import {
  Sparkles,
  Server,
  Cpu,
  Database,
  ExternalLink,
  Copy,
  Check,
  Search,
  Bot,
  Play,
  Clock,
  MapPin,
  Mail,
  Phone,
  RefreshCw,
  Key,
  ShieldCheck,
  AlertTriangle,
} from "lucide-react";
import { Tenant, OVHSizingRecommendation, OVHStatusResponse } from "../types";
import { getAgentMeta } from "../data";
import { requestOVHCredential } from "../api";

interface OnboardingViewProps {
  tenants: Tenant[];
  ovhSizing: OVHSizingRecommendation | null;
  ovhStatus?: OVHStatusResponse | null;
  onSelectTenant: (t: Tenant) => void;
  onProvisionTenant: (tenantId: string) => Promise<void>;
  onRefresh: () => void;
}

export const OnboardingView: React.FC<OnboardingViewProps> = ({
  tenants,
  ovhSizing,
  ovhStatus,
  onSelectTenant,
  onProvisionTenant,
  onRefresh,
}) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<"pending" | "active" | "all">("pending");
  const [copiedSnippet, setCopiedSnippet] = useState<string | null>(null);
  const [requestingKey, setRequestingKey] = useState(false);
  const [credentialResult, setCredentialResult] = useState<{
    consumer_key: string;
    validation_url: string;
  } | null>(null);

  const handleRequestKey = async () => {
    setRequestingKey(true);
    try {
      const res = await requestOVHCredential();
      setCredentialResult(res);
    } catch (err: any) {
      alert(err.message || "Erreur lors de la demande de clé");
    } finally {
      setRequestingKey(false);
    }
  };

  // Filtrage des clients onboarding (clients ayant des agent_instances ou en trial)
  const onboardingTenants = tenants.filter((t) => {
    return (t.agent_instances && t.agent_instances.length > 0) || t.status === "trial";
  });

  const filteredTenants = onboardingTenants.filter((t) => {
    const isPending =
      t.agent_instances?.some((a) => a.provisioning_status === "PENDING_SETUP") ||
      t.instance?.status === "provisioning" ||
      t.instance?.status === "not_provisioned";

    if (statusFilter === "pending" && !isPending) return false;
    if (statusFilter === "active" && isPending) return false;

    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return (
      t.name.toLowerCase().includes(term) ||
      t.slug.toLowerCase().includes(term) ||
      (t.siret && t.siret.includes(term)) ||
      (t.city && t.city.toLowerCase().includes(term)) ||
      t.contact.full_name.toLowerCase().includes(term) ||
      t.contact.email.toLowerCase().includes(term)
    );
  });

  const pendingCount = onboardingTenants.filter(
    (t) =>
      t.agent_instances?.some((a) => a.provisioning_status === "PENDING_SETUP") ||
      t.instance?.status === "provisioning"
  ).length;

  const handleCopy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSnippet(label);
    setTimeout(() => setCopiedSnippet(null), 2500);
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-2xl font-bold text-white tracking-tight">Arrivées Onboarding & Flotte OVH</h1>
            {pendingCount > 0 && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse">
                {pendingCount} en attente
              </span>
            )}
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Consultez les calibrations IA des nouveaux clients déposées via le tunnel web et dimensionnez les instances OVH.
          </p>
        </div>

        <button
          onClick={onRefresh}
          className="p-2.5 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800 transition-all flex items-center space-x-2 text-xs font-semibold cursor-pointer self-start sm:self-auto"
        >
          <RefreshCw className="w-4 h-4" />
          <span>Actualiser</span>
        </button>
      </div>

      {/* ── SECTION 1 : ASSISTANT DE DIMENSIONNEMENT & COMMANDE OVH ── */}
      <div className="rounded-3xl bg-slate-900 border border-slate-800 p-6 shadow-xl relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-gradient-to-bl from-sky-500/10 via-indigo-500/5 to-transparent rounded-full blur-3xl pointer-events-none"></div>

        <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6 pb-6 border-b border-slate-800">
          <div>
            <span className="text-xs font-bold uppercase tracking-wider text-sky-400 flex items-center space-x-2">
              <Server className="w-4 h-4" />
              <span>Dimensionnement Infrastructure OVHcloud</span>
            </span>
            <h2 className="text-lg font-bold text-white mt-1">
              Capacité du Cluster & Recommandation d'Instance
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Calcul prévisionnel des besoins d'hébergement calculé selon le nombre d'agents actifs souscrits.
            </p>
          </div>

          <div className="flex items-center space-x-3">
            <a
              href={ovhSizing?.ovh_console_url || "https://www.ovh.com/manager/#/public-cloud"}
              target="_blank"
              rel="noreferrer"
              className="py-2.5 px-4 rounded-xl text-xs font-bold bg-sky-500/20 hover:bg-sky-500/30 text-sky-300 border border-sky-500/30 flex items-center space-x-2 transition-all cursor-pointer shadow-sm"
            >
              <span>Accéder à OVH Public Cloud</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>

        {/* Statut de Connexion API OVH */}
        {ovhStatus?.configured ? (
          ovhStatus.has_wildcard_rights ? (
            <div className="mt-4 p-3.5 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <ShieldCheck className="w-5 h-5 text-emerald-400 shrink-0" />
                <div>
                  <div className="text-xs font-bold text-emerald-300">
                    Connexion API OVH Active & Autorisée (Droits complets /*)
                  </div>
                  <div className="text-[11px] text-emerald-400/80">
                    Application ORSO-AGENTS validée — Prêt pour le pilotage autonome d'instances et de VPS.
                  </div>
                </div>
              </div>
              <div className="flex items-center space-x-2 text-xs font-mono text-emerald-300">
                {ovhStatus.cloud_projects && ovhStatus.cloud_projects.length > 0 && (
                  <span className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-500/30">
                    {ovhStatus.cloud_projects.length} projet(s) cloud
                  </span>
                )}
              </div>
            </div>
          ) : (
            <div className="mt-4 p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30 space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-start space-x-3">
                  <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                  <div>
                    <div className="text-xs font-bold text-amber-300">
                      Clés API OVH Détectées (ORSO-AGENTS) — Droits restreints au chemin racine
                    </div>
                    <p className="text-[11px] text-slate-300 mt-0.5">
                      La Consumer Key actuelle a été créée avec <code className="text-amber-300 font-mono">path=""</code>.
                      Pour permettre le provisionnement autonome (gestion Cloud & VPS),
                      l'API requiert une permission sur <code className="text-amber-300 font-mono">/*</code>.
                    </p>
                  </div>
                </div>

                {!credentialResult && (
                  <button
                    onClick={handleRequestKey}
                    disabled={requestingKey}
                    className="px-3.5 py-2 rounded-xl text-xs font-bold bg-amber-500 hover:bg-amber-400 text-slate-950 flex items-center space-x-1.5 transition-all cursor-pointer shrink-0 shadow-md self-start sm:self-auto"
                  >
                    <Key className="w-3.5 h-3.5" />
                    <span>{requestingKey ? "Génération..." : "Activer Droits /* (1 clic)"}</span>
                  </button>
                )}
              </div>

              {credentialResult && (
                <div className="p-3.5 rounded-xl bg-slate-950/80 border border-amber-500/40 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-white">Lien d'activation OVH généré :</span>
                    <a
                      href={credentialResult.validation_url}
                      target="_blank"
                      rel="noreferrer"
                      className="px-3 py-1 rounded-lg text-xs font-bold bg-sky-500 hover:bg-sky-400 text-white flex items-center space-x-1 transition-all"
                    >
                      <span>Valider sur OVH</span>
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  </div>
                  <div className="text-[11px] text-slate-400 font-mono break-all">
                    Nouvelle Consumer Key à renseigner dans <span className="text-sky-300">.env</span> : <strong className="text-amber-300">{credentialResult.consumer_key}</strong>
                  </div>
                </div>
              )}
            </div>
          )
        ) : (
          <div className="mt-4 p-3 rounded-2xl bg-slate-950/50 border border-slate-800 flex items-center space-x-3 text-xs text-slate-400">
            <Key className="w-4 h-4 text-slate-500" />
            <span>Clés API OVH en attente de configuration (.env). Recommandations calculées sur l'algorithme standard Orso.</span>
          </div>
        )}

        {/* Cartes Métriques Dimensionnement */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
          <div className="p-4 rounded-2xl bg-slate-950/70 border border-slate-800">
            <div className="flex items-center space-x-2 text-slate-400 text-xs font-semibold">
              <Sparkles className="w-3.5 h-3.5 text-amber-400" />
              <span>Nouveaux Clients</span>
            </div>
            <div className="text-2xl font-bold text-white mt-2">
              {ovhSizing?.pending_tenants ?? pendingCount}
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5">En attente de déploiement</div>
          </div>

          <div className="p-4 rounded-2xl bg-slate-950/70 border border-slate-800">
            <div className="flex items-center space-x-2 text-slate-400 text-xs font-semibold">
              <Bot className="w-3.5 h-3.5 text-sky-400" />
              <span>Agents à Instancier</span>
            </div>
            <div className="text-2xl font-bold text-sky-400 mt-2">
              {ovhSizing?.pending_agents ?? 0}
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5">Lettres de mission prêtes</div>
          </div>

          <div className="p-4 rounded-2xl bg-slate-950/70 border border-slate-800">
            <div className="flex items-center space-x-2 text-slate-400 text-xs font-semibold">
              <Database className="w-3.5 h-3.5 text-indigo-400" />
              <span>RAM Requise Estimée</span>
            </div>
            <div className="text-2xl font-bold text-indigo-400 mt-2">
              {ovhSizing ? `${(ovhSizing.ram_mb_estimated / 1024).toFixed(1)} Go` : "1.5 Go"}
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5">1 Go / agent + 512 Mo socle</div>
          </div>

          <div className="p-4 rounded-2xl bg-slate-950/70 border border-slate-800">
            <div className="flex items-center space-x-2 text-slate-400 text-xs font-semibold">
              <Cpu className="w-3.5 h-3.5 text-emerald-400" />
              <span>Gabarit Conseillé</span>
            </div>
            <div className="text-xl font-bold text-emerald-400 mt-2 font-mono">
              {ovhSizing?.flavor_details?.name || "d2-4"}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">
              {ovhSizing?.flavor_details?.price_monthly_eur ? `~${ovhSizing.flavor_details.price_monthly_eur} € / mois` : "12.00 € / mois"}
            </div>
          </div>
        </div>

        {/* Stratégie d'hébergement & Snippets */}
        <div className="mt-6 p-4 rounded-2xl bg-slate-950/50 border border-slate-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className={`w-3 h-3 rounded-full ${ovhSizing?.can_fit_on_current_pool ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`}></div>
            <div>
              <div className="text-xs font-bold text-white">
                {ovhSizing?.can_fit_on_current_pool
                  ? `Hébergement direct possible sur le VPS OVH actuel (${ovhSizing?.current_pool_ip || "92.222.68.80"})`
                  : "Seuil de débordement atteint : commande d'un VPS OVH supplémentaire recommandée"}
              </div>
              <p className="text-[11px] text-slate-400">
                Grâce au Wake-on-Demand, les conteneurs sont placés en veille et ne saturent pas la mémoire vive.
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={() => handleCopy(ovhSizing?.cloud_init_snippet || "", "cloud-init")}
              className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold border border-slate-700 flex items-center space-x-1.5 transition-all cursor-pointer"
            >
              {copiedSnippet === "cloud-init" ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copiedSnippet === "cloud-init" ? "Copié !" : "Script Cloud-Init"}</span>
            </button>

            <button
              onClick={() => handleCopy(ovhSizing?.docker_deploy_snippet || "", "docker")}
              className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold border border-slate-700 flex items-center space-x-1.5 transition-all cursor-pointer"
            >
              {copiedSnippet === "docker" ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copiedSnippet === "docker" ? "Copié !" : "Commande Docker"}</span>
            </button>
          </div>
        </div>
      </div>

      {/* ── SECTION 2 : LISTE DES NOUVEAUX CLIENTS ONBOARDÉS ── */}
      <div className="space-y-4">
        {/* Filtres & Recherche */}
        <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 bg-slate-900/90 border border-slate-800 p-4 rounded-2xl">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Rechercher par entreprise, SIRET, ville BAN ou contact..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-slate-950/80 border border-slate-800 rounded-xl text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-sky-500 transition-all"
            />
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={() => setStatusFilter("pending")}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                statusFilter === "pending"
                  ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                  : "bg-slate-950/60 text-slate-400 hover:text-white border border-slate-800"
              }`}
            >
              En attente ({pendingCount})
            </button>

            <button
              onClick={() => setStatusFilter("active")}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                statusFilter === "active"
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                  : "bg-slate-950/60 text-slate-400 hover:text-white border border-slate-800"
              }`}
            >
              Déployés
            </button>

            <button
              onClick={() => setStatusFilter("all")}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                statusFilter === "all"
                  ? "bg-sky-500/20 text-sky-300 border border-sky-500/40"
                  : "bg-slate-950/60 text-slate-400 hover:text-white border border-slate-800"
              }`}
            >
              Tous ({onboardingTenants.length})
            </button>
          </div>
        </div>

        {/* Liste des cartes d'onboarding */}
        {filteredTenants.length === 0 ? (
          <div className="text-center py-12 bg-slate-900/50 rounded-3xl border border-slate-800 p-8">
            <Clock className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <h3 className="text-lg font-bold text-white">Aucune commande d'onboarding trouvée</h3>
            <p className="text-sm text-slate-400 mt-1 max-w-md mx-auto">
              Tous les clients inscrits sont déjà déployés ou aucun enregistrement ne correspond aux filtres actuels.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {filteredTenants.map((t) => {
              const isPending =
                t.agent_instances?.some((a) => a.provisioning_status === "PENDING_SETUP") ||
                t.instance?.status === "provisioning" ||
                t.instance?.status === "not_provisioned";

              const agentList = t.agent_instances || [];

              return (
                <div
                  key={t.id}
                  className="bg-slate-900 border border-slate-800 hover:border-slate-700/80 rounded-2xl p-5 shadow-lg transition-all"
                >
                  <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                    {/* Colonne 1 : Entreprise, BAN & Contact */}
                    <div className="space-y-1.5">
                      <div className="flex items-center space-x-2.5">
                        <span className="text-lg font-bold text-white tracking-tight">{t.name}</span>
                        <span className="text-xs px-2 py-0.5 rounded-full font-mono bg-slate-800 text-slate-300 border border-slate-700">
                          {t.legal_form || "SAS"}
                        </span>
                        <span className="text-xs px-2 py-0.5 rounded-full font-mono bg-sky-500/10 text-sky-400 border border-sky-500/20">
                          {t.slug}
                        </span>
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full font-bold ${
                            isPending
                              ? "bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse"
                              : "bg-emerald-500/20 text-emerald-400 border border-emerald-500/20"
                          }`}
                        >
                          {isPending ? "À Déployer" : "Actif"}
                        </span>
                      </div>

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
                        <span>SIRET : <strong className="text-slate-300 font-mono">{t.siret || "N/A"}</strong></span>
                        {t.city && (
                          <span className="flex items-center space-x-1">
                            <MapPin className="w-3 h-3 text-rose-400" />
                            <span>{t.postal_code} {t.city}</span>
                          </span>
                        )}
                        <span className="flex items-center space-x-1">
                          <Mail className="w-3 h-3 text-slate-400" />
                          <span>{t.contact.email}</span>
                        </span>
                        {t.contact.phone && (
                          <span className="flex items-center space-x-1">
                            <Phone className="w-3 h-3 text-slate-400" />
                            <span>{t.contact.phone}</span>
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Colonne 2 : Forfait & Agents */}
                    <div className="flex flex-wrap items-center gap-4">
                      {/* Abonnement */}
                      <div className="text-right">
                        <div className="text-xs font-bold text-white">{t.subscription?.tier_label || "1 agent"}</div>
                        <div className="text-xs font-semibold text-emerald-400">{t.subscription?.price_ht} € HT / mois</div>
                        <div className="text-[10px] text-slate-400">Essai 30j • {t.subscription?.payment_method || "Carte"}</div>
                      </div>

                      {/* Agents badges */}
                      <div className="flex items-center space-x-1.5">
                        {agentList.map((ai) => {
                          const catalog = getAgentMeta(ai.agent_slug);
                          const isAgentPending = ai.provisioning_status === "PENDING_SETUP";
                          return (
                            <span
                              key={ai.id || ai.agent_slug}
                              className={`px-2.5 py-1 rounded-xl text-xs font-bold flex items-center space-x-1 border ${
                                isAgentPending
                                  ? "bg-amber-500/10 text-amber-300 border-amber-500/30"
                                  : "bg-sky-500/10 text-sky-300 border-sky-500/30"
                              }`}
                              title={`Calibration : ${ai.tone} / ${ai.autonomy_mode}`}
                            >
                              <span className={`w-1.5 h-1.5 rounded-full ${isAgentPending ? "bg-amber-400 animate-pulse" : "bg-sky-400"}`}></span>
                              <span>{ai.alias_name || catalog?.name || ai.agent_slug}</span>
                            </span>
                          );
                        })}
                      </div>

                      {/* Actions */}
                      <div className="flex items-center space-x-2">
                        <button
                          onClick={() => onSelectTenant(t)}
                          className="py-2 px-3.5 bg-slate-800 hover:bg-slate-700 text-white rounded-xl text-xs font-bold border border-slate-700 transition-all cursor-pointer shadow-sm"
                        >
                          Consulter Calibration
                        </button>

                        {isPending && (
                          <button
                            onClick={() => onProvisionTenant(t.id)}
                            className="py-2 px-3.5 bg-sky-500/20 hover:bg-sky-500/30 text-sky-300 rounded-xl text-xs font-bold border border-sky-500/40 flex items-center space-x-1.5 transition-all cursor-pointer"
                          >
                            <Play className="w-3.5 h-3.5" />
                            <span>Déployer</span>
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
