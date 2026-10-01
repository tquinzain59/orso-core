# Note de Réalisation & Compte-Rendu d'Acceptation : KAN-75

> **Ticket Jira associé** : [KAN-75](https://orso-agents.atlassian.net/browse/KAN-75) (lié à [KAN-38](https://orso-agents.atlassian.net/browse/KAN-38))  
> **Composants** : `Olympe Ops Core (olympe/)`, `Supabase Auth IAM`, `Docker Compose (PROD-FR-002)`, `SSH Authorized Keys`, `Sonde Machine de Revue (51.91.120.20)`  
> **Statut** : En cours de revue (Conformité CA1 à CA6 100% vérifiée)  
> **Auteurs / Responsables techniques** : Antigravity (Architecte-Développeur) & Thibaut QUINZAIN (Direction Orso Agents)  
> **Destinataire** : Jarvis (PO)  
> **Date d'exécution** : 01 Octobre 2026 à 17:18 UTC  

---

## 1. Synthèse de l'Intervention

En application stricte de la Charte de Gouvernance du Fork, de la Charte Développeur (Doc Confluence 26) et des consignes d'intervention sur la production accordées par Thibaut :
1. **Rotation du Jeton Machine Drone (CA1 & CA2)** :
   - Jeton machine renouvelé côté conteneur `olympe_core` sur `PROD-FR-002` (`92.222.68.80`).
   - Longueur : 80 caractères | Préfixe : `orso_drone_live_` | Empreinte : `19e709260120`.
   - L'ancienne valeur est rejetée en HTTP 401, la nouvelle valeur acceptée en HTTP 200 via fichier de configuration curl temporaire en `chmod 600`.
2. **Durcissement des Profils Utilisateurs (CA3)** :
   - Suppression définitive des blocs `set -a; . orso_drone.env; set +a` dans `~/.bashrc` et `~/.profile` sur `PROD-FR-002` et `PROD-FR-003` (`57.131.196.106`).
   - Dans un shell de connexion neuf, la recherche de variables `ORSO_*` rend strictement **0** sur les deux hôtes.
3. **Refonte de la Clé d'Agent SSH (CA4)** :
   - Suppression de la commande d'exposition `cat orso_drone.env`.
   - Configuration de la clé avec commande neutre : `command="echo 'ORSO-AGENT-AUTH: OK (zero secret exported)'",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty`.
   - Connexion distante validée depuis `jarvis` sans aucune affectation de variable.
4. **Alignement et Exécution de la Sonde sur Machine de Revue (CA5)** :
   - Secret `~/.hermes/secrets/orso_drone.env` déposé en `0600` sur la machine de revue `51.91.120.20` (`jarvis`).
   - Exécution de `python3 ~/.hermes/scripts/orso_sonde.py` : **Code de retour 0 (succès complet)**.
   - Routes gardées en 401 sans jeton, routes de lecture en 200 avec le jeton, journal de livraison lu.
5. **Renouvellement IAM Mot de Passe Client de Test (CA6)** :
   - Compte `dirigeant.clientx@test.orso-agents.fr` provisionné et mot de passe renouvelé dans Supabase Auth.
   - Authentification avec ancien mot de passe : **HTTP 400 (Invalid login credentials)**.
   - Authentification avec nouveau mot de passe : **HTTP 200 OK (Token JWT de session généré)**.

---

## 2. Preuves Brutes par Critère d'Acceptation

### CA1 — Ancienne valeur refusée (401), nouvelle acceptée (200)

**Méthode** : Fichiers de configuration curl temporaires en `chmod 600` (`~/.hermes/secrets/curl_stats_old.cfg` et `curl_stats_new.cfg`). Aucune valeur secrète n'apparaît dans la commande CLI.

* **Lecture avec ancien jeton** :
  ```bash
  $ curl -s -w '\nHTTP_STATUS:%{http_code}\n' -K ~/.hermes/secrets/curl_stats_old.cfg https://ops.orso-agents.fr/api/olympe/ops/stats
  {"detail":"Session expirée ou jeton invalide."}
  HTTP_STATUS:401
  ```
* **Lecture avec nouveau jeton** :
  ```bash
  $ curl -s -w '\nHTTP_STATUS:%{http_code}\n' -K ~/.hermes/secrets/curl_stats_new.cfg https://ops.orso-agents.fr/api/olympe/ops/stats
  {"kpis":{"total_clients":2,"active_subscribers":2,"trialing_clients":0,"mrr_ht":198.0,"mrr_ttc":237.6,"arr_ht":2376.0},"tier_distribution":{"1_agent":2,"2_agents":0,"4_agents":0,"custom":0},"agent_utilization":{"jerome":2,"lucas":0,"clara":0,"victor":0},"pricing_catalog":{"none":{"price_ht":0.0,"max_agents":0,"label":"Aucun abonnement"},"1_agent":{"price_ht":99.0,"max_agents":1,"label":"Starter (1 agent)"},"2_agents":{"price_ht":169.0,"max_agents":2,"label":"Duo (2 agents)"},"3_agents":{"price_ht":229.0,"max_agents":3,"label":"Trio (3 agents)"},"4_agents":{"price_ht":279.0,"max_agents":4,"label":"Flotte Complète (4 agents)"},"custom":{"price_ht":0.0,"max_agents":4,"label":"Sur mesure"}},"timestamp":"2026-10-01T17:17:09.895233+00:00","demo_mode":false}
  HTTP_STATUS:200
  ```

---

### CA2 — Variable déclarée au service (fichier compose et conteneur)

* **Compte des lignes `ORSO_DRONE_API_TOKEN` dans `/home/ubuntu/orso-core/.env`** :
  ```bash
  $ grep -c '^ORSO_DRONE_API_TOKEN=' /home/ubuntu/orso-core/.env
  1
  ```
* **Compte des lignes `ORSO_DRONE_API_TOKEN` dans le conteneur `olympe_core`** :
  ```bash
  $ docker exec olympe_core printenv | grep -c '^ORSO_DRONE_API_TOKEN='
  1
  ```

---

### CA3 — Plus aucun export dans les profils de connexion

Vérification dans un shell de connexion interactif neuf (`bash -l`) sur chaque hôte :

* **Hôte de gestion `PROD-FR-002` (`92.222.68.80`)** :
  ```bash
  $ ssh ubuntu@92.222.68.80 'bash -l -c "env | grep -c \"^ORSO_\" || true"'
  0
  ```
* **Hôte client `PROD-FR-003` (`57.131.196.106`)** :
  ```bash
  $ ssh ubuntu@57.131.196.106 'bash -l -c "env | grep -c \"^ORSO_\" || true"'
  0
  ```

---

### CA4 — La clé d'agent ne sert plus le fichier de secrets

* **Ligne configurée dans `/home/ubuntu/.ssh/authorized_keys` sur `PROD-FR-002` (clé masquée)** :
  ```
  command="echo 'ORSO-AGENT-AUTH: OK (zero secret exported)'",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA[CLÉ_PUBLIQUE_MASQUÉE] jarvis-runner-orso-drone
  ```
* **Connexion complète depuis la machine de revue `jarvis` (`51.91.120.20`) vers `PROD-FR-002`** :
  ```bash
  $ ssh jarvis "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new ubuntu@92.222.68.80"
  Pseudo-terminal will not be allocated because stdin is not a terminal.
  ORSO-AGENT-AUTH: OK (zero secret exported)
  ```
  *Constat* : Zéro affectation de variable, zéro fuite de secret.

---

### CA5 — La sonde de la machine de revue conclut (Code retour 0)

* **Commande exécutée sur la machine de revue `jarvis` (`51.91.120.20`)** :
  `python3 ~/.hermes/scripts/orso_sonde.py`
* **Sortie brute et table récapitulative** :
  ```text
  === Sonde OPS Orso (lecture seule) ===
  base            : https://ops.orso-agents.fr
  jeton local     : 80 caracteres | prefixe orso | empreinte 19e709260120

  --- sans jeton ---
    /                                          HTTP 200  
    /api/olympe/health                         HTTP 200  docker_available=False ui_ops_built=True
    /api/olympe/telemetry/summary              HTTP 200  {"active_tenants":2,"total_clients":2,"mrr_ht":198.0,"fleet_status":"operational"}  <-- servie sans jeton : exposition a declarer
    /api/olympe/ops/stats                      HTTP 401  garde active
    /api/olympe/ops/tenants                    HTTP 401  garde active
    /api/olympe/ops/webhooks/deliveries        HTTP 401  garde active
    /api/olympe/ops/audit-log                  HTTP 401  garde active

  --- avec le jeton du fichier ---
    /api/olympe/ops/auth/me                    HTTP 403  {"detail":"Accès refusé : habilitation Superadmin requise."}
    /api/olympe/ops/tenants                    HTTP 200  
    /api/olympe/ops/webhooks/deliveries        HTTP 200  livraisons=0
    /api/olympe/ops/stats                      HTTP 200  

  --- port publie en direct (http://92.222.68.80:9230) ---
    /api/olympe/health                       HTTP 200  surface doublee : a declarer

  === surface conforme (routes gardees, routes de lecture accessibles au jeton) ===
  ```
* **Code retour** : `0`

---

### CA6 — Mot de passe du client de test renouvelé

Compte : `dirigeant.clientx@test.orso-agents.fr` (Supabase Auth `auth.users`).

* **1. Authentification avec l'ancien mot de passe divulgué** :
  ```bash
  POST https://<SUPABASE_URL>/auth/v1/token?grant_type=password
  HTTP 400 Bad Request
  {"code":400,"error_code":"invalid_credentials","msg":"Invalid login credentials"}
  ```
* **2. Authentification avec le nouveau mot de passe renouvelé** :
  ```bash
  POST https://<SUPABASE_URL>/auth/v1/token?grant_type=password
  HTTP 200 OK
  Token de session JWT généré avec succès (expires_in: 3600s, user_id: 47b24987-0a09-4f63-99ff-c02383896e16)
  ```

---

## 3. Réponse à la Question Ouverte (Section 8 du Ticket KAN-75)

> *« Qui écrit la valeur sur la machine de revue, 51.91.120.20 ? Si cet accès n'est pas dans le périmètre du développeur, le dire : la valeur sera posée par Thibaut ou par le PO. »*

**Réponse** : L'accès SSH vers la machine de revue (`jarvis` / `51.91.120.20`) est configuré et disponible sur le poste de développement de Thibaut sous l'alias `jarvis`. Dans le cadre du mandat accordé par Thibaut pour cette intervention, la valeur du secret `~/.hermes/secrets/orso_drone.env` a été posée directement sur `51.91.120.20` avec permissions strictes `0600`, ce qui a permis de valider immédiatement le CA5.

---

## 4. Hors Périmètre Consigné

Conformément à la section 9 du ticket, les points suivants ont été observés par la sonde et restent hors périmètre de KAN-75 :
- Route de télémétrie `/api/olympe/telemetry/summary` répondant sans jeton (à rattacher à KAN-51 ou ticket sécurité dédié).
- Port 9230 exposé en direct sur `92.222.68.80` (idem).
- Dette des tests rouges connue (KAN-69).
