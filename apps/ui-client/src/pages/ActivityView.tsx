import React, { useState, useEffect } from 'react';
import {
  ClientActivityEntry,
  ActivityFilterOptions,
  fetchClientActivities,
  exportClientActivities,
} from '@/lib/api';
import {
  Clock,
  CheckCircle2,
  AlertCircle,
  XCircle,
  Download,
  FileSpreadsheet,
  FileJson,
  RotateCw,
  ShieldCheck,
  Search,
  ChevronRight,
  Info,
} from 'lucide-react';

interface ActivityViewProps {
  onNavigateToChat?: (agentId?: string) => void;
}

export const ActivityView: React.FC<ActivityViewProps> = ({ onNavigateToChat }) => {
  const [activities, setActivities] = useState<ClientActivityEntry[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [exporting, setExporting] = useState<boolean>(false);
  const [selectedAgent, setSelectedAgent] = useState<string>('all');
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [selectedPeriodDays, setSelectedPeriodDays] = useState<number>(30);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [exportDropdownOpen, setExportDropdownOpen] = useState<boolean>(false);

  const loadActivities = async () => {
    setLoading(true);
    try {
      const options: ActivityFilterOptions = {
        days: selectedPeriodDays,
        agentId: selectedAgent,
        status: selectedStatus,
      };
      const data = await fetchClientActivities(options);
      setActivities(data);
    } catch (err) {
      console.error('Erreur chargement journal:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadActivities();
  }, [selectedAgent, selectedStatus, selectedPeriodDays]);

  const handleExport = async (format: 'json' | 'csv') => {
    setExporting(true);
    setExportDropdownOpen(false);
    try {
      await exportClientActivities(format, {
        days: selectedPeriodDays,
        agentId: selectedAgent,
        status: selectedStatus,
      });
    } catch (err) {
      console.error('Erreur export:', err);
    } finally {
      setExporting(false);
    }
  };

  // Filtrage local par texte de recherche
  const filteredActivities = activities.filter((act) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      act.action_label.toLowerCase().includes(q) ||
      act.source_ref.toLowerCase().includes(q) ||
      act.agent_name.toLowerCase().includes(q) ||
      (act.rejection_reason && act.rejection_reason.toLowerCase().includes(q))
    );
  });

  const countDone = activities.filter((a) => a.status_code === 'done').length;
  const countPending = activities.filter((a) => a.status_code === 'pending_validation').length;
  const countRejected = activities.filter((a) => a.status_code === 'rejected').length;

  const formatDate = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return new Intl.DateTimeFormat('fr-FR', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }).format(d);
    } catch {
      return isoString;
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 p-6 sm:p-8 space-y-6">
      {/* Header & Export Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-xl bg-blue-950/80 border border-blue-800 text-blue-400">
              <Clock className="w-5 h-5" />
            </div>
            <h2 className="text-xl font-black tracking-tight text-white">Journal d'activité des agents</h2>
            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 border border-slate-700 text-slate-300">
              Ajout seul • 10 ans
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1 max-w-2xl">
            Ce que vos agents ont fait concrètement pour votre entreprise. Historique vérifié en français sans jargon,
            infalsifiable et exportable sans solliciter notre équipe.
          </p>
        </div>

        {/* Export and Refresh buttons */}
        <div className="flex items-center gap-2 relative">
          <button
            onClick={() => loadActivities()}
            title="Rafraîchir les données"
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-750 text-xs font-semibold text-slate-300 transition-colors"
          >
            <RotateCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Actualiser</span>
          </button>

          <div className="relative">
            <button
              onClick={() => setExportDropdownOpen(!exportDropdownOpen)}
              disabled={exporting || activities.length === 0}
              className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-bold shadow-md shadow-blue-950 transition-all"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Exporter le journal</span>
            </button>

            {exportDropdownOpen && (
              <div className="absolute right-0 mt-2 w-48 bg-slate-900 border border-slate-750 rounded-xl shadow-xl z-30 py-1.5 text-xs">
                <button
                  onClick={() => handleExport('csv')}
                  className="w-full text-left px-3.5 py-2 hover:bg-slate-800 text-slate-200 flex items-center gap-2"
                >
                  <FileSpreadsheet className="w-4 h-4 text-emerald-400" />
                  <span>Format CSV (Excel)</span>
                </button>
                <button
                  onClick={() => handleExport('json')}
                  className="w-full text-left px-3.5 py-2 hover:bg-slate-800 text-slate-200 flex items-center gap-2"
                >
                  <FileJson className="w-4 h-4 text-amber-400" />
                  <span>Format JSON (complet)</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800">
          <p className="text-[11px] font-semibold text-slate-400">Total des actions menées</p>
          <p className="text-2xl font-black text-white mt-1">{activities.length}</p>
          <p className="text-[10px] text-slate-500 mt-1">Sur la période sélectionnée</p>
        </div>
        <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800">
          <p className="text-[11px] font-semibold text-emerald-400 flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Actions faites</span>
          </p>
          <p className="text-2xl font-black text-emerald-300 mt-1">{countDone}</p>
          <p className="text-[10px] text-slate-500 mt-1">Exécutées avec succès</p>
        </div>
        <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800">
          <p className="text-[11px] font-semibold text-amber-400 flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            <span>En attente de validation</span>
          </p>
          <p className="text-2xl font-black text-amber-300 mt-1">{countPending}</p>
          <p className="text-[10px] text-slate-500 mt-1">Sous contrôle dirigeant</p>
        </div>
        <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800">
          <p className="text-[11px] font-semibold text-rose-400 flex items-center gap-1.5">
            <XCircle className="w-3.5 h-3.5" />
            <span>Actions refusées</span>
          </p>
          <p className="text-2xl font-black text-rose-300 mt-1">{countRejected}</p>
          <p className="text-[10px] text-slate-500 mt-1">Classées sans suite</p>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col md:flex-row gap-3 bg-slate-900/60 p-3.5 rounded-2xl border border-slate-800">
        {/* Search */}
        <div className="flex-1 relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Rechercher par action, facture, client ou motif..."
            className="w-full pl-9 pr-3 py-2 rounded-xl bg-slate-950 border border-slate-750 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* Agent Filter */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-semibold text-slate-400 whitespace-nowrap">Agent :</span>
          <select
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="bg-slate-950 border border-slate-750 rounded-xl px-2.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
          >
            <option value="all">Tous les agents</option>
            <option value="jerome">Jérôme (Recouvrement)</option>
            <option value="lucas">Lucas (Prospection & Devis)</option>
            <option value="clara">Clara (Support Client)</option>
            <option value="victor">Victor (Appels d'Offres)</option>
          </select>
        </div>

        {/* Status Filter */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-semibold text-slate-400 whitespace-nowrap">Issue :</span>
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
            className="bg-slate-950 border border-slate-750 rounded-xl px-2.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
          >
            <option value="all">Toutes les issues</option>
            <option value="done">Faite</option>
            <option value="pending_validation">En attente de validation</option>
            <option value="rejected">Refusée</option>
            <option value="expired">Expirée</option>
          </select>
        </div>

        {/* Period Selector */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-semibold text-slate-400 whitespace-nowrap">Période :</span>
          <select
            value={selectedPeriodDays}
            onChange={(e) => setSelectedPeriodDays(Number(e.target.value))}
            className="bg-slate-950 border border-slate-750 rounded-xl px-2.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
          >
            <option value={30}>30 derniers jours (standard)</option>
            <option value={90}>90 jours</option>
            <option value={365}>1 an</option>
            <option value={3650}>10 ans (archivage légal)</option>
          </select>
        </div>
      </div>

      {/* Activity List */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-slate-400 text-xs flex flex-col items-center gap-3">
            <RotateCw className="w-6 h-6 animate-spin text-blue-500" />
            <span>Chargement du journal d'activité...</span>
          </div>
        ) : filteredActivities.length === 0 ? (
          <div className="p-12 text-center text-slate-400 text-xs space-y-2">
            <Info className="w-8 h-8 text-slate-500 mx-auto" />
            <p className="font-bold text-slate-300 text-sm">Aucune activité enregistrée sur cette période</p>
            <p className="text-slate-500 max-w-md mx-auto">
              Dès que vos agents mèneront des actions (envoi de relance, devis, écritures), elles apparaîtront ici
              avec leur date, leur source et leur issue.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-800/80">
            {filteredActivities.map((act) => {
              const isPending = act.status_code === 'pending_validation';
              const isRejected = act.status_code === 'rejected';
              const isDone = act.status_code === 'done';
              const isExpired = act.status_code === 'expired';

              return (
                <div
                  key={act.id}
                  className="p-4 sm:p-5 hover:bg-slate-900/80 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-4"
                >
                  <div className="space-y-1.5 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-bold text-slate-200">{act.agent_name}</span>
                      <span className="text-[10px] text-slate-500">•</span>
                      <span className="text-[11px] text-slate-400">{formatDate(act.timestamp)}</span>

                      {/* Status Badge */}
                      {isDone && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-950/90 text-emerald-300 border border-emerald-800">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Faite</span>
                        </span>
                      )}
                      {isPending && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-950/90 text-amber-300 border border-amber-800">
                          <Clock className="w-3 h-3" />
                          <span>En attente de validation</span>
                        </span>
                      )}
                      {isRejected && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-950/90 text-rose-300 border border-rose-800">
                          <XCircle className="w-3 h-3" />
                          <span>Refusée</span>
                        </span>
                      )}
                      {isExpired && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700">
                          <AlertCircle className="w-3 h-3" />
                          <span>Expirée</span>
                        </span>
                      )}
                    </div>

                    {/* Plain Action Description */}
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-white tracking-tight">{act.action_label}</p>
                    </div>

                    {/* Source reference */}
                    <p className="text-xs text-slate-400">
                      <span className="text-slate-500">Source :</span> {act.source_type} • <span className="text-slate-300 font-medium">{act.source_ref}</span>
                    </p>

                    {/* Rejection or Expiration reason if applicable (CA4) */}
                    {(isRejected || isExpired) && act.rejection_reason && (
                      <div className="mt-2 p-2.5 rounded-xl bg-rose-950/30 border border-rose-900/50 text-[11px] text-rose-300 flex items-start gap-2">
                        <AlertCircle className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-0.5" />
                        <div>
                          <span className="font-bold">Motif du refus :</span> {act.rejection_reason}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Actions / Jump to review (CA3) */}
                  {isPending && onNavigateToChat && (
                    <button
                      onClick={() => onNavigateToChat(act.agent_id)}
                      className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-amber-600/90 hover:bg-amber-500 text-slate-950 text-xs font-bold transition-all shadow-sm shadow-amber-950"
                    >
                      <span>Examiner la demande</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Trust & Legal Compliance Note */}
      <div className="p-4 rounded-2xl bg-slate-900/40 border border-slate-800 text-[11px] text-slate-400 flex items-center gap-3">
        <ShieldCheck className="w-5 h-5 text-blue-400 shrink-0" />
        <p>
          <span className="font-bold text-slate-300">Garantie d'intégrité Orso :</span> Ce journal est en ajout seul
          (aucune modification ou effacement rétroactif possible). Les enregistrements liés à des opérations comptables
          sont conservés pendant dix ans conformément à la réglementation des pièces justificatives.
        </p>
      </div>
    </div>
  );
};
