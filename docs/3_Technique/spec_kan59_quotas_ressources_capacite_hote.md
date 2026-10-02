# Spécification Technique KAN-59 : Quotas de Ressources & Refus de Provisioning au-delà de la Capacité Hôte

- **Date** : 02 octobre 2026
- **Auteurs** : Thibaut (Lead / PO), Antigravity (Architecte Projet)
- **Ticket Jira** : [KAN-59](https://orso-agents.atlassian.net/browse/KAN-59) (Statut : Validé / Prêt pour Revue)
- **Épique associée** : [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62) (POC d'architecture : deux artefacts)
- **Documents sources** : Confluence Document 27 (section 6 étape 6 & section 9), ADR 2026-09-30-04, ADR 2026-10-01-05 (KAN-74), Ticket KAN-58 (espaces agents propres).

---

## 1. Contexte & Constat Vérifié (Prérequis P2 de Document 27)

Le 30/09/2026, l'audit du superviseur Olympe (`olympe/lifecycle_manager.py`) a mis en évidence une vulnérabilité d'exploitation majeure :
- Les quotas de processeur, de mémoire vive et de processus n'étaient appliqués que pour l'unique tenant de test `clientx-orso` (0,5 vCPU, 512 Mo, 100 processus).
- **Aucun des trois chemins de provisioning en production ne transmettait de limites de ressources** :
  1. Le bouton d'onboarding du cockpit (`/api/olympe/ops/onboarding/{tenant_id}/provision`).
  2. La route historique de provisioning (`/api/olympe/tenants/provision`).
  3. Le traitement automatique du webhook Stripe (`ops_manager.handle_stripe_webhook`).
- Le modèle de dimensionnement théorique de l'infrastructure (`olympe/ovh_client.py`) reposait sur une règle de calcul empirique arbitraire (1 Go de RAM par agent actif + 500 Mo par conteneur client) servant uniquement à conseiller un achat d'instance OVH, mais jamais à contrôler l'admission ou refuser un déploiement.

### Risques & Conséquences identifiés :
1. **Risque d'emballement et de déni de service mutuel** : Un conteneur client non bridé dont l'agent boucle ou sature la mémoire sature l'hôte complet (`OOM Killer`), provoquant l'effondrement de tous les autres conteneurs clients hébergés sur le même serveur.
2. **Faussage des mesures de performance du POC (Document 27, étape 6)** : Sans plafonds étanches, la mesure de charge du POC mesurerait l'absence de garde-fous plutôt que la capacité soutenable réelle de la plateforme.

L'objectif de **KAN-59 (POC 2)** est de poser des limites de ressources strictes sur **tout conteneur client**, et de refuser formellement et explicitement tout provisioning que l'hôte ne peut pas soutenir sans dégrader la flotte en service.

---

## 2. Architecture des Quotas & Contrôle d'Admission de l'Hôte

### 2.1 Grille des Quotas par Palier Tarifaire (`TIER_RESOURCE_QUOTAS`)

Les limites physiques sont strictement calquées sur les forfaits d'abonnement officiels d'Orso Agents (`TIER_PRICING`) :

| Palier Tarifaire | Nombre d'Agents Max | Quota RAM | Quota Swap | Quota vCPU | Limite PIDs | Marge vs Charge Réelle |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Starter (1 agent)** | 1 | **512 Mo** | **512 Mo** (no-leak) | **0.5 vCPU** | **100** | 5.1x au repos (~100 Mo), 2.0x en pic (~250 Mo) |
| **Duo (2 agents)** | 2 | **1024 Mo** (1 Go) | **1024 Mo** | **1.0 vCPU** | **150** | 10.2x au repos, 2.0x sous 2 requêtes simultanées |
| **Trio (3 agents)** | 3 | **1536 Mo** (1.5 Go)| **1536 Mo** | **1.5 vCPU** | **200** | 15.3x au repos, 2.0x sous 3 requêtes simultanées |
| **Flotte Complète (4 agents)** | 4 | **2048 Mo** (2 Go) | **2048 Mo** | **2.0 vCPU** | **250** | 20.4x au repos, 2.0x sous 4 requêtes simultanées |
| *Sur mesure (custom)* | ≥ 4 | **2048 Mo+** | = RAM | **2.0 vCPU+** | **250+** | Ajusté selon contrat |

> [!IMPORTANT]
> **Verrouillage inviolable du Swap (`--memory-swap == --memory`)** :
> En fixant `memory-swap` à une valeur strictement égale à `memory`, Docker interdit au conteneur d'utiliser le fichier d'échange (swap) de l'hôte. Cela prévient tout ralentissement de l'hôte et garantit une étanchéité mémoire absolue.

---

### 2.2 Contrôle d'Admission de l'Hôte (`check_host_admission`)

Avant toute instanciation physique ou simulée de conteneur, `DockerLifecycleManager.provision_tenant` calcule l'empreinte totale déjà allouée aux conteneurs clients gérés (`com.orso.managed=true` et `com.orso.role=client_backend`) :
$$\text{Mémoire Allouée} = \sum \text{quota.memory}(\text{conteneurs existants})$$
$$\text{vCPU Alloué} = \sum \text{quota.cpus}(\text{conteneurs existants})$$

Si $\text{Mémoire Allouée} + \text{Mémoire Requise} > \text{Plafond Hôte}$ ou $\text{vCPU Alloué} + \text{vCPU Requis} > \text{Plafond Hôte vCPU}$ :
1. **Refus formel d'admission** avec le code d'erreur standardisé `ERR_HOST_CAPACITY_EXCEEDED`.
2. **Message d'information clair** précisant la mémoire requise, la mémoire disponible et le plafond hôte (ex: `Capacité mémoire de l'hôte dépassée pour 'poc-delta' : 2048 Mo requis, 428 Mo disponibles (plafond hôte: 3500 Mo, alloué: 3072 Mo)`).
3. **Consignation d'audit** (`ops_manager.record_audit_event`) avec action `provision:failed` et l'objet complet `capacity_details`.
4. **Préservation absolue des espaces en service** : aucun conteneur existant n'est altéré, redémarré ou dégradé.
5. **Restitution Cockpit en HTTP 400** : Le refus est traité comme une information d'exploitation claire pour l'opérateur et non comme un crash système 500.

---

## 3. Déclinaison des 4 Critères d'Acceptation et Preuves Réelles

Toutes les preuves ci-dessous ont été produites sur conteneurs Docker réels via le script d'automatisation `scripts/poc/execute_kan59_poc.py` et consolidées dans `docs/3_Technique/kan59_e2e_poc_evidence.json`.

### CA1 : Aucun conteneur sans quotas stricts
- **Conteneurs testés** : `orso_client_poc_alpha` (Starter), `orso_client_poc_beta` (Duo), `orso_client_poc_gamma` (Trio).
- **Inspection Docker (`docker inspect`)** :
  - `poc-alpha` : `Memory=536870912` (512 Mo), `MemorySwap=536870912`, `NanoCpus=500000000` (0.5 vCPU), `PidsLimit=100`.
  - `poc-beta` : `Memory=1073741824` (1024 Mo), `MemorySwap=1073741824`, `NanoCpus=1000000000` (1.0 vCPU), `PidsLimit=150`.
  - `poc-gamma` : `Memory=1610612736` (1536 Mo), `MemorySwap=1610612736`, `NanoCpus=1500000000` (1.5 vCPU), `PidsLimit=200`.
- **Labels OCI vérifiés** : `com.orso.quotas.cpus`, `com.orso.quotas.memory`, `com.orso.quotas.pids_limit`, `com.orso.tier_id`.
- **Preuve JSON** : Section `ca1_quotas_enforced` (`passed: true`).

### CA2 : Refus formel de dépassement de capacité & intégrité des espaces
- **Capacité hôte configurée pour le test** : 3500 Mo RAM, 3.5 vCPU.
- **Ressources allouées aux 3 premiers espaces** : 512 + 1024 + 1536 = 3072 Mo (Reste disponible : 428 Mo).
- **Demande de provisioning de `poc-delta` (Forfait Flotte - 2048 Mo requis)** :
  - **Code d'erreur retourné** : `ERR_HOST_CAPACITY_EXCEEDED`.
  - **Message** : `Provisioning refusé : Capacité mémoire de l'hôte dépassée pour 'poc-delta' : 2048 Mo requis, 428 Mo disponibles (plafond hôte: 3500 Mo, alloué: 3072 Mo).`
  - **Contrôle d'intégrité** : `poc-alpha`, `poc-beta` et `poc-gamma` sont restés en état `running / ready`, zéro downtime, mémoire allouée strictement maintenue à 3072 Mo.
- **Preuve JSON** : Section `ca2_admission_refusal_proof` (`passed: true`).

### CA3 : Valeurs dérivées de mesures empiriques réelles
- **Mesures en direct sur le conteneur moteur Orso (`docker stats` & `docker top`)** :
  - `poc-alpha` : **96.7 MiB** / 512 MiB au repos (18.8% du quota), 9 PIDs, 0.18% CPU.
  - `poc-beta` : **94.8 MiB** / 1024 MiB au repos (9.2% du quota), 9 PIDs, 0.63% CPU.
  - `poc-gamma` : **93.9 MiB** / 1536 MiB au repos (6.1% du quota), 9 PIDs, 0.17% CPU.
- **Enseignement empirique** : L'empreinte socle d'un conteneur Orso backend au repos est remarquablement stable entre 93 et 97 Mo RAM. Le modèle de dimensionnement `estimate_sizing` (`olympe/ovh_client.py`) a été enrichi avec les métriques mesurées réelles (`empirical_measured_ram_mb`), confirmant qu'une allocation de 512 Mo par conteneur de base offre une marge de sécurité de 5x sans gaspillage.
- **Preuve JSON** : Section `ca3_raw_measurements` (`passed: true`).

### CA4 : Cohérence des paliers tarifaires et catalogue OVH
- **Matrice tarifaire croisée** : Vérification que chaque agent vendu correspond au minimum à 512 Mo de RAM et 0.5 vCPU garanti.
- **Correspondance gabarits OVH Public Cloud** :
  - `d2-2` (2 Go RAM) : Capacité d'accueil de 2 conteneurs Starter ou 1 Duo (avec 1 Go réservé à l'OS/Olympe).
  - `d2-4` (4 Go RAM) : Capacité d'accueil de 6 conteneurs Starter ou 3 conteneurs Duo ou 1 Flotte + 1 Duo.
  - `b2-7` (7 Go RAM) : Capacité d'accueil de 12 conteneurs Starter ou 6 Duo.
  - `b2-15` (15 Go RAM) : Capacité d'accueil de 24 conteneurs Starter ou 12 Duo ou 6 Flotte.
  - `b2-30` (30 Go RAM) : Capacité d'accueil de 50 conteneurs Starter ou 25 Duo ou 12 Flotte.
- **Preuve JSON** : Section `ca4_tier_consistency` (`passed: true`).

---

## 4. Alignement des 3 Chemins de Provisioning

1. **Chemin 1 - Bouton d'onboarding du cockpit** (`olympe/server.py:provision_onboarding_order`) :
   - Extrait le forfait client (`subscription.tier_id` ou `1_agent` par défaut).
   - Invoque `manager.provision_tenant(..., tier_id=client_tier)`.
   - Si capacité dépassée : lève une `HTTPException(400)` et consigne l'événement `provision:failed` avec `capacity_details`.
2. **Chemin 2 - Route historique de provisioning** (`olympe/server.py:provision_tenant`) :
   - `ProvisionRequest` supporte `tier_id` et `quotas: Dict[str, Any]`.
   - Mappe `ERR_HOST_CAPACITY_EXCEEDED` en code HTTP 400.
3. **Chemin 3 - Traitement automatique webhook Stripe** (`olympe/ops_manager.py:handle_stripe_webhook`) :
   - Dérive automatiquement les quotas via `get_quotas_for_tier(effective_tier_id)`.
   - Transmet les quotas stricts et capture `capacity_details` dans le journal d'audit en cas de refus.
4. **Nouvel Endpoint de Supervision Cockpit** (`GET /api/olympe/ops/host/capacity`) :
   - Expose en temps réel au cockpit la mémoire allouée, la mémoire disponible et le nombre de conteneurs clients actifs.

---

## 5. Intégrité de la Charte de Gouvernance du Fork

- **Sanctuaire (Zone A)** : `agent/`, `run_agent.py`, `conversation_loop.py`, `hermes_state*.py`, `providers/` sont **100% intacts** (0 modification).
- **Zone d'Évolution (Zone B)** : Toutes les modifications ont été cantonnées au périmètre superviseur d'Orso Agents (`olympe/`, `tests/olympe/`, `scripts/`).
- **Tests automatisés** : 92/92 tests unitaires et d'acceptation au vert (12 fichiers, 100% succès).
