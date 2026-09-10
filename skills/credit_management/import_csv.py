#!/usr/bin/env python3
"""
Import et normalisation d'exports comptables CSV et Excel (Tiime, EBP, Sage, Odoo, etc.).
Détecte automatiquement les colonnes et les délimiteurs (, vs ;).

Usage CLI :
    python -m skills.credit_management.import_csv --file export.csv [--json]
"""

import sys
import os
import csv
import json
import argparse
from datetime import date
from typing import Any, Dict, List, Optional

try:
    from skills.common.parsers import detect_csv_delimiter, parse_montant, parse_date, format_euros, strip_accents
except ImportError:
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    from skills.common.parsers import detect_csv_delimiter, parse_montant, parse_date, format_euros, strip_accents


COLONNES_CLIENT = ["client", "nom", "customer", "raison sociale", "raisonsociale", "compte", "tiers", "partenaire"]
COLONNES_FACTURE = ["facture", "numero", "number", "no facture", "n facture", "invoice", "ref", "reference"]
COLONNES_MONTANT = ["montant", "amount", "solde", "balance", "total", "net", "ttc", "montant ttc", "restant du", "reste du"]
COLONNES_ECHEANCE = ["date echeance", "date_echeance", "echeance", "due date", "due_date", "expiry", "date ech", "limite paiement", "terme"]
COLONNES_STATUT = ["statut", "status", "etat", "paye", "paid", "state"]


def detecter_mapping_colonnes(header: List[str]) -> Dict[str, Optional[int]]:
    """Identifie les index des colonnes clés d'après les en-têtes."""
    mapping: Dict[str, Optional[int]] = {
        "client": None,
        "facture": None,
        "montant": None,
        "echeance": None,
        "statut": None,
    }

    for i, raw_col in enumerate(header):
        col = strip_accents(raw_col)

        if mapping["client"] is None and any(k in col for k in COLONNES_CLIENT):
            mapping["client"] = i
        if mapping["facture"] is None and any(k in col for k in COLONNES_FACTURE):
            mapping["facture"] = i
        if mapping["montant"] is None and any(k in col for k in COLONNES_MONTANT):
            mapping["montant"] = i
        if mapping["echeance"] is None and any(k in col for k in COLONNES_ECHEANCE):
            mapping["echeance"] = i
        if mapping["statut"] is None and any(k in col for k in COLONNES_STATUT):
            mapping["statut"] = i

    return mapping


def import_csv(filepath: str) -> List[Dict[str, Any]]:
    """Importe et normalise un fichier CSV en gérant le délimiteur."""
    delimiter = detect_csv_delimiter(filepath)
    invoices: List[Dict[str, Any]] = []

    with open(filepath, "r", newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f, delimiter=delimiter)
        rows = [r for r in reader if r and any(cell.strip() for cell in r)]
        if not rows:
            return []

        header = rows[0]
        mapping = detecter_mapping_colonnes(header)

        for row in rows[1:]:
            if len(row) < len(header):
                continue
            client = row[mapping["client"]].strip() if mapping["client"] is not None and mapping["client"] < len(row) else "Client inconnu"
            numero = row[mapping["facture"]].strip() if mapping["facture"] is not None and mapping["facture"] < len(row) else "?"
            montant_str = row[mapping["montant"]] if mapping["montant"] is not None and mapping["montant"] < len(row) else "0"
            echeance_str = row[mapping["echeance"]] if mapping["echeance"] is not None and mapping["echeance"] < len(row) else None
            statut = row[mapping["statut"]].strip() if mapping["statut"] is not None and mapping["statut"] < len(row) else "Non payé"

            invoices.append({
                "client": client,
                "numero": numero,
                "montant": parse_montant(montant_str),
                "echeance": parse_date(echeance_str, fallback=date.today()),
                "statut": statut,
            })

    return invoices


def import_xlsx(filepath: str) -> List[Dict[str, Any]]:
    """Importe et normalise un fichier Excel (XLSX)."""
    try:
        import openpyxl
    except ImportError:
        print("❌ openpyxl non installé. Installez-le avec: pip install openpyxl")
        return []

    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    header = [str(c) if c is not None else "" for c in rows[0]]
    mapping = detecter_mapping_colonnes(header)

    invoices: List[Dict[str, Any]] = []
    for row in rows[1:]:
        if not row or all(c is None for c in row):
            continue
        row_str = [str(c) if c is not None else "" for c in row]

        client = row_str[mapping["client"]] if mapping["client"] is not None and mapping["client"] < len(row_str) else "Client inconnu"
        numero = row_str[mapping["facture"]] if mapping["facture"] is not None and mapping["facture"] < len(row_str) else "?"
        montant_val = row[mapping["montant"]] if mapping["montant"] is not None and mapping["montant"] < len(row) else 0.0
        echeance_val = row[mapping["echeance"]] if mapping["echeance"] is not None and mapping["echeance"] < len(row) else None
        statut = row_str[mapping["statut"]] if mapping["statut"] is not None and mapping["statut"] < len(row_str) else "Non payé"

        invoices.append({
            "client": client.strip() or "Client inconnu",
            "numero": numero.strip() or "?",
            "montant": parse_montant(montant_val),
            "echeance": parse_date(echeance_val, fallback=date.today()),
            "statut": statut.strip() or "Non payé",
        })

    return invoices


def import_invoices_file(filepath: str) -> List[Dict[str, Any]]:
    """Point d'entrée universel pour charger et normaliser un fichier CSV ou Excel."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Fichier comptable introuvable : {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xltx"):
        return import_xlsx(filepath)
    return import_csv(filepath)


def main():
    parser = argparse.ArgumentParser(description="Import et normalisation d'exports comptables")
    parser.add_argument("--file", required=True, help="Chemin du fichier CSV ou Excel")
    parser.add_argument("--json", action="store_true", help="Afficher le résultat au format JSON")
    args = parser.parse_args()

    invoices = import_invoices_file(args.file)

    if args.json:
        # Sérialisation avec date ISO
        serializable = [
            {**inv, "echeance": inv["echeance"].isoformat() if isinstance(inv["echeance"], date) else str(inv["echeance"])}
            for inv in invoices
        ]
        print(json.dumps(serializable, indent=2, ensure_ascii=False))
    else:
        print(f"\n{'='*75}")
        print(f"  {len(invoices)} facture(s) importée(s) depuis {os.path.basename(args.file)}")
        print(f"{'='*75}")
        total = sum(inv["montant"] for inv in invoices)
        for inv in invoices[:20]:
            print(
                f"  {inv['numero']:<15} {inv['client'][:24]:<26} "
                f"{str(inv['echeance']):<12} {format_euros(inv['montant']):>14}  [{inv['statut']}]"
            )
        if len(invoices) > 20:
            print(f"  ... et {len(invoices) - 20} autre(s) facture(s)")
        print(f"{'-'*75}")
        print(f"  TOTAL FACTURÉ : {format_euros(total)}")
        print(f"{'='*75}\n")


if __name__ == "__main__":
    main()
