import React, { useState, useEffect, useRef } from 'react';
import {
  fetchEnvironmentStatus,
  wakeTenantEnvironment,
  EnvironmentStatusResponse,
} from '@/lib/api';
import {
  Loader2,
  Server,
  ShieldCheck,
  Cpu,
  CheckCircle2,
  AlertOctagon,
  Moon,
  RefreshCw,
  LogOut,
  Mail,
  ArrowRight,
  PhoneCall,
  UserCheck,
} from 'lucide-react';

interface EnvironmentWaitingViewProps {
  tenantSlug?: string;
  tenantName?: string;
  initialStatus?: string;
  onReady: () => void;
  onLogout: () => void;
}

export const EnvironmentWaitingView: React.FC<EnvironmentWaitingViewProps> = ({
  tenantSlug,
  tenantName,
  initialStatus = 'pending_validation',
  onReady,
  onLogout,
}) => {
  const [status, setStatus] = useState<EnvironmentStatusResponse['status']>(
    (initialStatus as any) || 'pending_validation'
  );
  const [currentStep, setCurrentStep] = useState<string>(
    'Votre espace est en cours de préparation par notre équipe.'
  );
  const [nextStep, setNextStep] = useState<string>(
    'Appel de cadrage personnalisé avec notre équipe'
  );
  const [contactPerson, setContactPerson] = useState<string>('Thibaut Quinzain');
  const [contactEmail, setContactEmail] = useState<string>('contact@orso-agents.fr');
  const [errorDetails, setErrorDetails] = useState<string | null>(null);
  const [isWaking, setIsWaking] = useState<boolean>(false);
  const [isChecking, setIsChecking] = useState<boolean>(false);

  const pollIntervalRef = useRef<any>(null);

  const checkStatus = async () => {
    setIsChecking(true);
    try {
      const res = await fetchEnvironmentStatus(tenantSlug);
      setStatus(res.status);

      if (res.status === 'ready' || res.ready) {
        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
        setTimeout(() => {
          onReady();
        }, 800);
      } else if (res.status === 'provisioning' || (res.status as any) === 'pending_validation') {
        if (res.current_step) setCurrentStep(res.current_step);
        if ((res as any).next_step) setNextStep((res as any).next_step);
        if ((res as any).contact_person) setContactPerson((res as any).contact_person);
        if ((res as any).contact_email) setContactEmail((res as any).contact_email);
      } else if (res.status === 'error') {
        setErrorDetails(res.error_details || res.message || 'Une difficulté technique a été rencontrée lors de la préparation.');
      }
    } catch (err: any) {
      console.warn('Erreur polling statut environnement:', err);
    } finally {
      setIsChecking(false);
    }
  };

  useEffect(() => {
    checkStatus();
    pollIntervalRef.current = setInterval(checkStatus, 4000);

    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, [tenantSlug]);

  const handleWake = async () => {
    setIsWaking(true);
    try {
      await wakeTenantEnvironment(tenantSlug);
      await checkStatus();
    } finally {
      setIsWaking(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-between p-6">
      {/* Header minimaliste */}
      <header className="flex items-center justify-between max-w-4xl w-full mx-auto pb-6 border-b border-slate-800">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-blue-600/20 border border-blue-500/40 flex items-center justify-center font-bold text-blue-400">
            🐻
          </div>
          <div>
            <h1 className="font-semibold text-lg text-slate-200">Orso Agents</h1>
            <p className="text-xs text-slate-400">
              Organisation : <span className="text-slate-300 font-medium">{tenantName || tenantSlug || 'Espace Client'}</span>
            </p>
          </div>
        </div>

        <button
          onClick={onLogout}
          className="flex items-center space-x-2 text-xs text-slate-400 hover:text-slate-200 bg-slate-900 hover:bg-slate-800 px-3 py-2 rounded-lg border border-slate-800 transition"
        >
          <LogOut className="w-4 h-4" />
          <span>Déconnexion</span>
        </button>
      </header>

      {/* Contenu Central */}
      <main className="max-w-xl w-full mx-auto my-auto py-8">
        <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-8 shadow-2xl backdrop-blur-sm">
          {/* Cas 1 : En attente de validation ou en cours de préparation (KAN-105) */}
          {(status === 'pending_validation' || status === 'provisioning') && (
            <div className="space-y-6 text-center">
              <div className="relative w-20 h-20 mx-auto flex items-center justify-center">
                <div className="absolute inset-0 rounded-full border-4 border-blue-500/20 animate-ping opacity-25" />
                <div className="w-20 h-20 rounded-full border-4 border-blue-500 border-t-transparent animate-spin" />
                <Server className="w-8 h-8 text-blue-400 absolute" />
              </div>

              <div className="space-y-2">
                <h2 className="text-xl font-bold text-slate-100">
                  Votre espace Orso Agents est en préparation.
                </h2>
                <p className="text-sm text-slate-300">
                  Votre souscription est bien enregistrée. Votre espace est pris en charge et la préparation est pilotée par notre équipe.
                </p>
                <p className="text-xs text-blue-400 font-medium pt-1">
                  {currentStep}
                </p>
              </div>

              {/* Prochaine étape : cadrage humain */}
              <div className="text-left bg-slate-950/70 rounded-xl p-4 border border-slate-800 space-y-3">
                <div className="flex items-start space-x-3">
                  <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 shrink-0 mt-0.5">
                    <PhoneCall className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-xs font-semibold text-slate-200 uppercase tracking-wider">
                      Prochaine étape
                    </h3>
                    <p className="text-xs text-slate-300 mt-0.5">
                      {nextStep}
                    </p>
                    <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">
                      Notre équipe prépare votre conteneur dédié et calibre vos agents. Un appel de cadrage permet de valider vos accès et intégrations avant la mise en service.
                    </p>
                  </div>
                </div>

                <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-xs">
                  <div className="flex items-center space-x-2 text-slate-300">
                    <UserCheck className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Référent : <strong className="text-slate-200">{contactPerson}</strong></span>
                  </div>
                  <a
                    href={`mailto:${contactEmail}`}
                    className="flex items-center space-x-1.5 text-blue-400 hover:text-blue-300 transition font-medium"
                  >
                    <Mail className="w-3.5 h-3.5" />
                    <span>{contactEmail}</span>
                  </a>
                </div>
              </div>

              {/* Statut honnête & rafraîchissement automatique */}
              <div className="flex items-center justify-between text-xs text-slate-400 pt-1 px-1">
                <span className="flex items-center space-x-1.5">
                  <Loader2 className={`w-3.5 h-3.5 ${isChecking ? 'animate-spin text-blue-400' : 'text-slate-500'}`} />
                  <span>Actualisation automatique active</span>
                </span>
                <button
                  onClick={checkStatus}
                  disabled={isChecking}
                  className="flex items-center space-x-1 text-slate-400 hover:text-slate-200 transition"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isChecking ? 'animate-spin' : ''}`} />
                  <span>Actualiser</span>
                </button>
              </div>
            </div>
          )}

          {/* Cas 2 : Environnement en veille */}
          {status === 'sleeping' && (
            <div className="space-y-6 text-center">
              <div className="w-16 h-16 rounded-2xl bg-amber-500/20 border border-amber-500/40 text-amber-400 flex items-center justify-center mx-auto">
                <Moon className="w-8 h-8" />
              </div>

              <div>
                <h2 className="text-xl font-bold text-slate-100">Votre espace d’agents est en veille.</h2>
                <p className="text-sm text-slate-400 mt-2">
                  Pour préserver vos ressources, votre espace d’agents a été mis en sommeil.
                  Cliquez sur le bouton ci-dessous pour le relancer.
                </p>
              </div>

              <button
                onClick={handleWake}
                disabled={isWaking}
                className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-medium flex items-center justify-center space-x-2 transition shadow-lg shadow-blue-500/20 disabled:opacity-50"
              >
                {isWaking ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Réveil en cours...</span>
                  </>
                ) : (
                  <>
                    <Cpu className="w-4 h-4" />
                    <span>Réveiller mon espace maintenant</span>
                  </>
                )}
              </button>
            </div>
          )}

          {/* Cas 3 : Incident ou Erreur (M4) */}
          {status === 'error' && (
            <div className="space-y-6 text-center">
              <div className="w-16 h-16 rounded-2xl bg-rose-500/20 border border-rose-500/40 text-rose-400 flex items-center justify-center mx-auto">
                <AlertOctagon className="w-8 h-8" />
              </div>

              <div>
                <h2 className="text-xl font-bold text-slate-100">
                  Votre espace Orso Agents : nous avons besoin d'un échange.
                </h2>
                <p className="text-sm text-slate-400 mt-2">
                  Une difficulté technique a été rencontrée lors de la préparation de votre environnement.
                </p>
              </div>

              {errorDetails && (
                <div className="bg-rose-950/40 border border-rose-900/60 rounded-xl p-3 text-xs text-rose-300 text-left font-mono">
                  {errorDetails}
                </div>
              )}

              <div className="flex flex-col sm:flex-row gap-3 pt-2">
                <a
                  href={`mailto:${contactEmail}?subject=Aide%20deploiement%20espace%20${tenantSlug || ''}`}
                  className="flex-1 py-2.5 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium flex items-center justify-center space-x-2 border border-slate-700 transition"
                >
                  <Mail className="w-4 h-4" />
                  <span>Contacter {contactPerson}</span>
                </a>
                <button
                  onClick={checkStatus}
                  className="flex-1 py-2.5 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium flex items-center justify-center space-x-2 transition"
                >
                  <RefreshCw className="w-4 h-4" />
                  <span>Réessayer la connexion</span>
                </button>
              </div>
            </div>
          )}

          {/* Cas 4 : Organisation non configurée */}
          {status === 'not_configured' && (
            <div className="space-y-6 text-center">
              <div className="w-16 h-16 rounded-2xl bg-slate-800 border border-slate-700 text-slate-400 flex items-center justify-center mx-auto">
                <Server className="w-8 h-8" />
              </div>

              <div>
                <h2 className="text-xl font-bold text-slate-100">Organisation en attente de configuration</h2>
                <p className="text-sm text-slate-400 mt-2">
                  Aucune organisation n'est encore activement rattachée à votre compte. Notre équipe d'exploitation est à votre disposition pour débloquer votre accès.
                </p>
              </div>

              <div className="pt-2">
                <a
                  href={`mailto:${contactEmail}?subject=Rattachement%20organisation%20${tenantSlug || ''}`}
                  className="inline-flex items-center space-x-2 py-2.5 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition"
                >
                  <Mail className="w-4 h-4" />
                  <span>Contacter l'exploitation ({contactPerson})</span>
                </a>
              </div>
            </div>
          )}

          {/* Cas 5 : Prêt */}
          {status === 'ready' && (
            <div className="space-y-6 text-center">
              <div className="w-16 h-16 rounded-2xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 flex items-center justify-center mx-auto">
                <CheckCircle2 className="w-8 h-8" />
              </div>

              <div>
                <h2 className="text-xl font-bold text-slate-100">Votre espace Orso Agents est prêt.</h2>
                <p className="text-sm text-slate-400 mt-2">
                  Votre espace sécurisé est opérationnel. Vos agents IA sont disponibles.
                </p>
              </div>

              <button
                onClick={onReady}
                className="w-full py-3 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-medium flex items-center justify-center space-x-2 transition"
              >
                <span>Accéder à mes agents</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </main>

      {/* Footer sécurité souveraine */}
      <footer className="max-w-4xl w-full mx-auto pt-6 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-500">
        <div className="flex items-center space-x-2">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span>Hébergement souverain étanche en France • Chiffrement de bout en bout</span>
        </div>
        <span>Orso Agents v1.1.0</span>
      </footer>
    </div>
  );
};
