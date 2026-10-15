# Spécification Technique & Handoff : Source de Vérité Unique du Cockpit OPS (KAN-43)

**Auteur** : @Developpeur (Orso Agents)  
**Date** : 01/10/2026  
**Référence Jira** : [KAN-43](https://orso-agents.atlassian.net/browse/KAN-43)  
**Branche** : `KAN-43-source-de-verite-cockpit-ops`  
**Statut** : Validé / Prêt pour fusion  

---

## 1. Contexte & Constat Initial Vérifié

Lors de la qualification de l'accès Drone (ticket KAN-35, cas CA1 : lecture de la flotte) le 28/09/2026 et de la préparation du POC le 30/09/2026 :
* L'appel `GET /api/olympe/ops/tenants` renvoyait 6 clients codés en dur (`financia-solutions`, `commercialink`, `helpdesk360`, `batipro-services`, `eurotech-conseil`, `nexis-solutions`) issus de la méthode `_init_seed_data()` de `olympe/ops_manager.py`.
* Les indicateurs consolidés (`GET /api/olympe/ops/stats`) et la facturation (`GET /api/olympe/ops/invoices`) puisaient dans ce même dictionnaire d'amorçage.
* Le mode démonstration s'activait implicitement sans configuration explicite dès lors que Supabase n'était pas configuré ou hors production, et la variable `APP_ENV=production` présente dans `docker-compose.olympe.yml` n'était pas vérifiée par `is_production()`.
* L'interface web du Cockpit OPS (`apps/ui-ops`) n'affichait aucun signal visuel lorsque le mode démonstration était actif.

### Impact opérationnel & de gouvernance
1. Toute validation effectuée par le Cockpit en production n'avait aucune valeur légale ou technique (lecture de SIRETs et données inventés).
2. La création d'un tenant réel en base n'était pas immédiatement reflétée si un jeu de mock parasitait les requêtes.
3. Le tenant de test drone `clientx-orso` était sujet à des 404 lors des croisements.
4. Les mesures de charge du POC du 30/09/2026 étaient ininterprétables sans une source de vérité assainie.

---

## 2. Décisions d'Architecture & Règles Inviolables

Conformément aux directives du PO et à la **Charte de Gouvernance du Fork Orso** :

### Règle 1 — Source de Vérité Unique en Base de Données
* En production, la flotte, les profils, les abonnements, les indicateurs et les factures proviennent **strictement de PostgreSQL (Supabase)**.
* Zéro client d'amorçage et zéro jeu résiduel en mémoire pour la flotte, les indicateurs et la facturation issus de la base (`olympe/ops_manager.py`). La télémétrie (`olympe/telemetry_client.py`) a conservé des valeurs de repli après KAN-43 ; elles sont retirées par KAN-73 (voir §5, qui énumère ce qui est retiré et ce qui reste). Si la base est saine mais vide, la réponse est une liste vide (`[]`). Si la base est inaccessible, défaillante ou non configurée en production, l'API applique un **Fail-Closed strict** et retourne un statut **HTTP 503 (Service Unavailable)**, interdisant tout affichage silencieux trompeur de 0€ MRR.

### Règle 2 — Activation Explicite et Refus Inconditionnel du Mode Démo en Prod
* Le mode démonstration ne s'active **JAMAIS par défaut**. Il requiert impérativement la configuration explicite `ORSO_DEMO_MODE=1` (ou `demo_mode=True`).
* En production (`is_production() == True`), la présence de `ORSO_DEMO_MODE=1` lève immédiatement une exception fatale bloquante (`RuntimeError`), interdisant au conteneur ou au serveur de démarrer.
* La détection de production couvre l'ensemble des variables canoniques de l'infrastructure : `ORSO_ENV`, `APP_ENV`, `ENVIRONMENT`, `ENV`.

### Règle 3 — Signalement Visuel Obligatoire dans le Cockpit OPS (UI)
* Lorsque le mode démonstration est actif (hors production), l'API retourne `"demo_mode": true`.
* L'interface web `apps/ui-ops` affiche immédiatement :
  1. Une **bannière supérieure d'alerte** permanente : `⚠️ MODE DÉMONSTRATION ACTIF — Les données affichées proviennent d'un jeu d'amorçage simulé en mémoire et non de la base de production`.
  2. Un badge contrasté `MODE DÉMO` dans le header `Navbar` (remplaçant le badge `Live DB`).
  3. Un avertissement contextuel dans la section KPIs du `DashboardView`.

### Règle 4 — Sanctuaire Upstream 100% Intouché
* La boucle d'exécution de l'agent, le cache de prompt et les connecteurs modèles ne subissent aucune altération.
* Toutes les modifications se concentrent sur la couche Olympe (`olympe/ops_manager.py`, `olympe/telemetry_client.py`), l'interface (`apps/ui-ops/`) et la suite de tests (`tests/olympe/`).

---

## 3. Matrice de Preuves Formelles (Handoff)

L'ensemble des critères d'acceptation du ticket KAN-43 est couvert par des tests unitaires et d'intégration automatisés dans `tests/olympe/test_kan43_kan44_acceptance.py`.

### Critère 1 : Aucun client fictif renvoyé par les routes du cockpit en production
* **Test** : `test_kan43_ca1_no_mock_tenants_in_production`
* **Preuve** :
  - Avec une base vide, `get_tenants_overview()` renvoie strictement `[]` (0 client).
  - Avec un client réel `Entreprise Réelle SAS` (`entreprise-reelle`), la liste contient exactement 1 client, et aucun des 6 mocks (`financia-solutions`, `commercialink`, etc.) n'apparaît.
* **Statut** : **PASSÉ** (0.01s).

### Critère 2 : Créer un client en base le rend visible dans le cockpit sans redémarrage
* **Test** : `test_kan43_ca2_db_client_reflected_immediately_without_restart`
* **Preuve** :
  - Appel 1 : 1 client constaté en base (`premier-client`).
  - Insertion dynamique en base d'un second client (`second-client-nouveau`).
  - Appel 2 immédiat sans redémarrage : 2 clients constatés avec leurs caractéristiques exactes.
* **Statut** : **PASSÉ** (0.01s).

### Critère 3 : Les indicateurs et la facturation se recalculent depuis la base
* **Test** : `test_kan43_ca3_metrics_and_billing_recalculated_from_db`
* **Preuve** :
  - Lecture initiale : client Starter 1 agent -> `mrr_ht = 99.00 €`, `active_subscribers = 1`.
  - Mise à jour en base vers le forfait Flotte Complète 4 agents (279.00 €).
  - Deuxième lecture : `mrr_ht = 279.00 €`, recalculé instantanément depuis la base de données.
  - En production, `list_all_invoices()` ne renvoie aucune facture fictive d'amorçage.
* **Statut** : **PASSÉ** (0.01s).

### Critère 4 : Le mode démonstration est refusé en production et signalé dans l'interface
* **Test** : `test_kan43_ca4_demo_mode_safety_locks`
* **Preuve** :
  - Avec `ORSO_ENV=production` et `ORSO_DEMO_MODE=1` : `RuntimeError` bloquant levé.
  - Avec `APP_ENV=production` et `ORSO_DEMO_MODE=1` : `RuntimeError` bloquant levé.
  - Hors production avec `ORSO_DEMO_MODE=1` : `GET /api/olympe/ops/stats`, `GET /api/olympe/ops/tenants` et `GET /api/olympe/ops/invoices` renvoient `"demo_mode": true`.
  - En mode standard (`demo_mode=False`) : les routes renvoient `"demo_mode": false`.
  - Frontend `apps/ui-ops` : composants `Navbar.tsx`, `App.tsx` et `DashboardView.tsx` compilés avec succès (`npm run build --workspace=@orso/ui-ops` : 178ms, 0 avertissement bloquant).
* **Statut** : **PASSÉ**.

---

## 4. Résultats de la Suite Complète Olympe

Exécution via le script d'isolation canonique du projet :
```console
$ scripts/run_tests.sh tests/olympe/
=== Summary: 9 files, 66 tests passed, 0 failed (100% complete) in 13.0s (20 workers) ===
```
* `tests/olympe/test_kan43_kan44_acceptance.py` : 9/9 validés.
* `tests/olympe/test_drone_access.py` : 10/10 validés.
* `tests/olympe/test_ops_manager.py` : 11/11 validés.
* `tests/olympe/test_lifecycle_manager.py` : 10/10 validés.
* `tests/olympe/test_ops_auth.py` : 6/6 validés.
* `tests/olympe/test_stripe_onboarding.py` : 7/7 validés.
* `tests/olympe/test_ops_password_change.py` : 5/5 validés.
* `tests/olympe/test_ovh_client.py` : 5/5 validés.
* `tests/olympe/test_onboarding_worker.py` : 3/3 validés.

---

## 5. Rectificatif KAN-73 — Télémétrie : replis retirés et état réel du code

**Date** : 15/10/2026 — **Base vérifiée** : `c13b03698c` (`main`, qui contient `cc9ed937bf`, dernier commit KAN-43). Le SHA du commit KAN-73 est celui de `git log -1 --format=%H -- docs/3_Technique/spec_kan43_source_de_verite_cockpit_ops.md` ; le SHA déployé est consigné dans le ticket KAN-73 après déploiement.

**Phrase corrigée** : la phrase de la Règle 1 affirmait « zéro fallback de données fictives » pour l'ensemble de la couche Olympe. C'était inexact pour `olympe/telemetry_client.py`, qui rendait encore des valeurs fabriquées (voir ci-dessous). Elle est désormais limitée à la base, et renvoie à ce paragraphe.

### 5.1 État avant KAN-73 (après KAN-43, `cc9ed937bf`)

| Repli dans `olympe/telemetry_client.py` | Statut au 15/10/2026 avant KAN-73 |
|---|---|
| `"simulated": True`, `display_name: "PROD-FR-002"`, `"Up 6 hours (healthy)"` | Déjà retirés par `679f529c44` (KAN-43). |
| Marqueur `"simulated": False` dans le résumé d'indisponibilité, métriques à `0`/`0.0` | Présents. |
| Agents synthétisés depuis les conteneurs Docker (`status: "active"`, compteurs à 0, IP `127.0.0.1`) | Présents. |
| Valeurs par défaut `"Agent"`, `"générique"`, `status: "active"`, compteurs à 0, signes vitaux à `0.0`, IP hôte | Présentes. |
| Nom `Agent #<id>` dans l'historique | Présent. |
| Alertes `[]` quand la collecte est coupée (« Fallback simulation propre ») | Présent : une collecte coupée se lisait « aucune alerte ». |
| Mesures Docker à `0` quand les statistiques échouent | Présentes. |
| Valeurs par défaut de tenant `"Services Financiers"`, `"Starter (1 agent)"` | Présentes. |

### 5.2 Retiré par KAN-73

* Tout marqueur de simulation, tout agent synthétisé depuis Docker, toute valeur par défaut de statut, de nom, de module, de compteur, de coût, d'IP, de signe vital ou de tenant.
* Collecte coupée ou réponse illisible : les routes `GET /api/olympe/ops/telemetry/{summary,environments,history/{id},alerts}` répondent `200` avec `connected: false`, `status: "unknown"`, `error: "telemetry_unavailable"`, un `message` lisible et `last_valid_at` (horodatage de la dernière réponse valide du processus, `null` s'il n'y en a pas). Les champs de mesure (`environments`, `alerts`, `snapshots`, `count`, métriques du résumé) sont `null` ou absents, jamais `0` ni `[]`.
* Une mesure non obtenue vaut `null` (`status` de l'agent : `"unknown"`).
* Cockpit (`apps/ui-ops`) : bannière « État inconnu », KPI masqués, `n/a` pour toute mesure absente ; l'écran ne casse pas.

### 5.3 Ce qui reste (limites connues)

* Une liste `[]` n'est rendue que si la collecte a répondu et n'a rien signalé.
* Les routes de télémétrie répondent `200` même collecte coupée (le champ `connected` porte l'information) ; le `503` de la Règle 1 ne concerne que la base.
* Le filtre de l'ancien agent de test « Recouvrement » (`agent_id == 3`, `recouvrement_default`) et le rattachement au tenant `financia-solutions` pour les modules « recouvrement » sont conservés (hors périmètre KAN-73).
* La lecture de base en échec qui rend `200` avec une flotte vide sur les routes du cockpit, la purge de la base de production (KAN-71) et la distinction des clients sandbox restent hors périmètre.
* Question ouverte (décideur : Thibaut) : inconnu seul, ou dernier état connu horodaté. Implémenté : inconnu, avec l'horodatage de la dernière mesure valide à côté (recommandation du ticket).

### 5.4 Commande de contrôle

```console
$ grep -n -i -E "simulat|PROD-FR-002|Up [0-9]+ hours|healthy|Agent #|127\.0\.0\.1" olympe/telemetry_client.py
$ echo $?
1
```
Garde-fou automatisé : `tests/olympe/test_kan73_telemetry_no_fabrication.py`.
