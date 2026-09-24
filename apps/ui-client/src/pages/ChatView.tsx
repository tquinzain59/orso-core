import React, { useState, useEffect, useRef } from 'react';
import { AgentId, ChatMessage, ActionCardData } from '@/types';
import { ORSO_AGENTS } from '@/lib/data';
import { sendUserPrompt, checkBackendHealth } from '@/lib/api';
import { ActionCard } from '@/components/ActionCard';
import { QuickActions } from '@/components/QuickActions';
import {
  Send,
  RotateCcw,
  User,
} from 'lucide-react';

interface ChatViewProps {
  activeAgentId: AgentId;
}

export const ChatView: React.FC<ChatViewProps> = ({ activeAgentId }) => {
  const currentAgent = ORSO_AGENTS.find((a) => a.id === activeAgentId) || ORSO_AGENTS[0];
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [backendStatus, setBackendStatus] = useState<{ online: boolean; llmConnected?: boolean }>({ online: false });
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Probe live backend connection
  useEffect(() => {
    checkBackendHealth().then(setBackendStatus);
    const interval = setInterval(() => {
      checkBackendHealth().then(setBackendStatus);
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  // Initialize or reload conversation when active agent changes
  useEffect(() => {
    setMessages([]);
    setStreamingText('');
    setIsLoading(false);
  }, [activeAgentId]);

  // Auto-scroll to bottom on new messages
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingText, isLoading]);

  const handleSendMessage = async (textToSend?: string) => {
    const prompt = (textToSend || inputText).trim();
    if (!prompt || isLoading) return;

    setInputText('');
    const userTimestamp = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      agentId: activeAgentId,
      role: 'user',
      content: prompt,
      timestamp: userTimestamp,
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);
    setStreamingText('');

    try {
      const assistantMsg = await sendUserPrompt(activeAgentId, prompt, (delta) => {
        setStreamingText(delta);
      });
      setMessages((prev) => [...prev, assistantMsg]);
      setStreamingText('');
    } catch (err) {
      console.error(err);
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
    setMessages([]);
    setStreamingText('');
    setIsLoading(false);
  };

  const handleUpdateActionStatus = (actionId: string, status: ActionCardData['status'], feedback?: string) => {
    setMessages((prev) =>
      prev.map((msg) => {
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
      })
    );
  };

  return (
    <div className="flex flex-col h-full bg-slate-950 overflow-hidden relative">
      {/* Agent Top Header Bar */}
      <div className="px-6 py-3.5 border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md flex items-center justify-between z-10 shrink-0">
        <div className="flex items-center gap-3">
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
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-950/60 border border-emerald-800/40 text-emerald-400 font-medium flex items-center gap-1" title="Modèle IA actif (Gemini / OpenRouter)">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Connecté au LLM
                </span>
              ) : backendStatus.online ? (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-950/60 border border-amber-800/40 text-amber-400 font-medium flex items-center gap-1" title="Backend actif, clé API non renseignée">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  Backend actif (Clé requise)
                </span>
              ) : (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800/60 border border-slate-700/50 text-slate-400 font-medium flex items-center gap-1" title="Backend local ou Docker non connecté">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                  Mode démo locale
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
            title="Réinitialiser la conversation"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-800 transition-all"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Nouvelle discussion</span>
          </button>
        </div>
      </div>

      {/* Messages Scroll Area */}
      <div className={`flex-1 overflow-y-auto px-4 sm:px-6 py-6 ${messages.length === 0 ? 'flex flex-col justify-center' : 'space-y-6'}`}>
        {messages.length === 0 && !isLoading ? (
          <div className="flex flex-col items-center justify-center text-center p-6 max-w-xl mx-auto my-auto animate-in fade-in duration-300">
            <div
              className={`w-16 h-16 rounded-2xl flex items-center justify-center text-3xl mb-4 shadow-xl ${currentAgent.themeColor.bg} border ${currentAgent.themeColor.border}`}
            >
              {currentAgent.avatar}
            </div>
            <h3 className="text-lg font-bold text-white mb-1">
              Discussion avec {currentAgent.name}
            </h3>
            <span className={`text-xs px-2.5 py-0.5 rounded-full border font-semibold mb-3 ${currentAgent.themeColor.badge}`}>
              {currentAgent.role}
            </span>
            <p className="text-xs text-slate-400 mb-8 leading-relaxed max-w-md">
              {currentAgent.description}
            </p>

            <div className="w-full space-y-2.5">
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider text-left">
                Suggestions pour démarrer :
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-left">
                {currentAgent.quickActions.map((qa, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleSendMessage(qa.prompt)}
                    disabled={isLoading}
                    className="p-3.5 rounded-xl bg-slate-900/90 hover:bg-slate-850 border border-slate-800 hover:border-slate-700 text-xs text-slate-200 transition-all hover:scale-[1.01] active:scale-[0.99] flex flex-col gap-1.5 shadow-sm group"
                  >
                    <span className="font-semibold text-white group-hover:text-blue-400 transition-colors">
                      {qa.label}
                    </span>
                    <span className="text-[11px] text-slate-400 line-clamp-2">
                      {qa.prompt}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          messages.map((msg) => {
            const isUser = msg.role === 'user';
            return (
              <div
                key={msg.id}
                className={`flex gap-3 max-w-3xl ${isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'}`}
              >
                {/* Avatar Icon */}
                <div
                  className={`w-8 h-8 rounded-xl flex items-center justify-center text-sm shrink-0 mt-0.5 select-none ${
                    isUser
                      ? 'bg-blue-600 text-white shadow-md shadow-blue-900/40'
                      : `${currentAgent.themeColor.bg} border ${currentAgent.themeColor.border} text-white`
                  }`}
                >
                  {isUser ? <User className="w-4 h-4" /> : currentAgent.avatar}
                </div>

                {/* Message Content Bubble */}
                <div className="space-y-1 max-w-[88%] sm:max-w-[82%]">
                  <div className="flex items-center gap-2 px-1">
                    <span className="text-xs font-semibold text-slate-300">
                      {isUser ? 'Vous' : currentAgent.name}
                    </span>
                    <span className="text-[10px] text-slate-500">{msg.timestamp}</span>
                  </div>

                  <div
                    className={`p-4 rounded-2xl text-sm leading-relaxed ${
                      isUser
                        ? 'bg-blue-600 text-white rounded-tr-sm shadow-md'
                        : 'bg-slate-900/95 border border-slate-800/90 text-slate-200 rounded-tl-sm shadow-sm'
                    }`}
                  >
                    <div className="whitespace-pre-wrap space-y-2">
                      {msg.content}
                    </div>

                    {/* Interactive Action Card inside message */}
                    {msg.actionCard && (
                      <ActionCard
                        action={msg.actionCard}
                        onUpdateStatus={handleUpdateActionStatus}
                      />
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}

        {/* Live Streaming or Thinking Indicator */}
        {isLoading && (
          <div className="flex gap-3 max-w-3xl mr-auto">
            <div className={`w-8 h-8 rounded-xl flex items-center justify-center text-sm shrink-0 select-none ${currentAgent.themeColor.bg} border ${currentAgent.themeColor.border}`}>
              {currentAgent.avatar}
            </div>
            <div className="space-y-1 max-w-[82%]">
              <div className="flex items-center gap-2 px-1">
                <span className="text-xs font-semibold text-slate-300">{currentAgent.name}</span>
                <span className="text-[10px] text-blue-400 font-medium animate-pulse">En cours de réflexion...</span>
              </div>
              <div className="p-4 rounded-2xl bg-slate-900/95 border border-slate-800/90 text-slate-200 text-sm leading-relaxed rounded-tl-sm">
                {streamingText ? (
                  <div className="whitespace-pre-wrap">{streamingText}</div>
                ) : (
                  <div className="flex items-center gap-2 text-slate-400">
                    <span className="w-2 h-2 rounded-full bg-blue-500 animate-bounce" />
                    <span className="w-2 h-2 rounded-full bg-blue-500 animate-bounce [animation-delay:0.2s]" />
                    <span className="w-2 h-2 rounded-full bg-blue-500 animate-bounce [animation-delay:0.4s]" />
                    <span className="text-xs ml-1 font-medium text-slate-400">
                      {currentAgent.id === 'jerome'
                        ? 'Consultation de la balance âgée et des encours...'
                        : 'Analyse de votre demande...'}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Bottom Composer and Quick Actions Area */}
      <div className="px-4 sm:px-6 pb-4 pt-1 bg-gradient-to-t from-slate-950 via-slate-950 to-transparent border-t border-slate-900 shrink-0">
        {/* Quick Actions Pills */}
        <QuickActions
          agent={currentAgent}
          onTriggerPrompt={(prompt) => handleSendMessage(prompt)}
          disabled={isLoading}
        />

        {/* Input Bar */}
        <div className="relative mt-2 flex items-end gap-2 bg-slate-900/95 border border-slate-800 rounded-2xl p-2 shadow-2xl focus-within:border-blue-500/70 focus-within:ring-1 focus-within:ring-blue-500/30 transition-all">
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Posez votre question à ${currentAgent.name} ou demandez une action (Entrée pour envoyer)...`}
            rows={1}
            disabled={isLoading}
            className="flex-1 max-h-36 min-h-[44px] py-2 px-3 bg-transparent text-sm text-slate-100 placeholder-slate-500 focus:outline-none resize-none scrollbar-none font-sans"
          />

          <button
            onClick={() => handleSendMessage()}
            disabled={!inputText.trim() || isLoading}
            className="flex items-center justify-center w-10 h-10 rounded-xl bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:hover:bg-blue-600 transition-all shrink-0 shadow-md shadow-blue-900/40 active:scale-95"
            title="Envoyer le message"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>

        <p className="text-[11px] text-slate-500 text-center mt-2">
          Orso agents assiste votre entreprise • Vos données et vos échanges restent strictement confidentiels et sécurisés.
        </p>
      </div>
    </div>
  );
};
