#!/usr/bin/env python3
"""
Outil Hermès de détection des factures en retard et de calcul des pénalités légales (L.441-10).
Conçu pour être invoqué en tant qu'outil par l'agent ou exécuté en ligne de commande.

Usage CLI :
    python skills/check_overdue.py [--file chemin/fichier.csv] [--min-days 1] [--json]
"""

import sys
import os
import json
import argparse
from datetime import date
from typing import Any, Dict, List, Optional

# Ajout du chemin parent pour import robuste
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skills.credit_management.balance_agee import calculer_balance_agee, fetch_invoices
from skills.common.parsers import format_euros


# Taux d'intérêt légal de retard de paiement (Code de commerce art. L.441-10)
# Taux Refi BCE semestriel + 10 points (environ 14 % annuel)
TAUX_PENALITE_ANNUEL = 0.14
INDEMNITE_FORFAITAIRE_RECOUVREMENT = 40.0  # 40 € par facture échue


def trouver_fichier_comptable_defaut() -> Optional[str]:
    """Recherche un fichier de factures par défaut dans les dossiers data usuels."""
    candidats = [
        "/app/data/factures.csv",
        "/app/data/export_factures.csv",
        "/app/data/invoices.csv",
        "./data/factures.csv",
        "./data/export_factures.csv",
        "./data/invoices.csv",
    ]
    for c in candidats:
        if os.path.exists(c):
            return c
    return None


def check_overdue_invoices(
    file_path: Optional[str] = None,
    erp: str = "csv",
    token: Optional[str] = None,
    realm: Optional[str] = None,
    min_days_overdue: int = 1,
) -> Dict[str, Any]:
    """
    Point d'entrée principal pour l'agent Hermès et les workflows de recouvrement.
    Analyse les factures, filtre les impayés au-delà du seuil et calcule les pénalités L.441-10.
    """
    target_file = file_path
    if erp.lower() in ("csv", "excel") and not target_file:
        target_file = trouver_fichier_comptable_defaut()
        if not target_file:
            return {
                "status": "warning",
                "message": "Aucun fichier de factures trouvé. Veuillez fournir un chemin de fichier comptable.",
                "retards": [],
                "nb_factures_en_retard": 0,
                "montant_principal_total": 0.0,
                "penalites_totales": 0.0,
            }

    try:
        raw_invoices = fetch_invoices(erp=erp, filepath=target_file, token=token, realm=realm)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Erreur lors de la récupération des factures : {str(e)}",
            "retards": [],
        }

    balance = calculer_balance_agee(raw_invoices, erp=erp)
    factures_retard = balance.get("factures_en_retard", [])

    items_a_relancer: List[Dict[str, Any]] = []
    total_principal = 0.0
    total_penalites = 0.0
    total_indemnites = 0.0

    for f in factures_retard:
        jours = f["retard_jours"]
        if jours < min_days_overdue:
            continue

        montant = f["montant"]
        total_principal += montant

        # Calcul intérêt moratoire prorata temporis
        interets = round(montant * (TAUX_PENALITE_ANNUEL / 365.0) * jours, 2)
        indemnite = INDEMNITE_FORFAITAIRE_RECOUVREMENT

        total_penalites += interets
        total_indemnites += indemnite

        # Détermination de l'urgence et du canal conseillé
        if jours > 60:
            urgence = "critique"
            action_recommandee = "Mise en demeure formelle avec accusé de réception"
        elif jours > 30:
            urgence = "elevee"
            action_recommandee = "Relance niveau 2 (Téléphone + Email formel avec calcul de pénalités)"
        else:
            urgence = "moderee"
            action_recommandee = "Relance courtoise niveau 1 (Email / WhatsApp)"

        items_a_relancer.append({
            "numero_facture": f["numero"],
            "client": f["client"],
            "echeance": f["echeance"],
            "jours_de_retard": jours,
            "montant_principal": montant,
            "montant_principal_formate": format_euros(montant),
            "interets_moratoires": interets,
            "indemnite_forfaitaire": indemnite,
            "total_exigible": round(montant + interets + indemnite, 2),
            "total_exigible_formate": format_euros(montant + interets + indemnite),
            "urgence": urgence,
            "action_recommandee": action_recommandee,
        })

    return {
        "status": "success",
        "date_analyse": date.today().isoformat(),
        "nb_factures_en_retard": len(items_a_relancer),
        "montant_principal_total": round(total_principal, 2),
        "montant_principal_formate": format_euros(total_principal),
        "interets_moratoires_total": round(total_penalites, 2),
        "indemnites_forfaitaires_total": round(total_indemnites, 2),
        "total_global_reclame": round(total_principal + total_penalites + total_indemnites, 2),
        "total_global_formate": format_euros(total_principal + total_penalites + total_indemnites),
        "retards": items_a_relancer,
    }


def main():
    parser = argparse.ArgumentParser(description="Détection des factures en retard de paiement (Hermès Core)")
    parser.add_argument("--file", help="Chemin vers le fichier comptable (CSV/Excel)")
    parser.add_argument("--erp", default="csv", choices=["csv", "sellsy", "sage", "qbo", "odoo", "d365"], help="Source ERP")
    parser.add_argument("--min-days", type=int, default=1, help="Nombre minimum de jours de retard pour relancer")
    parser.add_argument("--json", action="store_true", help="Sortie au format JSON pour l'agent ou une API")
    args = parser.parse_args()

    resultats = check_overdue_invoices(file_path=args.file, erp=args.erp, min_days_overdue=args.min_days)

    if args.json:
        print(json.dumps(resultats, indent=2, ensure_ascii=False))
    else:
        if resultats.get("status") == "warning":
            print(f"⚠️ {resultats.get('message')}")
            sys.exit(0)
        elif resultats.get("status") == "error":
            print(f"❌ {resultats.get('message')}")
            sys.exit(1)

        print(f"\n{'='*80}")
        print(f"  ANALYSE DES IMPAYÉS AU {resultats['date_analyse']} (Article L.441-10 C. Commerce)")
        print(f"{'='*80}")
        print(f"  Factures en retard : {resultats['nb_factures_en_retard']}")
        print(f"  Montant principal  : {resultats['montant_principal_formate']}")
        print(f"  Pénalités + Frais  : {format_euros(resultats['interets_moratoires_total'] + resultats['indemnites_forfaitaires_total'])}")
        print(f"  Total réclamable   : {resultats['total_global_formate']}")
        print(f"{'-'*80}")

        for r in resultats["retards"]:
            print(
                f"  [{r['urgence'].upper():<8}] {r['numero_facture']:<12} {r['client'][:22]:<24} "
                f"+{r['jours_de_retard']}j | Dû: {r['total_exigible_formate']:>12} | {r['action_recommandee']}"
            )
        print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
