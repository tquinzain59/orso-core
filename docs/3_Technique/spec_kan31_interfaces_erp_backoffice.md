# Spécification Technique d'Architecture : Raccordement Dynamique des Interfaces & ERP au Backoffice Hermès

> **Ticket Jira associé** : [KAN-31](https://orso-agents.atlassian.net/browse/KAN-31)  
> **Page Confluence de référence** : [Confluence Orso-agents (Page 3964930)](https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/3964930)  
> **Composants** : `UI Client (apps/ui-client)`, `Routeur FastAPI Client (hermes_cli/web_routers/client_ui.py)`, `Outils Hermès & MCP`, `Moteur Hermès Agent`  
> **Statut** : Validé et Déployé en Production (`https://prod-fr-002.orso-agents.fr` / VPS OVH `92.222.68.80`)  
> **Auteur / Responsable d'instruction** : Antigravity (Architecte Projet)  
> **Validation Métier & Décision** : Thibaut QUINZAIN (Direction Orso Agents)  
> **Date** : 25 Septembre 2026  

---

## 1. Contexte & Problématique Métier

Dans l'application cliente PWA d'Orso Agents (`apps/ui-client`), l'onglet **Interfaces & ERP** permet aux directions financières, dirigeants et équipes de suivre et gérer l'interconnexion de leur assistant autonome avec leurs outils quotidiens.

### Constat initial
L'écran présentait auparavant des compteurs et états purement statiques et simulés :
- Chiffres de facturation arbitraires (*"284 factures (142 580 €)"* pour Pennylane, *"152 factures (89 200 €)"* pour Sellsy).
- Délais et historiques de synchronisation fictifs (*"Il y a 10 min"*, *"Il y a 1h"*).
- Absence de visibilité sur les outils réels mis à disposition par le moteur Hermès (recherche web, navigateur autonome Playwright, compétences installées, serveurs MCP).

### Objectif d'alignement & de transparence
Raccorder l'intégralité de la vue sur l'état **réel et vérifié** du conteneur client :
1. **Élimination totale des données factices** : suppression de tous les volumes ou montants inventés.
2. **Sondage dynamique de l'instance Hermès** : inspection en temps réel de l'environnement (`os.environ`, `.env`, `config.yaml`), des compétences chargées et des serveurs MCP déclarés.
3. **Statuts honnêtes et exploitables** :
   - `Connecté (Backoffice)` : la clé d'API ou le service est actif et joignable.
   - `En attente / Libre` : service accessible en Open Data (sans clé requise) ou en attente d'appairage utilisateur.
   - `Non configuré` : clé API absente, avec mention explicite de la variable d'environnement ou de la configuration attendue.
4. **Capacité de test & d'explication** : mise à disposition d'une modale guidant le paramétrage et permettant de déclencher un test de liaison en direct.

---

## 2. Architecture Globale

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                NAVIGATEUR CLIENT PWA                                   │
│                        (https://prod-fr-002.orso-agents.fr)                            │
│                                                                                        │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                        Onglet 'Interfaces & ERP'                               │   │
│   │  - Filtres : Tous | Facturation & ERP | Messageries | Données Légales | MCP    │   │
│   │  - Badges réels : Connecté (Backoffice) | En attente / Libre | Non configuré   │   │
│   │  - Modale de paramétrage : Variables d'environnement & fichiers cibles         │   │
│   │  - Bouton d'action 'Tester la connexion / Synchroniser'                        │   │
│   └───────────────────────────────────────┬────────────────────────────────────────┘   │
└───────────────────────────────────────────┼────────────────────────────────────────────┘
                                            │ Requêtes HTTP REST
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        ORSO REVERSE PROXY NGINX (Port 9300 / 9229)                     │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ /api/client/integrations
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                    CONTENEUR BACKEND HERMES (orso_client_backend)                      │
│                                                                                        │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │       FastAPI Routeur Client UI (hermes_cli/web_routers/client_ui.py)           │   │
│   │       - GET /api/client/integrations                                           │   │
│   │       - POST /api/client/integrations/{id}/sync                                │   │
│   └───────────────────────┬────────────────────────────────────────────────────────┘   │
│                           │                                                            │
│                           ▼                                                            │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │           Sondeur Dynamique Hermès (_probe_hermes_backoffice_integrations)      │   │
│   │                                                                                │   │
│   │   ├── Environnement (.env / os.environ)                                        │   │
│   │   │   ├── PENNYLANE_API_KEY, SELLSY_TOKEN, ODOO_URL                            │   │
│   │   │   ├── SUPABASE_URL, ATLASSIAN_DOMAIN, AIRTABLE_API_KEY                     │   │
│   │   │   └── PAPPERS_API_KEY, GOOGLE_WORKSPACE, MICROSOFT_365                     │   │
│   │   │                                                                            │   │
│   │   ├── Compétences & Outils Système                                             │   │
│   │   │   ├── Compétence 'consulter-bodacc-creditsafe' (BODACC / DILA Open Data)   │   │
│   │   │   ├── Navigateur Playwright (browser_navigate)                             │   │
│   │   │   └── Moteur de Recherche Web (web_search)                                 │   │
│   │   │                                                                            │   │
│   │   └── Configuration Hermès (config.yaml)                                       │   │
│   │       └── Serveurs MCP configurés (mcp_servers)                                │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Détails d'Implémentation

### 3.1 Backend FastAPI (`hermes_cli/web_routers/client_ui.py`)

1. **Sondage dynamique du backoffice (`_probe_hermes_backoffice_integrations`)** :
   - Analyse les variables de configuration sans jamais exposer les secrets en clair côté client.
   - Restitue pour chaque connecteur :
     - `status` : `'connected'` (si clé présente ou outil actif), `'pending'` (si Open Data ou liaison partielle), ou `'not_configured'`.
     - `syncStatus` : `'success'`, `'idle'` ou `'offline'`.
     - `accountDetails` : information contextuelle non sensible (ex: `"URL: https://... (configuré)"` ou `"Requiert PENNYLANE_API_KEY"`).
     - `metrics` : descriptif d'exploitation vérifié (ex: *"Sonde BODACC & annonces collectives active (Open Data DILA / OpenDataSoft)"*, *"Playwright Chromium headless actif"*).
     - `configKey` : variable d'environnement ou bloc de configuration requis pour faciliter le diagnostic.

2. **Connecteurs sondés** :
   | ID Connecteur | Catégorie | Pré-requis de détection | Statut si configuré |
   | :--- | :--- | :--- | :--- |
   | `pennylane` | billing | `PENNYLANE_API_KEY` | `connected` |
   | `sellsy` | crm | `SELLSY_TOKEN` ou `SELLSY_API_KEY` | `connected` |
   | `odoo` | billing | `ODOO_URL` ou `ODOO_HOST` | `connected` |
   | `airtable` | crm | `AIRTABLE_API_KEY` | `connected` |
   | `atlassian` | tools | `ATLASSIAN_DOMAIN` / `JIRA_API_TOKEN` | `connected` |
   | `supabase` | tools | `SUPABASE_URL` | `connected` |
   | `pappers` | legal | `PAPPERS_API_KEY` | `connected` |
   | `bodacc` | legal | Skill `consulter-bodacc-creditsafe` | `connected` (ou `pending` via DILA direct) |
   | `google_workspace`| comms | `GOOGLE_WORKSPACE_CREDENTIALS` | `connected` |
   | `microsoft_365` | comms | `MICROSOFT_365_TOKEN` | `connected` |
   | `hermes_browser` | tools | Outil natif `browser_navigate` | `connected` |
   | `hermes_websearch`| tools | Outil natif `web_search` | `connected` |
   | `mcp_*` | tools | Entrées déclarées dans `config.yaml` (`mcp_servers`) | `connected` |

3. **Synchronisation et test en direct (`_sync_tenant_integration`)** :
   - Route `POST /api/client/integrations/{integration_id}/sync` :
     - Vérifie la présence des identifiants réels.
     - Met à jour l'état de synchronisation en mémoire (`_SYNC_OVERRIDES`).
     - Renvoie un accusé de réception précis (`success=True`, horodatage ISO, message d'état clair).

---

### 3.2 Frontend PWA (`apps/ui-client`)

1. **Modèle de données & typage (`src/types/index.ts`)** :
   - Extension du type `IntegrationCategory` : `'all' | 'billing' | 'comms' | 'legal' | 'crm' | 'tools'`.
   - Ajout du champ optionnel `configKey?: string`.

2. **Purge des fausses données (`src/lib/data.ts`)** :
   - Remplacement des 284 factures et métriques factices par des descripteurs honnêtes.
   - Valeurs de repli transparentes indiquant la nécessité de renseigner les clés dans l'environnement d'exploitation.

3. **Interface utilisateur (`src/pages/IntegrationsView.tsx`)** :
   - **Cartouche d'état Moteur** : affiche la liaison temps réel avec l'instance Hermès locale.
   - **Badges de statut explicites** :
     - 🟢 `Connecté (Backoffice)`
     - 🟡 `En attente / Libre`
     - ⚪ `Non configuré`
   - **Modale de Détails & Guide de Configuration** :
     - Affiche la variable d'environnement exacte ou le fichier cible (`.env` ou `config/hermes.yaml`).
     - Donne les instructions pas-à-pas pour obtenir la clé et recharger le conteneur.
     - Fournit le bouton d'action *"Tester la connexion / Synchroniser"* avec spinner et confirmation toast.

---

## 4. Conformité avec la Charte de Gouvernance du Fork

Cette évolution respecte rigoureusement la **Charte de Gouvernance Fork Orso** (`docs/3_Technique/charte_gouvernance_fork.md`) :
- **Le Sanctuaire (Zone A - Inviolable)** :
  - `agent/turn_*.py`, `run_agent.py`, `conversation_loop.py` : **Aucune altération**.
  - Persistance (`hermes_state*.py`) : **Aucune altération**.
  - Cache de prompt et modèles (`providers/`, `tools/registry.py`) : **Invariance absolue préservée**.
- **La Zone d'Évolution (Zone B - Périmètre Orso)** :
  - Routeurs d'API : `hermes_cli/web_routers/client_ui.py`.
  - Interface cliente : `apps/ui-client`.
  - Tests associés : `tests/hermes_cli/test_client_ui.py`.

---

## 5. Recette & Déploiement

### 5.1 Tests Automatisés
- Exécution de la suite de tests unitaires via `./scripts/run_tests.sh` :
  - `tests/hermes_cli/test_client_ui.py` : **18/18 tests passés (100% green)** en 3.1s.
  - `tests/hermes_cli/test_client_environment_routing.py` : **3/3 tests passés (100% green)**.
- Compilation de l'interface cliente :
  - `npm run build` dans `apps/ui-client` : **100% réussi sans avertissement ni erreur**.

### 5.2 Déploiement en Production (VPS OVH `92.222.68.80`)
1. **GitHub** : Commit `7cab9dec28` poussé sur la branche `feature/ops-admin-cockpit` du dépôt `origin`.
2. **Synchronisation Serveur** : `git pull origin feature/ops-admin-cockpit` exécuté en Fast-forward dans `/home/ubuntu/orso-core`.
3. **Conteneurs Docker** :
   - `docker compose -f docker-compose.orso.yml restart orso-backend orso-ui-client` exécuté.
   - `orso_client_backend` : **Up (healthy)** sur le port 9229.
   - `orso_client_ui` : **Up** sur le port 9300.
4. **Contrôle en direct** :
   - Accès HTTPS public vérifié sur `https://prod-fr-002.orso-agents.fr`.
   - Nouveau bundle Vite `index-DkebWEHV.js` actif et servi avec succès.
