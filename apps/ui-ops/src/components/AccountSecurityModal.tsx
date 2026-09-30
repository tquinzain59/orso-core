import React, { useState, useEffect } from "react";
import {
  X,
  Shield,
  KeyRound,
  Eye,
  EyeOff,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Clock,
  Terminal,
  History,
  Lock,
} from "lucide-react";
import { AdminUser, AuthAuditEvent } from "../types";
import { changeSuperadminPassword, fetchAuthAuditLog } from "../api";

interface AccountSecurityModalProps {
  isOpen: boolean;
  onClose: () => void;
  adminUser?: AdminUser | null;
  onPasswordChangedSuccessfully: () => void;
}

export const AccountSecurityModal: React.FC<AccountSecurityModalProps> = ({
  isOpen,
  onClose,
  adminUser,
  onPasswordChangedSuccessfully,
}) => {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const [auditEvents, setAuditEvents] = useState<AuthAuditEvent[]>([]);
  const [loadingAudit, setLoadingAudit] = useState(false);
  const [activeTab, setActiveTab] = useState<"form" | "audit" | "emergency">("form");

  useEffect(() => {
    if (isOpen) {
      setError(null);
      setSuccessMsg(null);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      loadAuditLog();
    }
  }, [isOpen]);

  const loadAuditLog = async () => {
    setLoadingAudit(true);
    try {
      const data = await fetchAuthAuditLog();
      setAuditEvents(data.events || []);
    } catch (e) {
      console.warn("Impossible de charger le journal d'audit:", e);
    } finally {
      setLoadingAudit(false);
    }
  };

  if (!isOpen) return null;

  // Validation des critères en temps réel
  const hasMinLength = newPassword.length >= 12;
  const hasUpper = /[A-Z]/.test(newPassword);
  const hasLower = /[a-z]/.test(newPassword);
  const hasDigit = /[0-9]/.test(newPassword);
  const hasSpecial = /[!@#$%^&*()_\-+=\[\]{}<>?,.:;~]/.test(newPassword);
  const notTrivial = !/admin|password|azerty|qwerty|orso|olympe|123456/i.test(newPassword);
  const isDifferentFromCurrent = currentPassword ? newPassword !== currentPassword : true;
  const passwordsMatch = newPassword.length > 0 && newPassword === confirmPassword;

  const isFormValid =
    currentPassword.length > 0 &&
    hasMinLength &&
    hasUpper &&
    hasLower &&
    hasDigit &&
    hasSpecial &&
    notTrivial &&
    isDifferentFromCurrent &&
    passwordsMatch;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isFormValid) return;

    setLoading(true);
    setError(null);
    setSuccessMsg(null);

    try {
      const res = await changeSuperadminPassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });

      setSuccessMsg(res.message || "Mot de passe modifié avec succès ! Redirection en cours...");
      loadAuditLog();

      // Redirection / invalidation après un court délai pour lecture du message
      setTimeout(() => {
        onPasswordChangedSuccessfully();
      }, 2000);
    } catch (err: any) {
      setError(err.message || "Erreur lors du changement de mot de passe.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto">
      <div className="relative w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden my-8 animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/50">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center text-white shadow-lg shadow-sky-500/20">
              <KeyRound className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white flex items-center space-x-2">
                <span>Sécurité du Compte</span>
                <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-sky-500/10 text-sky-400 border border-sky-500/20">
                  Superadmin
                </span>
              </h2>
              <p className="text-xs text-slate-400">
                Modification du mot de passe & audit d'accès Cockpit OPS
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* User Card */}
        <div className="px-6 py-3 bg-slate-950/40 border-b border-slate-800/80 flex flex-wrap items-center justify-between text-xs text-slate-300 gap-2">
          <div className="flex items-center space-x-2">
            <span className="text-slate-500">Compte actif :</span>
            <span className="font-semibold text-slate-200">{adminUser?.email || "admin@orso-agents.fr"}</span>
            <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono text-[10px]">
              {adminUser?.role || "superadmin"}
            </span>
          </div>
          <div className="text-slate-500">
            Administrateur unique : <strong className="text-slate-300">Thibaut Quinzain</strong>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-800 px-6 pt-2 bg-slate-900/30">
          <button
            onClick={() => setActiveTab("form")}
            className={`flex items-center space-x-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
              activeTab === "form"
                ? "border-sky-500 text-sky-400 bg-sky-500/5"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Lock className="w-3.5 h-3.5" />
            <span>Changer le mot de passe</span>
          </button>

          <button
            onClick={() => setActiveTab("audit")}
            className={`flex items-center space-x-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
              activeTab === "audit"
                ? "border-sky-500 text-sky-400 bg-sky-500/5"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <History className="w-3.5 h-3.5" />
            <span>Journal d'audit</span>
            {auditEvents.length > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-slate-800 text-slate-300">
                {auditEvents.length}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab("emergency")}
            className={`flex items-center space-x-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
              activeTab === "emergency"
                ? "border-sky-500 text-sky-400 bg-sky-500/5"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>Secours d'urgence (CLI)</span>
          </button>
        </div>

        {/* Tab Content */}
        <div className="p-6">
          {activeTab === "form" && (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-400 text-xs flex items-start space-x-2">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}

              {successMsg && (
                <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-400 text-xs flex items-start space-x-2">
                  <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>{successMsg}</span>
                </div>
              )}

              {/* Champ 1 : Ancien mot de passe */}
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Ancien mot de passe actuel <span className="text-rose-400">*</span>
                </label>
                <div className="relative">
                  <input
                    type={showCurrent ? "text" : "password"}
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    placeholder="Entrez votre mot de passe actuel"
                    required
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-sky-500 pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowCurrent(!showCurrent)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                  >
                    {showCurrent ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* Champ 2 : Nouveau mot de passe */}
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Nouveau mot de passe <span className="text-rose-400">*</span>
                </label>
                <div className="relative">
                  <input
                    type={showNew ? "text" : "password"}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="Nouveau mot de passe complexe (≥ 12 caractères)"
                    required
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-sky-500 pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNew(!showNew)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                  >
                    {showNew ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>

                {/* Exigences de sécurité */}
                <div className="mt-2.5 p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 grid grid-cols-2 gap-2 text-[11px]">
                  <div className={`flex items-center space-x-1.5 ${hasMinLength ? "text-emerald-400" : "text-slate-500"}`}>
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>Au moins 12 caractères</span>
                  </div>
                  <div className={`flex items-center space-x-1.5 ${hasUpper ? "text-emerald-400" : "text-slate-500"}`}>
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>1 lettre majuscule</span>
                  </div>
                  <div className={`flex items-center space-x-1.5 ${hasLower ? "text-emerald-400" : "text-slate-500"}`}>
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>1 lettre minuscule</span>
                  </div>
                  <div className={`flex items-center space-x-1.5 ${hasDigit ? "text-emerald-400" : "text-slate-500"}`}>
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>1 chiffre</span>
                  </div>
                  <div className={`flex items-center space-x-1.5 ${hasSpecial ? "text-emerald-400" : "text-slate-500"}`}>
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>1 caractère spécial (!@#$...)</span>
                  </div>
                  <div className={`flex items-center space-x-1.5 ${notTrivial ? "text-emerald-400" : "text-slate-500"}`}>
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    <span>Non trivial (pas admin/orso...)</span>
                  </div>
                </div>
              </div>

              {/* Champ 3 : Confirmation */}
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Confirmer le nouveau mot de passe <span className="text-rose-400">*</span>
                </label>
                <div className="relative">
                  <input
                    type={showConfirm ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Répétez le nouveau mot de passe"
                    required
                    className={`w-full bg-slate-950 border rounded-xl px-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none pr-10 ${
                      confirmPassword && !passwordsMatch
                        ? "border-rose-500 focus:border-rose-400"
                        : "border-slate-800 focus:border-sky-500"
                    }`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirm(!showConfirm)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                  >
                    {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {confirmPassword && !passwordsMatch && (
                  <p className="text-[11px] text-rose-400 mt-1">Les mots de passe ne correspondent pas.</p>
                )}
              </div>

              {/* Notice d'invalidation */}
              <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-300 text-xs flex items-start space-x-2">
                <Shield className="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
                <span>
                  <strong>Effet immédiat :</strong> La validation mettra à jour Supabase Auth (0ms sans redémarrage de conteneur) et invalidera votre session active pour des raisons de sécurité.
                </span>
              </div>

              {/* Actions */}
              <div className="flex items-center justify-end space-x-3 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={loading}
                  className="px-4 py-2 rounded-xl text-xs font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-colors cursor-pointer"
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  disabled={!isFormValid || loading}
                  className="flex items-center space-x-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white text-xs font-semibold shadow-lg shadow-sky-500/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Mise à jour en cours...</span>
                    </>
                  ) : (
                    <>
                      <KeyRound className="w-4 h-4" />
                      <span>Valider le nouveau mot de passe</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          )}

          {activeTab === "audit" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-xs text-slate-400">
                  Historique des modifications et réinitialisations de mot de passe (sans secrets).
                </p>
                <button
                  onClick={loadAuditLog}
                  disabled={loadingAudit}
                  className="text-xs text-sky-400 hover:underline cursor-pointer flex items-center space-x-1"
                >
                  <Clock className="w-3.5 h-3.5" />
                  <span>Actualiser</span>
                </button>
              </div>

              {loadingAudit ? (
                <div className="py-8 flex justify-center text-slate-500">
                  <Loader2 className="w-6 h-6 animate-spin text-sky-400" />
                </div>
              ) : auditEvents.length === 0 ? (
                <div className="py-8 text-center text-xs text-slate-500 bg-slate-950/40 rounded-xl border border-slate-800">
                  Aucun événement d'audit enregistré pour le moment.
                </div>
              ) : (
                <div className="max-h-72 overflow-y-auto rounded-xl border border-slate-800 divide-y divide-slate-800/80">
                  {auditEvents.map((evt, idx) => (
                    <div key={idx} className="p-3 bg-slate-950/50 hover:bg-slate-950 text-xs flex items-center justify-between gap-3">
                      <div>
                        <div className="flex items-center space-x-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                              evt.result === "success"
                                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                            }`}
                          >
                            {evt.result}
                          </span>
                          <span className="font-medium text-slate-200">{evt.action}</span>
                          <span className="text-slate-500 font-mono text-[11px]">IP: {evt.ip}</span>
                        </div>
                        {evt.reason && (
                          <p className="text-[11px] text-rose-400/90 mt-1">Motif: {evt.reason}</p>
                        )}
                      </div>
                      <div className="text-right text-[11px] text-slate-500 whitespace-nowrap">
                        {new Date(evt.timestamp).toLocaleString("fr-FR")}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === "emergency" && (
            <div className="space-y-4">
              <div className="p-3.5 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-300 space-y-2">
                <div className="flex items-center space-x-2 font-semibold">
                  <Terminal className="w-4 h-4 text-amber-400" />
                  <span>Procédure de Secours d'Urgence CLI (CA8)</span>
                </div>
                <p className="text-slate-300">
                  En cas d'oubli ou de perte du mot de passe superadmin, l'administrateur unique dispose d'un script CLI d'urgence exécutable directement depuis le terminal du serveur ou en local avec la clé de service Supabase.
                </p>
              </div>

              <div className="space-y-2">
                <label className="block text-xs font-semibold text-slate-300">
                  Commande de rotation automatique sécurisée :
                </label>
                <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 font-mono text-xs text-sky-300 select-all overflow-x-auto">
                  python3 scripts/iam/reset_superadmin_password.py --email admin@orso-agents.fr --generate
                </div>
              </div>

              <div className="space-y-2">
                <label className="block text-xs font-semibold text-slate-300">
                  Commande avec mot de passe spécifique :
                </label>
                <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 font-mono text-xs text-sky-300 select-all overflow-x-auto">
                  python3 scripts/iam/reset_superadmin_password.py --email admin@orso-agents.fr --password "VotreMotDePasseComplexe123!"
                </div>
              </div>

              <ul className="text-xs text-slate-400 space-y-1 list-disc list-inside">
                <li>Le script vérifie la politique de sécurité (≥ 12 caractères, majuscule, chiffre, etc.).</li>
                <li>Il teste immédiatement la connexion auprès de Supabase Auth.</li>
                <li>Il consigne l'événement dans le journal d'audit local sans exposer le mot de passe.</li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
