# Spécification Technique KAN-61 : Plan de Gestion et Acheminement du Trafic sur Deux Hôtes

- **Date** : 04 octobre 2026
- **Auteurs** : Thibaut (Lead / PO), Antigravity (Architecte Projet & Développeur)
- **Ticket Jira** : [KAN-61](https://orso-agents.atlassian.net/browse/KAN-61) (Statut : En cours)
- **Épique associée** : [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62) (POC d'architecture : deux artefacts)
- **Documents sources** : Confluence Document 27 (sections 2, 4, 5 et 6), ADR 2026-10-04-07, ADR 2026-09-30-04 (Distribution Moteur), ADR 2026-10-01-05 (KAN-74 / Arbitrage Provisioning Production), ADR 2026-10-02-06 (KAN-60 / Artefact Espace Client).

---

## 1. Contexte & Problématique (POC 4 - Cœur de la Topologie Multi-Hôtes)

La décision d'hébergement structurante du 30/09/2026 (Document 27) et l'arbitrage formel KAN-74 (ADR 2026-10-01-05) établissent une séparation physique stricte entre :
1. **L'Hôte de Gestion (Hôte 1 - `prod-fr-002` / `92.222.68.80`)** : Exécute le superviseur Olympe (port 9230), le Cockpit Ops (`ops.orso-agents.fr`), la passerelle Ingress (`app.orso-agents.fr`), et les chaînes de build.
2. **L'Hôte d'Exécution Client (Hôte 2 - `prod-fr-003` / `57.131.196.106`)** : Nouveau serveur OVH dédié hébergeant exclusivement les conteneurs étanches des clients.

### Constat technique de code :
- Historiquement, `olympe/lifecycle_manager.py` pilotait Docker par la commande locale de l'hôte (`_exec_docker` avec le binaire `docker`), et le routage des clients dans `nginx.ingress.conf` s'appuyait sur le nom de conteneur local et un alias réseau Docker (`http://orso_client_$tenant:9119`).
- Aucun de ces deux mécanismes ne franchissait un hôte distant.
- Sur deux hôtes, sans outillage d'orchestration distante et sans acheminement de trafic réseau :
  - Olympe ne peut ni instancier, ni inspecter, ni arrêter de conteneur sur l'Hôte 2.
  - Les requêtes clients adressées à `app.orso-agents.fr/t/{slug}/...` échouent en boucle locale.

L'objectif de **KAN-61 (POC 4)** est d'établir, d'outiller et de prouver de bout en bout :
- Le pilotage automatisé du moteur Docker sur l'Hôte 2 depuis le plan de gestion (CA1).
- L'acheminement étanche du trafic client par slug (CA2).
- La restriction et la traçabilité de l'accès au moteur Docker (CA3).
- La garantie absolue qu'aucune donnée propre à un client ne transite par le plan de gestion (CA4).

---

## 2. Architecture Technique Multi-Hôtes

```
       UTILISATEUR CLIENT                             ADMINISTRATEUR OPS / STRIPE
               |                                                   |
      HTTPS / WSS / API                                   HTTPS (Port 9230 / Ops)
               v                                                   v
+-----------------------------------------------------------------------------------+
|                        HÔTE 1 : PLAN DE GESTION (prod-fr-002)                    |
|                                (92.222.68.80)                                     |
|                                                                                   |
|  +-------------------------------------+  +------------------------------------+  |
|  |           INGRESS NGINX             |  |           OLYMPE CORE              |  |
|  |       (app.orso-agents.fr)          |  |       (Superviseur & API)          |  |
|  |                                     |  |                                    |  |
|  |  Table de routage multi-hôtes :     |  |  DockerLifecycleManager            |  |
|  |  /t/poc-alpha -> 57.131.196.106:9231|  |  - Pilote Docker distant via SSH   |  |
|  |  /t/poc-beta  -> 57.131.196.106:9232|  |  - DOCKER_HOST=ssh://ubuntu@H2     |  |
|  |  /t/{offline} -> 503 Wake-on-demand |  |  - Journal d'audit d'orchestration |  |
|  +------------------+------------------+  +-----------------+------------------+  |
+---------------------|---------------------------------------|---------------------+
                      | Flux de Données (HTTP/WS L7)          | Ordres de Contrôle (SSH)
                      | Port applicatif client (9231, 9232)   | docker -H ssh://... (Port 22)
                      v                                       v
+-----------------------------------------------------------------------------------+
|                     HÔTE 2 : EXÉCUTION CLIENTS (prod-fr-003)                      |
|                                (57.131.196.106)                                   |
|                                                                                   |
|  [Pare-feu / iptables DOCKER-USER]                                                |
|  Ports 9200-9299 autorisés UNIQUEMENT depuis IP Hôte 1 (92.222.68.80), DROP sinon |
|  Port 2375/2376 : STRICTEMENT FERMÉS (Non exposés)                               |
|                                                                                   |
|  Démon Docker (Docker 29.8.1)                                                     |
|  +-----------------------------------+   +-------------------------------------+  |
|  |   Conteneur : poc-alpha           |   |   Conteneur : poc-beta              |  |
|  |   - Port interne: 9119 -> 9231    |   |   - Port interne: 9119 -> 9232      |  |
|  |   - Quotas stricts: 0.5 CPU, 512M |   |   - Quotas stricts: 0.5 CPU, 512M   |  |
|  |   - Artefact v1.0.0 monté :ro     |   |   - Artefact v1.0.0 monté :ro       |  |
|  |   - Volume dédié: /app/data (RW)  |   |   - Volume dédié: /app/data (RW)    |  |
|  +-----------------------------------+   +-------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 3. Critères d'Acceptation & Preuves Factuelles

### 3.1 CA1 - Pilotage Non-Interactif du Moteur Docker Distant
- **Exigence** : Le plan de gestion crée, arrête et inspecte un conteneur sur le second hôte, sans accès interactif à cet hôte.
- **Implémentation** :
  - `DockerLifecycleManager` s'enrichit de la capacité de cibler un démon distant via `remote_host` (ex: `ssh://ubuntu@57.131.196.106`) ou variable `ORSO_REMOTE_DOCKER_HOST`.
  - Toutes les commandes Docker (`run`, `inspect`, `stop`, `rm`, `ps`) s'exécutent en mode non-interactif via le drapeau standard `-H <remote_host>`.
  - Les commandes SSH sous-jacentes utilisent `BatchMode=yes`, `StrictHostKeyChecking=accept-new` et une clé d'authentification asymétrique `ed25519`.
- **Preuve attendue** :
  - Journal horodaté d'exécution consignant la ligne de commande exacte (`docker -H ssh://... run ...`), le code de retour (0), et les sorties brutes d'inspection prouvant l'instanciation, la détection et la terminaison sur l'Hôte 2.

### 3.2 CA2 - Table de Routage Multi-Hôtes et Décision d'Autorisation par Slug (Amendement 04/10/2026 - Voie b)
- **Exigence (Amendée par le PO le 04/10/2026)** :
  Le plan de gestion associe chaque espace à un slug et refuse tout autre slug : la table de routage résout un slug vers son hôte et son port, et toute requête dont le slug ne correspond pas à une route active est rejetée par une décision explicite. L'acheminement L7 réel en réseau fait l'objet du ticket dédié KAN-97.
- **Implémentation** :
  - `RemoteDockerHostManager` gère la table de routage dynamique multi-hôtes (`get_routing_table()`) associant chaque slug d'espace client à un tuple `(host_id, host_ip, port, status)`.
  - Décision d'autorisation explicite (`authorize_and_resolve_slug(slug)`) :
    - Si le slug correspond à une route active : renvoie `decision: "ACCEPT"`, `status: "AUTHORIZED"`, `host_id`, `host_ip`, `port`, et l'URL cible.
    - Si le slug n'est pas provisionné : rejet explicite `decision: "REJECT"`, `status: "REJECTED_UNPROVISIONED"`, `error_code: "ERR_TENANT_ROUTE_NOT_FOUND"`.
    - Si le slug est en veille : rejet explicite `decision: "REJECT"`, `status: "REJECTED_OFFLINE"`, `error_code: "ERR_TENANT_CONTAINER_OFFLINE"`.
- **Preuve attendue** :
  - Sortie brute de la résolution et de la décision d'autorisation pour deux slugs distincts (un espace actif, un espace non provisionné), obtenue par exécution du gestionnaire, la table de routage étant lue avant et après.

### 3.3 CA3 - Accès au Moteur Docker Limité et Tracé
- **Exigence** : L'accès au moteur Docker du second hôte est limité et tracé.
- **Implémentation** :
  1. **Limitation de l'exposition réseau & Sonde étanche** :
     - Les ports d'API TCP Docker 2375 et 2376 sont formellement fermés et non exposés.
     - La sonde réseau `verify_port_exposure_security` contrôle au préalable la joignabilité de l'hôte (port 22 SSH) pour éviter toute fausse conformité en cas de panne réseau, et distingue les ports fermés (`ECONNREFUSED` / TCP RST) des ports filtrés (`ETIMEDOUT`).
     - L'accès d'orchestration s'opère exclusivement via SSH durci (`PasswordAuthentication no`, clé asymétrique `ed25519`).
     - Relevé et inspection de la chaîne pare-feu iptables `DOCKER-USER` sur l'Hôte 2 (`sudo iptables -S DOCKER-USER`).
     - Décision d'architecture sur le bind : publication de port (`-p 9231:9119`) protégée par filtrage pare-feu ; le régime définitif d'acheminement L7 fait l'objet de KAN-97.
  2. **Traçabilité & Journalisation** :
     - Journal d'audit structuré des opérations distantes (`data/remote_audit.jsonl`) consignant :
       - `timestamp` : Date et heure ISO 8601 UTC.
       - `host_id` : Identifiant de l'hôte (`prod-fr-003`).
       - `tenant_slug` : Client concerné.
       - `operation` : `probe_info`, `provision`, `inspect`, `stop`, `cleanup`.
       - `command` : Commande complète exécutée.
       - `return_code` : 0 ou code d'erreur.
       - `duration_ms` : Temps de réponse en millisecondes.
- **Preuve attendue** :
  - Extrait du journal d'audit `data/remote_audit.jsonl`, scan des ports de l'Hôte 2 (distinguant fermeture et panne réseau) et sortie brute `iptables -S DOCKER-USER`.

### 3.4 CA4 - Non-Transit des Données Clients par le Plan de Gestion
- **Exigence** : Aucune donnée propre à un client ne transite par le plan de gestion.
- **Implémentation & Inspection Réelle** :
  - L'inspection ne repose sur aucune entrée artificielle et interroge directement l'Hôte 1 de gestion (`prod-fr-002` / `92.222.68.80`) en SSH direct non-interactif :
    - Points de montage réels d'Olympe : `ssh ubuntu@92.222.68.80 docker inspect olympe_core --format '{{json .Mounts}}'` certifie qu'aucun volume de données client déporté (`/app/data`) n'est monté.
    - Journaux réels d'Olympe : `ssh ubuntu@92.222.68.80 docker logs --tail 30 olympe_core` certifie que le superviseur ne traite que de la télémétrie et aucun payload métier client.
    - Stockage Hôte 1 : `ssh ubuntu@92.222.68.80 ls -d /home/ubuntu/orso-core/data/tenants/kan61*` certifie l'absence de répertoire client pour l'espace déporté.
- **Preuve attendue** :
  - Commandes brutes exécutées contre `prod-fr-002`, sorties JSON et textuelles réelles sans injection factice.

---

## 4. Matrice de Traçabilité des Exigences

| Critère Jira | Composant Technique | Fichier Source | Preuve d'Acceptation |
| :--- | :--- | :--- | :--- |
| **CA1** (Pilotage non-interactif) | `DockerLifecycleManager` + `RemoteDockerHostManager` | `olympe/remote_host_client.py` & `olympe/lifecycle_manager.py` | Commandes brutes exécutées et sorties d'inspection Docker sur Hôte 2 (image sha256 mesurée, ID complet, status running/exited) |
| **CA2** (Table de routage & Décision d'autorisation) | `RemoteDockerHostManager` (`authorize_and_resolve_slug`) | `olympe/remote_host_client.py` | Table de routage lue avant/après, décision brute ACCEPT (port 9231) vs REJECT (ERR_TENANT_ROUTE_NOT_FOUND) ; acheminement L7 réel versé à KAN-97 |
| **CA3** (Accès limité & tracé) | Règle `DOCKER-USER`, scan de ports durci, `remote_audit.jsonl` | `olympe/remote_host_client.py` & `scripts/poc/execute_kan61_poc.py` | 0 port Docker exposé (2375/2376), sortie brute iptables DOCKER-USER, journal d'audit structuré |
| **CA4** (Zéro donnée client sur Olympe) | Inspection SSH réelle de `prod-fr-002` (Hôte 1) | `scripts/poc/execute_kan61_poc.py` | Inspection réelle montages `olympe_core`, logs Olympe et stockage Hôte 1 certifiant 0 fuite |
