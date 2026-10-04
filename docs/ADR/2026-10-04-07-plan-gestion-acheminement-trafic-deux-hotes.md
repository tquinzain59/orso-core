# ADR 2026-10-04-07 : Plan de Gestion et Acheminement du Trafic Multi-Hôtes

- **Date** : 04 octobre 2026
- **Statut** : Accepté et Validé (Décision d'architecture KAN-61 / Épique KAN-62)
- **Auteurs** : Thibaut (Lead / PO), Antigravity (Architecte Projet)
- **Référence Documents** : Confluence Document 27 (sections 2, 4, 5 et 6), Document 06 (Architecture système), Document 21 (Journal des réalisations), ADR 2026-09-30-04 (Distribution Moteur), ADR 2026-10-01-05 (KAN-74 / Arbitrage Provisioning Production), ADR 2026-10-02-06 (KAN-60 / Mécanique de Montage)
- **Tickets Jira associés** : [KAN-61](https://orso-agents.atlassian.net/browse/KAN-61), [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62), [KAN-60](https://orso-agents.atlassian.net/browse/KAN-60), [KAN-59](https://orso-agents.atlassian.net/browse/KAN-59), [KAN-58](https://orso-agents.atlassian.net/browse/KAN-58), [KAN-74](https://orso-agents.atlassian.net/browse/KAN-74)

---

## 1. Contexte & Problématique (POC 4 - KAN-61)

Suite à la décision d'hébergement structurante du 30/09/2026 (Document 27, section 4) et à l'arbitrage d'architecture KAN-74 (ADR 2026-10-01-05) :
1. **Séparation physique des plans** :
   - Le serveur initial OVH (**Hôte 1 - `prod-fr-002`**, IP `92.222.68.80`) conserve exclusivement le plan de gestion (**Olympe**, port 9230), le **Cockpit OPS** (`ops.orso-agents.fr`), la passerelle **Ingress** (`app.orso-agents.fr`), et les pipelines d'intégration.
   - Un nouveau serveur OVH dédié (**Hôte 2 - `prod-fr-003`**, IP `57.131.196.106`) héberge exclusivement les conteneurs clients étanches.
2. **Constat de rupture technique identifié** :
   - `olympe/lifecycle_manager.py` pilotait historiquement Docker par la commande locale de l'hôte (`_exec_docker` via le binaire local `docker`), sans capacité d'adresser un moteur distant.
   - Le routage des requêtes client dans Nginx Ingress reposait sur le résolveur DNS interne Docker (`127.0.0.11`) et l'alias de conteneur local `http://orso_client_$tenant:9119`.
   - **Aucun de ces deux mécanismes ne franchit un hôte tel quel**.

L'objectif de **KAN-61 (POC 4)** est d'établir et prouver formellement :
1. Comment le plan de gestion pilote le moteur Docker du second hôte sans accès interactif humain.
2. Comment une requête client HTTP/WebSocket atteint son espace sur le second hôte, et comment un slug invalide ou inactif est rejeté.
3. Comment l'accès au moteur Docker du second hôte est restreint, sécurisé et audité.
4. Comment l'étanchéité absolue est garantie afin qu'aucune donnée propre à un client ne transite ni ne soit persistée sur le plan de gestion.

---

## 2. Décision d'Architecture

### 2.1 Arbitrage de l'Accès au Moteur Docker Distant (Question Ouverte KAN-61)

Trois options d'accès ont été analysées pour permettre au superviseur Olympe de piloter Docker sur l'Hôte 2 :

| Critère | Option A : Contexte Docker distant via SSH (Retenue) | Option B : Port Docker TCP avec Mutual TLS (mTLS) | Option C : Agent local mandataire (Olympe-Node) |
| :--- | :--- | :--- | :--- |
| **Exposition réseau** | **0 port Docker ouvert**. Utilise le port 22 (SSH) existant et durci. | Port TCP 2376 exposé publiquement sur Internet. | Nouveau port applicatif exposé sur Internet. |
| **Gestion des identifiants** | **Clé privée ed25519 dédiée**, sans mot de passe, gérée nativement par l'OS. | PKI complexe : autorité de certification (CA), certificats client et serveur X.509 à renouveler. | Jetons API / JWT à distribuer et rafraîchir. |
| **Sécurité d'authentification** | **Authentification forte SSH**, `PasswordAuthentication no`, `BatchMode=yes`. | mTLS fort mais risque de rupture sur expiration de certificat. | Variable selon implémentation de l'agent. |
| **Traçabilité & Audit** | **Double audit** : `journalctl -u ssh` / `auth.log` système OS + journal structuré Olympe. | Logs Docker Daemon bruts. | Logs applicatifs de l'agent. |
| **Empreinte logicielle** | **0 composant additionnel**. Binaire standard `docker -H ssh://...` ou Docker context. | Configuration du démon `dockerd` (daemon.json) avec flags TLS. | Service Python / Go résident à superviser et mettre à jour. |
| **Verdict** | **Retenu formellement** | Écarté (surface d'attaque et complexité PKI inutiles) | Écarté (surcoût d'exploitation prématuré pour Vagues 0 et 1) |

#### Justification du choix retenu (Option A) :
- **Surface d'attaque minimale** : L'exposition d'un port d'API Docker (`2376`) sur IP publique est formellement proscrite par la politique de sécurité Orso Agents (KAN-51 / KAN-61). Le tunnel SSH natif garantit le chiffrement de bout en bout et l'authentification par clé asymétrique ed25519 sans exposer aucun port additionnel.
- **Sobriété d'exploitation** : Le CLI Docker supporte nativement le protocole `ssh://user@host` depuis Docker 18.09+. Les commandes du cycle de vie (`run`, `ps`, `inspect`, `stop`, `rm`) sont adressées de manière transparente au démon de l'Hôte 2 via `_exec_docker(args, remote_host="ssh://ubuntu@57.131.196.106")`.
- **Exécution non-interactive** : Toutes les commandes sont exécutées en mode automatisé (`ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8`), excluant toute intervention humaine interactive.

---

### 2.2 Acheminement du Trafic Client & Protection Réseau (CA2 & Point de Vigilance Jarvis)

#### 1. Ingress Multi-Hôtes & Table de Routage d'Espaces :
- L'Ingress Nginx principal (`app.orso-agents.fr`) réside sur l'Hôte 1.
- Olympe maintient le registre de localisation des espaces clients : `{tenant_slug: {"host_id": "prod-fr-003", "host_ip": "57.131.196.106", "port": 9229 + offset}}`.
- Pour chaque tenant provisionné sur l'Hôte 2, le conteneur publie son port applicatif (ex: `9231` pour `poc-alpha`, `9232` pour `poc-beta`) vers le serveur d'exécution.
- La passerelle Ingress Nginx achemine le trafic `/t/{slug}/api/(.*)` et `/t/{slug}/ws` directement vers `http://57.131.196.106:{port_du_tenant}/...`.
- Si le slug n'existe pas ou si le conteneur est éteint, Ingress ou le résolveur intercepte l'appel et retourne une réponse d'erreur explicite :
  - `503 TENANT_CONTAINER_OFFLINE` (avec lien de réveil Olympe) si le conteneur est inactif.
  - `404 / 403 TENANT_NOT_FOUND_OR_FORBIDDEN` si le slug est invalide ou si le jeton JWT ne correspond pas au tenant demandé.

#### 2. Durcissement Pare-Feu & Règle iptables DOCKER-USER (Contournement UFW neutralisé) :
- **Point de vigilance soulevé par Jarvis (PO)** : *"Les ports publiés par Docker écrivent leurs règles directement dans iptables et contournent ufw."*
- **Solution architecturale mise en place** :
  Sur l'Hôte 2 (`prod-fr-003`), une règle stricte dans la chaîne `DOCKER-USER` d'iptables est configurée :
  ```bash
  iptables -I DOCKER-USER -i eth0 -p tcp --dport 9200:9299 ! -s 92.222.68.80 -j DROP
  ```
  **Effet** : Seules les connexions TCP issues de l'adresse IP publique de l'Hôte 1 (`92.222.68.80` - Ingress / Olympe) sont autorisées à atteindre les conteneurs clients sur l'Hôte 2. Toute tentative d'accès direct depuis une autre IP Internet est immédiatement rejetée en silence (`DROP`).

---

### 2.3 Non-Transit des Données Clients par le Plan de Gestion (CA4)

L'architecture à deux hôtes sanctuarise le principe de non-transit des données clients :
1. **Flux de contrôle vs Flux de données** :
   - **Olympe (Port 9230)** traite **exclusivement** le plan de contrôle : commandes de cycle de vie Docker (`docker run`, `docker stop`, `docker inspect`), quotas de ressources, supervision de disponibilité et facturation Stripe.
   - Les données applicatives (messages de chat, pièces jointes, balances âgées financières, mémoires d'agents `state.db`) **ne transitent jamais par Olympe**.
2. **Ingress L7 transparent** :
   - Nginx Ingress agit comme un mandataire de transport HTTP/WebSocket sans état (Zero-Storage). Aucun log de niveau DEBUG ne persiste le corps des messages (`request_body`), et aucun stockage persistant de conversation n'est présent sur l'Hôte 1.
3. **Étanchéité des montages système** :
   - Sur l'Hôte 1, **aucun volume de données client n'est monté**. Le répertoire `/app/data` des clients réside physiquement sur le disque dédié de l'Hôte 2 (`/home/ubuntu/data/tenants/{slug}`).

---

## 3. Conséquences & Engagements Opérationnels

1. **Clé SSH d'orchestration Olympe dédiée** :
   - Une paire de clés SSH `ed25519` (`id_ed25519_olympe`) est déployée pour les communications Hôte 1 -> Hôte 2.
   - Droits sur la clé privée : `0600 root:root` ou utilisateur de service Olympe.
2. **Journal d'Audit des Opérations Distantes** :
   - Toutes les commandes exécutées sur le second hôte sont enregistrées dans un journal d'audit horodaté en UTC (`data/remote_audit.jsonl`), consignant : `timestamp`, `target_host`, `tenant_slug`, `action`, `command`, `return_code`, `duration_ms`.
3. **Fail-Closed en cas de perte de connectivité** :
   - En cas d'indisponibilité réseau entre Hôte 1 et Hôte 2, le plan de gestion renvoie une erreur explicite `ERR_REMOTE_HOST_UNREACHABLE` sans jamais basculer vers un mode dégradé in-process local sur l'Hôte 1 (proscription formelle KAN-74).
