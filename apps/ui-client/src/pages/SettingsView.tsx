import React, { useState, useEffect } from 'react';
import {
  Building2,
  User,
  CreditCard,
  Lock,
  Eye,
  EyeOff,
  CheckCircle2,
  AlertTriangle,
  Download,
  ExternalLink,
  ShieldCheck,
  Server,
  ArrowLeft,
  Sparkles,
  RefreshCw,
  Check,
  FileText,
  Phone,
  Mail,
  MapPin,
  Calendar,
} from 'lucide-react';
import { CompanyData, UserProfileData, BillingData } from '@/types';
import {
  fetchClientSettingsProfile,
  updateClientPassword,
  fetchClientBilling,
  updateClientSubscription,
  createStripePortalSession,
  downloadClientInvoice,
} from '@/lib/api';

interface SettingsViewProps {
  isAdmin: boolean;
  onBack: () => void;
}

type SettingsTab = 'company' | 'profile' | 'billing';

export const SettingsView: React.FC<SettingsViewProps> = ({ isAdmin, onBack }) => {
  const [activeTab, setActiveTab] = useState<SettingsTab>('company');
  const [loading, setLoading] = useState<boolean>(true);

  // Données entreprise & profil
  const [company, setCompany] = useState<CompanyData | null>(null);
  const [userProfile, setUserProfile] = useState<UserProfileData | null>(null);

  // Données facturation & Stripe
  const [billing, setBilling] = useState<BillingData | null>(null);
  const [billingLoading, setBillingLoading] = useState<boolean>(false);

  // Formulaire mot de passe
  const [currentPassword, setCurrentPassword] = useState<string>('');
  const [newPassword, setNewPassword] = useState<string>('');
  const [confirmPassword, setConfirmPassword] = useState<string>('');
  const [showCurrentPass, setShowCurrentPass] = useState<boolean>(false);
  const [showNewPass, setShowNewPass] = useState<boolean>(false);
  const [passwordLoading, setPasswordLoading] = useState<boolean>(false);
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  // Actions de changement de formule / Stripe
  const [updatingTierId, setUpdatingTierId] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState<boolean>(false);
  const [downloadingInvId, setDownloadingInvId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<{ text: string; type: 'success' | 'error' | 'info' } | null>(null);

  // Confirmation modale de changement de formule
  const [selectedTierToConfirm, setSelectedTierToConfirm] = useState<{ id: string; name: string; price_ht: number } | null>(null);

  const showToast = (text: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToastMessage({ text, type });
    setTimeout(() => setToastMessage(null), 4500);
  };

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        const profileRes = await fetchClientSettingsProfile();
        if (profileRes) {
          setCompany(profileRes.company);
          setUserProfile(profileRes.user);
        }

        if (isAdmin) {
          setBillingLoading(true);
          const billingRes = await fetchClientBilling();
          if (billingRes) {
            setBilling(billingRes);
          }
          setBillingLoading(false);
        }
      } catch (err) {
        console.error('Erreur chargement paramètres client:', err);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [isAdmin]);

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(null);

    if (newPassword.length < 8) {
      setPasswordError('Le nouveau mot de passe doit comporter au moins 8 caractères.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setPasswordError('La confirmation ne correspond pas au nouveau mot de passe.');
      return;
    }

    setPasswordLoading(true);
    try {
      const res = await updateClientPassword({
        current_password: currentPassword || undefined,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });

      if (res.success) {
        setPasswordSuccess(res.message);
        setCurrentPassword('');
        setNewPassword('');
        setConfirmPassword('');
      } else {
        setPasswordError(res.message);
      }
    } catch (err: any) {
      setPasswordError(err?.message || 'Erreur lors du changement de mot de passe.');
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleOpenStripePortal = async () => {
    setPortalLoading(true);
    try {
      const res = await createStripePortalSession();
      if (res.success && res.url) {
        window.open(res.url, '_blank', 'noopener,noreferrer');
        showToast('Portail sécurisé Stripe ouvert dans un nouvel onglet.', 'info');
      } else {
        showToast(res.error || 'Impossible d’accéder au portail Stripe.', 'error');
      }
    } catch {
      showToast('Erreur de connexion avec le service Stripe.', 'error');
    } finally {
      setPortalLoading(false);
    }
  };

  const handleConfirmPlanChange = async () => {
    if (!selectedTierToConfirm) return;
    const tierId = selectedTierToConfirm.id;
    setUpdatingTierId(tierId);
    setSelectedTierToConfirm(null);

    try {
      const res = await updateClientSubscription(tierId);
      if (res.success) {
        showToast(res.message, 'success');
        // Rafraîchir les données de facturation
        const updatedBilling = await fetchClientBilling();
        if (updatedBilling) {
          setBilling(updatedBilling);
        }
      } else {
        showToast(res.message || 'Impossible de mettre à jour le forfait.', 'error');
      }
    } catch (err: any) {
      showToast(err?.message || 'Erreur lors de la mise à jour de l’abonnement.', 'error');
    } finally {
      setUpdatingTierId(null);
    }
  };

  const handleDownloadInvoice = async (invoiceId: string, invoiceNumber: string) => {
    setDownloadingInvId(invoiceId);
    try {
      await downloadClientInvoice(invoiceId, invoiceNumber);
      showToast(`Téléchargement de la facture ${invoiceNumber} réussi !`, 'success');
    } catch (err: any) {
      showToast(err?.message || 'Erreur lors du téléchargement de la facture.', 'error');
    } finally {
      setDownloadingInvId(null);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 p-4 sm:p-6 md:p-8 space-y-6">
      {/* Toast Feedback */}
      {toastMessage && (
        <div
          className={`fixed top-6 right-6 z-50 flex items-center gap-2.5 px-4 py-3 rounded-2xl border text-xs font-semibold shadow-2xl backdrop-blur-md animate-in fade-in slide-in-from-top-2 ${
            toastMessage.type === 'success'
              ? 'bg-emerald-950/90 border-emerald-600/60 text-emerald-200'
              : toastMessage.type === 'error'
              ? 'bg-rose-950/90 border-rose-600/60 text-rose-200'
              : 'bg-blue-950/90 border-blue-600/60 text-blue-200'
          }`}
        >
          {toastMessage.type === 'success' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
          {toastMessage.type === 'error' && <AlertTriangle className="w-4 h-4 text-rose-400" />}
          {toastMessage.type === 'info' && <RefreshCw className="w-4 h-4 text-blue-400" />}
          <span>{toastMessage.text}</span>
        </div>
      )}

      {/* Top Header avec bouton Retour */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800/80 pb-5">
        <div className="flex items-center gap-3.5">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-750 text-slate-300 hover:text-white text-xs font-semibold transition-all active:scale-95 shadow-sm"
            title="Revenir au chat"
          >
            <ArrowLeft className="w-4 h-4" />
            <span className="hidden sm:inline">Retour</span>
          </button>
          <div>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-white flex items-center gap-2.5">
              <span>Paramètres & Organisation</span>
              <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-blue-950 border border-blue-800 text-blue-300">
                ORSO SOUVERAIN
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">
              Consultez vos données d'entreprise, sécurisez votre compte et pilotez votre abonnement Orso.
            </p>
          </div>
        </div>

        {/* Badge isolation / sécurité */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900/90 border border-slate-800 text-[11px] text-slate-300 self-start sm:self-auto">
          <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
          <span>Conteneur Dédié • Données Cloisonnées</span>
        </div>
      </div>

      {/* Barre d'onglets de navigation interne */}
      <div className="flex items-center gap-1.5 border-b border-slate-850 pb-2 overflow-x-auto">
        <button
          onClick={() => setActiveTab('company')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all shrink-0 ${
            activeTab === 'company'
              ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <Building2 className="w-4 h-4" />
          <span>Entreprise & Infrastructure</span>
        </button>

        <button
          onClick={() => setActiveTab('profile')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all shrink-0 ${
            activeTab === 'profile'
              ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <User className="w-4 h-4" />
          <span>Mon Profil & Sécurité</span>
        </button>

        {/* Onglet Abonnement & Facturation (Affiché UNIQUEMENT si l'utilisateur est administrateur) */}
        {isAdmin && (
          <button
            onClick={() => setActiveTab('billing')}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all shrink-0 ${
              activeTab === 'billing'
                ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <CreditCard className="w-4 h-4" />
            <span>Abonnement & Facturation</span>
            <span className="ml-1 px-1.5 py-0.5 rounded text-[9px] font-black uppercase bg-emerald-950 text-emerald-300 border border-emerald-800">
              Admin
            </span>
          </button>
        )}
      </div>

      {/* Contenu principal */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 text-slate-400 space-y-3">
          <RefreshCw className="w-8 h-8 text-blue-500 animate-spin" />
          <p className="text-xs font-medium">Chargement des données de votre organisation...</p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* ═════════════════════════════════════════════════════════════════════ */}
          {/* ONGLET 1 : ENTREPRISE & INFRASTRUCTURE SOUVERAINE                    */}
          {/* ═════════════════════════════════════════════════════════════════════ */}
          {activeTab === 'company' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Carte Identité Entreprise */}
              <div className="lg:col-span-2 p-6 rounded-3xl bg-slate-900/90 border border-slate-800/90 shadow-xl space-y-5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-2xl bg-blue-950/80 border border-blue-800/60 flex items-center justify-center text-blue-400 shadow-inner">
                      <Building2 className="w-5 h-5" />
                    </div>
                    <div>
                      <h2 className="text-base font-extrabold text-white">Identité de l'Organisation</h2>
                      <p className="text-xs text-slate-400">Raison sociale et immatriculation légale</p>
                    </div>
                  </div>
                  <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-950 border border-emerald-800 text-emerald-300 flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                    <span>Compte Certifié</span>
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs pt-2">
                  <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-850 space-y-1">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      Raison Sociale
                    </span>
                    <p className="text-sm font-bold text-white">{company?.name || 'Organisation Client'}</p>
                  </div>

                  <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-850 space-y-1">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      Forme Juridique & Secteur
                    </span>
                    <p className="text-sm font-bold text-white">
                      {company?.legal_form || 'SAS'} • {company?.sector || 'Services & Conseil'}
                    </p>
                  </div>

                  <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-850 space-y-1">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      Numéro SIRET
                    </span>
                    <p className="text-sm font-bold text-slate-200 font-mono tracking-wide">
                      {company?.siret || '832 145 678 00012'}
                    </p>
                  </div>

                  <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-850 space-y-1">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      Numéro TVA Intracommunautaire
                    </span>
                    <p className="text-sm font-bold text-slate-200 font-mono tracking-wide">
                      {company?.vat_number || 'FR45832145678'}
                    </p>
                  </div>

                  <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-850 space-y-1 md:col-span-2">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1">
                      <MapPin className="w-3.5 h-3.5 text-blue-400" />
                      <span>Siège Social & Localisation</span>
                    </span>
                    <p className="text-sm font-medium text-slate-200">
                      {company?.address_line1 || '14 Rue de la Paix'}, {company?.postal_code || '75002'}{' '}
                      {company?.city || 'Paris'}, {company?.country || 'France'}
                    </p>
                  </div>
                </div>

                <div className="p-3.5 rounded-2xl bg-slate-950/50 border border-slate-850/80 text-[11px] text-slate-400 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Calendar className="w-3.5 h-3.5 text-slate-500" />
                    <span>Identifiant Organisation :</span>
                    <span className="font-mono text-slate-300 font-semibold">{company?.slug || 'client'}</span>
                  </div>
                  <span className="text-[10px] text-slate-500">Souscription Orso Cloud B2B</span>
                </div>
              </div>

              {/* Carte Infrastructure Souveraine & Cloisonnement */}
              <div className="p-6 rounded-3xl bg-gradient-to-b from-slate-900 via-slate-900 to-blue-950/40 border border-slate-800/90 shadow-xl space-y-5">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-indigo-950/80 border border-indigo-800/60 flex items-center justify-center text-indigo-400 shadow-inner">
                    <Server className="w-5 h-5" />
                  </div>
                  <div>
                    <h2 className="text-base font-extrabold text-white">Infrastructure Dédiée</h2>
                    <p className="text-xs text-slate-400">Environnement souverain sécurisé</p>
                  </div>
                </div>

                <div className="space-y-3.5 text-xs">
                  <div className="p-3.5 rounded-2xl bg-slate-950/90 border border-slate-850 space-y-1.5">
                    <span className="text-[11px] text-slate-400 font-medium">Statut du Conteneur</span>
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
                      <span className="font-bold text-white">
                        {company?.environment?.status || 'En ligne • Cloisonné'}
                      </span>
                    </div>
                  </div>

                  <div className="p-3.5 rounded-2xl bg-slate-950/90 border border-slate-850 space-y-1.5">
                    <span className="text-[11px] text-slate-400 font-medium">Hébergement Souverain</span>
                    <p className="font-bold text-white">
                      {company?.environment?.region || 'Gravelines (France) • OVHcloud'}
                    </p>
                    <p className="text-[10px] text-slate-400">100% conforme RGPD, zéro transfert hors UE.</p>
                  </div>

                  <div className="p-3.5 rounded-2xl bg-slate-950/90 border border-slate-850 space-y-1.5">
                    <span className="text-[11px] text-slate-400 font-medium">Isolation Réseau</span>
                    <p className="font-semibold text-slate-200">
                      {company?.environment?.isolation_type || 'Conteneur Docker Dédié (Réseau privé)'}
                    </p>
                  </div>
                </div>

                {/* Agents Déployés */}
                <div className="pt-2 border-t border-slate-800">
                  <span className="text-[11px] font-bold text-slate-300 uppercase tracking-wider block mb-2">
                    Agents Déployés sur votre flotte
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {(company?.agents_deployed || ['jerome']).map((agentId) => (
                      <span
                        key={agentId}
                        className="px-2.5 py-1 rounded-xl text-[11px] font-bold bg-blue-950/80 border border-blue-800 text-blue-300 capitalize flex items-center gap-1"
                      >
                        <Sparkles className="w-3 h-3 text-blue-400" />
                        <span>{agentId}</span>
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ═════════════════════════════════════════════════════════════════════ */}
          {/* ONGLET 2 : MON PROFIL & MODIFICATION DU MOT DE PASSE                 */}
          {/* ═════════════════════════════════════════════════════════════════════ */}
          {activeTab === 'profile' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Carte Informations Collaborateur */}
              <div className="p-6 rounded-3xl bg-slate-900/90 border border-slate-800/90 shadow-xl space-y-5">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-indigo-950/80 border border-indigo-800/60 flex items-center justify-center text-indigo-400 shadow-inner">
                    <User className="w-5 h-5" />
                  </div>
                  <div>
                    <h2 className="text-base font-extrabold text-white">Mon Compte Personnel</h2>
                    <p className="text-xs text-slate-400">Coordonnées et niveau d'habilitation</p>
                  </div>
                </div>

                <div className="space-y-3.5 text-xs">
                  <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-850 space-y-1">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      Nom & Prénom
                    </span>
                    <p className="text-sm font-bold text-white">{userProfile?.full_name || 'Utilisateur Orso'}</p>
                  </div>

                  <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-850 space-y-1">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                      <Mail className="w-3.5 h-3.5 text-blue-400" />
                      <span>Adresse Email Professionnelle</span>
                    </span>
                    <p className="text-sm font-bold text-white">{userProfile?.email || 'email@societe.fr'}</p>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-850 space-y-1">
                      <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                        Fonction dans l'entreprise
                      </span>
                      <p className="text-sm font-bold text-white">{userProfile?.job_title || 'Directrice Administrative et Financière (DAF)'}</p>
                    </div>

                    <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-850 space-y-1">
                      <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                        Habilitation Orso
                      </span>
                      <div>
                        {userProfile?.is_admin ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                            <ShieldCheck className="w-3 h-3" />
                            <span>{userProfile?.role === 'superadmin' ? 'Super Admin' : 'Admin'}</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-slate-800 text-slate-300 border border-slate-700">
                            <span>Utilisateur simple</span>
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-850 space-y-1">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                      <Phone className="w-3.5 h-3.5 text-blue-400" />
                      <span>Téléphone de contact</span>
                    </span>
                    <p className="text-sm font-medium text-slate-300">{userProfile?.phone || '+33 6 45 78 12 34'}</p>
                  </div>
                </div>
              </div>

              {/* Formulaire Modification du Mot de Passe */}
              <div className="p-6 rounded-3xl bg-slate-900/90 border border-slate-800/90 shadow-xl space-y-5">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-blue-950/80 border border-blue-800/60 flex items-center justify-center text-blue-400 shadow-inner">
                    <Lock className="w-5 h-5" />
                  </div>
                  <div>
                    <h2 className="text-base font-extrabold text-white">Sécurité & Mot de Passe</h2>
                    <p className="text-xs text-slate-400">Modifiez votre mot de passe de connexion</p>
                  </div>
                </div>

                {passwordSuccess && (
                  <div className="p-3.5 rounded-2xl bg-emerald-950/70 border border-emerald-700/60 text-emerald-200 text-xs flex items-center gap-2.5 animate-in fade-in">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>{passwordSuccess}</span>
                  </div>
                )}

                {passwordError && (
                  <div className="p-3.5 rounded-2xl bg-rose-950/70 border border-rose-700/60 text-rose-200 text-xs flex items-center gap-2.5 animate-in fade-in">
                    <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                    <span>{passwordError}</span>
                  </div>
                )}

                <form onSubmit={handlePasswordSubmit} className="space-y-4 text-xs">
                  <div>
                    <label className="block text-slate-300 font-semibold mb-1.5">Mot de passe actuel</label>
                    <div className="relative">
                      <input
                        type={showCurrentPass ? 'text' : 'password'}
                        value={currentPassword}
                        onChange={(e) => setCurrentPassword(e.target.value)}
                        placeholder="••••••••••••"
                        className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950/90 border border-slate-800 text-slate-100 text-xs focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40 pr-10 font-mono transition-all"
                      />
                      <button
                        type="button"
                        onClick={() => setShowCurrentPass(!showCurrentPass)}
                        className="absolute right-3 top-2.5 text-slate-400 hover:text-slate-200 transition-colors"
                      >
                        {showCurrentPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  <div>
                    <label className="block text-slate-300 font-semibold mb-1.5">
                      Nouveau mot de passe (8 caractères minimum)
                    </label>
                    <div className="relative">
                      <input
                        type={showNewPass ? 'text' : 'password'}
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        placeholder="••••••••••••"
                        required
                        minLength={8}
                        className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950/90 border border-slate-800 text-slate-100 text-xs focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40 pr-10 font-mono transition-all"
                      />
                      <button
                        type="button"
                        onClick={() => setShowNewPass(!showNewPass)}
                        className="absolute right-3 top-2.5 text-slate-400 hover:text-slate-200 transition-colors"
                      >
                        {showNewPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  <div>
                    <label className="block text-slate-300 font-semibold mb-1.5">
                      Confirmer le nouveau mot de passe
                    </label>
                    <input
                      type="password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="••••••••••••"
                      required
                      minLength={8}
                      className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950/90 border border-slate-800 text-slate-100 text-xs focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40 font-mono transition-all"
                    />
                  </div>

                  <div className="pt-2">
                    <button
                      type="submit"
                      disabled={passwordLoading || !newPassword || !confirmPassword}
                      className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold shadow-lg shadow-blue-900/30 transition-all disabled:opacity-50 flex items-center justify-center gap-2 active:scale-95"
                    >
                      {passwordLoading ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          <span>Mise à jour en cours...</span>
                        </>
                      ) : (
                        <>
                          <Lock className="w-4 h-4" />
                          <span>Mettre à jour mon mot de passe</span>
                        </>
                      )}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* ═════════════════════════════════════════════════════════════════════ */}
          {/* ONGLET 3 : ABONNEMENT & FACTURATION STRIPE (ADMIN ONLY)              */}
          {/* ═════════════════════════════════════════════════════════════════════ */}
          {activeTab === 'billing' && isAdmin && (
            billingLoading ? (
              <div className="flex flex-col items-center justify-center py-16 text-slate-400 space-y-3">
                <RefreshCw className="w-8 h-8 text-blue-500 animate-spin" />
                <p className="text-xs font-medium">Synchronisation avec Stripe Billing en cours...</p>
              </div>
            ) : (
            <div className="space-y-6">
              {/* Carte Résumé de la souscription actuelle */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Forfait Actif */}
                <div className="p-6 rounded-3xl bg-gradient-to-br from-slate-900 via-slate-900 to-blue-950/60 border border-slate-800 shadow-xl space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Forfait Actif</span>
                    <span className="px-2.5 py-0.5 rounded-full text-[10px] font-extrabold bg-emerald-950 border border-emerald-800 text-emerald-300 uppercase">
                      {billing?.subscription?.status || 'Actif'}
                    </span>
                  </div>

                  <div>
                    <h3 className="text-xl font-black text-white">{billing?.subscription?.tier_label || 'Starter (1 agent)'}</h3>
                    <div className="flex items-baseline gap-1 mt-1">
                      <span className="text-3xl font-extrabold text-blue-400">
                        {billing?.subscription?.price_ht ?? 99} €
                      </span>
                      <span className="text-xs text-slate-400 font-medium">HT / mois</span>
                    </div>
                  </div>

                  <div className="pt-2 border-t border-slate-800/80 text-xs text-slate-400 space-y-1.5">
                    <div className="flex justify-between items-center">
                      <span>Nombre d'agents inclus :</span>
                      <span className="font-bold text-white">{billing?.subscription?.agents_count ?? 1} agent(s)</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span>Prochain renouvellement :</span>
                      <span className="font-medium text-slate-300">
                        {billing?.subscription?.current_period_end
                          ? new Date(billing.subscription.current_period_end).toLocaleDateString('fr-FR')
                          : '28/10/2026'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Moyen de Paiement */}
                <div className="p-6 rounded-3xl bg-slate-900/90 border border-slate-800 shadow-xl flex flex-col justify-between space-y-4">
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Moyen de Paiement</span>
                      <CreditCard className="w-4 h-4 text-blue-400" />
                    </div>
                    <p className="text-sm font-bold text-white">
                      {billing?.subscription?.payment_method || 'Carte Bancaire (•••• 4242)'}
                    </p>
                    <p className="text-[11px] text-slate-400 mt-1">
                      Prélèvement automatique mensuel sécurisé Stripe Billing.
                    </p>
                  </div>

                  <div className="pt-2">
                    <button
                      onClick={handleOpenStripePortal}
                      disabled={portalLoading}
                      className="w-full py-2.5 px-3 rounded-xl bg-slate-800 hover:bg-slate-750 border border-slate-700 text-white text-xs font-bold shadow-sm transition-all flex items-center justify-center gap-2 active:scale-95 disabled:opacity-50"
                    >
                      {portalLoading ? (
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <CreditCard className="w-3.5 h-3.5 text-blue-400" />
                      )}
                      <span>Modifier mon moyen de paiement</span>
                    </button>
                  </div>
                </div>

                {/* Synchronisation Stripe & Démarches */}
                <div className="p-6 rounded-3xl bg-slate-900/90 border border-slate-800 shadow-xl flex flex-col justify-between space-y-4">
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Portail Client Stripe</span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-950 text-indigo-300 border border-indigo-800">
                        Synchronisé
                      </span>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">
                      Accédez au portail officiel Stripe pour modifier votre adresse de facturation, renseigner votre n° de TVA ou télécharger vos reçus fiscaux.
                    </p>
                  </div>

                  <button
                    onClick={handleOpenStripePortal}
                    disabled={portalLoading}
                    className="w-full py-2.5 px-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-lg shadow-blue-900/30 transition-all flex items-center justify-center gap-2 active:scale-95 disabled:opacity-50"
                  >
                    <span>Gérer sur le portail Stripe</span>
                    <ExternalLink className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Sélecteur & Comparateur de Formules (Changer d'abonnement) */}
              <div className="p-6 rounded-3xl bg-slate-900/90 border border-slate-800 shadow-xl space-y-5">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <h2 className="text-base font-extrabold text-white flex items-center gap-2">
                      <span>Faire Évoluer votre Formule Orso</span>
                      <Sparkles className="w-4 h-4 text-amber-400" />
                    </h2>
                    <p className="text-xs text-slate-400">
                      Changez d'offre à tout moment. Le calcul du prorata est géré automatiquement par Stripe.
                    </p>
                  </div>
                  <span className="text-[11px] font-medium text-slate-400 bg-slate-950 px-3 py-1 rounded-full border border-slate-850">
                    Facturation Mensuelle Sans Engagement
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 pt-2">
                  {(billing?.available_tiers || []).map((tier) => {
                    const isCurrent = billing?.subscription?.tier_id === tier.id;
                    const isUpdating = updatingTierId === tier.id;

                    return (
                      <div
                        key={tier.id}
                        className={`p-5 rounded-2xl border transition-all flex flex-col justify-between relative ${
                          isCurrent
                            ? 'bg-blue-950/40 border-blue-500 ring-2 ring-blue-500/30 shadow-lg shadow-blue-950/50'
                            : 'bg-slate-950/70 border-slate-800 hover:border-slate-700 hover:bg-slate-900/70'
                        }`}
                      >
                        {tier.popular && !isCurrent && (
                          <div className="absolute -top-2.5 right-4 px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-wider bg-amber-500 text-slate-950 shadow-md">
                            Populaire
                          </div>
                        )}

                        {isCurrent && (
                          <div className="absolute -top-2.5 right-4 px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-wider bg-blue-500 text-white shadow-md">
                            Formule Actuelle
                          </div>
                        )}

                        <div className="space-y-3">
                          <div>
                            <h4 className="text-sm font-extrabold text-white">{tier.name}</h4>
                            <p className="text-[11px] text-slate-400 mt-0.5">{tier.description}</p>
                          </div>

                          <div className="flex items-baseline gap-1 py-1">
                            <span className="text-2xl font-black text-white">{tier.price_ht} €</span>
                            <span className="text-[11px] text-slate-400 font-medium">HT / mois</span>
                          </div>

                          <ul className="space-y-2 pt-2 border-t border-slate-800/80 text-[11px] text-slate-300">
                            {tier.features.map((feat, idx) => (
                              <li key={idx} className="flex items-start gap-2">
                                <Check className="w-3.5 h-3.5 text-blue-400 shrink-0 mt-0.5" />
                                <span>{feat}</span>
                              </li>
                            ))}
                          </ul>
                        </div>

                        <div className="pt-5 mt-4 border-t border-slate-850">
                          {isCurrent ? (
                            <button
                              disabled
                              className="w-full py-2 rounded-xl bg-blue-900/40 border border-blue-800/60 text-blue-200 text-xs font-bold cursor-default"
                            >
                              ✓ Votre formule
                            </button>
                          ) : (
                            <button
                              onClick={() => setSelectedTierToConfirm(tier)}
                              disabled={isUpdating}
                              className="w-full py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-md shadow-blue-900/30 transition-all active:scale-95 disabled:opacity-50 flex items-center justify-center gap-1.5"
                            >
                              {isUpdating ? (
                                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <span>Passer à cette formule</span>
                              )}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Historique des Factures avec Téléchargement PDF */}
              <div className="p-6 rounded-3xl bg-slate-900/90 border border-slate-800 shadow-xl space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-2xl bg-blue-950/80 border border-blue-800/60 flex items-center justify-center text-blue-400 shadow-inner">
                      <FileText className="w-5 h-5" />
                    </div>
                    <div>
                      <h2 className="text-base font-extrabold text-white">Historique des Factures</h2>
                      <p className="text-xs text-slate-400">Consultez et téléchargez vos factures acquittées</p>
                    </div>
                  </div>
                  <span className="text-xs font-semibold text-slate-400">
                    {billing?.invoices?.length || 0} facture(s) émise(s)
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-800 text-slate-400 font-semibold">
                        <th className="py-3 px-4">Numéro de Facture</th>
                        <th className="py-3 px-4">Date d'émission</th>
                        <th className="py-3 px-4">Montant HT</th>
                        <th className="py-3 px-4">Montant TTC (TVA 20%)</th>
                        <th className="py-3 px-4">Statut</th>
                        <th className="py-3 px-4 text-right">Téléchargement</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-850">
                      {(billing?.invoices || []).map((inv) => (
                        <tr key={inv.id} className="hover:bg-slate-850/40 transition-colors">
                          <td className="py-3.5 px-4 font-mono font-bold text-white flex items-center gap-2">
                            <FileText className="w-4 h-4 text-blue-400" />
                            <span>{inv.number}</span>
                          </td>
                          <td className="py-3.5 px-4 text-slate-300">{inv.date}</td>
                          <td className="py-3.5 px-4 font-semibold text-slate-200">{inv.amount_ht.toFixed(2)} €</td>
                          <td className="py-3.5 px-4 font-bold text-white">{inv.amount_ttc.toFixed(2)} €</td>
                          <td className="py-3.5 px-4">
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-extrabold uppercase bg-emerald-950 border border-emerald-800 text-emerald-300">
                              {inv.status === 'paid' ? 'Payée' : inv.status}
                            </span>
                          </td>
                          <td className="py-3.5 px-4 text-right">
                            <button
                              onClick={() => handleDownloadInvoice(inv.id, inv.number)}
                              disabled={downloadingInvId === inv.id}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-blue-600 hover:text-white text-slate-200 border border-slate-700 text-xs font-semibold shadow-sm transition-all active:scale-95 disabled:opacity-50"
                              title={`Télécharger la facture ${inv.number} en PDF`}
                            >
                              {downloadingInvId === inv.id ? (
                                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <Download className="w-3.5 h-3.5" />
                              )}
                              <span>PDF</span>
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
            )
          )}
        </div>
      )}

      {/* Modal Confirmation Changement de Forfait */}
      {selectedTierToConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-in fade-in">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl shadow-blue-950/50 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-blue-950 border border-blue-800 flex items-center justify-center text-blue-400">
                <Sparkles className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-extrabold text-white">Changer de formule d'abonnement</h3>
                <p className="text-xs text-slate-400">Confirmation de la modification Stripe</p>
              </div>
            </div>

            <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-2 text-xs">
              <div className="flex justify-between items-center py-1">
                <span className="text-slate-400">Nouvelle formule :</span>
                <span className="font-bold text-white text-sm">{selectedTierToConfirm.name}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-t border-slate-850">
                <span className="text-slate-400">Nouveau tarif mensuel :</span>
                <span className="font-extrabold text-blue-400 text-base">{selectedTierToConfirm.price_ht} € HT</span>
              </div>
              <div className="pt-2 text-[11px] text-slate-400 leading-relaxed border-t border-slate-850">
                💡 Votre nouveau palier prend effet immédiatement. La régularisation au prorata temporis sera reportée sur votre prochaine facture Stripe.
              </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2">
              <button
                onClick={() => setSelectedTierToConfirm(null)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition-all"
              >
                Annuler
              </button>
              <button
                onClick={handleConfirmPlanChange}
                className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-lg shadow-blue-900/30 transition-all flex items-center gap-1.5"
              >
                <span>Confirmer le changement</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
