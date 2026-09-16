import React, { useState, useEffect } from 'react';
import { AgentId } from '@/types';
import { AgentSelector } from '@/components/AgentSelector';
import { ChatView } from '@/pages/ChatView';
import { IntegrationsView } from '@/pages/IntegrationsView';
import { ChannelsView } from '@/pages/ChannelsView';
import {
  checkBackendHealth,
  checkSessionMe,
  loginClient,
  logoutClient,
  getClientToken,
  setClientToken,
  getStoredUser,
} from '@/lib/api';
import {
  MessageSquare,
  Layers,
  Smartphone,
  ArrowLeft,
  Lock,
  LogOut,
  ShieldCheck,
  AlertTriangle,
  UserCheck,
} from 'lucide-react';

type Tab = 'chat' | 'integrations' | 'channels';

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<Tab>('chat');
  const [activeAgentId, setActiveAgentId] = useState<AgentId>('jerome');
  const [companyName, setCompanyName] = useState<string>('');
  const [userName, setUserName] = useState<string>('');
  const [userRole, setUserRole] = useState<string>('');
  const [backendStatus, setBackendStatus] = useState<{ online: boolean; version?: string }>({
    online: false,
  });

  // Authentification & Session
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [authLoading, setAuthLoading] = useState<boolean>(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [loginEmail, setLoginEmail] = useState<string>('sophie.martin@finarecee20.fr');
  const [loginPassword, setLoginPassword] = useState<string>('TempOrso2026!Financia');
  const [showLoginModal, setShowLoginModal] = useState<boolean>(false);

  // Synchronisation de la session au démarrage
  useEffect(() => {
    checkBackendHealth().then(setBackendStatus);

    // 1. Détection du jeton passé dans l'URL (SSO ou redirection Vercel)
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get('token') || params.get('access_token');
    if (urlToken) {
      setClientToken(urlToken);
      // Nettoyage de l'URL pour ne pas laisser le token visible dans l'historique
      const cleanUrl = window.location.pathname + (window.location.hash || '');
      window.history.replaceState({}, document.title, cleanUrl);
    }

    // 2. Vérification de la session auprès du backend
    checkSessionMe().then((res) => {
      if (res.authenticated && res.user) {
        setIsAuthenticated(true);
        setCompanyName(res.tenant?.name || res.tenant?.tenant_slug?.replace('-', ' ').toUpperCase() || 'Financia Solutions');
        setUserName(res.user?.full_name || res.user?.email || 'Sophie Martin');
        setUserRole(res.user?.role || 'DAF');
      } else {
        const stored = getStoredUser();
        if (stored && getClientToken()) {
          setIsAuthenticated(true);
          setCompanyName(stored.tenant?.name || 'Financia Solutions');
          setUserName(stored.full_name || 'Sophie Martin');
          setUserRole(stored.role || 'DAF');
        } else {
          setIsAuthenticated(false);
          setShowLoginModal(true);
        }
      }
      setAuthLoading(false);
    });

    // 3. Lecture des paramètres de sélection d'agent
    const agentParam = params.get('agent')?.toLowerCase();
    if (agentParam) {
      if (agentParam === 'recouvrement' || agentParam === 'jerome') {
        setActiveAgentId('jerome');
      } else if (agentParam === 'commercial' || agentParam === 'lucas') {
        setActiveAgentId('lucas');
      } else if (agentParam === 'support' || agentParam === 'service client' || agentParam === 'clara') {
        setActiveAgentId('clara');
      } else if (agentParam === 'ao' || agentParam === "appel d'offres" || agentParam === 'victor') {
        setActiveAgentId('victor');
      }
    }
  }, []);

  const handleLogin = async (e?: React.FormEvent, customEmail?: string, customPass?: string) => {
    if (e) e.preventDefault();
    setAuthLoading(true);
    setAuthError(null);

    const emailToUse = customEmail || loginEmail;
    const passToUse = customPass || loginPassword;

    const res = await loginClient(emailToUse, passToUse);
    setAuthLoading(false);

    if (res.success && res.user) {
      if (res.redirect_url && typeof window !== 'undefined' && !window.location.href.startsWith(res.redirect_url)) {
        window.location.href = res.redirect_url;
        return;
      }
      setIsAuthenticated(true);
      setShowLoginModal(false);
      setCompanyName(res.tenant?.name || 'Financia Solutions');
      setUserName(res.user?.full_name || res.user?.email || 'Sophie Martin');
      setUserRole(res.user?.role || 'DAF');
    } else {
      setAuthError(res.error || 'Identifiants invalides.');
    }
  };

  const handleLogout = async () => {
    await logoutClient();
    setIsAuthenticated(false);
    setCompanyName('');
    setUserName('');
    setUserRole('');
    setShowLoginModal(true);
  };

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-950 text-slate-100 font-sans select-none">
      {/* Top Navbar */}
      <header className="h-16 px-5 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-md flex items-center justify-between shrink-0 z-20">
        {/* Brand Logo & Title */}
        <div className="flex items-center gap-3">
          <a
            href="https://www.orso-agents.fr"
            className="flex items-center gap-3 group"
            title="Retour au site orso-agents.fr"
          >
            <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-blue-600 via-indigo-600 to-blue-700 flex items-center justify-center shadow-lg shadow-blue-900/40 ring-1 ring-white/20 group-hover:scale-105 transition-transform">
              <span className="text-xl font-black text-white tracking-tighter">O</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-extrabold tracking-tight text-white group-hover:text-blue-300 transition-colors">
                  Orso <span className="text-blue-400 font-normal">agents</span>
                </h1>
                <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-blue-950 border border-blue-800 text-blue-300">
                  CLIENT
                </span>
                {companyName && (
                  <span className="hidden sm:inline-block px-2 py-0.5 rounded-md text-[10px] font-semibold bg-slate-800 border border-slate-700 text-slate-300 truncate max-w-[140px]" title={companyName}>
                    {companyName}
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-400 font-medium">
                {userName ? `Pilotage • ${userName}` : 'Espace Dirigeant & Pilotage Opérationnel'}
              </p>
            </div>
          </a>
        </div>

        {/* Center Main Nav Tabs */}
        <nav className="flex items-center gap-1 bg-slate-950/80 p-1.5 rounded-2xl border border-slate-800">
          <button
            onClick={() => setCurrentTab('chat')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all ${
              currentTab === 'chat'
                ? 'bg-blue-600 text-white shadow-md shadow-blue-900/30 scale-100'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <MessageSquare className="w-4 h-4" />
            <span>Discussion</span>
          </button>

          <button
            onClick={() => setCurrentTab('integrations')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all ${
              currentTab === 'integrations'
                ? 'bg-blue-600 text-white shadow-md shadow-blue-900/30 scale-100'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <Layers className="w-4 h-4" />
            <span>Interfaces & ERP</span>
          </button>

          <button
            onClick={() => setCurrentTab('channels')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all ${
              currentTab === 'channels'
                ? 'bg-blue-600 text-white shadow-md shadow-blue-900/30 scale-100'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            <Smartphone className="w-4 h-4" />
            <span>Canaux (WhatsApp/Telegram)</span>
          </button>
        </nav>

        {/* Right Info and Navigation */}
        <div className="flex items-center gap-3">
          {/* User Session Badge or Login Button */}
          {isAuthenticated ? (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-850/90 border border-slate-700/80 text-xs shadow-inner">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span className="font-bold text-white tracking-tight">{companyName}</span>
                <span className="hidden md:inline text-slate-400">• {userName}</span>
                <span className="hidden lg:inline px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-950 text-blue-300 border border-blue-800">
                  {userRole}
                </span>
              </div>
              <button
                onClick={handleLogout}
                title="Se déconnecter"
                className="ml-1 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded-lg p-1 transition-all"
              >
                <LogOut className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowLoginModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-md shadow-blue-900/30 transition-all active:scale-95"
            >
              <Lock className="w-3.5 h-3.5" />
              <span>Connexion</span>
            </button>
          )}

          {/* Backend Status Dot */}
          <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-850/80 border border-slate-800 text-[11px] text-slate-300 font-medium">
            <span
              className={`w-2 h-2 rounded-full ${
                backendStatus.online ? 'bg-emerald-400 animate-pulse' : 'bg-blue-400'
              }`}
            />
            <span className="hidden md:inline">
              {backendStatus.online ? 'Moteur Orso Connecté' : 'Mode Autonome Actif'}
            </span>
          </div>

          {/* Bouton Retour Espace Client */}
          <a
            href="https://www.orso-agents.fr/client.html"
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-md shadow-blue-900/30 transition-all active:scale-95"
            title="Retour à mon tableau de bord client"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Espace Client</span>
          </a>
        </div>
      </header>

      {/* Sub-Header Agent Switcher (Visible in Chat Mode) */}
      {currentTab === 'chat' && (
        <div className="px-6 py-2.5 bg-slate-900/40 border-b border-slate-850 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 overflow-x-auto">
            <span className="text-xs font-bold text-slate-400 uppercase tracking-wider shrink-0 mr-1">
              Flotte d'agents :
            </span>
            <AgentSelector
              activeAgentId={activeAgentId}
              onSelectAgent={(id) => setActiveAgentId(id)}
            />
          </div>

          {/* Instance matching status pill */}
          <div className="hidden md:flex items-center gap-1.5 text-[11px] text-slate-400 bg-slate-950/70 border border-slate-800/80 px-2.5 py-1 rounded-lg">
            <ShieldCheck className="w-3.5 h-3.5 text-blue-400" />
            <span>Environnement privé • Isolation active</span>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 overflow-hidden flex flex-col">
        {currentTab === 'chat' && <ChatView activeAgentId={activeAgentId} />}
        {currentTab === 'integrations' && <IntegrationsView />}
        {currentTab === 'channels' && <ChannelsView />}
      </main>

      {/* Modal d'Authentification Sécurisée Client (Supabase IAM) */}
      {showLoginModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-in fade-in">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl shadow-blue-950/50 space-y-5">
            {/* Modal Header */}
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-blue-600 via-indigo-600 to-blue-700 flex items-center justify-center shadow-lg shadow-blue-900/40 text-white font-black text-xl">
                  O
                </div>
                <div>
                  <h3 className="text-base font-extrabold text-white">Espace Client Sécurisé</h3>
                  <p className="text-xs text-slate-400">Authentification IAM & Isolation Multi-Tenant</p>
                </div>
              </div>
              {isAuthenticated && (
                <button
                  onClick={() => setShowLoginModal(false)}
                  className="text-slate-400 hover:text-slate-200 text-xs px-2 py-1 rounded-lg hover:bg-slate-800 transition-all"
                >
                  Fermer
                </button>
              )}
            </div>

            {/* Info Instance */}
            <div className="p-3.5 rounded-2xl bg-blue-950/40 border border-blue-800/40 text-xs text-blue-200 space-y-1">
              <div className="flex items-center gap-1.5 font-bold text-blue-300">
                <ShieldCheck className="w-4 h-4 text-blue-400" />
                <span>Instance Conteneur Dédiée</span>
              </div>
              <p className="text-[11px] text-blue-200/80">
                Cette instance est privée et strictement cloisonnée. Seuls les utilisateurs habilités de votre organisation peuvent accéder à ces agents.
              </p>
            </div>

            {/* Message d'erreur */}
            {authError && (
              <div className="p-3 rounded-xl bg-rose-950/70 border border-rose-700/60 text-rose-200 text-xs flex items-start gap-2 animate-in fade-in">
                <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <span>{authError}</span>
              </div>
            )}

            {/* Formulaire Login */}
            <form onSubmit={(e) => handleLogin(e)} className="space-y-3.5">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Email professionnel
                </label>
                <input
                  type="email"
                  value={loginEmail}
                  onChange={(e) => setLoginEmail(e.target.value)}
                  placeholder="sophie.martin@finarecee20.fr"
                  required
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950/90 border border-slate-800 text-slate-100 text-xs focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40 transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Mot de passe
                </label>
                <input
                  type="password"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  placeholder="••••••••••••"
                  required
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950/90 border border-slate-800 text-slate-100 text-xs focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40 transition-all font-mono"
                />
              </div>

              <button
                type="submit"
                disabled={authLoading}
                className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-lg shadow-blue-900/30 transition-all disabled:opacity-50 flex items-center justify-center gap-2 active:scale-95"
              >
                {authLoading ? (
                  <span>Vérification IAM...</span>
                ) : (
                  <>
                    <Lock className="w-3.5 h-3.5" />
                    <span>Se connecter</span>
                  </>
                )}
              </button>
            </form>

            {/* Séparateur pour Tests 1-Clic */}
            <div className="relative flex items-center justify-center my-2">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-slate-800" />
              </div>
              <span className="relative px-3 bg-slate-900 text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                Validation & Démonstration
              </span>
            </div>

            {/* Boutons de test rapide */}
            <div className="space-y-2">
              <button
                type="button"
                disabled={authLoading}
                onClick={() =>
                  handleLogin(
                    undefined,
                    'sophie.martin@finarecee20.fr',
                    'TempOrso2026!Financia'
                  )
                }
                className="w-full p-2.5 rounded-xl bg-emerald-950/50 hover:bg-emerald-950/80 border border-emerald-700/50 text-emerald-200 text-xs font-semibold flex items-center justify-between transition-all group active:scale-95"
              >
                <div className="flex items-center gap-2">
                  <UserCheck className="w-4 h-4 text-emerald-400 group-hover:scale-110 transition-transform" />
                  <div className="text-left">
                    <p className="font-bold text-white">⚡ Connexion Sophie Martin</p>
                    <p className="text-[10px] text-emerald-300/80">Financia Solutions • DAF (Accès Autorisé)</p>
                  </div>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-900/80 border border-emerald-700 text-emerald-300 font-bold">
                  200 OK
                </span>
              </button>

              <button
                type="button"
                disabled={authLoading}
                onClick={() =>
                  handleLogin(
                    undefined,
                    'claire.dubois@servicallc322.com',
                    'TempOrso2026!Commercia'
                  )
                }
                className="w-full p-2.5 rounded-xl bg-rose-950/40 hover:bg-rose-950/70 border border-rose-800/40 text-rose-200 text-xs font-semibold flex items-center justify-between transition-all group active:scale-95"
              >
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-rose-400 group-hover:scale-110 transition-transform" />
                  <div className="text-left">
                    <p className="font-bold text-white">🚫 Test Compte Non Autorisé</p>
                    <p className="text-[10px] text-rose-300/80">Compte tiers (Rejet étanchéité attendu 403)</p>
                  </div>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded bg-rose-900/80 border border-rose-700 text-rose-300 font-bold">
                  403 Rejet
                </span>
              </button>

              <button
                type="button"
                disabled={authLoading}
                onClick={() =>
                  handleLogin(
                    undefined,
                    'test.sansenv@orso-agents.fr',
                    'TempOrso2026!SansEnv'
                  )
                }
                className="w-full p-2.5 rounded-xl bg-amber-950/40 hover:bg-amber-950/70 border border-amber-800/40 text-amber-200 text-xs font-semibold flex items-center justify-between transition-all group active:scale-95"
              >
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-amber-400 group-hover:scale-110 transition-transform" />
                  <div className="text-left">
                    <p className="font-bold text-white">⚠️ Test Sans Environnement</p>
                    <p className="text-[10px] text-amber-300/80">Aura Sans Env (Alerte Support Orso 404)</p>
                  </div>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded bg-amber-900/80 border border-amber-700 text-amber-300 font-bold">
                  404 Alerte
                </span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
