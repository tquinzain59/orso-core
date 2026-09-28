import React, { useState } from "react";
import {
  X,
  CheckCircle,
  Copy,
  Bot,
  FileText,
  Code,
  Play,
  Check,
  Building2,
  MapPin,
  Mail,
  Phone,
  User,
  CreditCard,
} from "lucide-react";
import { Tenant } from "../types";
import { getAgentMeta } from "../data";

interface OnboardingDetailModalProps {
  tenant: Tenant | null;
  onClose: () => void;
  onProvision: (tenantId: string) => Promise<void>;
}

export const OnboardingDetailModal: React.FC<OnboardingDetailModalProps> = ({
  tenant,
  onClose,
  onProvision,
}) => {
  if (!tenant) return null;

  const [activeTab, setActiveTab] = useState<"calibration" | "legal" | "artefacts">("calibration");
  const [selectedAgentSlug, setSelectedAgentSlug] = useState<string>(
    tenant.agent_instances?.[0]?.agent_slug || "jerome"
  );
  const [copiedSoul, setCopiedSoul] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const [provisioning, setProvisioning] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const agentInstances = tenant.agent_instances || [];
  const currentAgent = agentInstances.find((a) => a.agent_slug === selectedAgentSlug) || agentInstances[0];

  const handleCopy = (text: string, type: "soul" | "json") => {
    navigator.clipboard.writeText(text);
    if (type === "soul") {
      setCopiedSoul(true);
      setTimeout(() => setCopiedSoul(false), 2000);
    } else {
      setCopiedJson(true);
      setTimeout(() => setCopiedJson(false), 2000);
    }
  };

  const handleProvision = async () => {
    setProvisioning(true);
    try {
      await onProvision(tenant.id);
      setToastMessage("Instance et agents activés avec succès !");
      setTimeout(() => {
        setToastMessage(null);
      }, 3000);
    } catch (e: any) {
      alert("Erreur lors de l'activation : " + (e.message || "Échec"));
    } finally {
      setProvisioning(false);
    }
  };

  const isPending = agentInstances.some((a) => a.provisioning_status === "PENDING_SETUP") || tenant.instance?.status === "provisioning";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/85 backdrop-blur-md overflow-y-auto">
      <div className="relative w-full max-w-5xl bg-slate-900 border border-slate-800 rounded-3xl shadow-2xl overflow-hidden my-6">
        {/* Header Modal */}
        <div className="flex items-center justify-between p-6 border-b border-slate-800 bg-slate-950/70">
          <div>
            <div className="flex items-center space-x-3">
              <h2 className="text-xl font-bold text-white tracking-tight">{tenant.name}</h2>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/30">
                {tenant.slug}
              </span>
              <span
                className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${
                  isPending
                    ? "bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse"
                    : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                }`}
              >
                {isPending ? "PENDING_SETUP (En attente)" : "ACTIVE (En service)"}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Commande d'onboarding • Inscrit le {new Date(tenant.created_at).toLocaleDateString("fr-FR")} à {new Date(tenant.created_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
            </p>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 border border-transparent hover:border-slate-700 transition-all cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Navigation Onglets de la modale */}
        <div className="flex items-center space-x-2 px-6 pt-4 border-b border-slate-800 bg-slate-950/30">
          <button
            onClick={() => setActiveTab("calibration")}
            className={`flex items-center space-x-2 px-4 py-2.5 border-b-2 text-sm font-semibold transition-all cursor-pointer ${
              activeTab === "calibration"
                ? "border-sky-400 text-sky-400"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Bot className="w-4 h-4" />
            <span>Lettres de Mission & Calibration ({agentInstances.length})</span>
          </button>

          <button
            onClick={() => setActiveTab("legal")}
            className={`flex items-center space-x-2 px-4 py-2.5 border-b-2 text-sm font-semibold transition-all cursor-pointer ${
              activeTab === "legal"
                ? "border-sky-400 text-sky-400"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Building2 className="w-4 h-4" />
            <span>Identité Juridique, BAN & Contact</span>
          </button>

          <button
            onClick={() => setActiveTab("artefacts")}
            className={`flex items-center space-x-2 px-4 py-2.5 border-b-2 text-sm font-semibold transition-all cursor-pointer ${
              activeTab === "artefacts"
                ? "border-sky-400 text-sky-400"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <FileText className="w-4 h-4" />
            <span>Artefacts (soul.md & config.json)</span>
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-6 max-h-[72vh] overflow-y-auto">
          {toastMessage && (
            <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 rounded-xl text-sm font-medium flex items-center space-x-2">
              <CheckCircle className="w-4 h-4" />
              <span>{toastMessage}</span>
            </div>
          )}

          {/* ── ONGLET 1 : CALIBRATION DES AGENTS ── */}
          {activeTab === "calibration" && (
            <div className="space-y-6">
              {/* Sélecteur d'agent souscrit */}
              {agentInstances.length > 0 ? (
                <div className="flex items-center space-x-3 overflow-x-auto pb-2 border-b border-slate-800">
                  {agentInstances.map((ai) => {
                    const catalog = getAgentMeta(ai.agent_slug);
                    const isSelected = selectedAgentSlug === ai.agent_slug;
                    return (
                      <button
                        key={ai.id || ai.agent_slug}
                        onClick={() => setSelectedAgentSlug(ai.agent_slug)}
                        className={`flex items-center space-x-2.5 px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                          isSelected
                            ? "bg-sky-500/20 text-sky-300 border border-sky-500/40 shadow-sm"
                            : "bg-slate-950/60 text-slate-400 hover:text-white border border-slate-800"
                        }`}
                      >
                        <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse"></span>
                        <span>{ai.alias_name || catalog?.name || ai.agent_slug}</span>
                        <span className="text-[10px] text-slate-400 font-mono">({ai.agent_type})</span>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="p-4 bg-slate-950 rounded-2xl border border-slate-800 text-slate-400 text-sm">
                  Aucune instance d'agent enregistrée pour cette organisation.
                </div>
              )}

              {currentAgent && (
                <div className="space-y-6">
                  {/* Fiche de synthèse de l'agent sélectionné */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-950/80 p-4 rounded-2xl border border-slate-800">
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Tempérament</span>
                      <div className="text-sm font-bold text-white mt-0.5">{currentAgent.tone || "DIPLOMATIC"}</div>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Autonomie</span>
                      <div className="text-sm font-bold text-sky-400 mt-0.5">{currentAgent.autonomy_mode || "SEMI_AUTONOMOUS"}</div>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Seuil Escalade</span>
                      <div className="text-sm font-bold text-amber-400 mt-0.5">{currentAgent.escalation_threshold_eur ? `${currentAgent.escalation_threshold_eur} €` : "Non défini"}</div>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Outil Connecté</span>
                      <div className="text-sm font-bold text-indigo-400 mt-0.5">{currentAgent.integration_tool || "Aucun"}</div>
                    </div>
                  </div>

                  {/* Lettre de Mission Complète en 4 volets */}
                  <div className="p-5 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold uppercase tracking-wider text-sky-400 flex items-center space-x-2">
                        <FileText className="w-4 h-4" />
                        <span>Lettre de Mission Opérationnelle Souveraine</span>
                      </span>
                      <button
                        onClick={() => handleCopy(currentAgent.mission_letter || "", "soul")}
                        className="text-xs text-slate-400 hover:text-white flex items-center space-x-1 cursor-pointer"
                      >
                        {copiedSoul ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                        <span>{copiedSoul ? "Copié" : "Copier"}</span>
                      </button>
                    </div>

                    <div className="bg-slate-900/90 rounded-xl p-4 border border-slate-800/80 text-sm text-slate-200 leading-relaxed font-sans whitespace-pre-wrap">
                      {currentAgent.mission_letter || "Aucune lettre de mission rédigée."}
                    </div>
                  </div>

                  {/* Configuration spécifique JSON */}
                  {currentAgent.specific_config && Object.keys(currentAgent.specific_config).length > 0 && (
                    <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-2">
                      <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center space-x-2">
                        <Code className="w-4 h-4 text-purple-400" />
                        <span>Paramètres Fins & Clés Métier (specific_config)</span>
                      </span>
                      <pre className="p-3 bg-slate-900 rounded-xl border border-slate-800 text-xs font-mono text-emerald-400 overflow-x-auto">
                        {JSON.stringify(currentAgent.specific_config, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── ONGLET 2 : JURIDIQUE, BAN & CONTACT ── */}
          {activeTab === "legal" && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Entreprise & BAN */}
              <div className="p-5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-4">
                <span className="text-xs font-bold uppercase tracking-wider text-sky-400 flex items-center space-x-2">
                  <Building2 className="w-4 h-4" />
                  <span>Identité Juridique Certifiée</span>
                </span>

                <div className="space-y-2.5 text-sm">
                  <div className="flex justify-between py-1 border-b border-slate-800/60">
                    <span className="text-slate-400">Raison Sociale :</span>
                    <span className="font-bold text-white">{tenant.name}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-slate-800/60">
                    <span className="text-slate-400">Forme Juridique :</span>
                    <span className="text-slate-200 font-mono">{tenant.legal_form || "SAS"}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-slate-800/60">
                    <span className="text-slate-400">Numéro SIRET :</span>
                    <span className="text-slate-200 font-mono font-bold">{tenant.siret || "Non renseigné"}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-slate-800/60">
                    <span className="text-slate-400">Numéro SIREN :</span>
                    <span className="text-slate-200 font-mono">{tenant.siren || (tenant.siret ? tenant.siret.substring(0, 9) : "Non renseigné")}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-slate-800/60">
                    <span className="text-slate-400">TVA Intracommunautaire :</span>
                    <span className="text-slate-200 font-mono">{tenant.vat_number || "Calculée automatiquement"}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-slate-800/60">
                    <span className="text-slate-400">Secteur d'activité :</span>
                    <span className="text-slate-200">{tenant.sector || "Non spécifié"}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-slate-800/60">
                    <span className="text-slate-400">Tranche d'effectif :</span>
                    <span className="text-slate-200">{tenant.employee_count_range || "Non renseignée"}</span>
                  </div>
                  <div className="pt-2">
                    <span className="text-xs font-semibold uppercase text-slate-400 flex items-center space-x-1.5 mb-1">
                      <MapPin className="w-3.5 h-3.5 text-rose-400" />
                      <span>Adresse Normalisée BAN</span>
                    </span>
                    <div className="text-slate-300 text-xs font-mono bg-slate-900 p-2.5 rounded-xl border border-slate-800">
                      {tenant.address_line1 || "Adresse non renseignée"}<br />
                      {tenant.postal_code} {tenant.city}
                    </div>
                  </div>
                </div>
              </div>

              {/* Contact Administrateur & Abonnement */}
              <div className="space-y-6">
                <div className="p-5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-3">
                  <span className="text-xs font-bold uppercase tracking-wider text-sky-400 flex items-center space-x-2">
                    <User className="w-4 h-4" />
                    <span>Contact Administrateur (Directeur / DAF)</span>
                  </span>

                  <div className="space-y-2 text-sm">
                    <div className="font-bold text-white text-base">{tenant.contact.full_name}</div>
                    <div className="flex items-center space-x-2 text-xs text-slate-300">
                      <Mail className="w-3.5 h-3.5 text-slate-400" />
                      <span>{tenant.contact.email}</span>
                    </div>
                    <div className="flex items-center space-x-2 text-xs text-slate-300">
                      <Phone className="w-3.5 h-3.5 text-slate-400" />
                      <span>{tenant.contact.phone || "Téléphone non renseigné"}</span>
                    </div>
                    <div className="text-xs text-slate-400 pt-1">
                      Rôle déclaré : <span className="text-sky-300 font-semibold">{tenant.contact.role || "Dirigeant"}</span>
                    </div>
                  </div>
                </div>

                <div className="p-5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-3">
                  <span className="text-xs font-bold uppercase tracking-wider text-emerald-400 flex items-center space-x-2">
                    <CreditCard className="w-4 h-4" />
                    <span>Abonnement Souscrit (Essai 30 Jours)</span>
                  </span>

                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">Forfait :</span>
                      <span className="font-bold text-white">{tenant.subscription?.tier_label || "Duo (2 agents)"}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">Tarif mensuel HT :</span>
                      <span className="font-bold text-emerald-400">{tenant.subscription?.price_ht} € HT / mois</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">Statut d'essai :</span>
                      <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400">
                        {tenant.subscription?.status === "trialing" ? "1er mois offert (30 jours)" : tenant.subscription?.status}
                      </span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">Moyen de paiement :</span>
                      <span className="text-slate-200">{tenant.subscription?.payment_method || "Carte bancaire"}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── ONGLET 3 : ARTEFACTS TÉLÉCHARGEABLES (SOUL.MD & CONFIG.JSON) ── */}
          {activeTab === "artefacts" && (
            <div className="space-y-6">
              {/* Soul.md */}
              <div className="p-5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-sky-400 flex items-center space-x-2">
                    <FileText className="w-4 h-4" />
                    <span>Manifeste Système Markdown (soul.md)</span>
                  </span>
                  <button
                    onClick={() => handleCopy(currentAgent?.soul_md_content || "", "soul")}
                    className="text-xs text-slate-400 hover:text-white flex items-center space-x-1 cursor-pointer"
                  >
                    {copiedSoul ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedSoul ? "Copié !" : "Copier soul.md"}</span>
                  </button>
                </div>
                <pre className="p-4 bg-slate-900 rounded-xl border border-slate-800 text-xs font-mono text-slate-300 max-h-56 overflow-y-auto whitespace-pre-wrap">
                  {currentAgent?.soul_md_content || "# Aucun contenu soul.md disponible"}
                </pre>
              </div>

              {/* Config.json */}
              <div className="p-5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-purple-400 flex items-center space-x-2">
                    <Code className="w-4 h-4" />
                    <span>Configuration Machine-Readable (agent-config.json)</span>
                  </span>
                  <button
                    onClick={() => handleCopy(JSON.stringify(currentAgent?.config_json || {}, null, 2), "json")}
                    className="text-xs text-slate-400 hover:text-white flex items-center space-x-1 cursor-pointer"
                  >
                    {copiedJson ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedJson ? "Copié !" : "Copier config.json"}</span>
                  </button>
                </div>
                <pre className="p-4 bg-slate-900 rounded-xl border border-slate-800 text-xs font-mono text-purple-300 max-h-56 overflow-y-auto">
                  {JSON.stringify(currentAgent?.config_json || {}, null, 2)}
                </pre>
              </div>
            </div>
          )}

          {/* Section d'action infrastructure & provisionnement */}
          <div className="p-5 rounded-2xl bg-gradient-to-r from-slate-950 via-slate-900 to-slate-950 border border-sky-500/20 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div>
              <div className="flex items-center space-x-2">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Routage Docker :</span>
                <span className="font-mono text-xs text-sky-400 font-bold bg-sky-500/10 px-2.5 py-1 rounded-lg border border-sky-500/30">
                  {tenant.instance?.internal_route_key || `orso_backend_${tenant.slug}`}
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-1">
                La validation du déploiement bascule les agents en statut ACTIVE et rend l'espace client opérationnel.
              </p>
            </div>

            <button
              onClick={handleProvision}
              disabled={provisioning || !isPending}
              className={`py-2.5 px-6 rounded-xl text-xs font-bold flex items-center space-x-2 transition-all cursor-pointer ${
                isPending
                  ? "bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white shadow-lg shadow-sky-500/20"
                  : "bg-slate-800 text-slate-500 cursor-not-allowed"
              }`}
            >
              <Play className="w-4 h-4" />
              <span>{provisioning ? "Activation en cours..." : isPending ? "Valider le Déploiement & Passer en Service" : "Déjà Déployé & Actif"}</span>
            </button>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 bg-slate-950/80 border-t border-slate-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-white bg-slate-900 hover:bg-slate-800 border border-slate-700 cursor-pointer transition-all"
          >
            Fermer
          </button>
        </div>
      </div>
    </div>
  );
};
