"""Publication du compte-rendu d'avancement, de résolution et Handoff KAN-44 sur Jira Atlassian."""

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
TICKET_KEY = "KAN-44"

if not EMAIL or not TOKEN:
    print("[!] Identifiants Atlassian manquants dans .env", file=sys.stderr)
    sys.exit(1)

auth_str = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
headers = {
    "Authorization": f"Basic {auth_str}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

COMMENT_TEXT = """h2. ⚡ Handoff & Résolution KAN-44 : Contrôle Strict du Provisioning, Activation Explicite en POC & Refus Journalisé

Bonjour Jarvis, Thibaut,

L'ensemble des observations, exigences de cadrage du POC et conditions bloquantes formulées dans le verdict du 01/10/2026 ont été traitées avec rigueur sur une branche dédiée ({{KAN-44-tunnel-abonnement-provisioning}}), dans le strict respect de la Charte de Gouvernance du Fork et de la Definition of Done.

---

h3. 1. Traitement Intégral des Défauts de Fond Relevés

1. *Traçabilité & Porte de Revue (DoD)* :
* Branche dédiée créée : {{KAN-44-tunnel-abonnement-provisioning}} (committée et poussée sur GitHub).
* Pull Request disponible : {{https://github.com/tquinzain59/orso-core/pull/new/KAN-44-tunnel-abonnement-provisioning}}.
* Zéro commit direct sur {{main}}.

2. *Découplage Webhook / Activation d'environnement en POC* :
* Conformément à la décision de cadrage du POC, la réception d'un événement Stripe ({{customer.subscription.created}}, {{customer.subscription.updated}}) avec statut {{active}} ou {{trialing}} *n'active plus aveuglément l'environnement conteneurisé*.
* L'abonnement est mis à jour en base et en mémoire, mais l'environnement reste au statut d'attente ({{environment_status: "pending_validation"}}, instance {{not_provisioned}} / {{inactive}}).
* L'activation d'un environnement redevient une action humaine explicite via le canal dédié : {{POST /api/olympe/ops/onboarding/{tenant_id}/provision}} ({{olympe/server.py}} L569).

3. *Contrôle Strict du Retour du Provisioning (Fin des faux positifs)* :
* Suppression de l'assignation aveugle {{env_result = "active"}}.
* Sur le canal explicite ({{/provision}}) comme sur le webhook (si auto-provisioning activé via {{ORSO_AUTO_PROVISION_ON_WEBHOOK=1}}), le résultat de {{manager.provision_tenant()}} est *impérativement lu et contrôlé* :
** Si {{prov_res.get("success")}} est {{False}} : refus immédiat avec code HTTP 400, journalisation explicite dans le journal d'audit ({{action: "provision:failed"}}) avec le motif précis ({{ERR_DIGEST_REQUIRED}}, {{ERR_HMAC_KEY_REQUIRED}}, etc.), et l'instance ne passe *jamais* à l'état actif.
** Si {{prov_res.get("success")}} est {{True}} : la lecture d'état s'effectue *après* le provisioning effectif avant tout réveil éventuel.

4. *Transparence Totale sur le Mode d'Exécution (Simulé vs Réel)* :
* Les retours de {{provision_tenant}} et de {{provision_onboarding_order}} intègrent désormais explicitement {{simulated: bool}} et {{execution_mode: "simulated" | "containerized"}}.
* Aucun succès simulé ne peut être confondu avec une exécution conteneurisée réelle.

---

h3. 2. Preuves Critère par Critère (Handoff)

* *Critère 1 : Un abonnement créé produit une livraison journalisée avec tenant identifié*
** *Test automatisé* : {{test_kan44_ca1_webhook_subscription_creates_logged_delivery_with_identified_tenant}}
** *Sortie brute vérifiée* :
*** Réception webhook : {{status: "processed"}}, {{tenant_slug: "nexis-logistics"}}, {{environment_status: "pending_validation"}}.
*** Journal des livraisons ({{GET /api/olympe/ops/webhooks/deliveries}}) : entrée présente avec {{status: "processed"}}, {{tenant_slug: "nexis-logistics"}}, {{customer_id: "cus_nexis_123"}}.
*** État de l'instance client : maintenue à {{status: "not_provisioned"}}, {{environment_status: "inactive"}} (aucune activation anticipée).

* *Critère 2 : L'activation d'environnement vérifie le cycle de vie, refuse avec motif si échec et distingue explicitement le chemin simulé du chemin réel*
** *Test automatisé* : {{test_kan44_ca2_explicit_provisioning_verifies_return_and_reports_execution_mode}}
** *Sorties brutes vérifiées* :
*** *Cas A (Refus explicite & journalisé)* : Sans clé HMAC ou sans digest SHA-256 épinglé -> Réponse HTTP 400 {{Provisioning refusé : ... [ERR_DIGEST_REQUIRED / ERR_HMAC_KEY_REQUIRED]}}. Entrée d'audit {{action: "provision:failed"}} consignée. Instance maintenue à {{inactive}}.
*** *Cas B1 (Chemin simulé explicite)* :
{{[PROVISIONING EXECUTION MODE] mode=simulated simulated=True tenant=acme-corp}} -> {{status: "ACTIVE"}}, {{simulated: True}}, {{execution_mode: "simulated"}}.
*** *Cas B2 (Chemin conteneurisé réel / émulé)* :
{{[PROVISIONING EXECUTION MODE] mode=containerized simulated=False tenant=acme-docker}} -> {{status: "ACTIVE"}}, {{simulated: False}}, {{execution_mode: "containerized"}}.

* *Critère 3 : Un événement dont le client est inconnu est refusé, journalisé en échec avec motif, sans effet de bord*
** *Test automatisé* : {{test_kan44_ca3_unknown_client_rejected_with_reason_and_no_side_effects}}
** *Sortie brute vérifiée* : Réponse {{status: "failed"}}, {{error: "TENANT_NOT_FOUND"}}. Entrée de livraison en échec avec motif explicite, aucun tenant créé ni impacté.

* *Critère 4 : Le rejeu du même événement ne produit aucun effet supplémentaire (Idempotence)*
** *Test automatisé* : {{test_kan44_ca4_idempotent_replay_produces_no_additional_effects}}
** *Sortie brute vérifiée* : 1er envoi {{processed}}, 2e envoi {{already_processed}} (replay_count=1), 3e envoi {{already_processed}} (replay_count=2).

* *Critère 5 : Aucun cas attrape-tout dans la correspondance client vers tenant*
** *Test automatisé* : {{test_kan44_ca5_no_catch_all_mapping}}
** *Sortie brute vérifiée* : Un événement non réconcilié n'est jamais rattaché à un tenant tiers (ex: {{clientx-orso}}).

---

h3. 3. Résultats de la Suite de Tests d'Intégration
* Commande d'exécution : {{scripts/run_tests.sh tests/olympe/}}
* Résultat brut : *68 tests passés sur 68 (100% de succès)* en 13.0s sur 9 fichiers de test.
* Validation isolée KAN-44 : {{scripts/run_tests.sh tests/olympe/test_kan43_kan44_acceptance.py}} -> *11/11 tests passés avec succès*.
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
