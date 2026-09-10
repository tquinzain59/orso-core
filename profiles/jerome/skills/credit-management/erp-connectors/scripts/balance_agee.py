#!/usr/bin/env python3
"""
Balance agee depuis les factures impayées d'un ERP.
Supporte : Sellsy, Sage, QuickBooks, Odoo, Dynamics 365 BC, et import CSV.

Usage:
    python balance_agee.py --erp sellsy --token $SELLSY_TOKEN
    python balance_agee.py --erp sage --token $SAGE_TOKEN
    python balance_agee.py --erp qbo --token $QBO_TOKEN --realm $QBO_REALM_ID
    python balance_agee.py --erp csv --file export_factures.csv
"""

import sys, json, argparse
from datetime import datetime, date
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

TRANCHES = [
    (0, 30, "0-30j"),
    (31, 60, "31-60j"),
    (61, 90, "61-90j"),
    (91, 180, "91-180j"),
    (181, 99999, "180j+"),
]


def fetch_invoices_sellsy(token, limit=500):
    url = f"https://api.sellsy.com/v2/invoices?status=unpaid&limit={limit}"
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data.get("data", data.get("invoices", []))


def fetch_invoices_sage(token, limit=500):
    url = f"https://api.accounting.sage.com/v3.1/sales_invoices?status=UNPAID&items_per_page={limit}"
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data.get("$items", data.get("items", []))


def fetch_invoices_qbo(token, realm):
    url = f'https://quickbooks.api.intuit.com/v3/company/{realm}/query?query=SELECT * FROM Invoice WHERE Balance > %270%27'
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data.get("QueryResponse", {}).get("Invoice", [])


def fetch_invoices_csv(filepath):
    import csv
    invoices = []
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            invoices.append(row)
    return invoices


def normalize_invoice(inv, erp):
    """Normalise une facture dans un format commun."""
    today = date.today()
    if erp == "sellsy":
        due_str = inv.get("due_date") or inv.get("expiry_date", "")
        try:
            due = datetime.fromisoformat(due_str[:10]).date()
        except:
            due = today
        return {
            "numero": inv.get("number", inv.get("id", "?")),
            "client": inv.get("contact_name") or inv.get("contact", {}).get("name", "?"),
            "montant": float(inv.get("amount_due", inv.get("total", 0))),
            "echeance": due,
        }
    elif erp == "sage":
        due_str = inv.get("due_date", "")
        try:
            due = datetime.fromisoformat(due_str[:10]).date()
        except:
            due = today
        return {
            "numero": inv.get("id", "?"),
            "client": inv.get("contact_name", "?"),
            "montant": float(inv.get("outstanding_amount", inv.get("total_amount", 0))),
            "echeance": due,
        }
    elif erp == "qbo":
        due_str = inv.get("DueDate", "")
        try:
            due = datetime.fromisoformat(due_str[:10]).date()
        except:
            due = today
        return {
            "numero": inv.get("DocNumber", inv.get("Id", "?")),
            "client": inv.get("CustomerRef", {}).get("name", "?"),
            "montant": float(inv.get("Balance", 0)),
            "echeance": due,
        }
    elif erp == "csv":
        # CSV générique : chercher colonnes communes (insensible à la casse)
        inv_lower = {k.lower(): v for k, v in inv.items()}
        numero = inv_lower.get("numero") or inv_lower.get("facture") or inv_lower.get("number") or inv_lower.get("no facture") or "?"
        client = inv_lower.get("client") or inv_lower.get("nom") or inv_lower.get("customer") or inv_lower.get("raison sociale") or "?"
        montant = 0
        for k in ("montant", "montant ttc", "amount", "solde", "balance", "total", "ttc", "net"):
            if k in inv_lower:
                try: montant = float(str(inv_lower[k]).replace(",", ".").replace("€", "").strip())
                except: pass
                break
        echeance = today
        for col_key in inv.keys():
            kl = col_key.lower()
            if "echeance" in kl or "due" in kl or "expiry" in kl:
                val = str(inv[col_key])[:10]
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try: echeance = datetime.strptime(val, fmt).date()
                    except: pass
                    else: break
                break
        return {"numero": numero, "client": client, "montant": montant, "echeance": echeance}
    return None


def calculer_balance_agee(invoices):
    """Calcule la balance âgée par tranche et par client."""
    today = date.today()
    par_tranche = {t[2]: {"montant": 0, "nb": 0} for t in TRANCHES}
    par_client = {}

    for inv in invoices:
        ni = normalize_invoice(inv, args_erp)
        if not ni or ni["montant"] <= 0:
            continue
        retard = (today - ni["echeance"]).days
        for mini, maxi, libelle in TRANCHES:
            if mini <= retard <= maxi:
                par_tranche[libelle]["montant"] += ni["montant"]
                par_tranche[libelle]["nb"] += 1
                if ni["client"] not in par_client:
                    par_client[ni["client"]] = {t[2]: 0 for t in TRANCHES}
                    par_client[ni["client"]]["total"] = 0
                    par_client[ni["client"]]["nb"] = 0
                par_client[ni["client"]][libelle] += ni["montant"]
                par_client[ni["client"]]["total"] += ni["montant"]
                par_client[ni["client"]]["nb"] += 1
                break

    return par_tranche, par_client


def afficher_balance(par_tranche, par_client):
    print(f"\n{'='*70}")
    print(f"  BALANCE AGEE AU {date.today().strftime('%d/%m/%Y')}")
    print(f"{'='*70}")

    total_general = sum(t["montant"] for t in par_tranche.values())
    nb_total = sum(t["nb"] for t in par_tranche.values())

    print(f"\n  Synthese par tranche :")
    print(f"  {'Tranche':<12} {'Nb factures':>12} {'Montant EUR':>15}")
    print(f"  {'-'*40}")
    for libelle in [t[2] for t in TRANCHES]:
        t = par_tranche[libelle]
        print(f"  {libelle:<12} {t['nb']:>12} {t['montant']:>15,.2f}".replace(",", " ").replace(".", ","))
    print(f"  {'-'*40}")
    print(f"  {'TOTAL':<12} {nb_total:>12} {total_general:>15,.2f}".replace(",", " ").replace(".", ","))

    print(f"\n  Detail par client :")
    print(f"  {'Client':<30} {'0-30j':>10} {'31-60j':>10} {'61-90j':>10} {'91-180j':>10} {'180j+':>10} {'Total':>12}")
    print(f"  {'-'*95}")
    for client in sorted(par_client.keys(), key=lambda c: par_client[c]["total"], reverse=True):
        c = par_client[client]
        print(f"  {client[:28]:<30} {c['0-30j']:>10,.0f} {c['31-60j']:>10,.0f} {c['61-90j']:>10,.0f} {c['91-180j']:>10,.0f} {c['180j+']:>10,.0f} {c['total']:>12,.0f}".replace(",", " "))

    print(f"\n{'='*70}")
    print(f"  {nb_total} facture(s) impayee(s) - Total : {total_general:,.2f} EUR".replace(",", " "))
    print(f"{'='*70}\n")


args_erp = "csv"

def main():
    global args_erp
    p = argparse.ArgumentParser(description="Balance agee depuis ERP")
    p.add_argument("--erp", required=True, choices=["sellsy", "sage", "qbo", "csv"])
    p.add_argument("--token", help="Token OAuth (Sellsy/Sage/QBO)")
    p.add_argument("--realm", help="Realm ID (QuickBooks)")
    p.add_argument("--file", help="Fichier CSV (mode csv)")
    args = p.parse_args()
    args_erp = args.erp

    if args.erp == "sellsy":
        invoices = fetch_invoices_sellsy(args.token)
    elif args.erp == "sage":
        invoices = fetch_invoices_sage(args.token)
    elif args.erp == "qbo":
        invoices = fetch_invoices_qbo(args.token, args.realm)
    elif args.erp == "csv":
        if not args.file:
            print("--file requis en mode csv")
            sys.exit(1)
        invoices = fetch_invoices_csv(args.file)

    print(f"Recupere {len(invoices)} facture(s) impayee(s)")
    par_tranche, par_client = calculer_balance_agee(invoices)
    afficher_balance(par_tranche, par_client)


if __name__ == "__main__":
    main()
