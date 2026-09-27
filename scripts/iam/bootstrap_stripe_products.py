"""Script d'initialisation souverain des produits et tarifs d'abonnement Orso Agents dans Stripe Billing.

Crée les 4 formules d'abonnement récurrent mensuel (HT) :
- Starter (1 agent) : 99,00 € HT / mois
- Duo (2 agents) : 169,00 € HT / mois
- Trio (3 agents) : 229,00 € HT / mois
- Flotte Complète (4 agents) : 279,00 € HT / mois

Idempotent : ne recrée pas les produits s'ils existent déjà.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()

TIERS_CONFIG = [
    {
        "tier_id": "1_agent",
        "name": "Orso Agents - Starter (1 agent)",
        "description": "1 Agent IA autonome dédié (Jérôme, Lucas, Clara ou Victor). 30 jours d'essai gratuit.",
        "monthly_price_ht_cents": 9900,
        "agents_count": 1,
    },
    {
        "tier_id": "2_agents",
        "name": "Orso Agents - Duo (2 agents)",
        "description": "2 Agents IA autonomes synchronisés. 30 jours d'essai gratuit.",
        "monthly_price_ht_cents": 16900,
        "agents_count": 2,
    },
    {
        "tier_id": "3_agents",
        "name": "Orso Agents - Trio (3 agents)",
        "description": "3 Agents IA autonomes synchronisés. 30 jours d'essai gratuit.",
        "monthly_price_ht_cents": 22900,
        "agents_count": 3,
    },
    {
        "tier_id": "4_agents",
        "name": "Orso Agents - Flotte Complète (4 agents)",
        "description": "Équipe complète de 4 Agents IA (Jérôme, Lucas, Clara, Victor). 30 jours d'essai gratuit.",
        "monthly_price_ht_cents": 27900,
        "agents_count": 4,
    },
]


def stripe_request(endpoint: str, method: str = "GET", data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"https://api.stripe.com/v1/{endpoint}"
    headers = {
        "Authorization": f"Bearer {STRIPE_SECRET_KEY}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    encoded_data = urllib.parse.urlencode(data).encode("utf-8") if data else None

    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"Erreur HTTP Stripe ({e.code}) sur {endpoint} : {err_msg}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"Erreur réseau Stripe sur {endpoint} : {e}", file=sys.stderr)
        raise


def bootstrap_products() -> Dict[str, Dict[str, str]]:
    print("=== Synchronisation des Produits & Tarifs Orso Agents sur Stripe ===")

    # 1. Lister les produits existants
    existing_products_resp = stripe_request("products?limit=100")
    existing_products = {
        p.get("metadata", {}).get("tier_id"): p
        for p in existing_products_resp.get("data", [])
        if "tier_id" in p.get("metadata", {})
    }

    # 2. Lister les prix existants
    existing_prices_resp = stripe_request("prices?limit=100&active=true")
    existing_prices = {
        p.get("metadata", {}).get("tier_id"): p
        for p in existing_prices_resp.get("data", [])
        if "tier_id" in p.get("metadata", {})
    }

    results: Dict[str, Dict[str, str]] = {}

    for cfg in TIERS_CONFIG:
        tier_id = cfg["tier_id"]
        prod = existing_products.get(tier_id)

        if not prod:
            print(f"-> Création du produit Stripe : {cfg['name']}")
            prod_payload = {
                "name": cfg["name"],
                "description": cfg["description"],
                "metadata[tier_id]": tier_id,
                "metadata[agents_count]": str(cfg["agents_count"]),
            }
            prod = stripe_request("products", method="POST", data=prod_payload)
            print(f"   ✓ Produit créé : {prod['id']}")
        else:
            print(f"-> Produit existant : {cfg['name']} ({prod['id']})")

        price = existing_prices.get(tier_id)
        if not price:
            print(f"-> Création du prix récurrent : {cfg['monthly_price_ht_cents']/100:.2f} € HT / mois")
            price_payload = {
                "product": prod["id"],
                "unit_amount": str(cfg["monthly_price_ht_cents"]),
                "currency": "eur",
                "recurring[interval]": "month",
                "metadata[tier_id]": tier_id,
                "metadata[agents_count]": str(cfg["agents_count"]),
            }
            price = stripe_request("prices", method="POST", data=price_payload)
            print(f"   ✓ Prix créé : {price['id']}")
        else:
            print(f"-> Prix existant : {price['id']} ({price['unit_amount']/100:.2f} €/mois)")

        results[tier_id] = {
            "product_id": prod["id"],
            "price_id": price["id"],
            "name": cfg["name"],
            "price_ht": f"{cfg['monthly_price_ht_cents']/100:.2f}",
        }

    # 3. Enregistrer la cartographie des prix dans un fichier JSON pour Olympe
    output_path = os.path.join(os.path.dirname(__file__), "stripe_pricing_catalog.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Catalogue des tarifs Stripe sauvegardé avec succès dans : {output_path}")

    return results


if __name__ == "__main__":
    catalog = bootstrap_products()
    print("\nRécapitulatif des identifiants Stripe :")
    for tid, info in catalog.items():
        print(f" - {tid} : Product={info['product_id']}, Price={info['price_id']} ({info['price_ht']} € HT)")
