# Architecture Système Multi-Niveaux

Ce document détaille l'infrastructure technique globale de l'écosystème Hermès, la topologie des conteneurs Docker, l'architecture de l'application cliente PWA et les schémas de données.

---

## 1. Topologie Globale des Conteneurs et des Flux

L'architecture repose sur trois briques logicielles découplées et interconnectées via un réseau Docker bridge (`hermes_network`) :

```
┌────────────────────────────────────────────────────────────────────────┐
│                              HÔTE DOCKER                                │
│                                                                        │
│   ┌───────────────────────────┐      ┌───────────────────────────────┐ │
│   │   App_Hermes Core (PWA)   │      │    hermes-core (Backend)      │ │
│   │   - Container:            │      │    - Container:               │ │
│   │     app_hermes_core       │      │      hermes_recouvrement_agent│ │
│   │   - Port: 9300:80         │      │    - Port: 9229:9119          │ │
│   │   - PWA / Service Worker  │      │    - Python 3.11 / LLM Engine │ │
│   └─────────────┬─────────────┘      └───────────────▲───────────────┘ │
│                 │                                    │                 │
│                 │ (WebSocket / REST : Port 9229)     │                 │
│                 └────────────────────────────────────┘                 │
│                                                      ▲                 │
│   ┌───────────────────────────┐                      │                 │
│   │     Site_Hermes-core      │                      │                 │
│   │   - Vitrine / Vidéos      │                      │                 │
│   │   - Monitoring (Chart.js) ├──────────────────────┘                 │
│   │   - Admin (Port 80/Vercel)│ (Télémétrie HTTP / JSON Export)        │
│   └───────────────────────────┘                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Spécifications Techniques des Composants

### A. Moteur Backend (`hermes-core`)
* **Image Docker** : Python 3.11 sur base Linux allégée.
* **Ports** : `9229:9119` (port interne 9119 redirigé sur 9229 de l'hôte).
* **Volumes Persistants** :
  * `./config` : `hermes.yaml` (modèles, identité, passerelles).
  * `./skills` (Lecture seule `:ro`) : Scripts de compétences Python (`balance_agee.py`, `veille_bodacc.py`, etc.).
  * `./data` : Base SQLite locale et exports de télémétrie (`telemetry_export.json`).
* **Moteur LLM** : Passerelle OpenRouter (modèle `deepseek/deepseek-v4-flash` à basse température `0.2`).

### B. Application Cliente Multi-Agents (`apps/ui-client` PWA)
* **Nature** : Single Page Application (SPA) / Progressive Web App (PWA) développée en React 19, TypeScript, Vite et Tailwind CSS.
* **Conteneurisation** : Serveur Web Nginx léger sur le port hôte `9300` montant le bundle compilé (`dist/`).
* **Architecture Front-End** :
  * `App.tsx` : Contrôleur global, détection de session JWT, gestionnaire de tabs unifiés.
  * **Onglet Discussion (`ChatView.tsx`)** : Dialogue multi-agents (Jérôme, Lucas, Clara, Victor), streaming Server-Sent Events (SSE) mot-à-mot via `/api/client/chat/stream`, cartes d'action interactives (`ActionCard.tsx`).
  * **Onglet Interfaces & ERP (`IntegrationsView.tsx` - KAN-31)** : Restitution en direct de l'état des connecteurs métiers et outils natifs, modale de configuration et de synchronisation temps réel.
  * **Onglet Canaux (`ChannelsView.tsx` - KAN-32)** : Supervision omnicanale (Telegram, WhatsApp, Email, Slack, Discord), modale guidée pas-à-pas et gestion de whitelist `allowedUsers`.
* **Endpoints Backend Associés** (`hermes_cli/web_routers/client_ui.py`) :
  * `POST /api/client/chat/stream` (Streaming SSE)
  * `GET /api/client/integrations` (Sondage dynamique ERP & MCP)
  * `POST /api/client/integrations/{key}/sync` (Test de synchronisation)
  * `GET /api/client/channels` (Sondage dynamique des passerelles de messagerie)
  * `POST /api/client/channels/{id}/allowed-users` (Gestion whitelist utilisateurs autorisés)
  * `POST /api/client/actions/execute` (Exécution d'arbitrages in-chat)

### C. Portail Vitrine & Espace Public (`Site_Hermes-core`)
* **Nature** : Site statique HTML5 / Tailwind CSS / Vanilla JS hébergé sur Vercel.
* **Supervision & Télémétrie** : Intégration de Chart.js pour le monitoring des consommations LLM.

---

## 3. Base de Données d'État Locale (`state.db`)

Hermès Core utilise **SQLite** pour sa persistance d'état locale (située dans `hermes_home_dot_hermes/profiles/jerome/state.db`) :

* **Table `sessions`** : Identifiant de session, début, messages d'erreurs éventuels (`handoff_error`, `compression_failure_error`).
* **Table `messages`** : Tous les messages échangés par rôle (`user`, `assistant`, `tool`), indexés par des tables virtuelles SQLite FTS5 (`messages_fts`) pour permettre des recherches instantanées par mots-clés.
* **Table `session_model_usage`** : Suivi rigoureux de l'inférence :
  * `input_tokens` et `output_tokens`
  * `api_call_count`
  * `actual_cost_usd` et `estimated_cost_usd`
  * `last_seen` (timestamp de dernière activité)

---

## 4. Architecture IAM & Isolation Multi-Tenant (KAN-26 à KAN-29)

Depuis le 16/09/2026, l'accès client et l'hébergement des agents obéissent à un partitionnement strict :

1. **Fournisseur d'Identité Souverain (IAM Supabase Auth - KAN-26)** :
   * Remplacement total du stockage Airtable par PostgreSQL managé (Supabase Auth).
   * Mots de passe chiffrés Argon2id, Row-Level Security (RLS) étanche, émission de JWT signés enrichis de claims de tenant (`tenant_id`, `tenant_slug`, `role`, `agents`).
   * Spécification détaillée : `docs/3_Technique/spec_kan26_iam_supabase_auth.md`.
2. **Guard d'Authentification sur le Backend (`orso-core` - KAN-27)** :
   * Validation cryptographique du JWT sur `/api/client/` dans FastAPI.
   * Vérification de correspondance entre le `tenant_id` du jeton et `ORSO_CLIENT_ID` du conteneur.
3. **Topologie 1 Client = 1 Conteneur Dédié (Multi-Agents - KAN-28)** :
   * Chaque client dispose d'une instance conteneurisée isolée avec ses propres volumes SQLite `state.db` et ses secrets ERP.
   * Routage interne unifié via Reverse Proxy Ingress aiguillant vers le bon conteneur.
4. **Cinématique SSO et Session Sécurisée (KAN-29)** :
   * Passage de session fluide et sans fuite de token entre le portail Vercel et l'interface applicative client (`apps/ui-client`).

---

## 5. Cockpit Orso Ops & IAM Superadmin (KAN-30)

Déployé sur le port 9230 (serveur Olympe) et accessible via `https://ops.orso-agents.fr`, le Cockpit d'Administration centralise la supervision technique, commerciale et financière :
* **Authentification IAM Superadmin (`olympe/auth.py`)** : Vérification stricte du rôle `superadmin` dans Supabase Auth, protection des endpoints `/api/olympe/ops/*`.
* **Résolution Dynamique des Utilisateurs** : Interrogation directe de l'API Supabase Admin pour faire correspondre les identifiants techniques avec les emails réels des clients.
* **Pilotage Financier & Feature Toggling** : Gestion des abonnements (Starter 99 € HT, Duo 169 € HT, Flotte Complète 279 € HT), activation des agents et périodes d'essai à chaud.

---

## 6. Vérité Terrain & Raccordement Dynamique du Backoffice (KAN-31 & KAN-32)

Afin d'éradiquer les métriques factices et d'offrir une transparence absolue, l'interface client interroge dynamiquement le backoffice Hermès :

### A. Raccordement des Interfaces & ERP (KAN-31)
* **Routeur Backend** : Fonction de sonde `_probe_hermes_backoffice_integrations` dans `hermes_cli/web_routers/client_ui.py`.
* **Périmètre d'inspection** :
  * Variables d'environnement pour ERP (`PENNYLANE_API_KEY`, `SELLSY_TOKEN`, `ODOO_URL`, `AIRTABLE_API_KEY`, `ATLASSIAN_DOMAIN`, `SUPABASE_URL`, `PAPPERS_API_KEY`).
  * Outils natifs intégrés : recherche Web, navigateur Chromium Playwright, Open Data BODACC / DILA via compétence `consulter-bodacc-creditsafe`.
  * Déclaration des serveurs MCP dans `config/hermes.yaml`.
* **Statuts affichés** : `Connecté` (vert), `En attente / Libre` (jaune), `Non configuré` (gris neutre).

### B. Pilotage Omnicanal des Messageries (KAN-32)
* **Routeur Backend** : Fonction de sonde `_probe_hermes_backoffice_channels` dans `hermes_cli/web_routers/client_ui.py`.
* **Périmètre d'inspection** :
  * Variables d'environnement de passerelles (`TELEGRAM_BOT_TOKEN`, `WHATSAPP_TOKEN`, `SMTP_HOST` / `RESEND_API_KEY`, `SLACK_BOT_TOKEN`, `DISCORD_BOT_TOKEN`).
* **Contrôle d'accès & Whitelists** : Stockage persistant des utilisateurs autorisés (`allowedUsers`) par canal pour filtrer les accès non sollicités.
* **Badge Moteur Hermès Gateway** : Restitution temps réel de l'état opérationnel de la passerelle.

---

## 7. Préservation du Sanctuaire (Charte de Gouvernance du Fork)

Toutes les évolutions des chantiers KAN-30, KAN-31 et KAN-32 respectent scrupuleusement la règle de vigilance active :
* **Sanctuaire Inviolé** : Aucun composant du cœur d'inférence (`agent/`, `conversation_loop.py`, `run_agent.py`, `hermes_state*.py`, prompt caching) n'a été altéré.
* **Zone d'Évolution** : Tous les enrichissements sont cantonnés aux routeurs FastAPI (`hermes_cli/web_routers/client_ui.py`) et à l'application PWA cliente (`apps/ui-client/`).

