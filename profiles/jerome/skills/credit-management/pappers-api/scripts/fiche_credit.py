#!/usr/bin/env python3
"""
Fiche crédit complète via l'API Pappers
Récupère et formate les données clés d'une entreprise pour l'analyse crédit.

Usage :
    python fiche_credit.py <SIREN> [--scoring] [--comptes] [--conformite NOM PRENOM DD-MM-YYYY]

Prérequis :
    export PAPPERS_API_TOKEN="votre_cle"

Options :
    --scoring        Inclut le scoring financier et non-financier (+60 crédits)
    --comptes        Inclut les comptes annuels détaillés
    --conformite     Vérifie la conformité d'un dirigeant (nom prenom date_naissance)
"""

import sys
import os
import json
import argparse
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

BASE_URL = "https://api.pappers.fr/v2"


def get_api_token():
    token = os.environ.get("PAPPERS_API_TOKEN")
    if not token:
        print("❌ Erreur : variable d'environnement PAPPERS_API_TOKEN non définie.")
        print("   Exportez votre clé : export PAPPERS_API_TOKEN='votre_cle'")
        sys.exit(1)
    return token


def api_get(endpoint, params, token):
    """Effectue un appel GET à l'API Pappers et retourne le JSON."""
    query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    url = f"{BASE_URL}/{endpoint}?api_token={token}&{query}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"❌ Erreur HTTP {e.code} sur {endpoint}: {body[:500]}")
        return None
    except URLError as e:
        print(f"❌ Erreur réseau sur {endpoint}: {e.reason}")
        return None


def format_euros(val):
    if val is None:
        return "N/A"
    try:
        return f"{int(val):,} €".replace(",", " ")
    except (ValueError, TypeError):
        return str(val)


def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def analyse_entreprise(data):
    """Affiche une analyse synthétique de l'entreprise pour le credit management."""
    if not data:
        return

    # --- Identité ---
    print_section("IDENTITÉ")
    print(f"  Nom                 : {data.get('nom_entreprise') or data.get('denomination', 'N/A')}")
    print(f"  SIREN               : {data.get('siren', 'N/A')}")
    print(f"  SIRET siège         : {data.get('siege', {}).get('siret', 'N/A')}")
    print(f"  Forme juridique     : {data.get('forme_juridique', 'N/A')}")
    print(f"  Capital social      : {format_euros(data.get('capital_social'))}")
    print(f"  Code NAF            : {data.get('code_naf', 'N/A')} — {data.get('nomenclature_code_naf', '')}")
    print(f"  Date de création    : {data.get('date_creation_formate', 'N/A')}")
    print(f"  Ancienneté          : {data.get('annee_effective_creation', 'N/A')} ans")

    # --- Statut ---
    print_section("STATUT LÉGAL")
    print(f"  Statut RCS          : {data.get('statut_rcs', 'N/A')}")
    print(f"  Activité cessée     : {'OUI ⚠️' if data.get('entreprise_cessee') else 'Non'}")
    print(f"  Diffusable Insee    : {'Oui' if data.get('diffusable', True) else 'Non (diffusion partielle)'}")
    if data.get('motif_cessation'):
        print(f"  Motif cessation     : {data.get('motif_cessation')}")

    # --- Adresse ---
    siege = data.get('siege', {})
    print_section("ADRESSE SIÈGE")
    print(f"  {siege.get('adresse_ligne_1', '')} {siege.get('code_postal', '')} {siege.get('ville', '')}")

    # --- Dirigeants ---
    dirigeants = data.get('dirigeants', [])
    print_section(f"DIRIGEANTS ({len(dirigeants)})")
    for d in dirigeants[:10]:
        nom = f"{d.get('prenom', '')} {d.get('nom', '')}".strip() or d.get('denomination', 'N/A')
        qualite = d.get('qualite', 'N/A')
        print(f"  • {nom} — {qualite}")
        if d.get('date_de_naissance_formate'):
            print(f"    Né(e) le : {d['date_de_naissance_formate']}")

    # --- Bénéficiaires effectifs ---
    be = data.get('beneficiaires_effectifs', [])
    print_section(f"BÉNÉFICIAIRES EFFECTIFS ({len(be)})")
    for b in be[:10]:
        nom = f"{b.get('prenom', '')} {b.get('nom', '')}".strip()
        parts = b.get('details_parts_directes', {})
        pct = parts.get('pourcentage_plein_propriete', 'N/A') if parts else 'N/A'
        print(f"  • {nom} — {pct}% parts directes")

    # --- Procédures collectives ---
    proc = data.get('procedures_collectives', [])
    print_section(f"PROCÉDURES COLLECTIVES ({len(proc)})")
    if not proc:
        print("  ✅ Aucune procédure collective en cours ou passée")
    else:
        for p in proc:
            print(f"  ⚠️ {p.get('type', 'N/A')} — {p.get('date_ouverture_formate', 'N/A')} — {p.get('statut', 'N/A')}")

    # --- Publications BODACC récentes ---
    bodacc = data.get('publications_bodacc', [])
    print_section(f"PUBLICATIONS BODACC ({len(bodacc)} récentes)")
    for b in bodacc[:5]:
        print(f"  • {b.get('type', 'N/A')} — {b.get('date', 'N/A')}")

    # --- Comptes / Financier ---
    comptes = data.get('comptes', [])
    print_section(f"COMPTES PUBLIÉS ({len(comptes)} exercices)")
    for c in comptes[:3]:
        print(f"  Exercice {c.get('date_cloture_exercice_formate', 'N/A')}:")
        print(f"    Chiffre d'affaires : {format_euros(c.get('chiffre_affaires'))}")
        print(f"    Résultat           : {format_euros(c.get('resultat'))}")
        print(f"    Trésorerie         : {format_euros(c.get('tresorerie'))}")
        print(f"    Total bilan        : {format_euros(c.get('total bilan') or c.get('total_bilan'))}")

    # --- Scoring ---
    sf = data.get('scoring_financier')
    if sf:
        print_section("SCORING FINANCIER")
        score = sf.get('score', 'N/A')
        print(f"  Score : {score}")
        print(f"  Note  : {sf.get('note', 'N/A')}")
        details = sf.get('details_score', {})
        if details:
            for k, v in details.items():
                print(f"    {k} : {v}")

    snf = data.get('scoring_non_financier')
    if snf:
        print_section("SCORING NON-FINANCIER")
        print(f"  Score : {snf.get('score', 'N/A')}")
        print(f"  Note  : {snf.get('note', 'N/A')}")

    # --- Sanctions / PPE ---
    if data.get('sanctions'):
        print_section("⚠️ SANCTIONS")
        for s in data.get('sanctions', []):
            print(f"  • {s}")

    # --- Synthèse risque ---
    print_section("SYNTHÈSE RISQUE CRÉDIT")
    risques = []
    if data.get('entreprise_cessee'):
        risques.append("🔴 Activité cessée")
    if data.get('statut_rcs') and 'radié' in data.get('statut_rcs', '').lower():
        risques.append("🔴 Radié du RCS")
    if proc:
        risques.append("🔴 Procédure collective détectée")
    if not comptes:
        risques.append("🟡 Comptes non publiés — transparence limitée")
    if len(comptes) > 0:
        dernier = comptes[0]
        if dernier.get('resultat') is not None and dernier.get('resultat') < 0:
            risques.append("🟡 Dernier exercice en pertes")
        if dernier.get('tresorerie') is not None and dernier.get('tresorerie') < 0:
            risques.append("🔴 Trésorerie négative")

    if not risques:
        print("  ✅ Aucun signal d'alerte majeur détecté sur les données disponibles")
    else:
        for r in risques:
            print(f"  {r}")

    print(f"\n{'='*60}")
    print(f"  Fin de l'analyse")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Fiche crédit via API Pappers")
    parser.add_argument("siren", help="SIREN de l'entreprise (9 chiffres)")
    parser.add_argument("--scoring", action="store_true", help="Inclut le scoring financier + non-financier (+60 crédits)")
    parser.add_argument("--comptes", action="store_true", help="Récupère les comptes annuels détaillés")
    parser.add_argument("--conformite", nargs=3, metavar=("NOM", "PRENOM", "DD-MM-YYYY"),
                        help="Vérifie la conformité d'un dirigeant")
    parser.add_argument("--json", action="store_true", help="Sortie JSON brute au lieu du formatage")
    args = parser.parse_args()

    token = get_api_token()

    # Construction des champs supplémentaires
    champs = ["representants_legaux", "categorie_entreprise", "entreprises_dirigees"]
    if args.scoring:
        champs.extend(["scoring_financier", "scoring_non_financier"])
    champs_str = ",".join(champs)

    # 1. Fiche entreprise
    print(f"\n📊 Récupération des données pour SIREN {args.siren}...\n")
    data = api_get("entreprise", {
        "siren": args.siren,
        "champs_supplementaires": champs_str,
        "validite_tva_intracommunautaire": "true",
    }, token)

    if not data:
        sys.exit(1)

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        analyse_entreprise(data)

    # 2. Comptes annuels détaillés
    if args.comptes:
        print("\n📥 Récupération des comptes annuels détaillés...")
        comptes = api_get("entreprise/comptes", {"siren": args.siren}, token)
        if comptes and args.json:
            print(json.dumps(comptes, indent=2, ensure_ascii=False))
        elif comptes:
            print(f"  → {len(comptes)} exercices récupérés (utilisez --json pour le détail)")

    # 3. Conformité dirigeant
    if args.conformite:
        nom, prenom, date_naissance = args.conformite
        print(f"\n🔍 Vérification conformité : {prenom} {nom}...")
        conf = api_get("conformite/personne_physique", {
            "nom": nom,
            "prenom": prenom,
            "date_de_naissance": date_naissance,
        }, token)
        if conf:
            print(json.dumps(conf, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()