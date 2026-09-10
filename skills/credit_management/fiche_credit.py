#!/usr/bin/env python3
"""
Fiche Crédit et Solvabilité d'Entreprise via l'API Pappers.
Analyse les bilans, scoring financier, dirigeants et signaux légaux.

Usage CLI :
    python -m skills.credit_management.fiche_credit <SIREN> [--scoring] [--comptes] [--json]
"""

import sys
import os
import json
import argparse
from typing import Any, Dict, List, Optional

try:
    from skills.common.parsers import clean_siren, format_euros
    from skills.common.client import HermesHttpClient
except ImportError:
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    from skills.common.parsers import clean_siren, format_euros
    from skills.common.client import HermesHttpClient


BASE_URL = "https://api.pappers.fr/v2"


def get_api_token(custom_token: Optional[str] = None) -> Optional[str]:
    return custom_token or os.environ.get("PAPPERS_API_TOKEN")


def fetch_fiche_credit(
    siren: str,
    token: Optional[str] = None,
    scoring: bool = False,
    comptes: bool = False,
) -> Dict[str, Any]:
    """
    Récupère et structure l'analyse de solvabilité d'une entreprise via Pappers.
    """
    valid_siren = clean_siren(siren)
    if not valid_siren:
        return {"status": "error", "message": f"Numéro SIREN invalide : {siren}"}

    api_token = get_api_token(token)
    if not api_token:
        return {
            "status": "error",
            "message": "Variable PAPPERS_API_TOKEN non définie. Clé API requise.",
        }

    client = HermesHttpClient()

    champs = ["representants_legaux", "categorie_entreprise", "entreprises_dirigees"]
    if scoring:
        champs.extend(["scoring_financier", "scoring_non_financier"])

    params = {
        "api_token": api_token,
        "siren": valid_siren,
        "champs_supplementaires": ",".join(champs),
        "validite_tva_intracommunautaire": "true",
    }

    raw_data = client.get(f"{BASE_URL}/entreprise", params=params)
    if not raw_data:
        return {"status": "error", "message": f"Entreprise introuvable ou erreur API pour le SIREN {valid_siren}"}

    # Extraction structurée
    identite = {
        "nom": raw_data.get("nom_entreprise") or raw_data.get("denomination", "N/A"),
        "siren": raw_data.get("siren", valid_siren),
        "siret_siege": raw_data.get("siege", {}).get("siret", "N/A"),
        "forme_juridique": raw_data.get("forme_juridique", "N/A"),
        "capital_social": raw_data.get("capital_social"),
        "capital_social_formate": format_euros(raw_data.get("capital_social")),
        "code_naf": raw_data.get("code_naf", "N/A"),
        "activite": raw_data.get("nomenclature_code_naf", ""),
        "date_creation": raw_data.get("date_creation_formate", "N/A"),
    }

    statut_legal = {
        "statut_rcs": raw_data.get("statut_rcs", "N/A"),
        "entreprise_cessee": bool(raw_data.get("entreprise_cessee", False)),
        "motif_cessation": raw_data.get("motif_cessation"),
        "procedures_collectives": raw_data.get("procedures_collectives", []),
    }

    dirigeants_liste = []
    for d in raw_data.get("dirigeants", [])[:5]:
        nom_complet = f"{d.get('prenom', '')} {d.get('nom', '')}".strip() or d.get("denomination", "N/A")
        dirigeants_liste.append({
            "nom": nom_complet,
            "qualite": d.get("qualite", "N/A"),
            "date_naissance": d.get("date_de_naissance_formate"),
        })

    comptes_liste = []
    for c in raw_data.get("comptes", [])[:3]:
        comptes_liste.append({
            "date_cloture": c.get("date_cloture_exercice_formate", "N/A"),
            "chiffre_affaires": c.get("chiffre_affaires"),
            "ca_formate": format_euros(c.get("chiffre_affaires")),
            "resultat": c.get("resultat"),
            "resultat_formate": format_euros(c.get("resultat")),
            "tresorerie": c.get("tresorerie"),
            "tresorerie_formatee": format_euros(c.get("tresorerie")),
        })

    # Synthèse des signaux de risque
    risques = []
    if statut_legal["entreprise_cessee"]:
        risques.append("🔴 Activité cessée")
    if statut_legal["statut_rcs"] and "radié" in statut_legal["statut_rcs"].lower():
        risques.append("🔴 Radiée du RCS")
    if statut_legal["procedures_collectives"]:
        risques.append("🔴 Procédure collective ouverte")
    if not comptes_liste:
        risques.append("🟡 Comptes non déposés au greffe")
    elif comptes_liste[0].get("resultat") is not None and comptes_liste[0]["resultat"] < 0:
        risques.append("🟡 Dernier résultat net déficitaire")
    if comptes_liste and comptes_liste[0].get("tresorerie") is not None and comptes_liste[0]["tresorerie"] < 0:
        risques.append("🔴 Trésorerie nette négative")

    return {
        "status": "success",
        "siren": valid_siren,
        "identite": identite,
        "statut_legal": statut_legal,
        "dirigeants": dirigeants_liste,
        "comptes": comptes_liste,
        "scoring_financier": raw_data.get("scoring_financier"),
        "scoring_non_financier": raw_data.get("scoring_non_financier"),
        "risques": risques,
        "niveau_risque": "critique" if any(r.startswith("🔴") for r in risques) else ("moyen" if risques else "faible"),
    }


def main():
    parser = argparse.ArgumentParser(description="Analyse de Solvabilité Pappers")
    parser.add_argument("siren", help="Numéro SIREN de l'entreprise (9 chiffres)")
    parser.add_argument("--token", help="Jeton d'accès API Pappers")
    parser.add_argument("--scoring", action="store_true", help="Inclure le scoring (+60 crédits)")
    parser.add_argument("--comptes", action="store_true", help="Récupérer les liasses détaillées")
    parser.add_argument("--json", action="store_true", help="Sortie au format JSON")
    args = parser.parse_args()

    fiche = fetch_fiche_credit(args.siren, token=args.token, scoring=args.scoring, comptes=args.comptes)

    if args.json:
        print(json.dumps(fiche, indent=2, ensure_ascii=False))
    else:
        if fiche.get("status") != "success":
            print(f"❌ {fiche.get('message')}")
            sys.exit(1)

        id_data = fiche["identite"]
        print(f"\n{'='*70}")
        print(f"  FICHE CRÉDIT : {id_data['nom']} (SIREN: {fiche['siren']})")
        print(f"  Niveau de risque estimé : {fiche['niveau_risque'].upper()}")
        print(f"{'='*70}")
        print(f"  Forme juridique : {id_data['forme_juridique']} — Capital : {id_data['capital_social_formate']}")
        print(f"  Code NAF        : {id_data['code_naf']} ({id_data['activite']})")
        print(f"  Statut RCS      : {fiche['statut_legal']['statut_rcs']}")

        if fiche["comptes"]:
            print(f"\n  Derniers comptes publiés :")
            c = fiche["comptes"][0]
            print(f"    Exercice {c['date_cloture']} : CA {c['ca_formate']} | Résultat {c['resultat_formate']} | Trésorerie {c['tresorerie_formatee']}")

        print(f"\n  Signaux de vigilance :")
        if not fiche["risques"]:
            print("    ✅ Aucun signal d'alerte majeur détecté.")
        else:
            for r in fiche["risques"]:
                print(f"    {r}")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
