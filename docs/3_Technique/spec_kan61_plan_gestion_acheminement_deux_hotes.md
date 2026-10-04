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

### 3.2 CA2 - Acheminement Étanche des Requêtes par Slug
- **Exigence** : Une requête pour un slug atteint son espace, et une requête portant un autre slug ne l'atteint pas.
- **Implémentation** :
  - Table de routage dynamique multi-hôtes : Olympe associe chaque espace client à un tuple `(host_id, host_ip, port)`.
  - La passerelle d'acheminement Ingress L7 relaie les requêtes `/t/{slug}/api/...` vers le port de l'espace sur l'Hôte 2.
  - Requête sur slug actif (`poc-alpha`) : retourne 200 OK avec le corps de réponse de l'espace client.
  - Requête sur slug inactif ou non provisionné (`poc-inconnu`) : retourne 503 `TENANT_CONTAINER_OFFLINE` ou 404 `TENANT_NOT_FOUND`.
  - Requête croisée (slug-a avec identifiant / clé de slug-b) : formellement rejetée par le garde d'authentification tenant (403 Forbidden).
- **Preuve attendue** :
  - Réponses HTTP brutes, en-têtes et codes d'état obtenus pour deux slugs distincts (`poc-alpha` -> 200 OK vs `poc-inexistant` -> 503 / 404).

### 3.3 CA3 - Accès au Moteur Docker Limité et Tracé
- **Exigence** : L'accès au moteur Docker du second hôte est limité et tracé.
- **Implémentation** :
  1. **Limitation de l'exposition réseau** :
     - Les ports d'API TCP Docker 2375 et 2376 sont formellement fermés et non exposés (`0.0.0.0:2375/2376` absent de `ss -tulpn`).
     - L'accès d'orchestration s'opère exclusivement via SSH durci (`PasswordAuthentication no`, clé `ed25519`).
     - Durcissement iptables `DOCKER-USER` sur l'Hôte 2 : les ports conteneurs publiés (9200-9299) ne répondent qu'à l'IP de l'Hôte 1 (`92.222.68.80`).
  2. **Traçabilité & Journalisation** :
     - Journal d'audit structuré des opérations distantes (`data/remote_audit.jsonl`) consignant :
       - `timestamp_utc` : Date et heure ISO 8601.
       - `target_host` : Identifiant de l'hôte (`prod-fr-003`).
       - `tenant_slug` : Client concerné.
       - `operation` : `provision`, `inspect`, `stop`, `teardown`.
       - `command` : Commande complète exécutée.
       - `return_code` : 0 ou code d'erreur.
       - `duration_ms` : Temps de réponse en millisecondes.
- **Preuve attendue** :
  - Extrait du journal d'audit Olympe, scan des ports de l'Hôte 2 prouvant l'absence de port Docker exposé publiquement, et règles actives `iptables -L DOCKER-USER -n -v`.

### 3.4 CA4 - Non-Transit des Données Clients par le Plan de Gestion
- **Exigence** : Aucune donnée propre à un client ne transite par le plan de gestion.
- **Implémentation** :
  - Séparation stricte des flux :
    - Le plan de gestion Olympe (port 9230) n'a aucun endpoint de relais de messagerie ou de données financières. Il n'ouvre que des flux de contrôle Docker.
    - Le flux de données applicatif client (chat, SSE, WebSocket) relie directement le client à son conteneur sur l'Hôte 2 via Nginx Ingress en mode mandataire inverse L7 transparent (sans persistance).
  - Étanchéité des systèmes de fichiers :
    - Sur l'Hôte 1, aucun volume de données client (`/app/data`) n'est monté ni stocké sur le disque.
    - Les volumes `/app/data` résident exclusivement sur le stockage local de l'Hôte 2 (`/home/ubuntu/data/tenants/{slug}`).
  - Audit des journaux d'Olympe :
    - Aucune trace de payload de conversation, clé d'API financière, balance âgée ou mémoire persistée dans les logs d'Olympe (`olympe.log`, `agent.log`).
- **Preuve attendue** :
  - Inspection de l'arborescence disque de l'Hôte 1 (0 volume de données client), inspection des points de montage Docker sur Hôte 1, et analyse automatisée des logs d'Olympe certifiant l'absence de toute donnée client.

---

## 4. Matrice de Traçabilité des Exigences

| Critère Jira | Composant Technique | Fichier Source | Preuve d'Acceptation |
| :--- | :--- | :--- | :--- |
| **CA1** (Pilotage non-interactif) | `DockerLifecycleManager` + `RemoteDockerHostManager` | `olympe/remote_host_client.py` & `olympe/lifecycle_manager.py` | Commandes brutes exécutées et sorties d'inspection Docker sur Hôte 2 |
| **CA2** (Routage par slug étanche) | Routeur dynamique Ingress & Résolveur multi-hôtes | `olympe/remote_host_client.py` & `docker/ingress/nginx.ingress.conf` | Requêtes HTTP sur `poc-alpha` (200 OK) vs slug inactif (503) |
| **CA3** (Accès limité & tracé) | Règle `DOCKER-USER`, scan de ports, `remote_audit.jsonl` | `olympe/remote_host_client.py` & `scripts/poc/execute_kan61_poc.py` | 0 port Docker exposé (2375/2376), journal d'audit structuré |
| **CA4** (Zéro donnée client sur Olympe) | Séparation des plans & isolation des montages | `olympe/lifecycle_manager.py` | Inspection disque Hôte 1 (0 volume client), scan anti-fuite des logs |
