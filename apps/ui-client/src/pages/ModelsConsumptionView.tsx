import React, { useEffect, useState } from 'react';
import {
  ModelsConsumptionResponse,
  TenantModelInfo,
} from '@/types';
import {
  fetchClientModelsConsumption,
  updateClientSelectedModel,
  updateClientConsumptionThreshold,
  addClientConsumptionCredits,
} from '@/lib/api';
import {
  Cpu,
  Activity,
  AlertTriangle,
  CheckCircle2,
  CreditCard,
  RefreshCw,
  ShieldCheck,
  Sliders,
  Sparkles,
  TrendingUp,
  Zap,
  Repeat,
  PlusCircle,
  KeyRound,
} from 'lucide-react';

export const ModelsConsumptionView: React.FC = () => {
  const [data, setData] = useState<ModelsConsumptionResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // États formulaires
  const [updatingModel, setUpdatingModel] = useState<string | null>(null);
  const [thresholdPctInput, setThresholdPctInput] = useState<number>(80);
  const [limitUsdInput, setLimitUsdInput] = useState<number>(25);
  const [savingThreshold, setSavingThreshold] = useState<boolean>(false);

  // États ajout de crédits Stripe
  const [creditAmount, setCreditAmount] = useState<number>(25);
  const [creditMode, setCreditMode] = useState<'one_shot' | 'monthly_subscription'>('one_shot');
  const [addingCredits, setAddingCredits] = useState<boolean>(false);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchClientModelsConsumption();
      setData(res);
      setThresholdPctInput(res.consumption.alert_threshold_pct);
      setLimitUsdInput(res.consumption.limit_usd);
    } catch (err: any) {
      setError(err?.message || 'Impossible de charger les données Modèles & Consommation.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const showNotice = (type: 'success' | 'error', text: string) => {
    setFeedback({ type, text });
    setTimeout(() => setFeedback(null), 5000);
  };

  const handleSelectModel = async (modelId: string) => {
    if (!data || modelId === data.selected_model || updatingModel) return;
    setUpdatingModel(modelId);
    try {
      const updated = await updateClientSelectedModel(modelId);
      setData(updated);
      showNotice('success', updated.message || `Modèle actif changé vers ${modelId}`);
    } catch (err: any) {
      showNotice('error', err?.message || 'Erreur lors du changement de modèle.');
    } finally {
      setUpdatingModel(null);
    }
  };

  const handleSaveThreshold = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingThreshold(true);
    try {
      const updated = await updateClientConsumptionThreshold({
        alert_threshold_pct: Number(thresholdPctInput),
        limit_usd: Number(limitUsdInput),
      });
      setData(updated);
      setThresholdPctInput(updated.consumption.alert_threshold_pct);
      setLimitUsdInput(updated.consumption.limit_usd);
      showNotice('success', updated.message || 'Seuil et plafond de consommation mis à jour.');
    } catch (err: any) {
      showNotice('error', err?.message || 'Erreur lors de la sauvegarde du seuil.');
    } finally {
      setSavingThreshold(false);
    }
  };

  const handleAddCredits = async (e: React.FormEvent) => {
    e.preventDefault();
    if (creditAmount <= 0 || addingCredits) return;
    setAddingCredits(true);
    try {
      const updated = await addClientConsumptionCredits({
        amount_usd: Number(creditAmount),
        mode: creditMode,
      });
      setData(updated);
      setLimitUsdInput(updated.consumption.limit_usd);
      showNotice('success', updated.message || `+${creditAmount} $ de crédits ajoutés avec succès.`);
    } catch (err: any) {
      showNotice('error', err?.message || "Erreur lors de l'ajout de crédits.");
    } finally {
      setAddingCredits(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-slate-400">
        <div className="flex items-center gap-3">
          <RefreshCw className="w-5 h-5 animate-spin text-blue-400" />
          <span className="text-sm font-medium">Chargement du pilotage Modèles & Consommation...</span>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex-1 p-8 flex items-center justify-center">
        <div className="max-w-md w-full bg-slate-900 border border-rose-800/60 rounded-2xl p-6 text-center space-y-4">
          <AlertTriangle className="w-8 h-8 text-rose-400 mx-auto" />
          <h3 className="text-base font-bold text-white">Accès ou chargement impossible</h3>
          <p className="text-xs text-slate-300">{error}</p>
          <button
            onClick={() => void loadData()}
            className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition-all"
          >
            Réessayer
          </button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { consumption, available_models, selected_model, current_model_info } = data;
  const progressPct = Math.min(100, Math.max(0, consumption.usage_pct));

  return (
    <div className="flex-1 overflow-y-auto p-6 bg-slate-950">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* En-tête */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-900/80 border border-slate-800 rounded-2xl p-5">
          <div>
            <div className="flex items-center gap-2">
              <Cpu className="w-5 h-5 text-blue-400" />
              <h2 className="text-lg font-extrabold text-white">Modèles IA & Suivi de Consommation</h2>
              <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                ESPACE ADMIN
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Pilotez le modèle d'intelligence artificielle commun à toute votre flotte d'agents, suivez votre consommation en temps réel et gérez vos seuils et crédits.
            </p>
          </div>
          <button
            onClick={() => void loadData()}
            className="self-start sm:self-auto flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition-all"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Actualiser</span>
          </button>
        </div>

        {/* Bannière de notification */}
        {feedback && (
          <div
            className={`p-4 rounded-2xl border flex items-center justify-between text-xs font-medium animate-in fade-in ${
              feedback.type === 'success'
                ? 'bg-emerald-950/70 border-emerald-700/70 text-emerald-200'
                : 'bg-rose-950/70 border-rose-700/70 text-rose-200'
            }`}
          >
            <div className="flex items-center gap-2.5">
              {feedback.type === 'success' ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              ) : (
                <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
              )}
              <span>{feedback.text}</span>
            </div>
          </div>
        )}

        {/* Alerte de dépassement de seuil ou de plafond (KAN-116 CA6 / KAN-123 CA5) */}
        {(consumption.threshold_reached || consumption.limit_exceeded) && (
          <div
            className={`p-4 rounded-2xl border flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
              consumption.limit_exceeded
                ? 'bg-rose-950/80 border-rose-700 text-rose-100'
                : 'bg-amber-950/80 border-amber-700 text-amber-100'
            }`}
          >
            <div className="flex items-start gap-3">
              <AlertTriangle
                className={`w-5 h-5 shrink-0 mt-0.5 ${
                  consumption.limit_exceeded ? 'text-rose-400' : 'text-amber-400'
                }`}
              />
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider">
                  {consumption.limit_exceeded
                    ? 'Plafond de consommation atteint'
                    : `Seuil de vigilance dépassé (${consumption.alert_threshold_pct}%)`}
                </h4>
                <p className="text-xs opacity-90 mt-0.5">
                  Votre consommation actuelle est de <strong>{consumption.cost_usd.toFixed(2)} $</strong> sur un plafond de{' '}
                  <strong>{consumption.limit_usd.toFixed(2)} $</strong> ({consumption.usage_pct}%). Ajoutez des crédits ci-dessous pour garantir la continuité de vos agents.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Section 1 : Sélection du modèle IA par le client (KAN-122 & KAN-123 CA2) */}
        <section className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-blue-400" />
                <span>Modèle d'Intelligence Artificielle de vos Agents</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Portée globale à l'entreprise : le modèle sélectionné équipe immédiatement tous vos agents actifs (Jérôme, Lucas, Clara, Victor).
              </p>
            </div>
            <div className="px-3 py-1.5 rounded-xl bg-blue-950/60 border border-blue-800/70 text-xs text-blue-200 flex items-center gap-2 shrink-0">
              <Zap className="w-3.5 h-3.5 text-blue-400" />
              <span>
                Modèle courant : <strong className="text-white">{current_model_info?.name || selected_model}</strong>
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
            {available_models.map((model: TenantModelInfo) => {
              const isSelected = model.id === selected_model;
              const isBusy = updatingModel === model.id;
              return (
                <div
                  key={model.id}
                  onClick={() => void handleSelectModel(model.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      void handleSelectModel(model.id);
                    }
                  }}
                  className={`relative rounded-2xl p-5 border transition-all cursor-pointer flex flex-col justify-between ${
                    isSelected
                      ? 'bg-blue-950/30 border-blue-500 ring-1 ring-blue-500/40 shadow-lg shadow-blue-950/40'
                      : 'bg-slate-950/70 border-slate-800 hover:border-slate-700 hover:bg-slate-900/60'
                  }`}
                >
                  <div className="space-y-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-blue-300 border border-slate-700 mb-1.5">
                          {model.badge}
                        </span>
                        <h4 className="text-base font-extrabold text-white">{model.name}</h4>
                        <p className="text-[11px] font-mono text-slate-400">{model.id}</p>
                      </div>
                      {isSelected ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-700">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          <span>Actif</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                          {isBusy ? 'Activation...' : 'Sélectionner'}
                        </span>
                      )}
                    </div>

                    <p className="text-xs text-slate-300 leading-relaxed">{model.description}</p>
                  </div>

                  <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
                    <span>
                      Origine : <strong className="text-slate-200">{model.origin}</strong>
                    </span>
                    <span>
                      Coût :{' '}
                      <strong className="text-slate-200">
                        {model.input_price_per_1m_usd} $ / {model.output_price_per_1m_usd} $
                      </strong>{' '}
                      / 1M tokens
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Section 2 : Consommation en temps réel & Jauge de seuil (KAN-116 CA2, CA6 / KAN-123 CA3) */}
        <section className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Activity className="w-4 h-4 text-emerald-400" />
                <span>Suivi de Consommation Dédié</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">{consumption.period_label}</p>
            </div>
            {consumption.openrouter_token && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950 border border-slate-800 text-[11px] text-slate-300">
                <KeyRound className="w-3.5 h-3.5 text-indigo-400" />
                <span>Token OpenRouter dédié :</span>
                <code className="font-mono text-indigo-300">{consumption.openrouter_token.key_masked || 'Protégé'}</code>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                  {consumption.openrouter_token.status === 'active' ? 'ACTIF' : consumption.openrouter_token.status.toUpperCase()}
                </span>
              </div>
            )}
          </div>

          {/* 4 Cartes de métriques */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-slate-950/80 border border-slate-800/90 rounded-xl p-4">
              <span className="text-[11px] text-slate-400 font-medium">Coût consommé (période)</span>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-2xl font-extrabold text-white">{consumption.cost_usd.toFixed(2)} $</span>
                <span className="text-xs text-slate-400">/ {consumption.limit_usd.toFixed(2)} $</span>
              </div>
              <p className="text-[11px] text-emerald-400 mt-1">
                Solde disponible : {consumption.remaining_usd.toFixed(2)} $
              </p>
            </div>

            <div className="bg-slate-950/80 border border-slate-800/90 rounded-xl p-4">
              <span className="text-[11px] text-slate-400 font-medium">Tokens totaux échangés</span>
              <div className="mt-1 text-2xl font-extrabold text-white">
                {consumption.total_tokens.toLocaleString('fr-FR')}
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                Entrée : {consumption.input_tokens.toLocaleString('fr-FR')} • Sortie :{' '}
                {consumption.output_tokens.toLocaleString('fr-FR')}
              </p>
            </div>

            <div className="bg-slate-950/80 border border-slate-800/90 rounded-xl p-4">
              <span className="text-[11px] text-slate-400 font-medium">Seuil d'alerte configuré</span>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-2xl font-extrabold text-amber-300">{consumption.alert_threshold_pct}%</span>
                <span className="text-xs text-slate-400">({consumption.alert_threshold_usd.toFixed(2)} $)</span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                {consumption.threshold_reached ? '⚠️ Seuil atteint' : '🟢 Sous le seuil de vigilance'}
              </p>
            </div>

            <div className="bg-slate-950/80 border border-slate-800/90 rounded-xl p-4">
              <span className="text-[11px] text-slate-400 font-medium">Crédits supplémentaires</span>
              <div className="mt-1 text-2xl font-extrabold text-blue-400">
                +{consumption.extra_credits_usd.toFixed(2)} $
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                {consumption.monthly_credit_addon_usd > 0
                  ? `Dont forfait récurrent : +${consumption.monthly_credit_addon_usd.toFixed(2)} $/mois`
                  : 'Aucun forfait mensuel additionnel actif'}
              </p>
            </div>
          </div>

          {/* Barre de progression avec repère du seuil */}
          <div className="space-y-2 pt-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-300 font-semibold">
                Jauge d'utilisation du plafond ({consumption.usage_pct}%)
              </span>
              <span className="text-slate-400">
                Alerte à {consumption.alert_threshold_pct}% • Plafond {consumption.limit_usd.toFixed(2)} $
              </span>
            </div>
            <div className="relative h-3.5 w-full rounded-full bg-slate-950 border border-slate-800 overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ${
                  consumption.limit_exceeded
                    ? 'bg-rose-500'
                    : consumption.threshold_reached
                    ? 'bg-amber-500'
                    : 'bg-gradient-to-r from-blue-600 to-emerald-500'
                }`}
                style={{ width: `${progressPct}%` }}
              />
              {/* Marqueur visuel du seuil d'alerte */}
              <div
                className="absolute top-0 bottom-0 w-0.5 bg-amber-300/90"
                style={{ left: `${Math.min(100, Math.max(1, consumption.alert_threshold_pct))}%` }}
                title={`Seuil d'alerte : ${consumption.alert_threshold_pct}%`}
              />
            </div>
          </div>
        </section>

        {/* Grille inférieure : Paramétrage du seuil (CA4) + Recharge Crédits Stripe (CA5) */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Section 3 : Configuration du seuil et plafond (KAN-123 CA4) */}
          <section className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 space-y-4">
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Sliders className="w-4 h-4 text-amber-400" />
                <span>Seuil d'Alerte & Plafond Configurable</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Un seuil par défaut (80% / 25 $) est appliqué à l'abonnement. Vous pouvez l'ajuster à tout moment.
              </p>
            </div>

            <form onSubmit={(e) => void handleSaveThreshold(e)} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Seuil d'alerte de consommation ({thresholdPctInput}%)
                </label>
                <input
                  type="range"
                  min={10}
                  max={100}
                  step={5}
                  value={thresholdPctInput}
                  onChange={(e) => setThresholdPctInput(Number(e.target.value))}
                  className="w-full accent-blue-500 cursor-pointer"
                />
                <div className="flex justify-between text-[11px] text-slate-500 mt-1">
                  <span>10% (Prudent)</span>
                  <span className="text-amber-300 font-bold">
                    Déclenchement à {((limitUsdInput * thresholdPctInput) / 100).toFixed(2)} $
                  </span>
                  <span>100% (Plafond)</span>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Plafond mensuel autorisé (USD)
                </label>
                <input
                  type="number"
                  min={5}
                  max={10000}
                  step={5}
                  value={limitUsdInput}
                  onChange={(e) => setLimitUsdInput(Number(e.target.value))}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-xs focus:outline-none focus:border-blue-500"
                />
              </div>

              <button
                type="submit"
                disabled={savingThreshold}
                className="w-full py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-white text-xs font-bold transition-all disabled:opacity-50"
              >
                {savingThreshold ? 'Enregistrement...' : 'Enregistrer le seuil de consommation'}
              </button>
            </form>
          </section>

          {/* Section 4 : Ajout de crédits via Stripe (One-shot ou Abonnement mensuel) (KAN-123 CA5) */}
          <section className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 space-y-4">
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <CreditCard className="w-4 h-4 text-blue-400" />
                <span>Ajouter des Crédits de Consommation (Stripe)</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Augmentez immédiatement votre plafond de consommation via un rechargement ponctuel ou un complément mensuel récurrent.
              </p>
            </div>

            <form onSubmit={(e) => void handleAddCredits(e)} className="space-y-4">
              {/* Choix du mode : One-Shot vs Abonnement Mensuel */}
              <div className="grid grid-cols-2 gap-2.5">
                <button
                  type="button"
                  onClick={() => setCreditMode('one_shot')}
                  className={`p-3 rounded-xl border text-left transition-all ${
                    creditMode === 'one_shot'
                      ? 'bg-blue-950/50 border-blue-500 text-white'
                      : 'bg-slate-950/70 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <div className="flex items-center gap-1.5 text-xs font-bold">
                    <PlusCircle className="w-3.5 h-3.5 text-blue-400" />
                    <span>Paiement One-Shot</span>
                  </div>
                  <p className="text-[11px] opacity-80 mt-1">Recharge ponctuelle immédiate</p>
                </button>

                <button
                  type="button"
                  onClick={() => setCreditMode('monthly_subscription')}
                  className={`p-3 rounded-xl border text-left transition-all ${
                    creditMode === 'monthly_subscription'
                      ? 'bg-blue-950/50 border-blue-500 text-white'
                      : 'bg-slate-950/70 border-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <div className="flex items-center gap-1.5 text-xs font-bold">
                    <Repeat className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Abonnement Mensuel</span>
                  </div>
                  <p className="text-[11px] opacity-80 mt-1">Crédits supplémentaires / mois</p>
                </button>
              </div>

              {/* Sélection rapide du montant */}
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Montant de crédits à ajouter (USD)
                </label>
                <div className="grid grid-cols-4 gap-2 mb-2.5">
                  {[10, 25, 50, 100].map((amt) => (
                    <button
                      key={amt}
                      type="button"
                      onClick={() => setCreditAmount(amt)}
                      className={`py-2 rounded-xl text-xs font-bold border transition-all ${
                        creditAmount === amt
                          ? 'bg-blue-600 border-blue-500 text-white'
                          : 'bg-slate-950 border-slate-800 text-slate-300 hover:bg-slate-800'
                      }`}
                    >
                      +{amt} $
                    </button>
                  ))}
                </div>
                <input
                  type="number"
                  min={5}
                  max={5000}
                  step={5}
                  value={creditAmount}
                  onChange={(e) => setCreditAmount(Number(e.target.value))}
                  className="w-full px-3.5 py-2 rounded-xl bg-slate-950 border border-slate-800 text-slate-100 text-xs focus:outline-none focus:border-blue-500"
                />
              </div>

              <button
                type="submit"
                disabled={addingCredits || creditAmount <= 0}
                className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-lg shadow-blue-900/30 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
              >
                <TrendingUp className="w-4 h-4" />
                <span>
                  {addingCredits
                    ? 'Traitement Stripe en cours...'
                    : creditMode === 'one_shot'
                    ? `Créditer +${creditAmount} $ maintenant (One-Shot Stripe)`
                    : `Souscrire +${creditAmount} $ / mois de crédits (Stripe)`}
                </span>
              </button>
            </form>

            {/* Historique récent des ajouts de crédits */}
            {consumption.credit_history && consumption.credit_history.length > 0 && (
              <div className="pt-3 border-t border-slate-800/80 space-y-2">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                  Derniers rechargements Stripe
                </span>
                <div className="space-y-1.5 max-h-32 overflow-y-auto">
                  {consumption.credit_history.slice(0, 5).map((entry) => (
                    <div
                      key={entry.id}
                      className="flex items-center justify-between text-xs bg-slate-950/70 border border-slate-800/80 px-3 py-2 rounded-lg"
                    >
                      <div>
                        <span className="font-bold text-emerald-400">+{entry.amount_usd.toFixed(2)} $</span>
                        <span className="text-slate-400 ml-2">({entry.mode_label})</span>
                      </div>
                      <span className="text-[11px] text-slate-500">
                        Plafond porté à {entry.new_limit_usd.toFixed(2)} $
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>

        {/* Pied de page sécurité & gouvernance */}
        <div className="p-4 rounded-2xl bg-slate-900/50 border border-slate-800/70 flex items-center justify-between text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-blue-400 shrink-0" />
            <span>
              Isolation cryptographique active : votre token OpenRouter dédié est chiffré au repos et injecté uniquement en mémoire dans votre conteneur.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
