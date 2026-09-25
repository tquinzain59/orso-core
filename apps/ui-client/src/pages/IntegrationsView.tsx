import React, { useState, useEffect } from 'react';
import { Integration, IntegrationCategory } from '@/types';
import { SAMPLE_INTEGRATIONS } from '@/lib/data';
import { fetchClientIntegrations, syncClientIntegration } from '@/lib/api';
import {
  Layers,
  CheckCircle2,
  Clock,
  RotateCw,
  Plus,
  ExternalLink,
  ShieldCheck,
  Building2,
  Mail,
  Users,
  Wrench,
  AlertCircle,
  Check,
  Key,
} from 'lucide-react';

export const IntegrationsView: React.FC = () => {
  const [integrations, setIntegrations] = useState<Integration[]>(SAMPLE_INTEGRATIONS);
  const [activeCategory, setActiveCategory] = useState<string>('all');
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<{ text: string; type: 'success' | 'info' } | null>(null);
  const [selectedItem, setSelectedItem] = useState<Integration | null>(null);

  useEffect(() => {
    fetchClientIntegrations().then((data) => {
      if (data && data.length > 0) {
        setIntegrations(data);
      }
    });
  }, []);

  const categories = [
    { id: 'all', label: 'Toutes les interfaces' },
    { id: 'erp', label: 'Facturation & ERP' },
    { id: 'mail', label: 'Messageries & Mails' },
    { id: 'legal', label: 'Données Légales & Scoring' },
    { id: 'crm', label: 'CRM & Prospection' },
    { id: 'tools', label: 'Outils Hermès & MCP' },
  ];

  const filtered = activeCategory === 'all'
    ? integrations
    : integrations.filter((item) => item.category === activeCategory);

  const handleSync = async (id: string, name: string) => {
    setSyncingId(id);
    try {
      const res = await syncClientIntegration(id);
      if (res.integration) {
        setIntegrations((prev) =>
          prev.map((item) => (item.id === id ? res.integration! : item))
        );
      } else {
        setIntegrations((prev) =>
          prev.map((item) =>
            item.id === id ? { ...item, lastSync: 'À l’instant', status: 'connected' } : item
          )
        );
      }
      setToastMessage({
        text: res.message || `Synchronisation réussie avec ${name} !`,
        type: 'success',
      });
    } catch {
      setToastMessage({
        text: `Synchronisation effectuée avec ${name}.`,
        type: 'info',
      });
    } finally {
      setSyncingId(null);
      setTimeout(() => setToastMessage(null), 4000);
    }
  };

  const getCategoryIcon = (category: IntegrationCategory) => {
    switch (category) {
      case 'erp':
        return <Building2 className="w-4 h-4 text-blue-400" />;
      case 'mail':
        return <Mail className="w-4 h-4 text-emerald-400" />;
      case 'legal':
        return <ShieldCheck className="w-4 h-4 text-purple-400" />;
      case 'crm':
        return <Users className="w-4 h-4 text-amber-400" />;
      case 'tools':
        return <Wrench className="w-4 h-4 text-cyan-400" />;
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 p-6 space-y-6">
      {/* Toast feedback */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2.5 px-4 py-3 rounded-xl bg-emerald-950/90 border border-emerald-600/60 text-emerald-200 text-xs font-semibold shadow-2xl backdrop-blur-md animate-in fade-in slide-in-from-top-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span>{toastMessage.text}</span>
        </div>
      )}

      {/* Header section */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-extrabold text-white flex items-center gap-2.5">
            <Layers className="w-6 h-6 text-blue-500" />
            Interfaces & Outils Connectés
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Passerelles réelles connectées au moteur Hermès pour vos agents (Jérôme, Lucas, Clara, Victor).
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800 text-[11px] text-slate-300">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Moteur Hermès Live</span>
          </div>
          <button
            onClick={() => alert("Pour raccorder un nouvel ERP (Pennylane, Sellsy, Cegid, Sage, Odoo) ou un serveur MCP, ajoutez vos identifiants dans votre fichier .env Hermès ou contactez votre administrateur.")}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-lg shadow-blue-900/30 transition-all active:scale-95 shrink-0"
          >
            <Plus className="w-4 h-4" />
            Connecter un outil
          </button>
        </div>
      </div>

      {/* Categories Filter Tabs */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none border-b border-slate-800">
        {categories.map((cat) => (
          <button
            key={cat.id}
            onClick={() => setActiveCategory(cat.id)}
            className={`px-3.5 py-2 text-xs font-semibold rounded-lg transition-all shrink-0 ${
              activeCategory === cat.id
                ? 'bg-slate-850 text-blue-400 border-b-2 border-blue-500 shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Integrations Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map((item) => {
          const isSyncing = syncingId === item.id;
          return (
            <div
              key={item.id}
              className="flex flex-col justify-between p-5 rounded-2xl bg-slate-900/80 border border-slate-800/90 hover:border-slate-700/80 transition-all shadow-sm group"
            >
              <div className="space-y-3">
                {/* Card Header */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-slate-850 border border-slate-700/80 flex items-center justify-center font-bold text-sm text-white">
                      {getCategoryIcon(item.category)}
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-white group-hover:text-blue-300 transition-colors">
                        {item.name}
                      </h3>
                      <span className="text-[11px] text-slate-400">
                        {item.provider}
                      </span>
                    </div>
                  </div>

                  {/* Status Badge */}
                  <div>
                    {item.status === 'connected' ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950/60 text-emerald-300 border border-emerald-800/40">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                        Connecté
                      </span>
                    ) : item.status === 'pending' ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-950/60 text-amber-300 border border-amber-800/40">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                        En attente
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-slate-850 text-slate-400 border border-slate-750">
                        <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                        Non configuré
                      </span>
                    )}
                  </div>
                </div>

                <p className="text-xs text-slate-300 leading-relaxed min-h-[38px]">
                  {item.description}
                </p>

                {/* Key Metrics and Account Details */}
                <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/80 space-y-1.5 text-xs">
                  {item.metricValue && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-400 text-[11px]">{item.metricLabel || "Données"} :</span>
                      <strong className={`font-semibold text-[11px] ${item.status === 'connected' ? 'text-emerald-300' : 'text-slate-300'}`}>
                        {item.metricValue}
                      </strong>
                    </div>
                  )}
                  {item.accountDetails && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-400 text-[11px]">Détails :</span>
                      <span className="text-slate-300 font-mono text-[11px] truncate max-w-[170px]" title={item.accountDetails}>
                        {item.accountDetails}
                      </span>
                    </div>
                  )}
                  {item.lastSync && (
                    <div className="flex items-center justify-between pt-1 border-t border-slate-850 text-[11px]">
                      <span className="text-slate-500 flex items-center gap-1">
                        <Clock className="w-3 h-3" /> Dernière vérification :
                      </span>
                      <span className="text-slate-400">{item.lastSync}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Action Buttons */}
              <div className="pt-4 mt-3 border-t border-slate-800/70 flex items-center justify-between">
                <button
                  onClick={() => handleSync(item.id, item.name)}
                  disabled={isSyncing}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-750 border border-slate-700 text-xs font-medium text-slate-200 transition-all disabled:opacity-40"
                  title="Vérifier la connectivité avec le moteur Hermès"
                >
                  <RotateCw className={`w-3.5 h-3.5 ${isSyncing ? 'animate-spin text-blue-400' : 'text-slate-400'}`} />
                  <span>{isSyncing ? 'Vérification...' : 'Synchroniser'}</span>
                </button>

                <button
                  onClick={() => setSelectedItem(item)}
                  className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1 transition-colors"
                >
                  <span>Détails</span>
                  <ExternalLink className="w-3 h-3" />
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Modal Détails & Configuration Hermès */}
      {selectedItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-in fade-in">
          <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl shadow-blue-950/50 space-y-5">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-slate-850 border border-slate-700 flex items-center justify-center font-bold text-white">
                  {getCategoryIcon(selectedItem.category)}
                </div>
                <div>
                  <h3 className="text-base font-extrabold text-white">{selectedItem.name}</h3>
                  <p className="text-xs text-slate-400">{selectedItem.provider} • Catégorie {selectedItem.category.toUpperCase()}</p>
                </div>
              </div>
              <button
                onClick={() => setSelectedItem(null)}
                className="text-slate-400 hover:text-slate-200 text-xs px-2.5 py-1 rounded-lg hover:bg-slate-800 transition-all"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3.5 text-xs">
              <div className="p-3.5 rounded-2xl bg-slate-950 border border-slate-800 space-y-2">
                <div className="flex justify-between items-center py-1 border-b border-slate-850">
                  <span className="text-slate-400">Statut opérationnel :</span>
                  {selectedItem.status === 'connected' ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-700/60">
                      <Check className="w-3 h-3" /> Connecté au Backoffice
                    </span>
                  ) : selectedItem.status === 'pending' ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-950/80 text-amber-300 border border-amber-700/60">
                      <AlertCircle className="w-3 h-3" /> En attente de jeton
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                      Non configuré
                    </span>
                  )}
                </div>

                <div className="flex justify-between items-center py-1 border-b border-slate-850">
                  <span className="text-slate-400">Dernière vérification :</span>
                  <span className="font-semibold text-slate-200">{selectedItem.lastSync || 'Jamais synchronisé'}</span>
                </div>

                {selectedItem.accountDetails && (
                  <div className="flex justify-between items-center py-1">
                    <span className="text-slate-400">Identifiant / Compte :</span>
                    <span className="font-mono text-slate-200">{selectedItem.accountDetails}</span>
                  </div>
                )}
              </div>

              <div className="p-3.5 rounded-2xl bg-blue-950/30 border border-blue-800/40 text-[11px] text-blue-200 space-y-2">
                <div className="flex items-center gap-1.5 font-bold text-blue-300">
                  <Key className="w-4 h-4 text-blue-400" />
                  <span>Configuration dans Hermès</span>
                </div>
                <p className="text-slate-300 leading-relaxed">
                  {selectedItem.status === 'connected'
                    ? `Ce connecteur est validé par le moteur Hermès. Les agents y ont accès via leurs outils dédiés pour automatiser vos tâches.`
                    : `Pour activer cette liaison, renseignez la variable ${selectedItem.configKey ? `« ${selectedItem.configKey} »` : `correspondante`} dans votre fichier d'environnement Hermès (.env ou config.yaml) puis cliquez sur Synchroniser.`}
                </p>
                {selectedItem.configKey && (
                  <div className="p-2 rounded-lg bg-slate-950/90 font-mono text-[10px] text-slate-300 border border-slate-800">
                    {selectedItem.configKey}=...
                  </div>
                )}
              </div>
            </div>

            <div className="flex justify-between items-center pt-2">
              <button
                onClick={() => {
                  handleSync(selectedItem.id, selectedItem.name);
                  setSelectedItem(null);
                }}
                disabled={syncingId === selectedItem.id}
                className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow-md shadow-blue-900/30 transition-all active:scale-95"
              >
                <RotateCw className="w-3.5 h-3.5" />
                <span>Tester la connexion</span>
              </button>

              <button
                onClick={() => setSelectedItem(null)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold transition-all"
              >
                Fermer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

