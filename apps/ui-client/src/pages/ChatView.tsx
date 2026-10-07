import React, { useState, useEffect, useRef } from 'react';
import { Agent, AgentId, ChatMessage, ActionCardData, ClientSession } from '@/types';
import { ORSO_AGENTS } from '@/lib/data';
import {
  sendUserPrompt,
  checkBackendHealth,
  getStoredUser,
  listClientSessions,
  renameClientSession,
  deleteClientSession,
  getSessionMessages,
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
  Folder,
  Plus,
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

  // Gestion de l'historique des conversations (KAN-83)
  const [isHistoryOpen, setIsHistoryOpen] = useState<boolean>(true);
  const [sessionsList, setSessionsList] = useState<ClientSession[]>([]);
  const [isSessionsLoading, setIsSessionsLoading] = useState<boolean>(false);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editTitleInput, setEditTitleInput] = useState<string>('');
  const [sessionToDelete, setSessionToDelete] = useState<ClientSession | null>(null);

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

  // Charger la liste des sessions pour l'agent actif
  const loadSessionsHistory = async (_preferredSid?: string) => {
    setIsSessionsLoading(true);
    try {
      const data = await listClientSessions(activeAgentId);
      setSessionsList(data.sessions || []);
    } catch (err) {
      console.warn("Impossible de charger la liste des conversations:", err);
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
        sid
      );
      setMessages((prev) => {
        const next = [...prev, assistantMsg];
        localStorage.setItem(getMessagesStorageKey(sid), JSON.stringify(next));
        return next;
      });
      setStreamingText('');
      // Rafraîchir l'historique pour afficher le nouveau titre automatique (CA1)
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
    // CA4: Le bouton Nouvelle discussion ouvre une nouvelle session différente
    // sans détruire la précédente, qui reste dans le magasin du moteur
    const newSid = generateNewSessionId(activeAgentId);
    localStorage.setItem(getSessionStorageKey(activeAgentId), newSid);
    setCurrentSessionId(newSid);
    setMessages([]);
    setStreamingText('');
    setIsLoading(false);
    setEditingSessionId(null);
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
      console.error("Erreur renommage:", err);
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

        {/* Bouton Nouvelle Discussion dans le volet */}
        <div className="p-3 border-b border-slate-800/60">
          <button
            onClick={handleResetChat}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/30 text-emerald-300 text-xs font-semibold transition-all shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Nouvelle discussion</span>
          </button>
        </div>

        {/* Bandeau de Rétention 60 Jours (CA7) */}
        <div className="px-3 py-2 bg-slate-950/60 border-b border-slate-800/40 flex items-center gap-1.5 text-[11px] text-slate-400">
          <Clock className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <span>Conservation : <strong className="text-slate-300 font-semibold">60 jours</strong></span>
        </div>

        {/* Liste des conversations de l'agent */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {isSessionsLoading ? (
            <div className="py-8 text-center text-xs text-slate-500">Chargement de l'historique...</div>
          ) : sessionsList.length === 0 ? (
            <div className="py-8 px-4 text-center text-xs text-slate-500">
              Aucune conversation archivée pour cet agent.
            </div>
          ) : (
            sessionsList.map((s) => {
              const isSelected = s.session_id === currentSessionId;
              const isEditing = editingSessionId === s.session_id;

              return (
                <div
                  key={s.session_id}
                  onClick={() => !isEditing && handleSelectSession(s)}
                  className={`group relative flex flex-col p-2.5 rounded-lg text-left transition-all cursor-pointer border ${
                    isSelected
                      ? 'bg-slate-800/90 border-emerald-500/50 text-white shadow-sm'
                      : 'hover:bg-slate-800/50 border-transparent text-slate-300'
                  }`}
                >
                  <div className="flex items-center justify-between gap-1.5 w-full">
                    <div className="flex items-center gap-2 overflow-hidden flex-1">
                      <MessageSquare className={`w-3.5 h-3.5 shrink-0 ${isSelected ? 'text-emerald-400' : 'text-slate-500'}`} />
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
                          <button
                            type="submit"
                            className="p-1 hover:text-emerald-400 text-slate-300"
                            title="Enregistrer"
                          >
                            <Check className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditingSessionId(null)}
                            className="p-1 hover:text-rose-400 text-slate-400"
                            title="Annuler"
                          >
                            <X className="w-3.5 h-3.5" />
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
                          title="Renommer"
                        >
                          <Edit3 className="w-3 h-3" />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setSessionToDelete(s);
                          }}
                          className="p-1 text-slate-400 hover:text-rose-400 rounded hover:bg-slate-700/60"
                          title="Supprimer"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Date et Dossier métier */}
                  <div className="flex items-center justify-between text-[10px] text-slate-500 mt-1">
                    <span>{formatSessionDate(s.last_activity_at || s.created_at)}</span>
                    {s.dossier_metier_id && (
                      <span className="flex items-center gap-1 text-indigo-400">
                        <Folder className="w-2.5 h-2.5" />
                        <span className="truncate max-w-[80px]">{s.dossier_metier_id}</span>
                      </span>
                    )}
                  </div>
                </div>
              );
            })
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
    </div>
  );
};
