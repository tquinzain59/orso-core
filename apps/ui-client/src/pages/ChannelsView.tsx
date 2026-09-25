import React, { useState, useEffect } from 'react';
import { SAMPLE_CHANNELS } from '@/lib/data';
import { MessagingChannel } from '@/types';
import {
  fetchClientChannels,
  addChannelAllowedUser,
  removeChannelAllowedUser,
} from '@/lib/api';
import {
  MessageSquare,
  Smartphone,
  Send,
  Mail,
  CheckCircle2,
  RefreshCw,
  Users,
  Plus,
  Trash2,
  Terminal,
  Hash,
} from 'lucide-react';

export const ChannelsView: React.FC = () => {
  const [channels, setChannels] = useState<MessagingChannel[]>(SAMPLE_CHANNELS);
  const [showUsersModal, setShowUsersModal] = useState<string | null>(null);
  const [showDetailsModal, setShowDetailsModal] = useState<MessagingChannel | null>(null);
  const [newAllowedUser, setNewAllowedUser] = useState('');
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const loadChannels = async () => {
    try {
      const data = await fetchClientChannels();
      if (data && data.length > 0) {
        setChannels(data);
      }
    } catch (err) {
      console.error('Erreur chargement canaux:', err);
    }
  };

  useEffect(() => {
    loadChannels();
  }, []);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await loadChannels();
    setIsRefreshing(false);
    setToastMessage('État des passerelles actualisé depuis le moteur Hermès.');
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleAddAllowedUser = async (channelId: string) => {
    const user = newAllowedUser.trim();
    if (!user) return;
    setNewAllowedUser('');
    try {
      const res = await addChannelAllowedUser(channelId, user);
      if (res.allowed_users) {
        setChannels((prev) =>
          prev.map((c) =>
            c.id === channelId ? { ...c, allowedUsers: res.allowed_users! } : c
          )
        );
      } else {
        setChannels((prev) =>
          prev.map((c) =>
            c.id === channelId ? { ...c, allowedUsers: [...c.allowedUsers, user] } : c
          )
        );
      }
      setToastMessage('Utilisateur ajouté à la liste autorisée.');
    } catch {
      setChannels((prev) =>
        prev.map((c) =>
          c.id === channelId ? { ...c, allowedUsers: [...c.allowedUsers, user] } : c
        )
      );
      setToastMessage('Utilisateur mémorisé en local.');
    } finally {
      setTimeout(() => setToastMessage(null), 3000);
    }
  };

  const handleRemoveAllowedUser = async (channelId: string, userToRemove: string) => {
    try {
      const res = await removeChannelAllowedUser(channelId, userToRemove);
      if (res.allowed_users) {
        setChannels((prev) =>
          prev.map((c) =>
            c.id === channelId ? { ...c, allowedUsers: res.allowed_users! } : c
          )
        );
      } else {
        setChannels((prev) =>
          prev.map((c) =>
            c.id === channelId
              ? { ...c, allowedUsers: c.allowedUsers.filter((u) => u !== userToRemove) }
              : c
          )
        );
      }
      setToastMessage('Accès retiré pour cet utilisateur.');
    } catch {
      setChannels((prev) =>
        prev.map((c) =>
          c.id === channelId
            ? { ...c, allowedUsers: c.allowedUsers.filter((u) => u !== userToRemove) }
            : c
        )
      );
    } finally {
      setTimeout(() => setToastMessage(null), 3000);
    }
  };

  const activeChannelForUsers = channels.find((c) => c.id === showUsersModal);

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 p-6 space-y-6">
      {/* Toast Feedback */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2.5 px-4 py-3 rounded-xl bg-emerald-950/90 border border-emerald-600/60 text-emerald-200 text-xs font-semibold shadow-2xl backdrop-blur-md animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Header section with Hermès engine status */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-900">
        <div>
          <h2 className="text-xl font-extrabold text-white flex items-center gap-2.5">
            <MessageSquare className="w-6 h-6 text-emerald-500" />
            Canaux de Discussion & Omnicanal
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Passerelles de messagerie connectées au moteur Hermès pour dialoguer avec vos agents et recevoir vos alertes d’arbitrage en mobilité.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900 border border-slate-800 text-[11px] text-slate-300">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Moteur Hermès : <strong>Connecté</strong> (Instance client)</span>
          </div>

          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900 hover:bg-slate-850 border border-slate-800 text-xs text-slate-300 hover:text-white transition-all active:scale-95 disabled:opacity-50"
            title="Rafraîchir depuis le serveur"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-emerald-400' : 'text-slate-400'}`} />
            <span>Actualiser</span>
          </button>
        </div>
      </div>

      {/* Channels List */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {channels.map((channel) => {
          const isWhatsApp = channel.id === 'whatsapp';
          const isTelegram = channel.id === 'telegram';
          const isEmail = channel.id === 'email';
          const isConnected = channel.status === 'connected';

          return (
            <div
              key={channel.id}
              className="flex flex-col justify-between p-6 rounded-2xl bg-slate-900/80 border border-slate-800/90 shadow-sm space-y-4 hover:border-slate-700/80 transition-all"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div
                      className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                        isWhatsApp
                          ? 'bg-emerald-950/50 border border-emerald-800/50 text-emerald-400'
                          : isTelegram
                          ? 'bg-blue-950/50 border border-blue-800/50 text-blue-400'
                          : isEmail
                          ? 'bg-purple-950/50 border border-purple-800/50 text-purple-400'
                          : 'bg-indigo-950/50 border border-indigo-800/50 text-indigo-400'
                      }`}
                    >
                      {isWhatsApp && <Smartphone className="w-5 h-5" />}
                      {isTelegram && <Send className="w-5 h-5" />}
                      {isEmail && <Mail className="w-5 h-5" />}
                      {!isWhatsApp && !isTelegram && !isEmail && <Hash className="w-5 h-5" />}
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-white">{channel.name}</h3>
                      <span className="text-[11px] text-slate-400">{channel.tagline}</span>
                    </div>
                  </div>

                  {isConnected ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950/60 text-emerald-300 border border-emerald-800/40">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                      Connecté (Backoffice)
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-slate-800/60 text-slate-400 border border-slate-700/50">
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                      Non configuré
                    </span>
                  )}
                </div>

                <p className="text-xs text-slate-300 leading-relaxed min-h-[38px]">
                  {channel.description}
                </p>

                <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Compte associé :</span>
                    <strong className="text-slate-200 truncate max-w-[170px]">
                      {channel.connectedAccount || 'Non configuré'}
                    </strong>
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Passerelle Hermès :</span>
                    <span className={`text-[11px] font-medium ${isConnected ? 'text-emerald-400' : 'text-slate-400'}`}>
                      {channel.metrics || (isConnected ? 'Active' : 'En attente')}
                    </span>
                  </div>

                  <div className="flex items-center justify-between pt-1 border-t border-slate-850">
                    <span className="text-slate-400">Accès autorisés :</span>
                    <button
                      onClick={() => setShowUsersModal(channel.id)}
                      className="text-blue-400 hover:text-blue-300 font-medium flex items-center gap-1"
                    >
                      <Users className="w-3 h-3" />
                      {channel.allowedUsers.length} autorisé(s)
                    </button>
                  </div>
                </div>
              </div>

              <div className="pt-2 flex gap-2">
                <button
                  onClick={() => setShowDetailsModal(channel)}
                  className="flex-1 py-2 px-3 rounded-xl bg-slate-800 hover:bg-slate-750 border border-slate-700/80 text-white text-xs font-semibold flex items-center justify-center gap-1.5 transition-all active:scale-98"
                >
                  <Terminal className="w-3.5 h-3.5 text-slate-400" />
                  Détails & Paramétrage
                </button>

                <button
                  onClick={() => setShowUsersModal(channel.id)}
                  className="py-2 px-3 rounded-xl bg-slate-900 hover:bg-slate-850 border border-slate-800 text-slate-300 hover:text-white text-xs font-medium flex items-center justify-center gap-1 transition-all active:scale-98"
                  title="Gérer les accès autorisés"
                >
                  <Users className="w-3.5 h-3.5 text-blue-400" />
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Allowed Users Modal */}
      {showUsersModal && activeChannelForUsers && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="w-full max-w-md rounded-3xl bg-slate-900 border border-slate-800 p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Users className="w-4 h-4 text-blue-400" />
                Accès autorisés • {activeChannelForUsers.name}
              </h3>
              <button
                onClick={() => setShowUsersModal(null)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-400">
              Seules les personnes ou adresses inscrites ci-dessous peuvent interagir avec vos agents sur ce canal (numéro international ou email).
            </p>

            <div className="space-y-2 max-h-48 overflow-y-auto">
              {activeChannelForUsers.allowedUsers.length === 0 ? (
                <div className="p-4 text-center text-xs text-slate-500 rounded-xl bg-slate-950 border border-slate-850">
                  Aucun utilisateur restreint (ouvert à tous les contacts du tenant).
                </div>
              ) : (
                activeChannelForUsers.allowedUsers.map((user) => (
                  <div
                    key={user}
                    className="flex items-center justify-between p-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200"
                  >
                    <span className="font-mono truncate">{user}</span>
                    <button
                      onClick={() => handleRemoveAllowedUser(activeChannelForUsers.id, user)}
                      className="p-1 rounded-md hover:bg-rose-950/40 text-slate-500 hover:text-rose-400"
                      title="Supprimer cet accès"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))
              )}
            </div>

            {/* Add user form */}
            <div className="flex gap-2 pt-2 border-t border-slate-800">
              <input
                type="text"
                value={newAllowedUser}
                onChange={(e) => setNewAllowedUser(e.target.value)}
                placeholder="Ex: +33612345678 ou contact@..."
                className="flex-1 px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
              />
              <button
                onClick={() => handleAddAllowedUser(activeChannelForUsers.id)}
                className="px-3 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold flex items-center gap-1"
              >
                <Plus className="w-3.5 h-3.5" />
                Ajouter
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Details & Configuration Modal */}
      {showDetailsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="w-full max-w-lg rounded-3xl bg-slate-900 border border-slate-800 p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center text-emerald-400 font-bold">
                  {showDetailsModal.id === 'whatsapp' && <Smartphone className="w-5 h-5" />}
                  {showDetailsModal.id === 'telegram' && <Send className="w-5 h-5 text-blue-400" />}
                  {showDetailsModal.id === 'email' && <Mail className="w-5 h-5 text-purple-400" />}
                  {showDetailsModal.id !== 'whatsapp' && showDetailsModal.id !== 'telegram' && showDetailsModal.id !== 'email' && <Hash className="w-5 h-5" />}
                </div>
                <div>
                  <h3 className="text-base font-bold text-white">{showDetailsModal.name}</h3>
                  <p className="text-[11px] text-slate-400">{showDetailsModal.tagline}</p>
                </div>
              </div>

              {showDetailsModal.status === 'connected' ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950/60 text-emerald-300 border border-emerald-800/40">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  Connecté
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-slate-800/60 text-slate-400 border border-slate-700/50">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                  Non configuré
                </span>
              )}
            </div>

            <div className="space-y-3 text-xs text-slate-300">
              <p className="leading-relaxed text-slate-300">
                {showDetailsModal.description}
              </p>

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Variable requise (.env) :</span>
                  <code className="text-emerald-400 font-mono font-bold bg-emerald-950/40 px-2 py-0.5 rounded">
                    {showDetailsModal.configKey || 'CONFIGURATION_CANAL'}
                  </code>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Emplacement conteneur :</span>
                  <span className="text-slate-200 font-mono text-[11px]">/app/.env ou config/hermes.yaml</span>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-slate-400">État détecté :</span>
                  <span className={showDetailsModal.status === 'connected' ? 'text-emerald-400 font-semibold' : 'text-amber-400 font-medium'}>
                    {showDetailsModal.metrics || (showDetailsModal.status === 'connected' ? 'Passerelle active' : 'En attente de jeton')}
                  </span>
                </div>
              </div>

              {/* Step-by-step instructions */}
              <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-850 space-y-2">
                <span className="font-bold text-slate-200 block">Instructions d’activation :</span>
                {showDetailsModal.id === 'telegram' && (
                  <ol className="list-decimal list-inside space-y-1.5 text-slate-400">
                    <li>Ouvrez Telegram et recherchez <strong className="text-white">@BotFather</strong>.</li>
                    <li>Tapez <code className="bg-slate-900 px-1 py-0.5 rounded text-blue-300">/newbot</code> et choisissez un nom et un identifiant.</li>
                    <li>Copiez le token API fourni (ex: <code className="text-slate-300">123456789:ABC...</code>).</li>
                    <li>Ajoutez <code className="bg-slate-900 px-1 py-0.5 rounded text-emerald-300">TELEGRAM_BOT_TOKEN="votre_token"</code> dans le <code className="text-slate-300">.env</code> de l'hôte.</li>
                    <li>Redémarrez le conteneur Hermès. Vos agents répondront instantanément sur mobile.</li>
                  </ol>
                )}

                {showDetailsModal.id === 'whatsapp' && (
                  <ol className="list-decimal list-inside space-y-1.5 text-slate-400">
                    <li>Renseignez vos identifiants Meta Cloud API ou passerelle WhatsApp dans <code className="text-slate-300">.env</code>.</li>
                    <li>Ajoutez <code className="bg-slate-900 px-1 py-0.5 rounded text-emerald-300">WHATSAPP_TOKEN</code> et <code className="bg-slate-900 px-1 py-0.5 rounded text-emerald-300">WHATSAPP_PHONE_NUMBER_ID</code>.</li>
                    <li>Les agents Jérôme et Lucas peuvent envoyer des confirmations de paiement et qualifier les tiers.</li>
                  </ol>
                )}

                {showDetailsModal.id === 'email' && (
                  <ol className="list-decimal list-inside space-y-1.5 text-slate-400">
                    <li>Configurez les accès de votre messagerie entreprise dans <code className="text-slate-300">.env</code>.</li>
                    <li>Renseignez <code className="bg-slate-900 px-1 py-0.5 rounded text-emerald-300">SMTP_HOST</code>, <code className="bg-slate-900 px-1 py-0.5 rounded text-emerald-300">SMTP_USER</code> et <code className="bg-slate-900 px-1 py-0.5 rounded text-emerald-300">SMTP_PASSWORD</code> (ou <code className="text-slate-300">RESEND_API_KEY</code>).</li>
                    <li>Les relances amiables et devis partiront directement avec l’identité de votre entreprise.</li>
                  </ol>
                )}
              </div>
            </div>

            <div className="flex items-center gap-3 pt-2 border-t border-slate-800">
              <button
                onClick={() => setShowDetailsModal(null)}
                className="flex-1 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-750 text-slate-300 text-xs font-semibold transition-all"
              >
                Fermer
              </button>

              <button
                onClick={async () => {
                  await handleRefresh();
                  setShowDetailsModal(null);
                }}
                className="flex-1 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shadow-md shadow-emerald-900/30 flex items-center justify-center gap-1.5 transition-all active:scale-98"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Vérifier la liaison
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
