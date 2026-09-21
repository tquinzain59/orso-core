import React from "react";
import { Download, CheckCircle2, Clock } from "lucide-react";
import { Tenant, Invoice } from "../types";

interface BillingViewProps {
  tenants: Tenant[];
  invoices: Invoice[];
  onSelectTenant: (t: Tenant) => void;
}

export const BillingView: React.FC<BillingViewProps> = ({
  tenants,
  invoices,
  onSelectTenant,
}) => {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Facturation, Abonnements & Forfaits</h1>
        <p className="text-sm text-slate-400 mt-1">
          Suivi des souscriptions Stripe Billing, encaissements et factures conformes.
        </p>
      </div>

      {/* Grille Tarifaire Officielle */}
      <div className="bg-slate-900/80 border border-slate-800 p-6 rounded-3xl">
        <h2 className="text-lg font-bold text-white mb-1">Grille Tarifaire Officielle Orso Agents</h2>
        <p className="text-xs text-slate-400 mb-6">Paliers mensuels validés par la direction</p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {/* Starter */}
          <div className="p-5 rounded-2xl bg-slate-950/70 border border-slate-800 relative">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20">
              Starter
            </span>
            <div className="mt-3">
              <div className="text-3xl font-extrabold text-white">99 € <span className="text-xs font-normal text-slate-400">HT / mois</span></div>
              <p className="text-xs text-slate-400 mt-2">
                1 agent au choix. Idéal pour débuter avec Jérôme (Recouvrement & Trésorerie).
              </p>
            </div>
            <ul className="mt-4 space-y-1.5 text-xs text-slate-300">
              <li className="flex items-center space-x-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-blue-400" />
                <span>1 conteneur dédié isolé</span>
              </li>
              <li className="flex items-center space-x-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-blue-400" />
                <span>Connecteurs ERP & Pappers</span>
              </li>
            </ul>
          </div>

          {/* Duo */}
          <div className="p-5 rounded-2xl bg-slate-950/70 border border-purple-500/40 relative shadow-lg shadow-purple-500/5">
            <div className="flex items-center justify-between">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/20">
                Duo
              </span>
              <span className="text-[10px] uppercase font-bold text-purple-300 bg-purple-500/20 px-2 py-0.5 rounded">
                Recommandé
              </span>
            </div>
            <div className="mt-3">
              <div className="text-3xl font-extrabold text-white">169 € <span className="text-xs font-normal text-slate-400">HT / mois</span></div>
              <p className="text-xs text-slate-400 mt-2">
                2 agents combinés (ex: Jérôme en trésorerie + Lucas en commercial/devis).
              </p>
            </div>
            <ul className="mt-4 space-y-1.5 text-xs text-slate-300">
              <li className="flex items-center space-x-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-purple-400" />
                <span>Économie de 29 € / mois</span>
              </li>
              <li className="flex items-center space-x-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-purple-400" />
                <span>Synergie Trésorerie & Vente</span>
              </li>
            </ul>
          </div>

          {/* Flotte Complète */}
          <div className="p-5 rounded-2xl bg-slate-950/70 border border-amber-500/40 relative shadow-lg shadow-amber-500/5">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
              Flotte Complète
            </span>
            <div className="mt-3">
              <div className="text-3xl font-extrabold text-white">279 € <span className="text-xs font-normal text-slate-400">HT / mois</span></div>
              <p className="text-xs text-slate-400 mt-2">
                Les 4 agents de la suite (Jérôme, Lucas, Clara, Victor) sans restriction.
              </p>
            </div>
            <ul className="mt-4 space-y-1.5 text-xs text-slate-300">
              <li className="flex items-center space-x-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-amber-400" />
                <span>Économie de 117 € / mois</span>
              </li>
              <li className="flex items-center space-x-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-amber-400" />
                <span>Support prioritaire & AO BOAMP</span>
              </li>
            </ul>
          </div>
        </div>
      </div>

      {/* Liste des Abonnements Clients */}
      <div className="bg-slate-900/80 border border-slate-800 p-6 rounded-3xl">
        <h2 className="text-lg font-bold text-white mb-4">Abonnements des Clients Actifs</h2>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                <th className="pb-3 font-semibold">Client</th>
                <th className="pb-3 font-semibold">Forfait Souscrit</th>
                <th className="pb-3 font-semibold">Montant Mensuel</th>
                <th className="pb-3 font-semibold">Moyen de Paiement</th>
                <th className="pb-3 font-semibold">Statut</th>
                <th className="pb-3 font-semibold text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {tenants.map((t) => (
                <tr key={t.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="py-3 font-medium text-white">
                    {t.name}
                    <div className="text-xs text-slate-400">{t.contact.email}</div>
                  </td>
                  <td className="py-3 text-slate-300">
                    <span className="font-semibold">{t.subscription.tier_label}</span>
                  </td>
                  <td className="py-3 font-bold text-white">
                    {t.subscription.price_ht > 0 ? `${t.subscription.price_ht} € HT` : "0 € (Essai)"}
                  </td>
                  <td className="py-3 text-xs text-slate-400 font-mono">
                    {t.subscription.payment_method || "Stripe Checkout"}
                  </td>
                  <td className="py-3">
                    {t.subscription.status === "active" && (
                      <span className="inline-flex items-center space-x-1 text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                        <CheckCircle2 className="w-3 h-3" />
                        <span>Actif</span>
                      </span>
                    )}
                    {t.subscription.status === "trialing" && (
                      <span className="inline-flex items-center space-x-1 text-xs px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 font-medium">
                        <Clock className="w-3 h-3" />
                        <span>Essai</span>
                      </span>
                    )}
                  </td>
                  <td className="py-3 text-right">
                    <button
                      onClick={() => onSelectTenant(t)}
                      className="text-xs text-sky-400 hover:text-sky-300 font-medium px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 transition-all"
                    >
                      Modifier Forfait
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Historique des Factures */}
      <div className="bg-slate-900/80 border border-slate-800 p-6 rounded-3xl">
        <h2 className="text-lg font-bold text-white mb-4">Dernières Factures Émises</h2>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-400">
                <th className="pb-3 font-semibold">Numéro Facture</th>
                <th className="pb-3 font-semibold">Client</th>
                <th className="pb-3 font-semibold">Date</th>
                <th className="pb-3 font-semibold">Montant HT</th>
                <th className="pb-3 font-semibold">Montant TTC</th>
                <th className="pb-3 font-semibold">Statut</th>
                <th className="pb-3 font-semibold text-right">Télécharger</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {invoices.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-400">
                    Aucune facture disponible.
                  </td>
                </tr>
              ) : (
                invoices.map((inv) => (
                  <tr key={inv.id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="py-3 font-mono font-semibold text-white">{inv.number}</td>
                    <td className="py-3 text-slate-300">{inv.tenant_name}</td>
                    <td className="py-3 text-slate-400 text-xs">
                      {new Date(inv.date).toLocaleDateString("fr-FR")}
                    </td>
                    <td className="py-3 font-bold text-white">{inv.amount_ht.toFixed(2)} €</td>
                    <td className="py-3 text-slate-400">{inv.amount_ttc.toFixed(2)} €</td>
                    <td className="py-3">
                      <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                        Payée
                      </span>
                    </td>
                    <td className="py-3 text-right">
                      <button
                        onClick={() => alert(`Téléchargement de la facture ${inv.number}`)}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-sky-400 hover:bg-slate-800 transition-all inline-flex items-center space-x-1"
                        title="Télécharger la facture PDF"
                      >
                        <Download className="w-4 h-4" />
                        <span className="text-xs">PDF</span>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
