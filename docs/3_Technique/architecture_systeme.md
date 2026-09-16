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

### B. Application Cliente Multi-Agents (`App_Hermes Core`)
* **Nature** : Single Page Application (SPA) transformable en Progressive Web App (PWA).
* **Conteneurisation** : Serveur Web Nginx/HTTP léger sur le port hôte `9300`.
* **Architecture JS (ES6 Modules)** :
  * `app.js` : Contrôleur principal et routage d'événements.
  * `agents.js` : Définition des profils des 4 agents (Jérôme, Lucas, Clara, Victor), couleurs d'accent, quick actions et compétences associées.
  * `gateway-client.js` : Client bi-mode gérant la connexion temps réel (WebSocket `ws://localhost:9229/ws` et HTTP REST) avec bascule automatique sur un simulateur réaliste en cas d'indisponibilité du conteneur.
  * `ui.js` : Rendu du chat, streaming mot à mot, cartes d'action interactives, modales et drawer de navigation.
  * `state.js` : Gestion de l'état persistant (LocalStorage : `ACTIVE_AGENT`, historique des conversations).
* **Déploiement Cloud** : Compatible Vercel (`vercel.json` configurant la réécriture des routes SPA).

### C. Portail Vitrine & Supervision (`Site_Hermes-core`)
* **Nature** : Site statique HTML5 / Tailwind CSS / Vanilla JS.
* **Tableau de Bord de Supervision (`monitoring.html`)** :
  * Intégration de **Chart.js** pour visualiser les courbes de requêtes et de dépenses en dollars.
  * Double alimentation des données : interrogation de l'API de télémétrie locale/distante (`http://localhost:9120`) avec mécanisme de fallback automatique sur données de simulation réalistes.

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
