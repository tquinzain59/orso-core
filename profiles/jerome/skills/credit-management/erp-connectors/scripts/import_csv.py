#!/usr/bin/env python3
"""
Import et normalisation d'exports CSV/Excel pour les ERP sans API.
Detecte automatiquement les colonnes (client, facture, montant, echeance).

Usage:
    python import_csv.py --file export_factures.csv
    python import_csv.py --file export.xlsx --format xlsx
"""

import sys, csv, argparse, os
from datetime import datetime, date

COLONNES_CLIENT = ["client", "nom", "customer", "raison sociale", "raisonsociale", "compte", "tiers"]
COLONNES_FACTURE = ["facture", "numero", "number", "no facture", "n facture", "invoice", "ref"]
COLONNES_MONTANT = ["montant", "amount", "solde", "balance", "total", "net", "ttc", "montant ttc"]
COLONNES_ECHEANCE = ["date echeance", "date_echeance", "echeance", "due date", "due_date", "expiry", "date ech", "limite paiement"]
COLONNES_DATE_FACTURE = ["date facture", "date", "date emission", "invoice date"]
COLONNES_STATUT = ["statut", "status", "etat", "paye", "paid"]


def detecter_colonnes(header):
    mapping = {"client": None, "facture": None, "montant": None, "echeance": None, "statut": None}
    for i, col in enumerate(header):
        col_lower = col.lower().strip()
        if mapping["client"] is None:
            for k in COLONNES_CLIENT:
                if k in col_lower:
                    mapping["client"] = i; break
        if mapping["facture"] is None:
            for k in COLONNES_FACTURE:
                if k in col_lower:
                    mapping["facture"] = i; break
        if mapping["montant"] is None:
            for k in COLONNES_MONTANT:
                if k in col_lower:
                    mapping["montant"] = i; break
        if mapping["echeance"] is None:
            for k in COLONNES_ECHEANCE:
                if k in col_lower:
                    mapping["echeance"] = i; break
        if mapping["statut"] is None:
            for k in COLONNES_STATUT:
                if k in col_lower:
                    mapping["statut"] = i; break
    return mapping


def parse_montant(val):
    if not val: return 0.0
    val = str(val).strip().replace("EUR", "").replace("€", "")
    val = val.replace("\u00a0", "").replace(" ", "")
    if "," in val and "." in val:
        val = val.replace(".", "").replace(",", ".")
    elif "," in val:
        val = val.replace(",", ".")
    try: return float(val)
    except: return 0.0


def parse_date(val):
    if not val: return date.today()
    val = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try: return datetime.strptime(val[:10], fmt).date()
        except: pass
    return date.today()


def import_csv(filepath):
    invoices = []
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        rows = list(reader)
        if not rows: return invoices
        header = rows[0]
        mapping = detecter_colonnes(header)
        print(f"Colonnes detectees : {mapping}")
        for row in rows[1:]:
            if not row or len(row) < len(header): continue
            inv = {}
            if mapping["client"] is not None: inv["client"] = row[mapping["client"]]
            else: inv["client"] = "?"
            if mapping["facture"] is not None: inv["numero"] = row[mapping["facture"]]
            else: inv["numero"] = "?"
            if mapping["montant"] is not None: inv["montant"] = parse_montant(row[mapping["montant"]])
            else: inv["montant"] = 0.0
            if mapping["echeance"] is not None: inv["echeance"] = parse_date(row[mapping["echeance"]])
            else: inv["echeance"] = date.today()
            if mapping["statut"] is not None: inv["statut"] = row[mapping["statut"]]
            else: inv["statut"] = "?"
            invoices.append(inv)
    return invoices


def import_xlsx(filepath):
    try:
        import openpyxl
    except ImportError:
        print("openpyxl requis pour xlsx. pip install openpyxl")
        sys.exit(1)
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows: return []
    header = [str(c) if c else "" for c in rows[0]]
    mapping = detecter_colonnes(header)
    print(f"Colonnes detectees : {mapping}")
    invoices = []
    for row in rows[1:]:
        if not row or all(c is None for c in row): continue
        row = [str(c) if c is not None else "" for c in row]
        inv = {}
        inv["client"] = row[mapping["client"]] if mapping["client"] is not None and mapping["client"] < len(row) else "?"
        inv["numero"] = row[mapping["facture"]] if mapping["facture"] is not None and mapping["facture"] < len(row) else "?"
        inv["montant"] = parse_montant(row[mapping["montant"]]) if mapping["montant"] is not None and mapping["montant"] < len(row) else 0.0
        inv["echeance"] = parse_date(row[mapping["echeance"]]) if mapping["echeance"] is not None and mapping["echeance"] < len(row) else date.today()
        inv["statut"] = row[mapping["statut"]] if mapping["statut"] is not None and mapping["statut"] < len(row) else "?"
        invoices.append(inv)
    return invoices


def afficher_invoices(invoices):
    print(f"\n{'='*80}")
    print(f"  {len(invoices)} facture(s) importee(s)")
    print(f"{'='*80}")
    total = 0
    for inv in invoices:
        mt = inv.get("montant", 0)
        total += mt
        print(f"  {inv.get('numero','?'):<15} {inv.get('client','?')[:25]:<26} {inv.get('echeance','?'):<12} {mt:>10,.2f} EUR  [{inv.get('statut','?')}]".replace(",", " "))
    print(f"  {'-'*80}")
    print(f"  TOTAL : {total:,.2f} EUR".replace(",", " "))
    print(f"{'='*80}\n")


def main():
    p = argparse.ArgumentParser(description="Import CSV/Excel pour ERP sans API")
    p.add_argument("--file", required=True, help="Fichier a importer")
    p.add_argument("--format", choices=["csv", "xlsx", "auto"], default="auto")
    args = p.parse_args()

    if args.format == "auto":
        ext = os.path.splitext(args.file)[1].lower()
        fmt = "xlsx" if ext in (".xlsx", ".xls") else "csv"
    else:
        fmt = args.format

    if fmt == "csv":
        invoices = import_csv(args.file)
    else:
        invoices = import_xlsx(args.file)

    afficher_invoices(invoices)


if __name__ == "__main__":
    main()
