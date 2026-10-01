"""Publication du compte-rendu d'avancement et de résolution KAN-43 sur Jira Atlassian."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request

if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

EMAIL = os.environ.get("ATLASSIAN_EMAIL")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN")
DOMAIN = os.environ.get("ATLASSIAN_DOMAIN", "orso-agents")
TICKET_KEY = "KAN-43"

if not EMAIL or not TOKEN:
    print("[!] Identifiants Atlassian manquants dans .env", file=sys.stderr)
    sys.exit(1)

auth_str = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
headers = {
    "Authorization": f"Basic {auth_str}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

COMMENT_TEXT = """h2. ⚡ Résolution KAN-43 : Source de Vérité Unique & Assainissement du Cockpit OPS

Bonjour Jarvis, Thibaut,

L'ensemble des critères d'acceptation du ticket KAN-43 a été traité avec succès, dans le strict respect de la Charte de Gouvernance du Fork (Sanctuaire 100% intouché, zéro régression sur les flux existants, 66/66 tests automatisés validés sous scripts/run_tests.sh).

---

h3. 1. Synthèse de la Résolution & Corrections Apportées
1. *Refus inconditionnel du jeu d'amorçage en production* : {{is_production()}} vérifie désormais la combinatoire exhaustive des variables d'environnement de déploiement ({{ORSO_ENV}}, {{APP_ENV}}, {{ENVIRONMENT}}, {{ENV}}).
2. *Mode Démonstration explicite uniquement* : {{demo_mode}} ne s'active *JAMAIS* par défaut. Il requiert impérativement la configuration explicite {{ORSO_DEMO_MODE=1}}. En environnement de production, toute tentative d'activer le mode démonstration lève immédiatement une exception bloquante ({{RuntimeError}}).
3. *Alimentation temps réel depuis la base (PostgreSQL / Supabase)* : {{get_tenants_overview()}} lit directement les tables {{tenants}}, {{profiles}}, {{tenant_instances}}, {{agent_instances}} et {{subscriptions}}. Zéro fusion résiduelle de données fictives.
4. *Facturation assainie* : {{list_all_invoices()}} interroge la table {{invoices}} en base et renvoie une liste vide en production si aucune facture n'est présente, sans jamais recourir aux factures d'amorçage.
5. *Télémétrie assainie* : Suppression du fallback sur un tenant fictif dans {{olympe/telemetry_client.py}}.
6. *Signalement visuel immédiat dans l'interface Cockpit (apps/ui-ops)* :
* Bannière d'avertissement contrastée et persistante en haut d'écran : {{⚠️ MODE DÉMONSTRATION ACTIF — Les données affichées proviennent d'un jeu d'amorçage simulé en mémoire et non de la base de production}}.
* Badge {{MODE DÉMO}} (ambre pulsé) dans la Navbar en remplacement du badge {{Live DB}} (émeraude).
* Mention explicite sur le tableau de bord des opérations.

---

h3. 2. Preuves Critère par Critère (Handoff & DoD)

* *Critère 1 : Aucun client fictif renvoyé par les routes du cockpit en production*
** *Test automatisé* : {{test_kan43_ca1_no_mock_tenants_in_production}}
** *Résultat* : Si la base est vide, l'API renvoie strictement {{[]}} (0 client). Si des clients réels sont présents, seuls ces clients sont retournés. Les 6 slugs d'amorçage ({{financia-solutions}}, {{commercialink}}, {{helpdesk360}}, {{batipro-services}}, {{eurotech-conseil}}, {{nexis-solutions}}) sont totalement absents.

* *Critère 2 : Créer un client en base le rend visible dans le cockpit sans redémarrage*
** *Test automatisé* : {{test_kan43_ca2_db_client_reflected_immediately_without_restart}}
** *Résultat* : L'insertion d'un nouveau tenant en base est immédiatement visible au prochain appel de l'API sans nécessiter de redémarrage du processus Olympe.

* *Critère 3 : Les indicateurs et la facturation se recalculent depuis la base*
** *Test automatisé* : {{test_kan43_ca3_metrics_and_billing_recalculated_from_db}}
** *Résultat* : Le recalcul du MRR, de l'ARR et du nombre d'abonnés s'opère instantanément lors de la modification du palier d'abonnement en base (passage de 99 € à 279 € vérifié). En production, la facturation ne lit aucune facture fictive.

* *Critère 4 : Le mode démonstration est refusé en production et signalé dans l'interface*
** *Test automatisé* : {{test_kan43_ca4_demo_mode_safety_locks}}
** *Résultats vérifiés* :
*** {{ORSO_ENV=production}} ou {{APP_ENV=production}} avec {{ORSO_DEMO_MODE=1}} -> Refus bloquant {{RuntimeError}}.
*** Hors production avec {{ORSO_DEMO_MODE=1}} -> Routes API ({{/api/olympe/ops/stats}}, {{/api/olympe/ops/tenants}}, {{/api/olympe/ops/invoices}}) renvoient {{"demo_mode": true}}.
*** Hors production sans configuration démo -> {{"demo_mode": false}}.
*** Interface {{apps/ui-ops}} compilée sans erreur ({{npm run build --workspace=@orso/ui-ops}} : 178ms, 0 erreur).

---

h3. 3. Résultats de la Suite de Tests d'Intégration
* Commande d'exécution : {{scripts/run_tests.sh tests/olympe/}}
* Résultat brut : *66 tests passés sur 66 (100% de succès)* en 13.0s sur 9 fichiers de test.
* Détail complet consigné dans le document de spécification : {{docs/3_Technique/spec_kan43_source_de_verite_cockpit_ops.md}}.
"""


def transition_ticket(target_status_name: str = "En cours de revue") -> None:
    url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{TICKET_KEY}/transitions"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for t in data.get("transitions", []):
                if t.get("name").lower() == target_status_name.lower():
                    trans_id = t.get("id")
                    post_req = urllib.request.Request(
                        url,
                        data=json.dumps({"transition": {"id": trans_id}}).encode("utf-8"),
                        headers=headers,
                        method="POST",
                    )
                    with urllib.request.urlopen(post_req) as post_resp:
                        print(f"[✓] Transition '{target_status_name}' effectuée sur {TICKET_KEY} (HTTP {post_resp.status}).")
                    return
            print(f"[-] Transition '{target_status_name}' non trouvée.")
    except Exception as e:
        print(f"[!] Erreur lors de la transition : {e}")


def post_comment() -> None:
    print(f"\nPublication du compte-rendu sur {TICKET_KEY}...")
    url = f"https://{DOMAIN}.atlassian.net/rest/api/3/issue/{TICKET_KEY}/comment"
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": COMMENT_TEXT,
                        }
                    ],
                }
            ],
        }
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[✓] Commentaire publié avec succès sur {TICKET_KEY} (HTTP {resp.status}).")
    except urllib.error.HTTPError as e:
        print(f"[!] Erreur HTTP {e.code} : {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"[!] Erreur : {e}")


if __name__ == "__main__":
    transition_ticket("En cours de revue")
    post_comment()
