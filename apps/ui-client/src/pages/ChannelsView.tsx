import React, { useState, useEffect } from 'react';
import QRCode from 'qrcode';
import { SAMPLE_CHANNELS } from '@/lib/data';
import { MessagingChannel } from '@/types';
import {
  fetchClientChannels,
  addChannelAllowedUser,
  removeChannelAllowedUser,
} from '@/lib/api';
import {
  MessageSquare,
  QrCode,
  Smartphone,
  Send,
  Mail,
  CheckCircle2,
  RefreshCw,
  ShieldCheck,
  Users,
  Plus,
  Trash2,
} from 'lucide-react';

export const ChannelsView: React.FC = () => {
  const [channels, setChannels] = useState<MessagingChannel[]>(SAMPLE_CHANNELS);
  const [showQrModal, setShowQrModal] = useState(false);
  const [qrCodeDataUrl, setQrCodeDataUrl] = useState<string>('');
  const [qrCountdown, setQrCountdown] = useState(60);
  const [showUsersModal, setShowUsersModal] = useState<string | null>(null);
  const [newAllowedUser, setNewAllowedUser] = useState('');
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchClientChannels().then((data) => {
      if (data && data.length > 0) {
        setChannels(data);
      }
    });
  }, []);

  // Generate QR Code on demand
  const handleOpenQrModal = async () => {
    setShowQrModal(true);
    setQrCountdown(60);
    try {
      // Simulates real WhatsApp pairing token
      const pairingString = `2@OrsoAgents-${Date.now()}-AuthSession-FR`;
      const dataUrl = await QRCode.toDataURL(pairingString, {
        width: 260,
        margin: 2,
        color: {
          dark: '#0f172a',
          light: '#ffffff',
        },
      });
      setQrCodeDataUrl(dataUrl);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    let timer: any;
    if (showQrModal && qrCountdown > 0) {
      timer = setInterval(() => setQrCountdown((prev) => prev - 1), 1000);
    }
    return () => clearInterval(timer);
  }, [showQrModal, qrCountdown]);

  const handleSimulatePairSuccess = () => {
    setShowQrModal(false);
    setChannels((prev) =>
      prev.map((c) =>
        c.id === 'whatsapp' ? { ...c, status: 'connected', connectedAccount: '+33 6 42 00 12 34 (Connecté)' } : c
      )
    );
    setToastMessage('WhatsApp Business associé avec succès !');
    setTimeout(() => setToastMessage(null), 4000);
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
      setToastMessage('Utilisateur ajouté.');
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
    } catch {
      setChannels((prev) =>
        prev.map((c) =>
          c.id === channelId
            ? { ...c, allowedUsers: c.allowedUsers.filter((u) => u !== userToRemove) }
            : c
        )
      );
    }
  };

  const activeChannelForUsers = channels.find((c) => c.id === showUsersModal);

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 p-6 space-y-6">
      {/* Toast Feedback */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2.5 px-4 py-3 rounded-xl bg-emerald-950/90 border border-emerald-600/60 text-emerald-200 text-xs font-semibold shadow-2xl backdrop-blur-md">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Header section */}
      <div>
        <h2 className="text-xl font-extrabold text-white flex items-center gap-2.5">
          <MessageSquare className="w-6 h-6 text-emerald-500" />
          Canaux de Discussion & Omnicanal
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Configurez les passerelles de messagerie instantanée (WhatsApp, Telegram, Email) pour permettre à vos agents d’interagir avec vos clients et vous alerter en mobilité.
        </p>
      </div>

      {/* Channels List */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {channels.map((channel) => {
          const isWhatsApp = channel.id === 'whatsapp';
          const isTelegram = channel.id === 'telegram';

          return (
            <div
              key={channel.id}
              className="flex flex-col justify-between p-6 rounded-2xl bg-slate-900/80 border border-slate-800/90 shadow-sm space-y-4"
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
                          : 'bg-purple-950/50 border border-purple-800/50 text-purple-400'
                      }`}
                    >
                      {isWhatsApp && <Smartphone className="w-5 h-5" />}
                      {isTelegram && <Send className="w-5 h-5" />}
                      {!isWhatsApp && !isTelegram && <Mail className="w-5 h-5" />}
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-white">{channel.name}</h3>
                      <span className="text-[11px] text-slate-400">{channel.tagline}</span>
                    </div>
                  </div>
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950/60 text-emerald-300 border border-emerald-800/40">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    {channel.status === 'connected' ? 'Connecté' : 'Actif'}
                  </span>
                </div>

                <p className="text-xs text-slate-300 leading-relaxed min-h-[38px]">
                  {channel.description}
                </p>

                <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Compte associé :</span>
                    <strong className="text-slate-200 truncate max-w-[170px]">{channel.connectedAccount}</strong>
                  </div>
                  {channel.stats && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-400">Échanges aujourd'hui :</span>
                      <span className="text-emerald-400 font-bold">{channel.stats.messagesToday} messages</span>
                    </div>
                  )}
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

              <div className="pt-2">
                {isWhatsApp ? (
                  <button
                    onClick={handleOpenQrModal}
                    className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shadow-md shadow-emerald-950/40 transition-all active:scale-98"
                  >
                    <QrCode className="w-4 h-4" />
                    Scanner le QR Code d'appairage
                  </button>
                ) : isTelegram ? (
                  <button
                    onClick={() => alert("Votre bot Telegram est déjà associé. Entrez /status dans votre chat Telegram pour vérifier.")}
                    className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-md shadow-blue-950/40 transition-all active:scale-98"
                  >
                    <ShieldCheck className="w-4 h-4" />
                    Gérer les accès Telegram
                  </button>
                ) : (
                  <button
                    onClick={() => alert("La passerelle email utilise les paramètres SMTP/IMAP sécurisés d'Orso.")}
                    className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-slate-800 hover:bg-slate-750 border border-slate-700 text-white text-xs font-bold transition-all active:scale-98"
                  >
                    <RefreshCw className="w-4 h-4 text-slate-400" />
                    Tester la réception des e-mails
                  </button>
                )}
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
              Seules les personnes ou adresses inscrites ci-dessous peuvent interagir avec l'agent sur ce canal.
            </p>

            <div className="space-y-2 max-h-48 overflow-y-auto">
              {activeChannelForUsers.allowedUsers.map((user) => (
                <div
                  key={user}
                  className="flex items-center justify-between p-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200"
                >
                  <span className="font-mono truncate">{user}</span>
                  <button
                    onClick={() => handleRemoveAllowedUser(activeChannelForUsers.id, user)}
                    className="p-1 rounded-md hover:bg-rose-950/40 text-slate-500 hover:text-rose-400"
                    title="Supprimer"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>

            {/* Add user form */}
            <div className="flex gap-2 pt-2 border-t border-slate-800">
              <input
                type="text"
                value={newAllowedUser}
                onChange={(e) => setNewAllowedUser(e.target.value)}
                placeholder="Ex: +33612345678 ou id"
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

      {/* WhatsApp QR Modal */}
      {showQrModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="w-full max-w-md rounded-3xl bg-slate-900 border border-slate-800 p-6 space-y-5 shadow-2xl text-center">
            <div className="space-y-1.5">
              <h3 className="text-lg font-bold text-white flex items-center justify-center gap-2">
                <QrCode className="w-5 h-5 text-emerald-400" />
                Lier votre WhatsApp Business
              </h3>
              <p className="text-xs text-slate-400">
                Scannez ce code QR avec votre application WhatsApp pour connecter votre agent en toute sécurité.
              </p>
            </div>

            {/* QR Code Container */}
            <div className="flex flex-col items-center justify-center p-4 bg-white rounded-2xl shadow-inner max-w-[280px] mx-auto">
              {qrCodeDataUrl ? (
                <img src={qrCodeDataUrl} alt="WhatsApp QR Code" className="w-56 h-56 rounded-lg" />
              ) : (
                <div className="w-56 h-56 flex items-center justify-center text-slate-400">
                  Génération du code...
                </div>
              )}
              <span className="text-[11px] text-slate-600 font-medium mt-2">
                Expire dans <strong className="text-slate-900 font-bold">{qrCountdown} secondes</strong>
              </span>
            </div>

            {/* Steps Instructions */}
            <div className="text-left p-3.5 rounded-xl bg-slate-950 border border-slate-800/80 text-xs space-y-1.5 text-slate-300">
              <p className="font-semibold text-white">Instructions simples :</p>
              <ol className="list-decimal list-inside space-y-1 text-slate-400">
                <li>Ouvrez WhatsApp sur votre smartphone</li>
                <li>Allez dans <strong>Réglages &gt; Appareils connectés</strong></li>
                <li>Touchez <strong>Connecter un appareil</strong> et visez l'écran</li>
              </ol>
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={() => setShowQrModal(false)}
                className="flex-1 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-750 text-slate-300 text-xs font-semibold"
              >
                Fermer
              </button>
              <button
                onClick={handleSimulatePairSuccess}
                className="flex-1 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shadow-md shadow-emerald-900/30"
              >
                Confirmer la liaison
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
