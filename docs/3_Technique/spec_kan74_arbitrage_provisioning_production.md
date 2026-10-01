# Spécification Technique & Architecture : Arbitrage Provisioning Production (KAN-74)

- **Ticket Jira** : [KAN-74](https://orso-agents.atlassian.net/browse/KAN-74) (Priorité Bloquante)
- **Épiques de Référence** : [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62) (POC 2 Artefacts), [KAN-44](https://orso-agents.atlassian.net/browse/KAN-44) (Tunnel Abonnement)
- **Décision d'Architecture** : ADR 2026-10-01-05 (Option B validée par Thibaut Quinzain)
- **Statut** : Documenté & Prêt pour Implémentation

---

## 1. Contexte & Problématique

En production sur le superviseur Olympe (`ops.orso-agents.fr` / Hôte 1 `92.222.68.80`), Olympe s'exécute au sein du conteneur `olympe_core`. 
En l'absence du binaire `docker` dans ce conteneur :
- Les méthodes de `olympe/lifecycle_manager.py` (get_tenant_status, wake_tenant, suspend_tenant, provision_tenant) dérivent sur `simulated: True`.
- Lors d'appels de provisioning ou d'événements Stripe, un statut `actif` ou `pret` risquait d'être inscrit en base alors qu'aucun conteneur n'était instancié.

L'arbitrage formel validé acte que :
1. Le superviseur Olympe n'héberge pas de conteneurs clients sur l'Hôte 1.
2. Les conteneurs clients sont exécutés sur les hôtes dédiés (ex: `PROD-FR-003`), distribués via GHCR privé et gérés par la chaîne d'outillage de flotte (`engine_image_manager.py`).
3. Olympe doit afficher une lucidité absolue sur ses capacités réelles et refuser formellement d'enregistrer des états de succès simulés en base.

---

## 2. Déclinaison des 5 Critères d'Acceptation (CA1 à CA5)

### CA1 : Lucidité de la Santé Superviseur (`GET /api/olympe/health`)
- L'endpoint `/api/olympe/health` reflète directement l'accès réel au démon Docker (`shutil.which("docker") is not None` et ping démon).
- En l'absence d'accès local :
  - `docker_available: false`
  - `fleet_mode: "delegated_host_provisioning"`
  - `status: "operational_management_plane"`
- Aucune ambiguïté : un auditeur ou le PO (Jarvis) sait immédiatement que ce superviseur ne pilote pas de conteneurs locaux directs.

### CA2 : Aucun État "Actif" ou "Prêt" Écrit en Base sur Branche Simulée
- Si une requête de provisioning ou de réveil arrive sur la voie in-process sans accès conteneur réel, **aucune mutation vers `status = 'pret'` ou `environment_status = 'actif'` n'est autorisée dans `tenant_instances`**.
- La tentative est inscrite avec l'état `pending_provisioning` ou `failed_no_docker_access` avec journalisation explicite.

### CA3 : Refus Explicite et Journalisé de Création Impossible
- La méthode `provision_tenant()` de `DockerLifecycleManager` refuse l'opération si `not self.has_docker` en production, retournant un statut d'échec contractuel :
  ```json
  {
    "success": false,
    "status": "unsupported_in_process",
    "error_code": "ERR_NO_LOCAL_DOCKER_DELEGATED_HOST_REQUIRED",
    "message": "Le provisioning direct in-process n'est pas supporté sur cet hôte. Le déploiement doit être délégué à l'hôte client dédié."
  }
  ```
- Un événement d'audit est consigné dans `_audit_log`.

### CA4 : Mode Nommé dans Toutes les Réponses de Cycle de Vie
Toutes les réponses des routes de cycle de vie (`status`, `wake`, `suspend`, `provision`) explicitent leur mode opératoire :
- `mode`: `"simulated"` (ou `"delegated_host"`) lorsque l'action n'a pas pu être exécutée sur un démon Docker réel.
- `action_taken`: `false`.
- `reason`: description textuelle claire.

### CA5 : Rapprochement Formel dans le Document d'Architecture du POC
- L'ADR [`docs/ADR/2026-10-01-05-arbitrage-provisioning-production-kan74.md`](file:///Users/tquinzain/Documents/Dev%20Projects/orso-core/docs/ADR/2026-10-01-05-arbitrage-provisioning-production-kan74.md) et la présente spécification nomment sans équivoque le composant de provisioning en production :
  - **Composant de Provisioning Client Réel** : `scripts/distribution/engine_image_manager.py` / Orchestrateur de Flotte GHCR sur les serveurs clients dédiés (Hôte 2 `PROD-FR-003`).
  - **Rôle d'Olympe (Hôte 1)** : Plan de Gestion, IAM, Cockpit OPS, Enregistrement des commandes, Supervision et Facturation Stripe.
