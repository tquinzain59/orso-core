"""Publication du commentaire d'avancement KAN-64 sur Jira Atlassian."""

import os
import base64
import json
import urllib.request
import urllib.error

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
TICKET_KEY = "KAN-64"

if not EMAIL or not TOKEN:
    raise ValueError("Identifiants Atlassian manquants dans .env")

auth_str = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
headers = {
    "Authorization": f"Basic {auth_str}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

COMMENT_MARKDOWN = """h2. ⚡ Avancement KAN-64 : Prise en compte de l'arbitrage Thibaut & Protocole d'Exécution sur PROD-FR-003

Bonjour Jarvis, Thibaut,

Suite à l'arbitrage sans ambiguïté de Thibaut (Commentaire 13), le plan de gestion a été mis à jour et validé à 100% par les tests automatisés.

---

h3. 1. Implémentation de l'Arbitrage Thibaut (Demandes 1, 2, 3)

* *Clé de flotte partagée* : Une seule clé de flotte partagée, alignée sur celle ayant scellé le manifeste {{personas.lock.json}} dans l'image.
* *Plan de gestion ({{olympe/lifecycle_manager.py}})* :
** Lit strictement {{ORSO_PERSONA_HMAC_KEY}} dans son propre environnement (ou paramètre) et l'injecte dans {{base_envs}} du conteneur client.
** *Refus explicite sans zombi* : Si la variable est absente lors de la demande de création, le provisioning est refusé immédiatement avec le code d'erreur {{ERR_HMAC_KEY_REQUIRED}} (aucun conteneur n'est créé).
** *Nommage strict* : Variable nommée exactement {{ORSO_PERSONA_HMAC_KEY}}.
* *Outil de distribution ({{scripts/distribution/engine_image_manager.py}})* :
** Support de l'injection automatique de {{ORSO_PERSONA_HMAC_KEY}} lors des mises à jour et rollbacks.
** Ajout du mode local direct (--local) pour sonder le démon Docker local sans passer par SSH.

---

h3. 2. Preuves Formelles Apportées (Demande 4 / 0 Secret)

Suite de tests complétée dans {{tests/distribution/test_kan64_execution_reelle_distribution.py}} (test {{test_persona_hmac_key_fleet_enforcement_and_container_launch}}) :
# *Preuve 1 (Contrôle avec clé)* : Vérification d'intégrité personas avec clé HMAC valide -> Code retour 0 ({{PER-INTEGRITY-000}}).
# *Preuve 2 (Contrôle sans clé)* : Vérification d'intégrité sans clé HMAC -> Échec immédiat Fail-Closed ({{PER-INTEGRITY-003}}).
# *Preuve 3 (Provisioning sans clé)* : Tentative de provisioning Olympe sans clé -> Refus immédiat {{ERR_HMAC_KEY_REQUIRED}}, 0 conteneur créé.
# *Preuve 4 (Provisioning avec clé)* : Provisioning Olympe avec clé -> Succès conteneur, transmission stricte dans {{base_envs}}.
# *Zero Secret* : Aucune valeur de secret n'a été affichée ni consignée (compteur secrets = 0, audit CA5 PASSED).

*Résultat des tests automatisés* :
{noformat}
Discovered 11 test files (~76 tests) under ['tests/olympe', 'tests/distribution']
=== Summary: 11 files, 76 tests passed, 0 failed (100% complete) in 13.0s ===
{noformat}

Commit : {{d0c099e21d}} poussé sur la branche {{KAN-64-execution-reelle-distribution}} et PR #3 synchronisée.

---

h3. 3. Protocole pour Jarvis : Commandes à jouer sur PROD-FR-003 (CA3 & CA4)

Puisque l'image officielle {{ghcr.io/tquinzain59/orso-engine@sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f}} est déjà en cache local sur {{prod-fr-003}}, voici la séquence de commandes à exécuter en root :

*Étape 1 : Nettoyage éventuel du conteneur précédent*
{code:bash}
docker rm -f orso_client_demo 2>/dev/null || true
{code}

*Étape 2 : Lancement avec la clé HMAC de flotte partagée*
*(S'assurer que {{ORSO_PERSONA_HMAC_KEY}} est exportée dans la session ou passée directement)* :
{code:bash}
docker run -d --name orso_client_demo \
  -p 9119:9119 \
  --label com.orso.managed=true \
  --label com.orso.engine.digest=sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f \
  --label com.orso.engine.pinned=true \
  -e ORSO_PERSONA_HMAC_KEY="$ORSO_PERSONA_HMAC_KEY" \
  ghcr.io/tquinzain59/orso-engine@sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f
{code}

*Étape 3 : Vérification de l'état d'exécution (Le conteneur doit rester Up)* :
{code:bash}
docker ps --filter "name=orso_client_demo"
{code}
*Attendu* : {{Up X seconds (healthy)}} ou {{Up X seconds}}.

*Étape 4 : Validation de la sonde de santé HTTP (CA4)* :
{code:bash}
curl -i http://localhost:9119/api/client/status
{code}
*Attendu* : Code HTTP {{200 OK}} avec payload JSON attestant de la disponibilité du moteur.

*Étape 5 : Validation de la sonde d'empreinte sans inventaire manuel (CA3)* :
{code:bash}
docker inspect --format '{{.Config.Image}} | {{index .Config.Labels "com.orso.engine.digest"}}' orso_client_demo
{code}
*Attendu* :
{{ghcr.io/tquinzain59/orso-engine@sha256:4506ccd6... | sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f}}

*Étape 6 : Test de retour arrière / rollback (CA4)* :
{code:bash}
docker stop -t 5 orso_client_demo
docker rm orso_client_demo
# Relance avec validation immédiate du statut Up et de la sonde curl
docker run -d --name orso_client_demo \
  -p 9119:9119 \
  --label com.orso.managed=true \
  --label com.orso.engine.digest=sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f \
  --label com.orso.engine.pinned=true \
  -e ORSO_PERSONA_HMAC_KEY="$ORSO_PERSONA_HMAC_KEY" \
  ghcr.io/tquinzain59/orso-engine@sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:9119/api/client/status
{code}
*Attendu* : Code {{200}}.
"""


def main():
    print(f"\nPublication du commentaire sur {TICKET_KEY}...")
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
                            "text": COMMENT_MARKDOWN,
                        }
                    ],
                }
            ],
        }
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[✓] Commentaire publié avec succès sur {TICKET_KEY} (HTTP {resp.status}).")
    except urllib.error.HTTPError as e:
        print(f"[!] Erreur HTTP {e.code} : {e.read().decode()}")
    except Exception as e:
        print(f"[!] Erreur : {e}")


if __name__ == "__main__":
    main()
