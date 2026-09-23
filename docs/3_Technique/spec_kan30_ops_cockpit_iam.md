# Spécification Technique d'Architecture : Cockpit Orso Ops, Facturation Stripe & Authentification IAM Superadmin

> **Ticket Jira associé** : [KAN-30](https://orso-agents.atlassian.net/browse/KAN-30)  
> **Composants** : `Orso Ops Cockpit (apps/ui-ops)`, `Olympe Ops Core (olympe/)`, `Supabase Auth IAM`, `Orso Ingress Nginx`  
> **Statut** : Validé et Déployé en Production (`https://ops.orso-agents.fr`)  
> **Auteur / Responsable d'instruction** : Antigravity (Architecte Projet)  
> **Validation Métier & Décision** : Thibaut QUINZAIN (Direction Orso Agents)  
> **Date** : 23 Septembre 2026  

---

## 1. Contexte & Problématique Métier

Avec le passage à l'exploitation commerciale multi-tenant (KAN-28, Option B), la gestion des clients et le pilotage des souscriptions nécessitaient une interface d'administration souveraine et centralisée :

1. **Visibilité sur les organisations clientes** : Consulter en temps réel les organisations créées (`public.tenants`), leurs contacts dirigeants/DAF (`public.profiles`) et leurs conteneurs Docker dédiés.
2. **Suivi financier et abonnements Stripe** :
   - Grille tarifaire officielle validée :
     - **Starter (1 agent)** : 99 € HT / mois
     - **Duo (2 agents)** : 169 € HT / mois
     - **Flotte Complète (4 agents)** : 279 € HT / mois
   - Calcul automatique du MRR HT, MRR TTC et ARR HT avec réconciliation des factures Stripe payées.
3. **Pilotage granulaire des agents & périodes d'essai (Feature Gating)** :
   - Activation / désactivation à la demande des 4 agents de la suite : **Jérôme** (Recouvrement), **Lucas** (Commercial), **Clara** (Support/SAV) et **Victor** (Marchés Publics).
   - Déclenchement de périodes d'essai gratuites (7j, 14j, 30j) sans carte bancaire, avec propagation instantanée sans redémarrage de conteneur.
4. **Sécurité et étanchéité absolue (IAM Superadmin)** :
   - Le cockpit ne doit en aucun cas être accessible à un utilisateur client régulier.
   - Contrôle d'accès strict via Supabase Auth basé sur le rôle `superadmin` vérifié par jeton JWT.

---

## 2. Architecture Globale

```
                         ┌────────────────────────────────────────────────────────┐
                         │                 NAVIGATEUR ADMINISTRATEUR              │
                         │              (https://ops.orso-agents.fr)              │
                         └───────────────────────────┬────────────────────────────┘
                                                     │
                                                     ▼
                         ┌────────────────────────────────────────────────────────┐
                         │                  ORSO INGRESS (Nginx)                  │
                         │          Virtual Host: ops.orso-agents.fr              │
                         │            Certificat SSL Let's Encrypt                │
                         └───────────────────────────┬────────────────────────────┘
                                                     │ Proxy HTTP vers port 9230
                                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 SUPERVISEUR OLYMPE (Port 9230)                                  │
│                                                                                                 │
│  ┌───────────────────────────────┐     ┌─────────────────────────────────────────────────────┐  │
│  │   SPA React 19 Orso Ops       │     │  FastAPI Ops & IAM Routers (olympe/server.py)       │  │
│  │   (apps/ui-ops/dist)          │     │  - /api/olympe/ops/auth/login, /me, /logout         │  │
│  │   - LoginView (Dark theme)    │◄────┤  - /api/olympe/ops/stats (MRR, KPIs, forfaits)      │  │
│  │   - Dashboard KPIs & MRR      │     │  - /api/olympe/ops/tenants (annuaire & instances)   │  │
│  │   - Annuaire & fiches clients │     │  - /api/olympe/ops/tenants/{id}/agents (toggles)    │  │
│  │   - Matrice 4 agents & trials │     │  - /api/olympe/ops/invoices (historique factures)   │  │
│  │   - Supervision Flotte Olympe │     │  - Dépendance de sécurité : require_superadmin      │  │
│  └───────────────────────────────┘     └──────────────────────────┬──────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┼─────────────────────────────┘
                                                                    │
                                    ┌───────────────────────────────┴─────────────────────────────┐
                                    ▼                                                             ▼
                    ┌───────────────────────────────┐                             ┌───────────────────────────────┐
                    │      SUPABASE POSTGRESQL      │                             │        STRIPE BILLING         │
                    │  - auth.users (Admin API)     │                             │  - Produits & Tarifs          │
                    │  - public.tenants             │                             │  - Subscriptions & Webhooks   │
                    │  - public.tenant_instances    │                             │  - Invoices & PDF téléchargeables
                    │  - public.profiles            │                             └───────────────────────────────┘
                    └───────────────────────────────┘
```

---

## 3. Spécifications Techniques des Composants

### 3.1 Authentification & Contrôle d'Accès IAM (`olympe/auth.py`)
* **Authentification Supabase** :
  - `authenticate_superadmin(email, password)` : Appelle `POST /auth/v1/token?grant_type=password` avec la clé de service.
  - Contrôle strict : vérifie que `app_metadata.role == "superadmin"` ou `user_metadata.role == "superadmin"`.
  - Rejet en **HTTP 401 Unauthorized** si identifiants invalides.
  - Rejet en **HTTP 403 Forbidden** si le compte existe mais n'a pas les droits superadmin.
* **Validation de Session JWT** :
  - `verify_superadmin_token(token)` : Interroge `GET /auth/v1/user` avec le bearer token pour valider l'intégrité et l'expiration de la session.
* **Dépendance FastAPI** :
  - `require_superadmin` : Intercepte les requêtes avec header `Authorization: Bearer <token>`, protège toutes les routes `/api/olympe/ops/*`.

### 3.2 Résolution des Utilisateurs & Emails (`olympe/ops_manager.py`)
* Les emails des utilisateurs ne sont pas stockés dans `public.profiles` mais dans `auth.users`.
* La méthode `_fetch_supabase_auth_users()` utilise l'API Admin Supabase (`GET /auth/v1/admin/users`) via `SUPABASE_SERVICE_ROLE_KEY` pour constituer une table de correspondance dynamique `user_id -> email`.
* Lors de la génération de la vue des tenants, chaque profil de contact est automatiquement complété avec son email réel.

### 3.3 Endpoints API Olympe (`olympe/server.py`)
* **Routes publiques / Auth** :
  - `POST /api/olympe/ops/auth/login` : Délivre le jeton JWT superadmin.
  - `GET /api/olympe/ops/auth/me` : Renvoie les informations du profil administrateur connecté.
  - `POST /api/olympe/ops/auth/logout` : Clôture de la session.
* **Routes d'exploitation protégées (`require_superadmin`)** :
  - `GET /api/olympe/ops/stats` : KPIs consolidés (MRR global, répartition par palier, taux d'adoption des agents).
  - `GET /api/olympe/ops/tenants` : Liste complète des clients inscrits avec instances et contacts.
  - `GET /api/olympe/ops/tenants/{tenant_id}` : Fiche détaillée d'une organisation.
  - `POST /api/olympe/ops/tenants/{tenant_id}/agents` : Modification instantanée des agents actifs (`jerome`, `lucas`, `clara`, `victor`) et paramétrage des périodes d'essai (`trials`).
  - `POST /api/olympe/ops/tenants/{tenant_id}/subscription` : Mise à jour du palier tarifaire Stripe (99€, 169€, 279€ HT).
  - `GET /api/olympe/ops/invoices` : Historique des factures émises.
* **Webhooks & Santé** :
  - `POST /api/olympe/ops/webhooks/stripe` : Réception des événements Stripe Billing (non soumis au JWT).
  - `GET /health` & `GET /api/olympe/health` : État de santé de base d'Olympe.

### 3.4 Interface Frontend SPA « Orso Ops » (`apps/ui-ops/`)
* **Stack technique** : React 19, TypeScript, Vite 8, Tailwind CSS 4, Lucide Icons.
* **Composants d'interface** :
  - `LoginView.tsx` : Écran de connexion soigné dark theme, formulaire email/password avec mémorisation de session.
  - `DashboardView.tsx` : Cartes métriques financières, jauges de déploiement des agents.
  - `TenantsView.tsx` : Recherche instantanée, filtres statut, boutons de réveil direct conteneur.
  - `TenantDetailModal.tsx` : Panneau de contrôle client avec switchs ON/OFF pour chaque agent et sélecteur de période d'essai (7j, 14j, 30j).
  - `BillingView.tsx` : Suivi des forfaits et des factures téléchargeables.
  - `FleetView.tsx` : Supervision physique des conteneurs isolés sur `orso_network`.
  - `Navbar.tsx` : Profil superadmin avec affichage de l'email et bouton de déconnexion.

---

## 4. Respect Inviolable de la Charte de Gouvernance du Fork

Cette réalisation respecte rigoureusement la **Charte de Gouvernance du Fork** (`docs/3_Technique/charte_gouvernance_fork.md`) :
* **Sanctuaire (Zone A) 100% Inviolé** : Le cœur de l'agent (`orso-core`, `agent/turn_*.py`, `conversation_loop.py`, `run_agent.py`, prompt caching) ne contient **aucune ligne de code relative à la facturation, aux forfaits ou à l'administration**.
* **Zone d'Évolution (Zone B)** :
  - Olympe (`olympe/`) agit en tant que superviseur et plan de contrôle externe (Control Plane).
  - Les conteneurs clients lisent uniquement leurs habilitations transmises par le jeton JWT (`agents_enabled`), garantissant une isolation totale entre plan de gestion et plan d'exécution.

---

## 5. Validation, Tests & Déploiement Production

### 5.1 Suite de Tests Automatisés
Exécution via `scripts/run_tests.sh tests/olympe/` :
* **20/20 tests passés au vert (100%)** en 1,4s :
  - `tests/olympe/test_ops_auth.py` : Tests de connexion, rejets 401/403, protection FastAPI.
  - `tests/olympe/test_ops_manager.py` : Calculs MRR, grille 99€/169€/279€, feature gating des agents.
  - `tests/olympe/test_lifecycle_manager.py` : Wake-on-demand et cycle de vie Docker.

### 5.2 Déploiement en Production (`92.222.68.80`)
* **Sous-domaine dédié** : `https://ops.orso-agents.fr` configuré avec Nginx reverse proxy et certificat SSL Let's Encrypt.
* **Comptes Superadmin provisionnés** :
  - `admin@orso-agents.fr`
  - `tquinzain@gmail.com`
* **Vérification Live** : Rejet 401 sur requêtes anonymes, connexion superadmin validée en HTTPS, consultation des clients et des métriques de flotte opérationnelle.
