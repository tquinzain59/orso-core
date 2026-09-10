#!/usr/bin/env python3
"""
Veille BODACC par SIREN via l'API OpenDataSoft (gratuit, sans authentification)
Récupère et formate les annonces BODACC d'une entreprise.

Usage :
    python veille_bodacc.py <SIREN> [--limit N] [--famille CODE] [--depuis YYYY-MM-DD] [--json]

Options :
    --limit N        Nombre max de résultats (défaut: 50)
    --famille CODE   Filtrer par famille (dpc, mod, cre, rad, pro, ven, imm, div)
    --depuis DATE    Date de parution minimale (YYYY-MM-DD)
    --json           Sortie JSON brute
"""

import sys
import json
import argparse
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
from urllib.error import HTTPError, URLError

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


def fetch_bodacc(siren, limit=50, famille=None, depuis=None):
    """Récupère les annonces BODACC d'une entreprise via l'API OpenDataSoft."""
    conditions = [f'registre = "{siren}"']

    if famille:
        conditions.append(f'familleavis = "{famille}"')

    if depuis:
        conditions.append(f'dateparution >= "{depuis}"')

    where = " AND ".join(conditions)

    params = {
        "where": where,
        "limit": limit,
        "order_by": "dateparution desc",
    }

    url = f"{API_BASE}?{urlencode(params, quote_via=quote)}"
    req = Request(url, headers={"Accept": "application/json"})

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"❌ Erreur HTTP {e.code}: {body[:500]}")
        return None
    except URLError as e:
        print(f"❌ Erreur réseau: {e.reason}")
        return None


def format_annonce(record):
    """Formate une annonce BODACC pour l'affichage."""
    fields = record.get("record", {}).get("fields", {})
    if not fields:
        return None

    famille_code = fields.get("familleavis", "?")
    famille_lib = fields.get("familleavis_lib", "Inconnue")
    icon = ICONS.get(famille_code, "ℹ️")

    date = fields.get("dateparution", "N/A")
    commercant = fields.get("commercant", "N/A")
    ville = fields.get("ville", "")
    cp = fields.get("cp", "")
    type_avis = fields.get("typeavis_lib", "")
    tribunal = fields.get("tribunal", "")

    line = f"  {icon} {date} | {famille_lib} | {type_avis}"
    line += f"\n     Entreprise : {commercant}"
    if ville or cp:
        line += f"\n     Adresse    : {cp} {ville}".rstrip()
    if tribunal:
        line += f"\n     Tribunal   : {tribunal}"

    return line


def analyse_risque(data):
    """Analyse les annonces et identifie les signaux d'alerte."""
    alerts = []
    records = data.get("records", [])

    for r in records:
        f = r.get("record", {}).get("fields", {})
        famille = f.get("familleavis", "")
        date = f.get("dateparution", "")

        if famille == "pro":
            alerts.append(f"🔴 Procédure collective détectée le {date}")
        elif famille == "rad":
            alerts.append(f"🔴 Radiation détectée le {date}")
        elif famille == "ven":
            alerts.append(f"🟡 Vente/cession détectée le {date}")

    return alerts


def main():
    parser = argparse.ArgumentParser(description="Veille BODACC par SIREN (open data gratuit)")
    parser.add_argument("siren", help="SIREN de l'entreprise (9 chiffres)")
    parser.add_argument("--limit", type=int, default=50, help="Nombre max de résultats (défaut: 50)")
    parser.add_argument("--famille", choices=list(FAMILLES.keys()),
                        help="Filtrer par famille d'annonces")
    parser.add_argument("--depuis", help="Date minimale (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Sortie JSON brute")
    args = parser.parse_args()

    # Nettoyer le SIREN
    siren = args.siren.replace(" ", "").strip()
    if len(siren) != 9 or not siren.isdigit():
        print("❌ SIREN invalide : doit contenir 9 chiffres")
        sys.exit(1)

    famille_lib = FAMILLES.get(args.famille, "Toutes") if args.famille else "Toutes"
    print(f"\n📊 Veille BODACC pour SIREN {siren}")
    print(f"   Famille : {famille_lib}")
    if args.depuis:
        print(f"   Depuis  : {args.depuis}")
    print()

    data = fetch_bodacc(siren, limit=args.limit, famille=args.famille, depuis=args.depuis)

    if not data:
        sys.exit(1)

    total = data.get("total_count", 0)
    records = data.get("records", [])

    print(f"📋 {total} annonce(s) trouvée(s), {len(records)} affichée(s)")
    print(f"{'='*70}")

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        for record in records:
            line = format_annonce(record)
            if line:
                print(line)
                print()

        # Synthèse risque
        print(f"{'='*70}")
        print("SYNTHÈSE RISQUE")
        print(f"{'='*70}")

        alerts = analyse_risque(data)
        if not alerts:
            print("  ✅ Aucun signal d'alerte majeur détecté dans le BODACC")
        else:
            for alert in alerts:
                print(f"  {alert}")

        print(f"\n{'='*70}")
        print("  Fin de la veille BODACC")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    main()