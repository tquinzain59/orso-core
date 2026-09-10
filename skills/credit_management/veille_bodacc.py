#!/usr/bin/env python3
"""
Veille légale BODACC par SIREN via l'API OpenDataSoft (sans authentification).
Détecte les signaux critiques : procédures collectives (redressement, liquidation), radiations, ventes.

Usage CLI :
    python -m skills.credit_management.veille_bodacc <SIREN> [--limit N] [--famille CODE] [--json]
"""

import sys
import json
import argparse
from typing import Any, Dict, List, Optional

try:
    from skills.common.parsers import clean_siren
    from skills.common.client import HermesHttpClient
except ImportError:
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    from skills.common.parsers import clean_siren
    from skills.common.client import HermesHttpClient


API_BASE = "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records"

FAMILLES = {
    "dpc": "Dépôts des comptes",
    "mod": "Modifications diverses",
    "cre": "Créations",
    "rad": "Radiations",
    "pro": "Procédures collectives",
    "ven": "Ventes et cessions",
    "imm": "Immatriculations",
    "div": "Annonces diverses",
}

ICONS = {
    "dpc": "🟢",
    "mod": "🟠",
    "cre": "🟢",
    "rad": "🔴",
    "pro": "🔴",
    "ven": "🟡",
    "imm": "🟢",
    "div": "ℹ️",
}


def fetch_bodacc_annonces(
    siren: str,
    limit: int = 50,
    famille: Optional[str] = None,
    depuis: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Interroge l'API BODACC pour un SIREN donné et renvoie une synthèse de risque structurée.
    """
    valid_siren = clean_siren(siren)
    if not valid_siren:
        return {"status": "error", "message": f"SIREN invalide: {siren}"}

    conditions = [f'registre = "{valid_siren}"']
    if famille:
        conditions.append(f'familleavis = "{famille}"')
    if depuis:
        conditions.append(f'dateparution >= "{depuis}"')

    params = {
        "where": " AND ".join(conditions),
        "limit": limit,
        "order_by": "dateparution desc",
    }

    client = HermesHttpClient()
    raw_data = client.get(API_BASE, params=params)

    if not raw_data:
        return {"status": "error", "message": "Impossible de contacter l'API BODACC."}

    records = raw_data.get("records", [])
    total_count = raw_data.get("total_count", 0)

    annonces_formatees: List[Dict[str, Any]] = []
    alertes: List[str] = []

    for r in records:
        f = r.get("record", {}).get("fields", {})
        if not f:
            continue

        famille_code = f.get("familleavis", "?")
        date_parution = f.get("dateparution", "")
        type_avis = f.get("typeavis_lib", "")
        commercant = f.get("commercant", "N/A")
        tribunal = f.get("tribunal", "")

        annonces_formatees.append({
            "famille_code": famille_code,
            "famille_lib": FAMILLES.get(famille_code, "Inconnue"),
            "date_parution": date_parution,
            "type_avis": type_avis,
            "commercant": commercant,
            "tribunal": tribunal,
            "ville": f.get("ville", ""),
            "cp": f.get("cp", ""),
        })

        if famille_code == "pro":
            alertes.append(f"🔴 Procédure collective détectée le {date_parution} ({type_avis})")
        elif famille_code == "rad":
            alertes.append(f"🔴 Radiation du RCS détectée le {date_parution}")
        elif famille_code == "ven":
            alertes.append(f"🟡 Vente ou cession d'activité détectée le {date_parution}")

    niveau_risque = "critique" if any(a.startswith("🔴") for a in alertes) else ("moyen" if alertes else "faible")

    return {
        "status": "success",
        "siren": valid_siren,
        "total_annonces": total_count,
        "annonces": annonces_formatees,
        "alertes": alertes,
        "niveau_risque": niveau_risque,
    }


def main():
    parser = argparse.ArgumentParser(description="Veille BODACC par SIREN")
    parser.add_argument("siren", help="SIREN de l'entreprise (9 chiffres)")
    parser.add_argument("--limit", type=int, default=50, help="Nombre max d'annonces")
    parser.add_argument("--famille", choices=list(FAMILLES.keys()), help="Filtrer par code famille")
    parser.add_argument("--depuis", help="Date minimale (AAAA-MM-JJ)")
    parser.add_argument("--json", action="store_true", help="Afficher le résultat au format JSON")
    args = parser.parse_args()

    res = fetch_bodacc_annonces(args.siren, limit=args.limit, famille=args.famille, depuis=args.depuis)

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        if res.get("status") != "success":
            print(f"❌ {res.get('message')}")
            sys.exit(1)

        print(f"\n{'='*70}")
        print(f"  VEILLE BODACC POUR LE SIREN {res['siren']}")
        print(f"  Total annonces : {res['total_annonces']} — Niveau de risque : {res['niveau_risque'].upper()}")
        print(f"{'='*70}\n")

        for a in res["annonces"][:10]:
            ico = ICONS.get(a["famille_code"], "ℹ️")
            print(f"  {ico} {a['date_parution']} | {a['famille_lib']} | {a['type_avis']}")
            print(f"     Entreprise : {a['commercant']}")
            if a['tribunal']:
                print(f"     Tribunal   : {a['tribunal']}")
            print()

        print(f"{'='*70}")
        print("  SYNTHÈSE DU RISQUE")
        print(f"{'='*70}")
        if not res["alertes"]:
            print("  ✅ Aucun signal d'alerte critique détecté dans le BODACC.")
        else:
            for alerte in res["alertes"]:
                print(f"  {alerte}")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
