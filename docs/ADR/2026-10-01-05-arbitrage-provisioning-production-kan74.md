# ADR 2026-10-01-05 : Arbitrage du Mode de Provisioning des Environnements Clients en Production (KAN-74)

- **Date** : 1er octobre 2026
- **Statut** : **Accepté et Validé par Thibaut Quinzain (Direction / Lead)**
- **Auteurs** : Antigravity (Architecte Système & Ops), Thibaut Quinzain (Lead / PO Orso)
- **Référence Documents** : Confluence Document 27 (Architecture 2 Artefacts & Séparation des Plans), Document 06 (Architecture Système), ADR 2026-09-30-04 (Distribution Image Moteur GHCR)
- **Tickets Jira associés** : [KAN-74](https://orso-agents.atlassian.net/browse/KAN-74) (Bloquant résolu), [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62) (Épique POC), [KAN-58](https://orso-agents.atlassian.net/browse/KAN-58) à [KAN-64](https://orso-agents.atlassian.net/browse/KAN-64) (Distribution Hôte Réel), [KAN-44](https://orso-agents.atlassian.net/browse/KAN-44) (Garde Webhook & Provisioning)

---

## 1. Contexte & Problématique (Constat KAN-74)

Le superviseur Olympe (port 9230) hébergé sur le serveur VPS OVH Hôte 1 (`92.222.68.80`) s'exécute dans un conteneur Docker isolé (`olympe_core`). 
Deux voies de gestion de conteneurs coexistaient historiquement :
1. **La voie historique in-process du superviseur** (`olympe/lifecycle_manager.py`) : conçue initialement pour piloter directement des conteneurs locaux sur la machine exécutant Olympe via `/var/run/docker.sock`.
2. **La voie machine hôte du POC / Distribution réelle** ([KAN-62](https://orso-agents.atlassian.net/browse/KAN-62) / [KAN-64](https://orso-agents.atlassian.net/browse/KAN-64)) : conçue pour la topologie de production multi-serveurs où les espaces clients sont exécutés sur des hôtes dédiés étanches (ex: `PROD-FR-003` / `57.131.196.106`), totalement séparés de la machine de gestion et de supervision.

Le ticket [KAN-74](https://orso-agents.atlassian.net/browse/KAN-74) a mis en lumière une ambiguïté bloquante :
- En l'absence du binaire `docker` dans le conteneur `olympe_core`, la voie in-process basculait silencieusement en mode simulé (`simulated: True`), renvoyant un statut trompeur `ready` / `success: True`.
- En conséquence, un abonnement pouvait être considéré comme provisionné alors qu'aucun conteneur physique n'avait été déployé.
- Un arbitrage formel devait donc trancher : soit installer le binaire Docker CLI dans `olympe_core` pour activer le pilotage Docker local sur l'Hôte 1, soit acter que la création des conteneurs clients en production est formellement déléguée à la voie machine hôte / orchestrateur de flotte.

---

## 2. Décision d'Architecture Validée

> **Décision Formelle (Option B validée le 01/10/2026 par Thibaut Quinzain)** :
> **Le provisioning physique des conteneurs clients en production est EXCLUSIVEMENT DÉLÉGUÉ à la voie machine hôte du POC / orchestrateur de flotte multi-serveurs (Épique KAN-62, scripts de distribution KAN-64 sur hôtes clients PROD-FR-003, etc.).**
> **Le provisioning in-process local depuis le conteneur Olympe sur l'Hôte 1 est FORMELLEMENT PROSCRIT en production.**

### Justification de l'Arbitrage :

1. **Respect de l'Isolation des Plans (Plan de Gestion vs Plan de Données Clients)** :
   Conformément au Document 27 (section 4) et à l'ADR 2026-09-30-04, les espaces conteneurisés des clients ne doivent **jamais résider sur l'hôte qui héberge Olympe et les chaînes de build**. Installer le binaire Docker dans `olympe_core` sur l'Hôte 1 aurait réintroduit l'exécution client sur le serveur de gestion, créant une régression architecturale majeure.

2. **Sécurité & Réduction de la Surface d'Attaque** :
   Monter `/var/run/docker.sock` avec un binaire Docker complet dans un conteneur web exposé (`olympe_core`) constitue un vecteur critique d'élévation de privilèges root sur l'Hôte 1. L'Option B maintient le superviseur Olympe sans privilèges root sur l'hôte.

3. **Immuabilité & Épinglage Cryptographique par Digest (GHCR)** :
   La voie hôte (scripts KAN-64 / `engine_image_manager.py`) impose un épinglage strict par digest SHA-256 (`ghcr.io/tquinzain59/orso-engine@sha256:...`) et un contrôle de conformité sans dérive (`is_drift_detected: false`), ce que la voie in-process locale ne garantissait pas.

---

## 3. Conséquences Techniques & Alignement des Contrats Olympe (KAN-74)

Pour répondre aux 5 critères d'acceptation de [KAN-74](https://orso-agents.atlassian.net/browse/KAN-74) :

### CA1 : Lucidité de la Santé Superviseur (`GET /api/olympe/health`)
- La sonde `/api/olympe/health` reflète l'accès réel au démon local : `docker_available: false` sur l'hôte de gestion.
- L'attribut `fleet_mode: "delegated_host_provisioning"` confirme explicitement que le superviseur n'opère pas de conteneurs en local, éliminant toute confusion.

### CA2 : Interdiction d'Écriture d'États Fictifs en Base
- Si une opération de cycle de vie in-process est invoquée sur un superviseur sans démon Docker, elle est déclarée non exécutée.
- **Aucun statut `pret` ni `actif` n'est persisté dans `tenant_instances`**. Le statut demeure `pending_setup` ou `provisioning_failed` avec le motif explicite `ERR_NO_LOCAL_DOCKER_DELEGATED_HOST_REQUIRED`.

### CA3 : Refus Explicite et Journalisé de Création Impossible
- Toute tentative de provisioning in-process local en production sans accès conteneur produit un refus immédiat (`HTTP 400` / `HTTP 503` ou statut `unsupported`), consigné dans les logs d'audit avec l'erreur `ERR_IN_PROCESS_PROVISIONING_PROHIBITED`.

### CA4 : Mode Explicite Nommé dans Toutes les Routes de Cycle de Vie
- Les 4 routes `/api/olympe/tenants/status/{slug}`, `/wake/{slug}`, `/suspend/{slug}` et `/provision` portent explicitement le champ `mode: "simulated"` (ou `mode: "delegated_host"`) et `action_taken: false` si le démon local est indisponible.

### CA5 : Documentation & Rapprochement des Deux Voies
- Le présent ADR et la spécification technique associée ([`docs/3_Technique/spec_kan74_arbitrage_provisioning_production.md`](file:///Users/tquinzain/Documents/Dev%20Projects/orso-core/docs/3_Technique/spec_kan74_arbitrage_provisioning_production.md)) font autorité pour le pilotage de la flotte Orso Agents.
