#!/usr/bin/env python3
"""
Calcul de Balance Âgée depuis les factures impayées d'un ERP ou d'un fichier comptable.
Supporte : Sellsy, Sage, QuickBooks, Odoo, Dynamics 365 BC, et import CSV/Excel.

Usage CLI :
    python -m skills.credit_management.balance_agee --erp sellsy --token $SELLSY_TOKEN
    python -m skills.credit_management.balance_agee --erp csv --file export.csv [--json]
"""

import sys
import json
import argparse
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

try:
    from skills.common.parsers import parse_montant, parse_date, format_euros
    from skills.common.client import HermesHttpClient
except ImportError:
    # Support si exécuté directement dans le sous-dossier
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    from skills.common.parsers import parse_montant, parse_date, format_euros
    from skills.common.client import HermesHttpClient


# Tranches standard conformes au credit management et aux spécifications
TRANCHES_STANDARD = [
    (0, 15, "0-15j"),
    (16, 30, "16-30j"),
    (31, 60, "31-60j"),
    (61, 90, "61-90j"),
    (91, 99999, "90j+"),
]


def fetch_invoices_sellsy(token: str, limit: int = 500) -> List[Dict[str, Any]]:
    client = HermesHttpClient()
    url = "https://api.sellsy.com/v2/invoices"
    data = client.get(url, params={"status": "unpaid", "limit": limit}, headers={"Authorization": f"Bearer {token}"})
    if not data:
        return []
    return data.get("data", data.get("invoices", []))


def fetch_invoices_sage(token: str, limit: int = 500) -> List[Dict[str, Any]]:
    client = HermesHttpClient()
    url = "https://api.accounting.sage.com/v3.1/sales_invoices"
    data = client.get(url, params={"status": "UNPAID", "items_per_page": limit}, headers={"Authorization": f"Bearer {token}"})
    if not data:
        return []
    return data.get("$items", data.get("items", []))


def fetch_invoices_qbo(token: str, realm: str) -> List[Dict[str, Any]]:
    client = HermesHttpClient()
    query = "SELECT * FROM Invoice WHERE Balance > '0'"
    url = f"https://quickbooks.api.intuit.com/v3/company/{realm}/query"
    data = client.get(url, params={"query": query}, headers={"Authorization": f"Bearer {token}"})
    if not data:
        return []
    return data.get("QueryResponse", {}).get("Invoice", [])


def fetch_invoices_odoo(url: str, db: str, user: str, password: str) -> List[Dict[str, Any]]:
    """Récupère les factures impayées depuis Odoo via JSON-RPC."""
    client = HermesHttpClient()
    auth_url = f"{url.rstrip('/')}/web/session/authenticate"
    auth_payload = {
        "jsonrpc": "2.0",
        "params": {"db": db, "login": user, "password": password}
    }
    auth_res = client.post(auth_url, json_data=auth_payload)
    if not auth_res or "result" not in auth_res:
        print("❌ Erreur authentification Odoo")
        return []

    dataset_url = f"{url.rstrip('/')}/web/dataset/call_kw"
    req_payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "account.move",
            "method": "search_read",
            "args": [[["move_type", "=", "out_invoice"], ["payment_state", "!=", "paid"]]],
            "kwargs": {
                "fields": ["name", "partner_id", "amount_total", "amount_residual", "invoice_date_due"],
                "limit": 500,
            }
        }
    }
    res = client.post(dataset_url, json_data=req_payload)
    if not res or "result" not in res:
        return []
    return res.get("result", [])


def fetch_invoices_d365(token: str, tenant_id: str) -> List[Dict[str, Any]]:
    """Récupère les factures impayées depuis Microsoft Dynamics 365 Business Central."""
    client = HermesHttpClient()
    url = f"https://api.businesscentral.dynamics.com/v2.0/{tenant_id}/production/api/v2.0/salesInvoices"
    data = client.get(url, params={"$filter": "status eq 'Open'"}, headers={"Authorization": f"Bearer {token}"})
    if not data:
        return []
    return data.get("value", [])


def fetch_invoices_csv_file(filepath: str) -> List[Dict[str, Any]]:
    from .import_csv import import_invoices_file
    return import_invoices_file(filepath)


def normalize_invoice(inv: Dict[str, Any], erp: str) -> Optional[Dict[str, Any]]:
    """Normalise une facture brute dans une structure commune standard."""
    today = date.today()
    erp_lower = erp.lower()

    if erp_lower == "sellsy":
        due_str = inv.get("due_date") or inv.get("expiry_date", "")
        due = parse_date(due_str, fallback=today)
        return {
            "numero": str(inv.get("number", inv.get("id", "?"))),
            "client": str(inv.get("contact_name") or inv.get("contact", {}).get("name", "Client inconnu")),
            "montant": parse_montant(inv.get("amount_due", inv.get("total", 0))),
            "echeance": due,
        }
    elif erp_lower == "sage":
        due_str = inv.get("due_date", "")
        due = parse_date(due_str, fallback=today)
        return {
            "numero": str(inv.get("id", "?")),
            "client": str(inv.get("contact_name", "Client inconnu")),
            "montant": parse_montant(inv.get("outstanding_amount", inv.get("total_amount", 0))),
            "echeance": due,
        }
    elif erp_lower == "qbo":
        due_str = inv.get("DueDate", "")
        due = parse_date(due_str, fallback=today)
        return {
            "numero": str(inv.get("DocNumber", inv.get("Id", "?"))),
            "client": str(inv.get("CustomerRef", {}).get("name", "Client inconnu")),
            "montant": parse_montant(inv.get("Balance", 0)),
            "echeance": due,
        }
    elif erp_lower == "odoo":
        due_str = inv.get("invoice_date_due", "")
        due = parse_date(due_str, fallback=today)
        partner = inv.get("partner_id")
        client_name = partner[1] if isinstance(partner, (list, tuple)) and len(partner) > 1 else "Client inconnu"
        return {
            "numero": str(inv.get("name", "?")),
            "client": str(client_name),
            "montant": parse_montant(inv.get("amount_residual", inv.get("amount_total", 0))),
            "echeance": due,
        }
    elif erp_lower == "d365":
        due_str = inv.get("dueDate", "")
        due = parse_date(due_str, fallback=today)
        return {
            "numero": str(inv.get("number", inv.get("id", "?"))),
            "client": str(inv.get("customerName", "Client inconnu")),
            "montant": parse_montant(inv.get("remainingAmount", inv.get("totalAmountIncludingTax", 0))),
            "echeance": due,
        }
    elif erp_lower in ("csv", "excel", "normalized"):
        # Si déjà normalisé par import_csv
        due = parse_date(inv.get("echeance"), fallback=today)
        return {
            "numero": str(inv.get("numero", inv.get("facture", "?"))),
            "client": str(inv.get("client", inv.get("nom", "Client inconnu"))),
            "montant": parse_montant(inv.get("montant", 0.0)),
            "echeance": due,
        }
    return None


def fetch_invoices(
    erp: str,
    token: Optional[str] = None,
    realm: Optional[str] = None,
    filepath: Optional[str] = None,
    odoo_url: Optional[str] = None,
    odoo_db: Optional[str] = None,
    odoo_user: Optional[str] = None,
    odoo_pass: Optional[str] = None,
    d365_tenant: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Point d'entrée pour récupérer les factures brutes d'une source."""
    erp_lower = erp.lower()
    if erp_lower == "sellsy":
        return fetch_invoices_sellsy(token or os.environ.get("SELLSY_TOKEN", ""))
    elif erp_lower == "sage":
        return fetch_invoices_sage(token or os.environ.get("SAGE_TOKEN", ""))
    elif erp_lower == "qbo":
        return fetch_invoices_qbo(token or os.environ.get("QBO_TOKEN", ""), realm or os.environ.get("QBO_REALM_ID", ""))
    elif erp_lower == "odoo":
        url = odoo_url or os.environ.get("ODOO_URL", "")
        db = odoo_db or os.environ.get("ODOO_DB", "")
        user = odoo_user or os.environ.get("ODOO_USER", "")
        pwd = odoo_pass or os.environ.get("ODOO_PASSWORD", "")
        return fetch_invoices_odoo(url, db, user, pwd)
    elif erp_lower == "d365":
        return fetch_invoices_d365(token or os.environ.get("BC_TOKEN", ""), d365_tenant or os.environ.get("BC_TENANT_ID", ""))
    elif erp_lower in ("csv", "excel"):
        if not filepath:
            raise ValueError("Fichier requis pour l'import CSV/Excel")
        return fetch_invoices_csv_file(filepath)
    else:
        raise ValueError(f"ERP '{erp}' non pris en charge.")


def calculer_balance_agee(
    invoices: List[Dict[str, Any]],
    erp: str = "csv",
    tranches: Optional[List[Tuple[int, int, str]]] = None,
    date_reference: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Calcule la balance âgée et renvoie un dictionnaire structuré.
    """
    ref_date = date_reference or date.today()
    buckets = tranches or TRANCHES_STANDARD

    par_tranche = {t[2]: {"montant": 0.0, "nb": 0} for t in buckets}
    par_client: Dict[str, Dict[str, Any]] = {}
    factures_en_retard: List[Dict[str, Any]] = []

    total_general = 0.0
    nb_total = 0

    for raw_inv in invoices:
        norm = normalize_invoice(raw_inv, erp)
        if not norm or norm["montant"] <= 0:
            continue

        retard_jours = (ref_date - norm["echeance"]).days
        norm["retard_jours"] = retard_jours
        total_general += norm["montant"]
        nb_total += 1

        client = norm["client"]
        if client not in par_client:
            par_client[client] = {
                "client": client,
                "tranches": {t[2]: 0.0 for t in buckets},
                "total": 0.0,
                "nb_factures": 0,
            }

        par_client[client]["total"] += norm["montant"]
        par_client[client]["nb_factures"] += 1

        # Affectation à la tranche de retard
        for mini, maxi, libelle in buckets:
            if mini <= retard_jours <= maxi:
                par_tranche[libelle]["montant"] += norm["montant"]
                par_tranche[libelle]["nb"] += 1
                par_client[client]["tranches"][libelle] += norm["montant"]
                break

        if retard_jours > 0:
            factures_en_retard.append({
                "numero": norm["numero"],
                "client": norm["client"],
                "montant": norm["montant"],
                "echeance": norm["echeance"].isoformat(),
                "retard_jours": retard_jours,
            })

    # Tri des clients par encours décroissant
    sorted_clients = sorted(par_client.values(), key=lambda c: c["total"], reverse=True)

    return {
        "date_calcul": ref_date.isoformat(),
        "nb_factures_total": nb_total,
        "montant_total": round(total_general, 2),
        "par_tranche": par_tranche,
        "clients": sorted_clients,
        "factures_en_retard": sorted(factures_en_retard, key=lambda f: f["retard_jours"], reverse=True),
    }


def afficher_balance_ascii(resultats: Dict[str, Any]) -> None:
    """Affiche la balance âgée au format tableau ASCII pour le terminal."""
    print(f"\n{'='*75}")
    print(f"  BALANCE ÂGÉE AU {resultats['date_calcul']}")
    print(f"{'='*75}")

    print("\n  Synthèse par tranche d'ancienneté :")
    print(f"  {'Tranche':<14} {'Nb Factures':>14} {'Montant Total':>18}")
    print(f"  {'-'*48}")
    for tranche, data in resultats["par_tranche"].items():
        print(f"  {tranche:<14} {data['nb']:>14} {format_euros(data['montant']):>18}")
    print(f"  {'-'*48}")
    print(f"  {'TOTAL':<14} {resultats['nb_factures_total']:>14} {format_euros(resultats['montant_total']):>18}")

    print("\n  Détail par client (Top encours) :")
    print(f"  {'Client':<28} {'Total':>14} {'0-15j':>10} {'16-30j':>10} {'31-60j':>10} {'61j+':>10}")
    print(f"  {'-'*85}")
    for c in resultats["clients"][:15]:
        tr = c["tranches"]
        t_61plus = tr.get("61-90j", 0.0) + tr.get("90j+", 0.0)
        print(
            f"  {c['client'][:26]:<28} {format_euros(c['total']):>14} "
            f"{tr.get('0-15j', 0):>10.0f} {tr.get('16-30j', 0):>10.0f} "
            f"{tr.get('31-60j', 0):>10.0f} {t_61plus:>10.0f}"
        )

    print(f"\n{'='*75}")
    print(f"  {resultats['nb_factures_total']} facture(s) impayée(s) — Total : {format_euros(resultats['montant_total'])}")
    print(f"{'='*75}\n")


def main():
    parser = argparse.ArgumentParser(description="Calcul de Balance Âgée Hermès (Multi-ERP & CSV)")
    parser.add_argument("--erp", choices=["sellsy", "sage", "qbo", "odoo", "d365", "csv"], default="csv", help="Source de facturation")
    parser.add_argument("--token", help="Jeton OAuth ou clé API")
    parser.add_argument("--realm", help="Realm ID (QuickBooks)")
    parser.add_argument("--file", help="Chemin du fichier CSV/Excel")
    parser.add_argument("--json", action="store_true", help="Afficher le résultat au format JSON")
    args = parser.parse_args()

    invoices = fetch_invoices(args.erp, token=args.token, realm=args.realm, filepath=args.file)
    resultats = calculer_balance_agee(invoices, erp=args.erp)

    if args.json:
        print(json.dumps(resultats, indent=2, ensure_ascii=False))
    else:
        afficher_balance_ascii(resultats)


if __name__ == "__main__":
    main()
