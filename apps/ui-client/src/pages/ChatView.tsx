import React, { useState, useEffect, useRef } from 'react';
import { Agent, AgentId, ChatMessage, ActionCardData, ClientSession, ClientTheme } from '@/types';
import { ORSO_AGENTS } from '@/lib/data';
import {
  sendUserPrompt,
  checkBackendHealth,
  getStoredUser,
  listClientSessions,
  renameClientSession,
  deleteClientSession,
  getSessionMessages,
  listClientThemes,
  createClientTheme,
  renameClientTheme,
  deleteClientTheme,
  getClientThemeContext,
} from '@/lib/api';
import { ActionCard } from '@/components/ActionCard';
import { QuickActions } from '@/components/QuickActions';
import {
  Send,
  RotateCcw,
  User,
  History,
  Clock,
  MessageSquare,
  Edit3,
  Trash2,
  Check,
  X,
  ChevronLeft,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderPlus,
  Plus,
  Sparkles,
} from 'lucide-react';

interface ChatViewProps {
  activeAgentId: AgentId;
  availableAgents?: Agent[];
}

function getSessionStorageKey(agentId: string): string {
  const user = getStoredUser();
  const userId = user?.id || user?.sub || user?.email || 'default';
  const tenantSlug = user?.tenant?.tenant_slug || user?.tenant_slug || 'default';
  return `orso_session_${tenantSlug}_${userId}_${agentId}`;
}

function getMessagesStorageKey(sessionId: string): string {
  return `orso_messages_${sessionId}`;
}

function generateNewSessionId(agentId: string): string {
  const user = getStoredUser();
  const userId = (user?.id || user?.sub || user?.email || 'user').toString().replace(/[^a-zA-Z0-9_-]/g, '_');
  const rand = Math.random().toString(36).substring(2, 10);
  return `session_${agentId}_${userId}_${Date.now()}_${rand}`;
}

function formatSessionDate(timestamp: number): string {
  if (!timestamp) return '';
  const date = new Date(timestamp * 1000);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 3600 * 24));

  if (diffDays === 0) {
    return `Aujourd'hui à ${date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`;
  } else if (diffDays === 1) {
    return `Hier à ${date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`;
  } else {
    return date.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
  }
}

export const ChatView: React.FC<ChatViewProps> = ({ activeAgentId, availableAgents }) => {
  const agentsList = availableAgents && availableAgents.length > 0 ? availableAgents : ORSO_AGENTS;
  const currentAgent = agentsList.find((a) => a.id === activeAgentId) || agentsList[0] || ORSO_AGENTS[0];
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>('');
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [backendStatus, setBackendStatus] = useState<{ online: boolean; llmConnected?: boolean }>({ online: false });

  // Gestion de l'historique des conversations et thèmes (KAN-83, KAN-84, KAN-85)
  const [isHistoryOpen, setIsHistoryOpen] = useState<boolean>(true);
  const [sessionsList, setSessionsList] = useState<ClientSession[]>([]);
  const [themesList, setThemesList] = useState<ClientTheme[]>([]);
  const [activeThemeId, setActiveThemeId] = useState<string | null>(null);
  const [collapsedThemes, setCollapsedThemes] = useState<Record<string, boolean>>({});
  const [isSessionsLoading, setIsSessionsLoading] = useState<boolean>(false);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editTitleInput, setEditTitleInput] = useState<string>('');
  const [sessionToDelete, setSessionToDelete] = useState<ClientSession | null>(null);

  // États pour les thèmes (KAN-84, KAN-85)
  const [isCreatingTheme, setIsCreatingTheme] = useState<boolean>(false);
  const [newThemeTitleInput, setNewThemeTitleInput] = useState<string>('');
  const [editingThemeId, setEditingThemeId] = useState<string | null>(null);
  const [editThemeTitleInput, setEditThemeTitleInput] = useState<string>('');
  const [themeToDelete, setThemeToDelete] = useState<ClientTheme | null>(null);
  const [deleteThemeWithSessions, setDeleteThemeWithSessions] = useState<boolean>(false);
  const [themeContextInfo, setThemeContextInfo] = useState<{ hasContext: boolean; lengthChars: number; tokensEst: number } | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const storedUser = getStoredUser();
  const tenantName = storedUser?.tenant?.name || storedUser?.tenant?.tenant_slug || 'Espace Client';

  // Probe live backend connection
  useEffect(() => {
    checkBackendHealth().then(setBackendStatus);
    const interval = setInterval(() => {
      checkBackendHealth().then(setBackendStatus);
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  // Charger la liste des sessions et thèmes pour l'agent actif
  const loadSessionsHistory = async (_preferredSid?: string) => {
    setIsSessionsLoading(true);
    try {
      const [sessionsData, themesData] = await Promise.all([
        listClientSessions(activeAgentId),
        listClientThemes(activeAgentId),
      ]);
      setSessionsList(sessionsData.sessions || []);
      setThemesList(themesData.themes || []);
    } catch (err) {
      console.warn("Impossible de charger la liste des conversations ou thèmes:", err);
    } finally {
      setIsSessionsLoading(false);
    }
  };

  // Initialize or reload conversation when active agent changes (survives page reload - CA3)
  useEffect(() => {
    const key = getSessionStorageKey(activeAgentId);
    let sid = localStorage.getItem(key);
    if (!sid) {
      sid = generateNewSessionId(activeAgentId);
      localStorage.setItem(key, sid);
    }
    setCurrentSessionId(sid);

    // Recharger les messages de la conversation active pour cet agent
    const saved = localStorage.getItem(getMessagesStorageKey(sid));
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          setMessages(parsed);
        } else {
          setMessages([]);
        }
      } catch {
        setMessages([]);
      }
    } else {
      setMessages([]);
    }

    setStreamingText('');
    setIsLoading(false);
    loadSessionsHistory(sid);
  }, [activeAgentId]);

  // Auto-scroll to bottom on new messages
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingText, isLoading]);

  const handleSelectSession = async (session: ClientSession) => {
    if (session.session_id === currentSessionId) return;

    setCurrentSessionId(session.session_id);
    localStorage.setItem(getSessionStorageKey(activeAgentId), session.session_id);
    const themeId = session.dossier_metier_id || null;
    setActiveThemeId(themeId);

    if (themeId) {
      getClientThemeContext(themeId, session.session_id, activeAgentId)
        .then((ctx) => setThemeContextInfo({ hasContext: ctx.has_context, lengthChars: ctx.length_chars, tokensEst: ctx.tokens_est }))
        .catch(() => setThemeContextInfo(null));
    } else {
      setThemeContextInfo(null);
    }

    setIsLoading(true);

    try {
      const data = await getSessionMessages(activeAgentId, session.session_id);
      if (data && Array.isArray(data.messages) && data.messages.length > 0) {
        const formatted: ChatMessage[] = data.messages.map((m, idx) => ({
          id: `msg-${session.session_id}-${idx}`,
          agentId: activeAgentId,
          role: m.role as any,
          content: m.content,
          timestamp: m.timestamp || new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }),
        }));
        setMessages(formatted);
        localStorage.setItem(getMessagesStorageKey(session.session_id), JSON.stringify(formatted));
      } else {
        // Fallback local storage
        const saved = localStorage.getItem(getMessagesStorageKey(session.session_id));
        if (saved) {
          try {
            setMessages(JSON.parse(saved));
          } catch {
            setMessages([]);
          }
        } else {
          setMessages([]);
        }
      }
    } catch (err: any) {
      console.warn("Erreur lors de la récupération des messages de la session:", err);
      const saved = localStorage.getItem(getMessagesStorageKey(session.session_id));
      if (saved) {
        try {
          setMessages(JSON.parse(saved));
        } catch {
          setMessages([]);
        }
      } else {
        setMessages([]);
      }
    } finally {
      setIsLoading(false);
      setStreamingText('');
    }
  };

  const handleSendMessage = async (textToSend?: string) => {
    const prompt = (textToSend || inputText).trim();
    if (!prompt || isLoading) return;

    let sid = currentSessionId;
    if (!sid) {
      sid = generateNewSessionId(activeAgentId);
      localStorage.setItem(getSessionStorageKey(activeAgentId), sid);
      setCurrentSessionId(sid);
    }

    setInputText('');
    const userTimestamp = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      agentId: activeAgentId,
      role: 'user',
      content: prompt,
      timestamp: userTimestamp,
    };

    const updatedWithUser = [...messages, userMsg];
    setMessages(updatedWithUser);
    localStorage.setItem(getMessagesStorageKey(sid), JSON.stringify(updatedWithUser));

    setIsLoading(true);
    setStreamingText('');

    try {
      const assistantMsg = await sendUserPrompt(
        activeAgentId,
        prompt,
        (delta) => {
          setStreamingText(delta);
        },
        sid,
        activeThemeId || undefined
      );
      setMessages((prev) => {
        const next = [...prev, assistantMsg];
        localStorage.setItem(getMessagesStorageKey(sid), JSON.stringify(next));
        return next;
      });
      setStreamingText('');
      // Rafraîchir l'historique et les thèmes pour afficher le nouveau thème en 4 mots (KAN-84)
      loadSessionsHistory(sid);
    } catch (err: any) {
      console.error("Erreur lors de l'envoi du message :", err);
      const errorMsg: ChatMessage = {
        id: `err-${Date.now()}`,
        agentId: activeAgentId,
        role: 'assistant',
        content: `⚠️ Erreur : ${err?.message || "Impossible de joindre l'agent."}`,
        timestamp: new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => {
        const next = [...prev, errorMsg];
        localStorage.setItem(getMessagesStorageKey(sid), JSON.stringify(next));
        return next;
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleResetChat = () => {
    // CA4: Nouvelle discussion neutre / hors-thème
    const newSid = generateNewSessionId(activeAgentId);
    localStorage.setItem(getSessionStorageKey(activeAgentId), newSid);
    setCurrentSessionId(newSid);
    setActiveThemeId(null);
    setThemeContextInfo(null);
    setMessages([]);
    setStreamingText('');
    setIsLoading(false);
    setEditingSessionId(null);
  };

  const handleStartSessionInTheme = (themeId: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    const newSid = generateNewSessionId(activeAgentId);
    localStorage.setItem(getSessionStorageKey(activeAgentId), newSid);
    setCurrentSessionId(newSid);
    setActiveThemeId(themeId);
    setMessages([]);
    setStreamingText('');
    setIsLoading(false);
    setEditingSessionId(null);

    // Charger immédiatement le contexte de reprise pour ce thème (KAN-85)
    getClientThemeContext(themeId, newSid, activeAgentId)
      .then((ctx) => setThemeContextInfo({ hasContext: ctx.has_context, lengthChars: ctx.length_chars, tokensEst: ctx.tokens_est }))
      .catch(() => setThemeContextInfo(null));
  };

  const handleCreateTheme = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanTitle = newThemeTitleInput.trim();
    if (!cleanTitle) return;

    try {
      const res = await createClientTheme(cleanTitle, activeAgentId);
      if (res.success && res.theme) {
        setThemesList((prev) => [res.theme, ...prev]);
        setNewThemeTitleInput('');
        setIsCreatingTheme(false);
        // Démarrer une conversation directement rattachée à ce thème
        handleStartSessionInTheme(res.theme.theme_id);
      }
    } catch (err) {
      console.error("Erreur création thème:", err);
      alert("Impossible de créer le thème.");
    }
  };

  const handleStartRename = (session: ClientSession, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingSessionId(session.session_id);
    setEditTitleInput(session.title);
  };

  const handleSaveRename = async (sessionId: string, e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!editTitleInput.trim()) return;

    try {
      await renameClientSession(sessionId, editTitleInput.trim(), activeAgentId);
      setSessionsList((prev) =>
        prev.map((s) => (s.session_id === sessionId ? { ...s, title: editTitleInput.trim(), title_source: 'user' } : s))
      );
      setEditingSessionId(null);
    } catch (err) {
      console.error("Erreur renommage session:", err);
      alert("Impossible de renommer la discussion.");
    }
  };

  const handleConfirmDelete = async () => {
    if (!sessionToDelete) return;
    const sid = sessionToDelete.session_id;

    try {
      await deleteClientSession(sid, activeAgentId);
      localStorage.removeItem(getMessagesStorageKey(sid));
      setSessionsList((prev) => prev.filter((s) => s.session_id !== sid));

      if (currentSessionId === sid) {
        handleResetChat();
      }
      setSessionToDelete(null);
    } catch (err) {
      console.error("Erreur suppression session:", err);
      alert("Impossible de supprimer la discussion.");
    }
  };

  const handleStartThemeRename = (theme: ClientTheme, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingThemeId(theme.theme_id);
    setEditThemeTitleInput(theme.title);
  };

  const handleSaveThemeRename = async (themeId: string, e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!editThemeTitleInput.trim()) return;

    try {
      const res = await renameClientTheme(themeId, editThemeTitleInput.trim());
      if (res.success) {
        setThemesList((prev) =>
          prev.map((t) => (t.theme_id === themeId ? { ...t, title: res.title, title_source: 'user' } : t))
        );
        setEditingThemeId(null);
      }
    } catch (err) {
      console.error("Erreur renommage thème:", err);
      alert("Impossible de renommer le thème.");
    }
  };

  const handleConfirmDeleteTheme = async () => {
    if (!themeToDelete) return;
    const tid = themeToDelete.theme_id;

    try {
      await deleteClientTheme(tid, deleteThemeWithSessions);
      setThemesList((prev) => prev.filter((t) => t.theme_id !== tid));
      if (deleteThemeWithSessions) {
        setSessionsList((prev) => prev.filter((s) => s.dossier_metier_id !== tid));
      } else {
        setSessionsList((prev) =>
          prev.map((s) => (s.dossier_metier_id === tid ? { ...s, dossier_metier_id: null } : s))
        );
      }

      if (activeThemeId === tid) {
        handleResetChat();
      }
      setThemeToDelete(null);
      setDeleteThemeWithSessions(false);
    } catch (err) {
      console.error("Erreur suppression thème:", err);
      alert("Impossible de supprimer le thème.");
    }
  };

  const toggleThemeCollapse = (themeId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setCollapsedThemes((prev) => ({ ...prev, [themeId]: !prev[themeId] }));
  };

  const handleUpdateActionStatus = (actionId: string, status: ActionCardData['status'], feedback?: string) => {
    setMessages((prev) => {
      const updated = prev.map((msg) => {
        if (msg.actionCard && msg.actionCard.id === actionId) {
          return {
            ...msg,
            actionCard: {
              ...msg.actionCard,
              status,
              feedbackMessage: feedback,
            },
          };
        }
        return msg;
      });
      if (currentSessionId) {
        localStorage.setItem(getMessagesStorageKey(currentSessionId), JSON.stringify(updated));
      }
      return updated;
    });
  };

  return (
    <div className="flex h-full w-full bg-slate-950 overflow-hidden relative">
      {/* ── VOLET LATÉRAL HISTORIQUE DES CONVERSATIONS (KAN-83) ── */}
      <div
        className={`border-r border-slate-800/80 bg-slate-900/95 flex flex-col shrink-0 transition-all duration-300 z-20 ${
          isHistoryOpen ? 'w-72 sm:w-80' : 'w-0 -translate-x-full overflow-hidden border-none'
        }`}
      >
        {/* Header Historique */}
        <div className="p-3.5 border-b border-slate-800/80 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-emerald-400" />
            <span className="text-xs font-bold text-white uppercase tracking-wider">Historique</span>
          </div>
          <button
            onClick={() => setIsHistoryOpen(false)}
            className="p-1 rounded-md text-slate-400 hover:text-white hover:bg-slate-800"
            title="Masquer l'historique"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        </div>

        {/* Boutons d'actions rapides dans le volet : Nouvelle discussion & Nouveau thème */}
        <div className="p-3 border-b border-slate-800/60 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={handleResetChat}
              className={`flex items-center justify-center gap-1.5 px-2.5 py-2 rounded-lg border text-xs font-semibold transition-all shadow-sm ${
                activeThemeId === null && messages.length === 0
                  ? 'bg-emerald-600 text-white border-emerald-500'
                  : 'bg-emerald-600/15 hover:bg-emerald-600/25 border-emerald-500/30 text-emerald-300'
              }`}
              title="Ouvrir une nouvelle discussion libre"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Discussion</span>
            </button>
            <button
              onClick={() => setIsCreatingTheme(!isCreatingTheme)}
              className="flex items-center justify-center gap-1.5 px-2.5 py-2 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 text-xs font-semibold transition-all shadow-sm"
              title="Créer un nouveau thème de conversation"
            >
              <FolderPlus className="w-3.5 h-3.5" />
              <span>Thème</span>
            </button>
          </div>

          {/* Formulaire inline de création de thème */}
          {isCreatingTheme && (
            <form onSubmit={handleCreateTheme} className="p-2 rounded-lg bg-slate-950 border border-indigo-500/40 space-y-1.5">
              <div className="flex items-center justify-between text-[11px] text-indigo-300 font-medium">
                <span>Nouveau thème (4 mots max)</span>
                <button type="button" onClick={() => setIsCreatingTheme(false)} className="text-slate-400 hover:text-white">
                  <X className="w-3 h-3" />
                </button>
              </div>
              <div className="flex items-center gap-1">
                <input
                  type="text"
                  placeholder="Ex: Audit Trésorerie 2026"
                  value={newThemeTitleInput}
                  onChange={(e) => setNewThemeTitleInput(e.target.value)}
                  autoFocus
                  className="flex-1 text-xs bg-slate-900 border border-slate-700 rounded px-2 py-1 text-white focus:outline-none focus:border-indigo-400"
                />
                <button
                  type="submit"
                  disabled={!newThemeTitleInput.trim()}
                  className="px-2 py-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-xs font-semibold rounded transition-all"
                >
                  Créer
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Bandeau de Rétention 60 Jours (CA7) */}
        <div className="px-3 py-1.5 bg-slate-950/60 border-b border-slate-800/40 flex items-center justify-between text-[11px] text-slate-400">
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-amber-400 shrink-0" />
            <span>Conservation : <strong className="text-slate-300 font-semibold">60j</strong></span>
          </div>
          <span className="text-[10px] text-slate-500">{themesList.length} thèmes</span>
        </div>

        {/* Liste des conversations organisées par blocs de thèmes (KAN-84, KAN-85) */}
        <div className="flex-1 overflow-y-auto p-2 space-y-3">
          {isSessionsLoading ? (
            <div className="py-8 text-center text-xs text-slate-500">Chargement de l'historique...</div>
          ) : (
            <>
              {/* Carte provisoire : Nouvelle discussion en cours (non écrite en DB - CA7) */}
              {messages.length === 0 && !sessionsList.some((s) => s.session_id === currentSessionId) && (
                <div className="p-2 rounded-lg border border-dashed border-emerald-500/40 bg-emerald-950/10 text-slate-300">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-3.5 h-3.5 text-emerald-400 animate-pulse shrink-0" />
                    <span className="text-xs font-semibold text-emerald-300">
                      {activeThemeId ? `Nouvelle discussion dans le thème` : `Nouvelle discussion`}
                    </span>
                  </div>
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    {activeThemeId
                      ? `Le contexte des échanges précédents sera repris pour répondre.`
                      : `Le thème en 4 mots sera généré dès le premier message.`}
                  </p>
                </div>
              )}

              {/* Blocs de Thèmes (KAN-84) */}
              {themesList.map((theme) => {
                const isCollapsed = Boolean(collapsedThemes[theme.theme_id]);
                const themeSessions = sessionsList.filter((s) => s.dossier_metier_id === theme.theme_id);
                const isEditingTheme = editingThemeId === theme.theme_id;
                const isThemeActive = activeThemeId === theme.theme_id;

                return (
                  <div
                    key={theme.theme_id}
                    className={`rounded-xl border transition-all ${
                      isThemeActive
                        ? 'border-indigo-500/50 bg-indigo-950/20 shadow-sm'
                        : 'border-slate-800/80 bg-slate-900/60'
                    }`}
                  >
                    {/* Entête du Thème */}
                    <div className="group flex items-center justify-between p-2 hover:bg-slate-800/40 rounded-t-xl transition-colors">
                      <div
                        className="flex items-center gap-1.5 flex-1 min-w-0 cursor-pointer"
                        onClick={(e) => toggleThemeCollapse(theme.theme_id, e)}
                      >
                        <button
                          type="button"
                          className="p-0.5 text-slate-400 hover:text-white"
                          title={isCollapsed ? 'Déplier le thème' : 'Plier le thème'}
                        >
                          {isCollapsed ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                        </button>
                        <Folder className={`w-3.5 h-3.5 shrink-0 ${isThemeActive ? 'text-indigo-400' : 'text-slate-400'}`} />

                        {isEditingTheme ? (
                          <form
                            onSubmit={(e) => handleSaveThemeRename(theme.theme_id, e)}
                            className="flex items-center gap-1 flex-1"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <input
                              type="text"
                              value={editThemeTitleInput}
                              onChange={(e) => setEditThemeTitleInput(e.target.value)}
                              autoFocus
                              className="w-full text-xs bg-slate-950 border border-indigo-500 rounded px-1.5 py-0.5 text-white focus:outline-none"
                            />
                            <button type="submit" className="p-1 hover:text-emerald-400 text-slate-300">
                              <Check className="w-3 h-3" />
                            </button>
                            <button type="button" onClick={() => setEditingThemeId(null)} className="p-1 hover:text-rose-400 text-slate-400">
                              <X className="w-3 h-3" />
                            </button>
                          </form>
                        ) : (
                          <span className="text-xs font-bold text-slate-200 truncate" title={theme.title}>
                            {theme.title}
                          </span>
                        )}
                        <span className="text-[10px] text-slate-500 font-mono px-1 rounded bg-slate-800">
                          {themeSessions.length}
                        </span>
                      </div>

                      {/* Actions du thème : Nouveau dans ce thème (+), renommer, supprimer */}
                      {!isEditingTheme && (
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={(e) => handleStartSessionInTheme(theme.theme_id, e)}
                            className="p-1 text-emerald-400 hover:text-emerald-300 rounded hover:bg-emerald-950/40 transition-colors"
                            title="Nouvelle conversation au sein de ce thème (continuité de contexte KAN-85)"
                          >
                            <Plus className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={(e) => handleStartThemeRename(theme, e)}
                            className="p-1 text-slate-500 hover:text-slate-300 rounded hover:bg-slate-700/40 opacity-0 group-hover:opacity-100 transition-opacity"
                            title="Renommer le thème"
                          >
                            <Edit3 className="w-3 h-3" />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setThemeToDelete(theme);
                            }}
                            className="p-1 text-slate-500 hover:text-rose-400 rounded hover:bg-slate-700/40 opacity-0 group-hover:opacity-100 transition-opacity"
                            title="Supprimer le thème"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Liste des conversations au sein du thème */}
                    {!isCollapsed && (
                      <div className="p-1.5 pt-0 space-y-1">
                        {themeSessions.length === 0 ? (
                          <div className="py-2 px-2 text-center text-[10px] text-slate-500">
                            Aucune discussion archivée. Cliquez sur <span className="text-emerald-400 font-bold">+</span> pour démarrer.
                          </div>
                        ) : (
                          themeSessions.map((s) => {
                            const isSelected = s.session_id === currentSessionId;
                            const isEditing = editingSessionId === s.session_id;

                            return (
                              <div
                                key={s.session_id}
                                onClick={() => !isEditing && handleSelectSession(s)}
                                className={`group relative flex flex-col p-2 rounded-lg text-left transition-all cursor-pointer border ${
                                  isSelected
                                    ? 'bg-slate-800/90 border-emerald-500/50 text-white shadow-sm'
                                    : 'hover:bg-slate-800/40 border-transparent text-slate-300'
                                }`}
                              >
                                <div className="flex items-center justify-between gap-1.5 w-full">
                                  <div className="flex items-center gap-1.5 overflow-hidden flex-1">
                                    <MessageSquare className={`w-3 h-3 shrink-0 ${isSelected ? 'text-emerald-400' : 'text-slate-500'}`} />
                                    {isEditing ? (
                                      <form
                                        onSubmit={(e) => handleSaveRename(s.session_id, e)}
                                        className="flex items-center gap-1 flex-1"
                                        onClick={(e) => e.stopPropagation()}
                                      >
                                        <input
                                          type="text"
                                          value={editTitleInput}
                                          onChange={(e) => setEditTitleInput(e.target.value)}
                                          autoFocus
                                          className="w-full text-xs bg-slate-950 border border-emerald-500 rounded px-1.5 py-0.5 text-white focus:outline-none"
                                        />
                                        <button type="submit" className="p-1 hover:text-emerald-400 text-slate-300">
                                          <Check className="w-3 h-3" />
                                        </button>
                                        <button type="button" onClick={() => setEditingSessionId(null)} className="p-1 hover:text-rose-400 text-slate-400">
                                          <X className="w-3 h-3" />
                                        </button>
                                      </form>
                                    ) : (
                                      <span className="text-xs font-medium truncate flex-1" title={s.title}>
                                        {s.title}
                                      </span>
                                    )}
                                  </div>

                                  {!isEditing && (
                                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                      <button
                                        onClick={(e) => handleStartRename(s, e)}
                                        className="p-1 text-slate-400 hover:text-white rounded hover:bg-slate-700/60"
                                        title="Renommer la discussion"
                                      >
                                        <Edit3 className="w-2.5 h-2.5" />
                                      </button>
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setSessionToDelete(s);
                                        }}
                                        className="p-1 text-slate-400 hover:text-rose-400 rounded hover:bg-slate-700/60"
                                        title="Supprimer la discussion"
                                      >
                                        <Trash2 className="w-2.5 h-2.5" />
                                      </button>
                                    </div>
                                  )}
                                </div>
                                <div className="text-[10px] text-slate-500 mt-0.5">
                                  {formatSessionDate(s.last_activity_at || s.created_at)}
                                </div>
                              </div>
                            );
                          })
                        )}
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Discussions hors-thèmes */}
              {(() => {
                const unassignedSessions = sessionsList.filter(
                  (s) => !s.dossier_metier_id || !themesList.some((t) => t.theme_id === s.dossier_metier_id)
                );
                if (unassignedSessions.length === 0) return null;

                return (
                  <div className="space-y-1 pt-1">
                    <div className="px-1 text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      Autres discussions
                    </div>
                    {unassignedSessions.map((s) => {
                      const isSelected = s.session_id === currentSessionId;
                      const isEditing = editingSessionId === s.session_id;

                      return (
                        <div
                          key={s.session_id}
                          onClick={() => !isEditing && handleSelectSession(s)}
                          className={`group relative flex flex-col p-2 rounded-lg text-left transition-all cursor-pointer border ${
                            isSelected
                              ? 'bg-slate-800/90 border-emerald-500/50 text-white shadow-sm'
                              : 'hover:bg-slate-800/50 border-transparent text-slate-300'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-1.5 w-full">
                            <div className="flex items-center gap-1.5 overflow-hidden flex-1">
                              <MessageSquare className={`w-3 h-3 shrink-0 ${isSelected ? 'text-emerald-400' : 'text-slate-500'}`} />
                              {isEditing ? (
                                <form
                                  onSubmit={(e) => handleSaveRename(s.session_id, e)}
                                  className="flex items-center gap-1 flex-1"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <input
                                    type="text"
                                    value={editTitleInput}
                                    onChange={(e) => setEditTitleInput(e.target.value)}
                                    autoFocus
                                    className="w-full text-xs bg-slate-950 border border-emerald-500 rounded px-1.5 py-0.5 text-white focus:outline-none"
                                  />
                                  <button type="submit" className="p-1 hover:text-emerald-400 text-slate-300">
                                    <Check className="w-3 h-3" />
                                  </button>
                                  <button type="button" onClick={() => setEditingSessionId(null)} className="p-1 hover:text-rose-400 text-slate-400">
                                    <X className="w-3 h-3" />
                                  </button>
                                </form>
                              ) : (
                                <span className="text-xs font-medium truncate flex-1" title={s.title}>
                                  {s.title}
                                </span>
                              )}
                            </div>

                            {!isEditing && (
                              <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                <button
                                  onClick={(e) => handleStartRename(s, e)}
                                  className="p-1 text-slate-400 hover:text-white rounded hover:bg-slate-700/60"
                                  title="Renommer la discussion"
                                >
                                  <Edit3 className="w-2.5 h-2.5" />
                                </button>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setSessionToDelete(s);
                                  }}
                                  className="p-1 text-slate-400 hover:text-rose-400 rounded hover:bg-slate-700/60"
                                  title="Supprimer la discussion"
                                >
                                  <Trash2 className="w-2.5 h-2.5" />
                                </button>
                              </div>
                            )}
                          </div>
                          <div className="text-[10px] text-slate-500 mt-0.5">
                            {formatSessionDate(s.last_activity_at || s.created_at)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </>
          )}
        </div>

        {/* Footer info tenant */}
        <div className="p-3 border-t border-slate-800/80 bg-slate-950/40 text-[10px] text-slate-500 flex items-center justify-between">
          <span className="truncate max-w-[160px]">{tenantName}</span>
          <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono text-[9px]">{currentAgent.name}</span>
        </div>
      </div>

      {/* ── ZONE DE DISCUSSION PRINCIPALE ── */}
      <div className="flex flex-col flex-1 h-full overflow-hidden relative">
        {/* Agent Top Header Bar */}
        <div className="px-6 py-3.5 border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md flex items-center justify-between z-10 shrink-0">
          <div className="flex items-center gap-3">
            {!isHistoryOpen && (
              <button
                onClick={() => setIsHistoryOpen(true)}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 transition-all mr-1 shadow-sm"
                title="Ouvrir l'historique des conversations"
              >
                <History className="w-3.5 h-3.5 text-emerald-400" />
                <span className="hidden sm:inline">Historique</span>
                {sessionsList.length > 0 && (
                  <span className="ml-0.5 px-1.5 py-0.2 rounded-full bg-slate-700 text-[10px] text-slate-300">
                    {sessionsList.length}
                  </span>
                )}
              </button>
            )}

            <div className="relative">
              <span className="text-2xl select-none">{currentAgent.avatar}</span>
              <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-400 ring-2 ring-slate-900" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-base font-bold text-white">{currentAgent.name}</h2>
                <span className={`text-[11px] px-2 py-0.5 rounded-full border font-semibold ${currentAgent.themeColor.badge}`}>
                  {currentAgent.role}
                </span>
                {backendStatus.online && backendStatus.llmConnected ? (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-950/60 border border-emerald-800/40 text-emerald-400 font-medium flex items-center gap-1" title="Modèle IA actif">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    Connecté au LLM
                  </span>
                ) : backendStatus.online ? (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-950/60 border border-amber-800/40 text-amber-400 font-medium flex items-center gap-1" title="Backend actif">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                    Backend actif
                  </span>
                ) : (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800/60 border border-slate-700/50 text-slate-400 font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                    Mode hors-ligne
                  </span>
                )}

                {/* Badge Thème Actif et Continuité (KAN-84, KAN-85) */}
                {(() => {
                  const currentTheme = themesList.find((t) => t.theme_id === activeThemeId);
                  if (!currentTheme) return null;
                  return (
                    <div className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-indigo-950/70 border border-indigo-700/50 text-indigo-300 text-[11px] font-medium shadow-sm">
                      <Folder className="w-3 h-3 text-indigo-400" />
                      <span className="truncate max-w-[140px] sm:max-w-[200px]" title={currentTheme.title}>
                        {currentTheme.title}
                      </span>
                      {themeContextInfo && themeContextInfo.hasContext ? (
                        <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-mono ml-0.5" title={`Reprise de contexte active : ${themeContextInfo.lengthChars} car. (~${themeContextInfo.tokensEst} tokens)`}>
                          <Sparkles className="w-2.5 h-2.5 text-emerald-400" />
                          <span>Continuité</span>
                        </span>
                      ) : (
                        <span className="text-[10px] text-slate-400 ml-0.5 font-mono">1ère conv.</span>
                      )}
                    </div>
                  );
                })()}
              </div>
              <p className="text-xs text-slate-400 mt-0.5 hidden sm:block">
                {currentAgent.description}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleResetChat}
              title="Nouvelle discussion (mint un identifiant neuf sans perdre les conversations antérieures)"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-300 hover:text-white hover:bg-slate-800 border border-slate-800 transition-all shadow-sm"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Nouvelle discussion</span>
            </button>
          </div>
        </div>

        {/* Messages Scroll Area */}
        <div className={`flex-1 overflow-y-auto px-4 sm:px-6 py-6 ${messages.length === 0 ? 'flex flex-col justify-center' : 'space-y-6'}`}>
          {messages.length === 0 && !isLoading ? (
            <div className="max-w-2xl mx-auto w-full text-center space-y-6">
              <div className="inline-flex p-4 rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl">
                <span className="text-5xl select-none">{currentAgent.avatar}</span>
              </div>
              <div>
                <h3 className="text-lg font-bold text-white mb-2">
                  Comment puis-je vous aider aujourd'hui ?
                </h3>
                <p className="text-sm text-slate-400 max-w-md mx-auto">
                  {currentAgent.description}
                </p>
              </div>

              {/* Suggestions d'actions rapides */}
              <div className="pt-2">
                <QuickActions agent={currentAgent} onTriggerPrompt={(p: string) => handleSendMessage(p)} />
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex gap-3 max-w-3xl ${
                    msg.role === 'user' ? 'ml-auto justify-end' : 'mr-auto justify-start'
                  }`}
                >
                  {msg.role !== 'user' && (
                    <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-base shrink-0 select-none shadow-sm">
                      {currentAgent.avatar}
                    </div>
                  )}

                  <div className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'} max-w-[85%] sm:max-w-[75%]`}>
                    <div
                      className={`px-4 py-3 rounded-2xl text-sm leading-relaxed shadow-sm whitespace-pre-wrap ${
                        msg.role === 'user'
                          ? 'bg-emerald-600 text-white rounded-br-none'
                          : 'bg-slate-900 border border-slate-800 text-slate-200 rounded-bl-none'
                      }`}
                    >
                      {msg.content}
                    </div>

                    {/* Carte d'Action 1-Click interactive si attachée */}
                    {msg.actionCard && (
                      <div className="mt-3 w-full">
                        <ActionCard
                          action={msg.actionCard}
                          onUpdateStatus={(actionId, status, feedback) => handleUpdateActionStatus(actionId, status, feedback)}
                        />
                      </div>
                    )}

                    <span className="text-[10px] text-slate-500 mt-1 px-1">
                      {msg.timestamp}
                    </span>
                  </div>

                  {msg.role === 'user' && (
                    <div className="w-8 h-8 rounded-full bg-emerald-950 border border-emerald-800 flex items-center justify-center text-xs text-emerald-400 shrink-0 select-none">
                      <User className="w-4 h-4" />
                    </div>
                  )}
                </div>
              ))}

              {/* Streaming token display */}
              {isLoading && streamingText && (
                <div className="flex gap-3 max-w-3xl mr-auto justify-start">
                  <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-base shrink-0 select-none">
                    {currentAgent.avatar}
                  </div>
                  <div className="flex flex-col items-start max-w-[85%] sm:max-w-[75%]">
                    <div className="px-4 py-3 rounded-2xl text-sm leading-relaxed shadow-sm whitespace-pre-wrap bg-slate-900 border border-slate-800 text-slate-200 rounded-bl-none">
                      {streamingText}
                      <span className="inline-block w-1.5 h-3.5 bg-emerald-400 ml-1 animate-pulse" />
                    </div>
                  </div>
                </div>
              )}

              {/* Loading spinner */}
              {isLoading && !streamingText && (
                <div className="flex gap-3 max-w-3xl mr-auto justify-start items-center text-slate-500 text-xs py-2">
                  <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-base shrink-0 select-none">
                    {currentAgent.avatar}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                    <span>{currentAgent.name} réfléchit...</span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Input Bar */}
        <div className="p-4 border-t border-slate-800/80 bg-slate-900/60 backdrop-blur-md shrink-0">
          <div className="max-w-3xl mx-auto flex items-end gap-2 bg-slate-950 border border-slate-800 rounded-xl p-2 focus-within:border-emerald-500/50 transition-all">
            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Message à ${currentAgent.name}...`}
              rows={1}
              className="flex-1 bg-transparent border-0 resize-none text-sm text-slate-200 placeholder-slate-500 focus:outline-none max-h-32 min-h-[38px] py-1.5 px-2"
            />
            <button
              onClick={() => handleSendMessage()}
              disabled={!inputText.trim() || isLoading}
              className="p-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:hover:bg-emerald-600 text-white transition-all shrink-0 shadow-md"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* ── MODALE DE CONFIRMATION DE SUPPRESSION (CA4) ── */}
      {sessionToDelete && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center gap-3 text-rose-400">
              <Trash2 className="w-5 h-5 shrink-0" />
              <h3 className="text-base font-bold text-white">Supprimer la conversation ?</h3>
            </div>
            <p className="text-sm text-slate-300">
              Cette action supprimera définitivement la discussion :
              <br />
              <strong className="text-white mt-1 block">« {sessionToDelete.title} »</strong>
            </p>
            <p className="text-xs text-slate-500">
              Les messages seront effacés du serveur et du magasin de données. Cette opération est irréversible.
            </p>
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setSessionToDelete(null)}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-slate-400 hover:text-white hover:bg-slate-800 border border-slate-800 transition-all"
              >
                Annuler
              </button>
              <button
                onClick={handleConfirmDelete}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-white bg-rose-600 hover:bg-rose-500 transition-all shadow-md"
              >
                Confirmer la suppression
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── MODALE DE CONFIRMATION DE SUPPRESSION DE THÈME (KAN-84 CA5) ── */}
      {themeToDelete && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center gap-3 text-rose-400">
              <Trash2 className="w-5 h-5 shrink-0" />
              <h3 className="text-base font-bold text-white">Supprimer le thème ?</h3>
            </div>
            <p className="text-sm text-slate-300">
              Vous êtes sur le point de supprimer le thème :
              <br />
              <strong className="text-white mt-1 block">« {themeToDelete.title} »</strong>
            </p>
            <div className="p-3 bg-slate-950/70 rounded-xl border border-slate-800 space-y-2">
              <label className="flex items-start gap-2.5 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={deleteThemeWithSessions}
                  onChange={(e) => setDeleteThemeWithSessions(e.target.checked)}
                  className="mt-0.5 rounded border-slate-700 bg-slate-900 text-rose-500 focus:ring-rose-500"
                />
                <span>
                  Supprimer également toutes les discussions archivées dans ce thème ({sessionsList.filter((s) => s.dossier_metier_id === themeToDelete.theme_id).length} conversation(s)).
                  <br />
                  <span className="text-[11px] text-slate-500">Si décoché, les conversations seront simplement détachées du thème sans être effacées.</span>
                </span>
              </label>
            </div>
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => {
                  setThemeToDelete(null);
                  setDeleteThemeWithSessions(false);
                }}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-slate-400 hover:text-white hover:bg-slate-800 border border-slate-800 transition-all"
              >
                Annuler
              </button>
              <button
                onClick={handleConfirmDeleteTheme}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-white bg-rose-600 hover:bg-rose-500 transition-all shadow-md"
              >
                Confirmer la suppression
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
