# 21. Journal des realisations Orso Agents - Etat des lieux consolide

> **Date** : 13/09/2026 | **Redacteur initial** : Jarvis (PO) | **Revue technique** : Antigravity (Architecte Projet)  
> **Espace documentaire de reference** : [Confluence Orso-agents (Page 131600)](https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/131600)  
> **Ticket Jira associe** : [KAN-20](https://orso-agents.atlassian.net/browse/KAN-20)  
> **Statut** : Version 2 - Revue de l'architecte validee et consignee le 13/09/2026.

---

## 1. Pourquoi ce journal

Le projet Orso Agents a produit une matiere considerable entre le 26/08 et le 13/09/2026 (site vitrine, fork du moteur autonome, application cliente multi-agents, documentation strategique). Cependant, aucun document ne consolidait l'etat factuel de ce qui est reellement operationnel, ce qui a genere trois difficultes majeures :

1. Le rebranding Orso code le 07/09 a ete **annule par des reversions le 08/09** : une partie du travail existe dans l'historique git mais plus sur le site en ligne.
2. Le backend unifie du fork (`orso-core`) a ete initialise le 10/09, sans document decrivant ses composants ni son etat de demarrage.
3. L'Architecte et le Product Owner (Jarvis) avaient besoin d'une base factuelle partagee pour travailler de maniere fluide et eviter toute regression.

Ce journal comble ce vide en reliant les audits, la feuille de route et le backlog Jira KAN.

---

## 2. Methode et niveau de confiance

Les informations de ce document s'appuient sur :
- **Verifications directes en production** : etat HTTP du site Vercel, code brut servi, routage DNS.
- **Audit de la base de code git** : inspection des commits, des diffs et des arborescences de `orso-core`, `hermes-core-site` et `hermes-core`.
- **Tests automatises executes localement** : validation de l'API FastAPI et des modules de synchronisation.
- **Espace Confluence** : alignement sur l'espace documentaire souverain `https://orso-agents.atlassian.net/wiki/spaces/Orsoagents`.

---

## 3. Chronologie factuelle des livrables (20/08 - 13/09/2026)

| Date | Domaine | Livrable / Fait marquant | Preuve / Depot |
| :--- | :--- | :--- | :--- |
| **20/08** | Infra | Socle technique initial Docker pour l'agent de recouvrement | `hermes-core` |
| **24-26/08** | ERP | Analyse documentaire de 13 ERP et developpement de `balance_agee.py` & `import_csv.py` | `hermes-core` |
| **27-28/08** | Open Data | Script `fiche_credit.py` (Pappers) et `veille_bodacc.py` (BODACC/DILA) | `hermes-core` |
| **29/08** | Canaux | Passerelle Bot Telegram et canal WhatsApp Business | `hermes-core` |
| **30-31/08** | Vitrine | Portail vitrine sombre et tableau de bord de supervision Chart.js (`monitoring.html`) | `hermes-core-site` |
| **01/09** | PWA | Console multi-agents client PWA avec Service Worker (`sw.js`) | `App_Hermes-core` |
| **02-03/09** | Vitrine | Pages CGU, politique RGPD, tarifs avec simulateur et acces client Airtable | `hermes-core-site` |
| **04/09** | Vitrine | Mise en oeuvre des recommandations d'audit (P1, P2, P3) : CGV, page experts-comptables | `hermes-core-site` (commit `711a2b7`) |
| **07/09** | Vitrine | Rebranding complet du site en Orso Agents (`contact.html`, `vercel.json`, assets) | `hermes-core-site` (commit `9d6bbca`) |
| **08/09** | Vitrine | **Rollback d'urgence** : 3 reverts retablissant le site initial avant refonte tarifaire | `hermes-core-site` (commit `eeeef3d`) |
| **10/09** | Moteur | **Charte de Gouvernance du Fork** (Sanctuaire Zone A vs Zone B) et mandat de vigilance active | `orso-core` (commit `cbfb9b8`) |
| **10/09** | Moteur | **Backend unifie Orso agents** : 46 fichiers (moteur, profils, skills, Docker unifie) | `orso-core` (commit `066e039`) |
| **10/09** | DevOps | Pipeline de rapatriement continu et d'assainissement de competences (`sync-agent-skills`) | `orso-core` |
| **12/09** | Client | **Module UI Client (`apps/ui-client`)** : React/Vite + routeur FastAPI SSE/Actions (`client_ui.py`) | `orso-core` (11 tests unitaires valides) |
| **13/09** | Pilotage | Initialisation du backlog Jira KAN, gouvernance Confluence, spec KAN-4, ticket KAN-20 | Atlassian Cloud |
| **16/09** | Architecture | **Cadrage securite IAM & isolation multi-tenant** : arbitrage Supabase Auth, routage interne et creation du lot Jira KAN-26 a KAN-29 | Atlassian Jira / `orso-core` |
| **16/09** | Securite & E2E | **Association conteneur Financia Solutions & Validation Live** : instance Docker associee a Sophie Martin (DAF), guard JWT, streaming SSE avec Jerome (200 OK) et rejet cross-tenant prouve (403 Forbidden) | `orso-core` (Docker 9229/9300) |
| **16/09** | Architecture & IAM | **Aiguillage conteneurs Docker & Alerte Support** : enrichissement Supabase (`tenant_instances`, `support_alerts`), détection automatique de l'environnement cible, alerte critique et renvoi du message exact "Environnement non trouvé, le support Orso-agents est alerté" | `orso-core` / Supabase / OVH |
| **20/09** | Architecture & Ingress | **Industrialisation Routage Multi-Tenant (Option B - KAN-28)** : Choix de l'URL unique `app.orso-agents.fr`, Ingress dynamique Nginx Zero-Reload via résolveur Docker DNS (`127.0.0.11`), support complet streaming SSE sans buffering et WebSockets `/t/{slug}/ws` | `docker/ingress/` (`nginx.ingress.conf`) |
| **20/09** | Orchestration & Flotte | **Superviseur Olympe (Port 9230)** : Module de gestion de cycle de vie (`olympe/lifecycle_manager.py`) et serveur FastAPI (`olympe/server.py`) assurant le provisioning automatique, le réveil à la demande (*Wake-on-Demand*), la mise en veille (*Scale-to-Zero*) et la télémétrie consolidée | `olympe/`, `docker-compose.olympe.yml` (10 tests unitaires) |
| **20/09** | Client & Vitrine | **Unification de l'accès client** : UI PWA (`apps/ui-client`) adaptée au préfixe dynamique `/t/{tenant_slug}/` avec détection de réveil Olympe. Assainissement complet du site vitrine (`Site_Hermes-core/client.html`) : suppression définitive des mots de passe en clair / bypass POC, passage à Supabase IAM souverain et redirection unifiée | `apps/ui-client`, `Site_Hermes-core` |
| **23/09** | Exploitation & IAM | **Cockpit Orso Ops & IAM Superadmin (KAN-30)** : Déploiement en production sur `https://ops.orso-agents.fr`, grille tarifaire 99€/169€/279€ HT, feature gating des 4 agents avec périodes d'essai, authentification IAM Superadmin Supabase Auth avec écran de login dédié et résolution dynamique des emails clients. 20 tests unitaires passés à 100%. | `orso-core` / `ops.orso-agents.fr` |
| **25/09** | Client & Backoffice | **Raccordement dynamique des Interfaces & ERP au Backoffice Hermès (KAN-31)** : Remplacement intégral des métriques factices par un sondage temps réel de l'environnement (Pennylane, Sellsy, Odoo, Airtable, Supabase, Atlassian, Pappers, BODACC Open Data, outils natifs Web/Playwright, serveurs MCP). Statuts transparents (Connecté, En attente/Libre, Non configuré) et modale de paramétrage. 18 tests unitaires validés (100%), bundle PWA recompilé et déployé en direct sur le VPS de production (`prod-fr-002.orso-agents.fr`). Confluence Page 3964930. | `orso-core` (commit `7cab9dec28`, Docker 9229/9300, Jira [KAN-31](https://orso-agents.atlassian.net/browse/KAN-31)) |
| **25/09** | Client & Omnicanal | **Raccordement dynamique des Canaux de Discussion (WhatsApp, Telegram, Email) au Backoffice Hermès (KAN-32)** : Suppression définitive des numéros et compteurs de messages factices, sondage temps réel des passerelles (`TELEGRAM_BOT_TOKEN`, `WHATSAPP_TOKEN`, `SMTP_HOST`), modale de configuration et d'instructions détaillées, badges réels et gestion propre des accès autorisés. 19 tests unitaires validés (100%), déployé en direct sur le VPS de production (`prod-fr-002.orso-agents.fr`). Confluence Page 3997698. | `orso-core` (Docker 9229/9300, Jira [KAN-32](https://orso-agents.atlassian.net/browse/KAN-32)) |
| **25/09** | Exploitation & IAM | **Gestion Multi-utilisateurs par Client & Rôles Admin (KAN-32/Ops)** : Gestion de collaborateurs multiples par entreprise dans le Cockpit Ops (`https://ops.orso-agents.fr`) avec email (login), mot de passe sécurisé, rôle métier et switch Admin. Gating des onglets sensibles (*Interfaces & ERP*, *Canaux*) réservés aux administrateurs dans l'UI Client (`https://prod-fr-002.orso-agents.fr`), les collaborateurs standards étant restreints à l'espace *Discussion*. Migration SQL Supabase `04_add_profile_is_admin_and_multiuser.sql`, 41 tests unitaires au vert (100%), déployé sur le VPS OVH. | `orso-core` (Docker 9230/9229/9300) |
| **27/09** | Onboarding & Métier | **Souscription Souveraine & Calibration des Agents** : Migration SQL `06_onboarding_subscriptions_agent_calibration.sql` et fonction RPC PostgreSQL `07_rpc_submit_onboarding_order.sql`. Enregistrement atomique de l'organisation (`public.tenants`), de l'abonnement d'essai 30 jours (`public.subscriptions`), et des agents IA calibrés (`public.agent_instances`) avec lettres de mission personnalisées. | Supabase / `orso-site` |
| **27/09 - 28/09** | Paiement & IAM | **Tunnel d'Onboarding Public, Facturation Stripe Billing & Provisioning Administrateur** : Intégration de l'empreinte bancaire carte/SEPA (`/api/olympe/onboarding/init-setup`), création d'abonnement récurrent officiel 30j à 0 € dans Stripe (`/create-subscription`) et création/synchronisation automatique du compte administrateur dans Supabase Auth (`auth.users`) et `public.profiles` (`/create-admin-user`). Verrouillage strict de l'empreinte bancaire dans `onboarding.html` et remplacement des fichiers techniques par un récapitulatif exécutif clair. Déployé et validé en production sur le VPS OVH (`https://ops.orso-agents.fr`). 39 tests unitaires validés (100%). | `orso-core` / `ops.orso-agents.fr` / `orso-site` |
| **28/09** | Client & Facturation | **Page Paramètres UI Client, Gestion de Compte & Synchronisation Stripe Billing (KAN-33)** : Remplacement de l'ancienne modale factice par une page complète intégrée dans l'UI Client (`SettingsView.tsx`). Consultation des données de l'organisation et infrastructure souveraine, profil utilisateur avec modification sécurisée de mot de passe via Supabase Auth Admin (`PUT /auth/v1/admin/users/{id}`). Espace Abonnement & Facturation réservé aux administrateurs : consultation du forfait actif, mise à jour du moyen de paiement (session Stripe Customer Portal), changement de formule en 1-clic avec prorata Stripe, et historique des factures avec téléchargement direct en PDF officiel. 29 tests unitaires validés (100%), bundle Vite compilé. | `orso-core` (Docker 9229/9300, Jira [KAN-33](https://orso-agents.atlassian.net/browse/KAN-33)) |
| **28/09** | Automatisation & Sécurité | **Accès Drone de Test au Cockpit OPS & Sécurisation RBAC Sandbox (KAN-35)** : Implémentation du contrôle d'accès machine à moindre privilège pour le drone de test automatisé Client-X-Orso (`drone-clientx`). Authentification par jeton Bearer révocable, portées limitées (`tenants:read`, `tenants:provision:sandbox`, `tenants:teardown:sandbox`, `agents:write:sandbox`, `billing:read`, `webhooks:read`), whitelist stricte sur `clientx-orso` (rejet 403 hors sandbox), quotas explicites CPU (0.5) / RAM (512m), point de terminaison de destruction idempotent (zéro résidu), réception et journalisation des webhooks Stripe, et isolation étanche du compte client (`app.orso-agents.fr` OK, refus 403 sur OPS). Suite de 8 tests de conformité validée à 100% (`test_drone_access.py`), Confluence Page 4784130. | `orso-core` (Docker 9230, Jira [KAN-35](https://orso-agents.atlassian.net/browse/KAN-35)) |
| **30/09** | Sécurité Plateforme & Vitrine | **Sécurisation Vitrine Vercel, Purge des Secrets du POC & Rotation IAM Supabase (KAN-46)** : Retrait et purge Git complète du fichier `Secrets/secrets_poc.md` et du dossier `Secrets/` sur `tquinzain59/orso-site`. Durcissement Vercel (`.vercelignore` et `vercel.json`) avec blocage des documents techniques/SQL et redirections permanentes HTTP 308 de `admin.html` et `monitoring.html` vers `https://ops.orso-agents.fr`. Rotation d'urgence des 5 comptes démo Supabase Auth et testeur (`rotate_poc_credentials.py`) avec révocation des sessions et validation du rejet HTTP 400 des anciens mots de passe `[MOTS DE PASSE DÉMO RÉVOQUÉS]`. Script d'audit de non-régression local (`check_no_secrets.py`), suite de tests unitaires (`test_kan46_vitrine_security.py`) et workflows GitHub Actions quotidiens (06h UTC). Confluence Document 11 (ID 65838) et Document 14 (ID 229757) mis à jour. | `orso-core` / `orso-site` (Jira [KAN-46](https://orso-agents.atlassian.net/browse/KAN-46)) |
| **30/09** | Sécurité Dépôt Public & Hardening | **Assainissement Documentation Publique, Workflow Quotidien orso-core & Alignement main (KAN-49)** : Retrait de `HERMES_DASHBOARD_BASIC_AUTH_USERNAME="admin"` et du hash scrypt dans `docs/3_Technique/guides_de_configuration.md`, création du générateur sécurisé d'identifiants (`generate_dashboard_credentials.py`), déploiement du workflow GitHub Actions quotidien à 03h UTC sur `orso-core`, audit et clôture formelle de l'alerte Secret Scanning #1 (Bot Telegram Jérôme révoqué), et fusion complète de la branche de sécurité KAN-46 dans `main` comblant l'écart de 39 commits. | `orso-core` (Jira [KAN-49](https://orso-agents.atlassian.net/browse/KAN-49)) |
| **30/09** | Sécurité Cockpit OPS & IAM | **Auto-modification du Mot de Passe Superadmin en Libre-Service & Secours CLI (KAN-50)** : Rotation d'urgence immédiate du mot de passe superadmin (`admin@orso-agents.fr`). Implémentation du formulaire à 3 champs dans le Cockpit OPS (`AccountSecurityModal.tsx`), politique de complexité stricte (≥ 12 caractères, majuscule, minuscule, chiffre, symbole, non-trivial), stockage 100% hashé dans Supabase Auth (0ms sans redémarrage conteneur), invalidation immédiate de l'ancien token/session, protection anti-bruteforce (max 5 échecs / 15 min), journal d'audit sans secret en clair ni condensat (`ops_auth_audit.json`), script d'urgence CLI testé (`reset_superadmin_password.py`), et préservation absolue du Sanctuaire Orso (0 modif dans Zone A). 5 tests unitaires validés (100%). | `orso-core` (`olympe/`, `apps/ui-ops/`, Jira [KAN-50](https://orso-agents.atlassian.net/browse/KAN-50)) |
| **30/09** | Architecture & Distribution | **Distribution et Versionnement Immuable de l'Image Moteur (KAN-63)** : Formalisation de l'ADR 2026-09-30-04 et spécification technique complète du découpage en deux artefacts (moteur immuable vs espaces clients). Choix et justification économique du registre privé GHCR (< 5 €/mois) avec rejet motivé du build local sur hôte client (Option D). Implémentation du gestionnaire de distribution (`engine_image_manager.py`) avec épinglage obligatoire par digest SHA-256 (`@sha256:...`), outillage d'audit et détection de dérive multi-hôtes avec alerte immédiate, procédures écrites et rejouées de mise à jour et rollback, et audit de sécurité automatisé (`audit_zero_secrets_and_client_data.py`) garantissant des compteurs de secrets et données client strictement nuls. 5 tests unitaires validés (100%), 0 modification dans le Sanctuaire (Zone A). | `orso-core` (`docs/ADR/`, `scripts/distribution/`, `scripts/security/`, Jira [KAN-63](https://orso-agents.atlassian.net/browse/KAN-63)) |
| **30/09** | Architecture & Distribution Réelle | **Exécution Réelle de la Distribution Moteur & Validation Hôte Client (KAN-64)** : Livraison et audit du serveur client OVH `prod-fr-003.orso-agents.fr` (IP 57.131.196.106, Docker 29.8.1, swapfile 2 Go, SSH durci `PasswordAuthentication no`). Sondage réel des démons Docker multi-hôtes (`engine_image_manager.py probe`), détection dynamique d'écart de version (CA3), exécution rejouable de mise à jour et rollback avec sonde de santé (CA4). Audit de sécurité automatisé avec compteurs dynamiques calculés (CA5, 0 violation). Refus formel de provisioning sans digest valide (`ERR_DIGEST_REQUIRED`) et alignement canonique sur `ORSO_TARGET_ENGINE_DIGEST` dans `olympe/lifecycle_manager.py` (CA6). Workflow de publication GHCR (`publish_orso_engine.yml`) et script de publication (`build_and_publish_engine.py`). 4 nouveaux tests unitaires validés (100%). | `orso-core` (`scripts/distribution/`, `tests/distribution/`, Jira [KAN-64](https://orso-agents.atlassian.net/browse/KAN-64)) |
| **01/10** | Architecture & Exploitation Prod | **Arbitrage Provisioning Production (KAN-74) & Maintenance Flotte Prod (ops.orso-agents.fr / PROD-FR-003)** : Validation formelle par la Direction de l'Option B (délégation exclusive du provisioning à la voie machine hôte KAN-62/KAN-64 sur serveurs clients dédiés ; interdiction du provisioning in-process local sur l'Hôte 1). ADR 2026-10-01-05 et spécification technique associés. Déploiement et bascule en production du nouveau bundle UI Ops KAN-43 (`index-PyfyTnTH.js` / `index-Dsv2B0vU.css`) sur `ops.orso-agents.fr`. Rétablissement du jeton machine drone de test (`ORSO_DRONE_API_TOKEN`) en permissions `0600` et sourcing automatique sur `PROD-FR-003` et Hôte 1, validant l'accès aux journaux de livraison webhook pour Jarvis. | `orso-core` (`docs/ADR/`, `docs/3_Technique/`, Jira [KAN-74](https://orso-agents.atlassian.net/browse/KAN-74)) |

---

## 4. Etat par chantier

### A. Site vitrine (`Site_Hermes-core`, prive)
- **Operationnel** : Site statique heberge sur Vercel (`www.orso-agents.fr`), pages CGU, confidentialite, tarifs avec simulateur, client Airtable.
- **Sécurisation & Durcissement (30/09 - KAN-46)** : Purge définitive du document `Secrets/secrets_poc.md` et suppression des pages legacy `admin.html` et `monitoring.html` (redirigées en 308 vers `https://ops.orso-agents.fr`). Protection `.vercelignore` bloquant `docs/`, `Secrets/` et scripts SQL. Contrôle automatisé d'absence de secrets et workflow GitHub Actions quotidien.
- **Doctrine de reprise** : Reprise granulaire et securisee via les tickets `KAN-4` (rebranding propre sans alteration des tarifs), `KAN-5` (accueil), `KAN-6` (mentions legales) et `KAN-7` (tarifs arbitres).


### B. Fork du moteur (`orso-core`, public)
- **Architecture** : Base sur `NousResearch/hermes-agent` (MIT, commit `6e07eb4838`).
- **Zone A (Sanctuaire)** : 100 % intacte. Aucune logique metier dans les boucles d'inference, maintien strict du prompt caching.
- **Zone B (Evolution)** : Profils metiers (`profiles/jerome`), connecteurs (`skills/credit_management/`), routeur UI client (`hermes_cli/web_routers/client_ui.py`) et nouveau front `apps/ui-client`.
- **Gouvernance des sources** : Migration de la reference documentaire vers **Confluence** pour sortir les documents strategiques du depot public.

### C. Application cliente & PWA
- **Ancienne PWA (`Site_Hermes-core/app/`)** : Developpee pour dialoguer en direct avec 4 conteneurs Docker via WebSocket sur 4 ports distincts (`9229..9233`), tournant actuellement en fallback de simulation.
- **Nouveau module UI Client (`apps/ui-client`)** : Interface moderne connectee au backend unifie via SSE (`/api/client/chat/stream`) et REST (`/api/client/actions/execute`). Dotee d'un ecran d'authentification securise Supabase IAM, d'un bandeau de session "Financia Solutions • Sophie Martin (DAF)" et de boutons de demonstration / test cross-tenant.
- **Raccordement Backoffice Interfaces & ERP (25/09 - KAN-31)** : L'onglet Interfaces & ERP est raccordé directement au moteur Hermès via `_probe_hermes_backoffice_integrations` dans `client_ui.py`. Élimination complète des données factices (anciennes 284 factures inventées), détection automatique des clés réelles d'environnement (Pennylane, Sellsy, Odoo, Airtable, Jira/Atlassian, Supabase, Pappers, Google, Microsoft), intégration des outils natifs Hermès (navigateur Playwright, recherche Web, BODACC Open Data DILA, serveurs MCP). Ajout d'une modale de paramétrage avec bouton de synchronisation/test en direct et statuts transparents (🟢 Connecté, 🟡 En attente / Libre, ⚪ Non configuré). Spécification technique complète : `docs/3_Technique/spec_kan31_interfaces_erp_backoffice.md`. Déployé en production sur `prod-fr-002.orso-agents.fr`.
- **Raccordement Backoffice Canaux de Discussion (25/09 - KAN-32)** : L'onglet Canaux est également branché en direct sur le moteur Hermès via `_probe_hermes_backoffice_channels` dans `client_ui.py`. Suppression intégrale des faux numéros, faux contacts et compteurs simulés. Détection automatique des variables réelles d'environnement (`TELEGRAM_BOT_TOKEN`, `WHATSAPP_TOKEN`, `SMTP_HOST`), modale complète d'instructions d'activation (@BotFather, SMTP, WhatsApp Cloud) avec bouton de vérification de liaison, et gestion pérenne des utilisateurs autorisés par tenant/canal. Spécification technique : `docs/3_Technique/spec_kan32_canaux_messaging_backoffice.md`. Déployé en production sur `prod-fr-002.orso-agents.fr`.

### D. Telemetrie et Supervision
- `skills/telemetry.py` extrait les tokens et couts depuis `state.db` vers `telemetry_export.json`.
- `monitoring.html` pointe vers un tunnel Cloudflare expire et affiche des donnees simulees (`mockData`). Liaison directe a refactoriser sous forme de routeur dedie.

### E. Securite, Authentification & Isolation Multi-Tenant
- **Constat d'audit (16/09)** : Risque de « chateau de cartes » identifie : mots de passe en clair dans Airtable cote vitrine, et absence de filtrage sur `/api/client/` cote conteneur backend.
- **Doctrine et arbitrage** : Remplacement definitif d'Airtable par **Supabase Auth**, isolation stricte (1 conteneur Docker = 1 client unique multi-agents), routage interne unifie et guard de securite JWT sur `orso-core`.
- **Avancement du chantier (16/09)** :
  - **KAN-26** (IAM Supabase Auth) : Instance Supabase initialisee (`nyntmjorcqgbzaxszekk`), schema PostgreSQL deploye (tables `tenants`, `profiles`, `tenant_instances` avec RLS), comptes clients migres en direct.
  - **KAN-27** (Guard JWT & isolation tenant) : Guard memoire haute performance implemente (`client_jwt.py`), routes `/api/client/` verrouillees, 13 tests unitaires valides via `scripts/run_tests.sh`.
  - **Recette concrète Live (16/09)** : Conteneurs Docker (`orso_financia_backend` et `orso_financia_ui`) relies au tenant `financia-solutions`. Connexion de Sophie Martin valide en direct (HTTP 200), streaming temps reel avec l'agent Jerome fonctionnel, et rejet cross-tenant de Claire Dubois (CommerciaLink) prouve en direct (HTTP 403).
  - **KAN-28 (20/09 - Ingress Dynamique & Olympe Lifecycle)** : Arbitrage de l'Option B (URL unique `app.orso-agents.fr`), Ingress Nginx dynamique résolvant à chaud les conteneurs clients (`orso_client_{slug}`) via le DNS Docker interne (`127.0.0.11`), serveur Olympe (port 9230) pour le wake-on-demand/provisioning, UI PWA adaptée (`/t/{tenant_slug}/`) et assainissement complet de `client.html` sur la vitrine. Spécification détaillée : `docs/3_Technique/spec_kan28_ingress_olympe_lifecycle.md`. 27 tests unitaires passés à 100%.
  - **KAN-30 (21/09 - 23/09 - Cockpit Orso Ops, Stripe Billing & IAM Superadmin)** : Implémentation et déploiement en production du Cockpit d'Administration Opérations et Commercial hébergé sur le superviseur Olympe (port 9230) et routé sur **`https://ops.orso-agents.fr`**.
    - Gestion centralisée des clients (`public.tenants`), contacts DAF/dirigeants et suivi des conteneurs physiques de la flotte.
    - Résolution dynamique des emails réels des clients par interconnexion directe avec l'API Admin de Supabase (`/auth/v1/admin/users`).
    - Intégration de la grille tarifaire officielle : **Starter (1 agent - 99 € HT/m)**, **Duo (2 agents - 169 € HT/m)**, **Flotte Complète (4 agents - 279 € HT/m)** avec suivi du MRR, de l'ARR et réconciliation Stripe Billing / factures PDF.
    - Matrice de feature toggling des 4 agents (Jérôme, Lucas, Clara, Victor) avec activation en 1-clic et paramétrage de périodes d'essai temporaires (7j, 14j, 30j) répercutées instantanément sans redémarrage de conteneur.
    - **Sécurisation IAM Superadmin (`olympe/auth.py`)** : Authentification auprès de Supabase Auth avec vérification stricte du rôle `superadmin`, protection des endpoints `/api/olympe/ops/*` (rejet 401 sans jeton, rejet 403 pour compte client classique).
    - Application SPA React 19 / Vite / Tailwind CSS 4 (`apps/ui-ops`) avec écran de login dark theme (`LoginView.tsx`), mémorisation de session et profil admin dans la Navbar. Suite de 20 tests unitaires validée à 100% (`test_ops_auth.py`, `test_ops_manager.py`).
  - **KAN-30 / Onboarding (27/09 - 28/09 - Tunnel Public, Facturation Stripe Billing & Provisioning Administrateur)** :
    - Déploiement des endpoints publics sécurisés sur le superviseur Olympe : `/api/olympe/onboarding/init-setup` (génération de SetupIntent et client Stripe), `/api/olympe/onboarding/create-subscription` (30 jours d'essai à 0 € dans Stripe Billing), et `/api/olympe/onboarding/create-admin-user`.
    - Résolution de la création d'administrateur : provisionnement automatique dans `auth.users` et `public.profiles` avec rattachement immédiat au tenant, assignation du statut `is_admin=True` et `is_primary_contact=True`.
    - Sécurisation stricte du tunnel côté vitrine (`onboarding.html`) : interdiction de valider l'inscription sans confirmation d'empreinte bancaire par Stripe.
    - Évolution UX : suppression définitive du téléchargement des fichiers d'infrastructure (`soul.md`, `agent-config.json`) au profit d'un récapitulatif contractuel et exécutif de commande complet.
    - Déploiement validé en production sur le VPS OVH (`92.222.68.80` / `ops.orso-agents.fr`). 39 tests unitaires au vert (100%).
  - **KAN-33 (28/09 - Page Paramètres Client, Gestion de Compte & Synchronisation Stripe Billing)** :
    - Développement d'une vue complète `SettingsView.tsx` dans `apps/ui-client` avec 3 onglets thématiques : *Entreprise & Infrastructure*, *Mon Profil & Sécurité*, et *Abonnement & Facturation*.
    - Consultation des données légales de l'entreprise (Raison sociale, SIRET, SIREN, TVA, adresse) et de l'infrastructure souveraine (conteneur Docker dédié sur OVHcloud Gravelines en France).
    - Modification sécurisée du mot de passe collaborateur avec vérification de l'ancien mot de passe et mise à jour dans Supabase Auth (`PUT /auth/v1/admin/users/{id}`).
    - Section Facturation Stripe réservée aux administrateurs (`is_admin=True`, rejet HTTP 403 pour collaborateurs) : grille de modification d'abonnement (Starter 99€, Duo 169€, Trio 229€, Flotte Complète 279€ HT) synchronisée avec `TIER_STRIPE_PRICES`, ouverture du portail autonome Stripe (`/billing_portal/sessions`) pour mise à jour de la CB/SEPA, et téléchargement immédiat des factures en format PDF officiel.
    - Endpoints backend dédiés dans `hermes_cli/web_routers/client_ui.py`, 10 nouveaux tests unitaires au vert (100% sur `test_client_settings_billing.py` et 29/29 au global client).
  - **KAN-47 (28/09 - Correction Anomalie Onboarding : Alignement des Slugs d'Agents Officiels vs Rôles Techniques)** :
    - Résolution du bug où les nouveaux clients onboardés (ex: Nexis solutions) affichaient l'identifiant technique « recouvrement » (badge gris) dans le Cockpit Ops au lieu de « Jérôme » (badge bleu Crédit Manager).
    - Vitrine `onboarding.html` : Définition des dictionnaires `AGENT_SLUG_MAP` et `CATALOG_TYPE_MAP`, envoi systématique des slugs officiels (`jerome`, `lucas`, `clara`, `victor`) et du catalog_type conforme (`RECOUVREMENT`, `COMMERCIAL`, `SUPPORT_CLIENT`, `APPEL_OFFRES`).
    - PostgreSQL RPC `submit_onboarding_order` (`scripts/iam/07` et vitrine) : Normalisation défensive automatique à l'insertion et repli sur les noms de baptême officiels par défaut.
    - Superviseur Olympe (`olympe/ops_manager.py` & `olympe/onboarding_worker.py`) : Ajout de `normalize_agent_slug` / `normalize_agents_enabled` sur toutes les requêtes (KPIs, quotas, toggles), injection du prompt système de base dans le worker et auto-guérison silencieuse des données en base Supabase.
    - Cockpit Ops (`apps/ui-ops`) : Ajout de `getAgentMeta` et `AGENT_SLUG_ALIASES` dans `data.ts`, `TenantsView`, `TenantDetailModal`, `OnboardingView`, `OnboardingDetailModal` et `DashboardView`.
    - Script de migration rétroactive `scripts/iam/08_fix_agent_slugs_and_instances.sql`.
    - 61 tests unitaires validés (100%).
  - **KAN-33 (30/09 - Sécurité & Intégrité des Personas SOUL.md - Attaque CARBONATO)** :
    - Élimination de la faille d'écriture de persona : passage du montage Docker `./profiles` en lecture seule stricte (`:ro`) dans `docker-compose.orso.yml`, permission `root:root` et `0444` (`-r--r--r--`) sur tous les fichiers `SOUL.md` dans `Dockerfile.orso` et `docker/orso-entrypoint.sh`.
    - Manifeste cryptographique `profiles/personas.lock.json` recensant les empreintes SHA-256 des 4 agents (Jérôme, Lucas, Clara, Victor) et support de signature HMAC-SHA256 (`ORSO_PERSONA_HMAC_KEY`).
    - Contrôle d'intégrité au boot (`scripts/security/persona_integrity.py verify --fail-fast`) avec arrêt immédiat (Fail-Closed, code `PER-INTEGRITY-001`, exit code 1) en cas d'altération.
    - Surveillance périodique à l'exécution toutes les 5 minutes (`persona_integrity.py monitor`), déclenchement de l'événement critique `PER-INTEGRITY-002`, journalisation et arrêt d'urgence du conteneur en cas d'écart.
    - Hard-refusal dans les outils de manipulation de fichiers (`tools/file_tools_write_guards.py`) sur `profiles/` et `personas.lock.json`.
    - Journalisation probante d'intégrité dans `personas_integrity.log` / `telemetry_export.json` (`skills/telemetry.py`).
    - 7 tests unitaires et d'intégration validés à 100% (`tests/security/test_persona_integrity.py`), 0 secret détecté. Spécification publiée sur Confluence (page ID 5767169).


---


## 5. Cause des reversions du 08/09/2026

Le 08/09 au matin, trois commits de revert consecutifs ont annule la refonte du 04/09 et le rebranding du 07/09.
- **Cause identifiee** : La refonte poussee en bloc modifiait la strategie de prix (passage a 99EUR/169EUR, suppression des frais de setup de 1000EUR-3000EUR) et creait des pages partenaires (`experts-comptables.html`) sans validation formelle prealable du dirigeant Thibaut.
- **Decision** : Rollback de precaution indispensable pour preserver la coherence commerciale.
- **Consigne pour la suite** : Ne pas reprendre la refonte en bloc. Traiter chaque besoin par ticket unitaire et pull request avec revue PO.

---

## 6. Revue formelle de l'Architecte Projet (Section 7 - KAN-20)

### 7.1 Etat reel du moteur et du backend

1. **Le backend unifie d'orso-core demarre-t-il ?**  
   **[FONCTIONNEL & INACHEVE]** : Oui, le backend demarre parfaitement.  
   - Commande de test unitaire : `./scripts/run_tests.sh tests/hermes_cli/test_client_ui.py` (11 tests passes en 2,8s).  
   - Commande de lancement serveur : `.venv/bin/python3 -m hermes_cli.main dashboard --port 9119 --skip-build`.  
   - L'API FastAPI, le routeur client et les endpoints SSE sont operationnels ; l'etat est inacheve uniquement sur l'injection des cles d'API LLM de production dans `.env`.

2. **Le Sanctuaire (Zone A) est-il intact ?**  
   **[INTACT]** : Le Sanctuaire (`agent/turn_*.py`, `run_agent.py`, `conversation_loop.py`, `hermes_state*.py`, prompt caching, `providers/`, `tools/registry.py`) est **100 % intact** (zero alteration metier). Le fork est epingle au commit `6e07eb4838` (`v2026.9.7-638-g6e07eb4838`), et le rebase upstream est garanti sans conflit sur le coeur.

3. **Les connecteurs ERP : squelettes ou integrations testees ?**  
   **[SQUELETTES OPERATIONNELS & IMPORT CSV VALIDE]** : `balance_agee.py` implemente des requetes directes pour Sellsy, Sage, QuickBooks, Odoo et Dynamics (squelettes de requetage direct sans mocks de test en CI ni sandbox). Pennylane et Cegid ne sont **PAS** dans le code (etude documentaire uniquement). Le seul connecteur entierement teste et valide de bout en bout sur des jeux de donnees reels est l'**import universel CSV / Excel (`import_csv.py`)**.

4. **Skills pappers-api et open-data-entreprises :**  
   **[BODACC VALIDE / PAPPERS EN ATTENTE DE CLE]** : `open-data-entreprises` (BODACC / DILA via OpenDataSoft) est open data public, sans cle, teste et valide. `pappers-api` (`fiche_credit.py`) est code avec quotas documentes (+30 credits scoring), mais la cle `PAPPERS_API_TOKEN` **n'est pas configuree** dans `.env`.

5. **La telemetrie alimente-t-elle monitoring.html ?**  
   **[FAUX EN L'ETAT ACTUEL]** : Non. `skills/telemetry.py` genere un fichier local `telemetry_export.json`. `monitoring.html` pointant sur un tunnel Cloudflare inactif, il bascule systematiquement sur son generateur de simulation `mockData`.

6. **Dockerfile.orso et docker-compose.orso.yml :**  
   **[NON PUBLIEE]** : Le conteneur initial de base (aout 2026) a tourne sur VPS OVH. Les fichiers unifies `Dockerfile.orso` et `docker-compose.orso.yml` (backend 9229 + UI client 9300) ont ete ecrits le 10/09 mais **n'ont pas encore ete construits en recette ni publies** sur un registre (etape Jalon 7).

### 7.2 Etat reel de l'application cliente

7. **Liaison PWA et backend orso-core :**  
   **[RUPTURE DE PROTOCOLE & NOUVEAU MODULE UI CLIENT]** : L'ancienne PWA du site vitrine cherchait 4 websockets distincts sur 4 conteneurs (9229..9233). Le backend `orso-core` centralise tout sur le port 9229 via SSE (`/api/client/chat/stream`) et REST (`/api/client/actions/execute`). Un nouveau module client dedie React/Vite (`apps/ui-client`) a ete developpe le 12/09 pour s'y brancher nativement. Pour une recette de bout en bout de l'ancienne PWA : router vers le port unique 9229, desactiver le fallback de simulation, et injecter une cle LLM valide.

### 7.3 Processus et histoire

8. **Les trois reverts du 08/09 sur le site :**  
   **[REPRISE MODULAIRE PAR TICKET / PAS A L'IDENTIQUE]** : Rollback de precaution suite a des modifications de prix non validees (99EUR/169EUR) et a l'introduction de pages partenaires non arbitrees. Il ne faut **pas reprendre a l'identique**, mais derouler les tickets unitaires KAN-4, KAN-5, KAN-6 et KAN-7.

9. **Modele de travail doc 19 (`t-<ticket>`) :**  
   **[ACCEPTE A 100%]** : Accepte sans reserve (branches dediees, PR avec section Handoff, revue PO avant merge, zero commit direct sur main).

10. **Depot orso-core public et Confluence :**  
    **[CONFLUENCE REFERENCE UNIQUE / EXTRACTION STRATEGIQUE]** : La publicite du depot resulte du mecanisme de fork GitHub. **Confluence (`https://orso-agents.atlassian.net/wiki/spaces/Orsoagents`) devient la reference documentaire unique du projet.** Les documents strategiques internes (`docs/1_Strategique/`) doivent etre extraits du depot public.

### 7.4 Ce qu'il faut corriger dans ce journal

11. **Affirmations fausses ou realisations oubliees :**  
    **[3 REALISATIONS MAJEURES AJOUTEES]** :
    - Ajout du module **UI Client (`apps/ui-client`)** et son routeur SSE/Actions du 12/09.
    - Ajout du pipeline **DevOps de rapatriement continu (`sync-agent-skills`)** du 10/09.
    - Ajout de la **Charte de Gouvernance du Fork** du 10/09.
    - Rectification factuelle sur les connecteurs ERP (import CSV seul valide) et la telemetrie (actuellement simulee sur le site).

---

## 7. Regles de tenue du journal

- Une livraison significative = une ligne dans la chronologie avec sa preuve verifiable.
- Confluence est la source de verite documentaire ; les depots git conservent le code et la documentation technique d'architecture.
- Toute ligne marquee `[a confirmer]` doit etre traitee sous 7 jours ou convertie en ticket de backlog.
