import React, { useState } from 'react';
import { ActionCardData } from '@/types';
import { executeClientAction } from '@/lib/api';
import {
  CheckCircle2,
  Clock,
  Edit3,
  XCircle,
  FileText,
  Mail,
  ChevronDown,
  ChevronUp
} from 'lucide-react';

interface ActionCardProps {
  action: ActionCardData;
  onUpdateStatus?: (actionId: string, status: ActionCardData['status'], feedback?: string) => void;
}

export const ActionCard: React.FC<ActionCardProps> = ({ action, onUpdateStatus }) => {
  const [currentStatus, setCurrentStatus] = useState<ActionCardData['status']>(action.status);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(action.draftContent);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleApprove = async () => {
    setIsSubmitting(true);
    setCurrentStatus('approved');
    onUpdateStatus?.(action.id, 'approved', 'Action approuvée et exécutée avec succès.');
    await executeClientAction('send', action.id, action.agentId, editedContent, action.recipientContact);
    setIsSubmitting(false);
  };

  const handleDelay = async () => {
    setIsSubmitting(true);
    setCurrentStatus('delayed');
    onUpdateStatus?.(action.id, 'delayed', 'Action reportée de 7 jours.');
    await executeClientAction('delay', action.id, action.agentId, editedContent, action.recipientContact);
    setIsSubmitting(false);
  };

  const handleCancel = async () => {
    setIsSubmitting(true);
    setCurrentStatus('cancelled');
    onUpdateStatus?.(action.id, 'cancelled', 'Action classée sans relance.');
    await executeClientAction('skip', action.id, action.agentId, editedContent, action.recipientContact);
    setIsSubmitting(false);
  };

  const handleSaveEdit = () => {
    setIsEditing(false);
  };

  return (
    <div className="mt-3 rounded-2xl border border-blue-800/40 bg-slate-900/90 shadow-xl overflow-hidden transition-all">
      {/* Header Banner */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-gradient-to-r from-blue-950/80 to-slate-900 border-b border-blue-800/30">
        <div className="flex items-center gap-2">
          <span className="p-1 rounded-md bg-blue-600/20 text-blue-400">
            <FileText className="w-4 h-4" />
          </span>
          <span className="text-xs font-bold text-blue-300 uppercase tracking-wider">
            Arbitrage Requis • 1-Clic
          </span>
        </div>
        {action.amount && (
          <span className="text-sm font-extrabold text-white px-2 py-0.5 rounded-lg bg-blue-600/30 border border-blue-500/40">
            {action.amount.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} € TTC
          </span>
        )}
      </div>

      {/* Main Content */}
      <div className="p-4 space-y-3">
        <div>
          <h4 className="text-base font-bold text-white flex items-center gap-2">
            {action.title}
          </h4>
          <p className="text-xs text-slate-400 mt-0.5">
            Destinataire : <strong className="text-slate-200">{action.recipientName}</strong>
            {action.recipientContact && ` (${action.recipientContact})`}
          </p>
        </div>

        {/* Badges and metadata */}
        <div className="flex flex-wrap gap-2 text-xs">
          {action.invoiceNumber && (
            <span className="px-2.5 py-1 rounded-md bg-slate-800 border border-slate-700 text-slate-300 font-mono">
              Facture : {action.invoiceNumber}
            </span>
          )}
          {action.dueDate && (
            <span className="px-2.5 py-1 rounded-md bg-amber-950/40 border border-amber-800/40 text-amber-300 flex items-center gap-1">
              <Clock className="w-3 h-3" /> Échéance : {action.dueDate}
            </span>
          )}
          <span className="px-2.5 py-1 rounded-md bg-blue-950/40 border border-blue-800/40 text-blue-300 flex items-center gap-1">
            <Mail className="w-3 h-3" /> Canal : Email
          </span>
        </div>

        {/* Message preview toggle */}
        <div className="pt-1">
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center justify-between w-full px-3 py-2 rounded-lg bg-slate-950/60 border border-slate-800/80 text-xs text-slate-300 hover:text-white hover:bg-slate-950 transition-all"
          >
            <span className="flex items-center gap-1.5 font-medium">
              <Mail className="w-3.5 h-3.5 text-blue-400" />
              {action.draftSubject || "Voir le message pré-rédigé"}
            </span>
            {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>

          {isExpanded && (
            <div className="mt-2 p-3 rounded-xl bg-slate-950/90 border border-slate-800 space-y-2">
              {isEditing ? (
                <div>
                  <textarea
                    value={editedContent}
                    onChange={(e) => setEditedContent(e.target.value)}
                    rows={6}
                    className="w-full text-xs bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-slate-100 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                  />
                  <div className="flex justify-end gap-2 mt-2">
                    <button
                      onClick={() => setIsEditing(false)}
                      className="px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200"
                    >
                      Annuler
                    </button>
                    <button
                      onClick={handleSaveEdit}
                      className="px-3 py-1 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-md font-medium"
                    >
                      Enregistrer
                    </button>
                  </div>
                </div>
              ) : (
                <div>
                  <pre className="text-xs text-slate-300 whitespace-pre-wrap font-sans leading-relaxed">
                    {editedContent}
                  </pre>
                  {currentStatus === 'pending' && (
                    <button
                      onClick={() => setIsEditing(true)}
                      className="mt-2 text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
                    >
                      <Edit3 className="w-3 h-3" /> Modifier le texte
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Action Buttons based on status */}
        <div className="pt-2 border-t border-slate-800/80">
          {currentStatus === 'pending' ? (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <button
                onClick={handleApprove}
                disabled={isSubmitting}
                className="flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-bold shadow-md shadow-blue-900/30 transition-all hover:scale-[1.02] active:scale-[0.98]"
              >
                <CheckCircle2 className="w-4 h-4 text-white" />
                {isSubmitting ? "Envoi..." : "Approuver & Envoyer"}
              </button>

              <button
                onClick={handleDelay}
                disabled={isSubmitting}
                className="flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-750 disabled:opacity-50 border border-slate-700 text-slate-200 text-xs font-semibold transition-all hover:bg-slate-700"
              >
                <Clock className="w-3.5 h-3.5 text-amber-400" />
                Reporter de 7 j
              </button>

              <button
                onClick={handleCancel}
                disabled={isSubmitting}
                className="flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl bg-transparent hover:bg-rose-950/30 disabled:opacity-50 border border-slate-800 hover:border-rose-800/50 text-slate-400 hover:text-rose-400 text-xs font-medium transition-all"
              >
                <XCircle className="w-3.5 h-3.5" />
                Ne pas relancer
              </button>
            </div>
          ) : currentStatus === 'approved' ? (
            <div className="flex items-center gap-2 p-2.5 rounded-xl bg-emerald-950/40 border border-emerald-700/50 text-emerald-300 text-xs font-semibold">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>✓ Action approuvée ! E-mail de relance transmis avec accusé de réception.</span>
            </div>
          ) : currentStatus === 'delayed' ? (
            <div className="flex items-center gap-2 p-2.5 rounded-xl bg-amber-950/40 border border-amber-700/50 text-amber-300 text-xs font-semibold">
              <Clock className="w-4 h-4 text-amber-400 shrink-0" />
              <span>Relance reportée au {new Date(Date.now() + 7 * 86400000).toLocaleDateString('fr-FR')}. Jérôme vous la représentera à échéance.</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 p-2.5 rounded-xl bg-slate-800/60 border border-slate-700/60 text-slate-400 text-xs">
              <XCircle className="w-4 h-4 text-slate-500 shrink-0" />
              <span>Action annulée. Aucune communication n'a été transmise au tiers.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
