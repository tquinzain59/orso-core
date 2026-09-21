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

---

## 4. Etat par chantier

### A. Site vitrine (`Site_Hermes-core`, prive)
- **Operationnel** : Site statique heberge sur Vercel (`www.orso-agents.fr`), pages CGU, confidentialite, tarifs avec simulateur, client Airtable.
- **Reliquats de marque** : Presence residuelle du terme "hermes" sur plusieurs pages (ex: `client.html`, `monitoring.html`). Page `/contact.html` en 404 suite au revert.
- **Doctrine de reprise** : Reprise granulaire et securisee via les tickets `KAN-4` (rebranding propre sans alteration des tarifs), `KAN-5` (accueil), `KAN-6` (mentions legales) et `KAN-7` (tarifs arbitres).

### B. Fork du moteur (`orso-core`, public)
- **Architecture** : Base sur `NousResearch/hermes-agent` (MIT, commit `6e07eb4838`).
- **Zone A (Sanctuaire)** : 100 % intacte. Aucune logique metier dans les boucles d'inference, maintien strict du prompt caching.
- **Zone B (Evolution)** : Profils metiers (`profiles/jerome`), connecteurs (`skills/credit_management/`), routeur UI client (`hermes_cli/web_routers/client_ui.py`) et nouveau front `apps/ui-client`.
- **Gouvernance des sources** : Migration de la reference documentaire vers **Confluence** pour sortir les documents strategiques du depot public.

### C. Application cliente & PWA
- **Ancienne PWA (`Site_Hermes-core/app/`)** : Developpee pour dialoguer en direct avec 4 conteneurs Docker via WebSocket sur 4 ports distincts (`9229..9233`), tournant actuellement en fallback de simulation.
- **Nouveau module UI Client (`apps/ui-client`)** : Interface moderne connectee au backend unifie via SSE (`/api/client/chat/stream`) et REST (`/api/client/actions/execute`). Desormais dotee d'un ecran d'authentification securise Supabase IAM, d'un bandeau de session "Financia Solutions • Sophie Martin (DAF)" et de boutons de demonstration / test cross-tenant.

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
  - **KAN-30 (21/09 - Cockpit Orso Ops, Stripe Billing & Activation Granulaire des Agents)** : Implémentation du Cockpit d'Administration Opérations et Commercial hébergé sur le superviseur Olympe (port 9230) et routé via le sous-domaine `ops.orso-agents.fr`.
    - Gestion centralisée des clients (`public.tenants`), contacts DAF/dirigeants et suivi des conteneurs physiques de la flotte.
    - Intégration de la grille tarifaire officielle : **Starter (1 agent - 99 € HT/m)**, **Duo (2 agents - 169 € HT/m)**, **Flotte Complète (4 agents - 279 € HT/m)** avec suivi du MRR, de l'ARR et réconciliation Stripe Billing / factures PDF.
    - Matrice de feature toggling des 4 agents (Jérôme, Lucas, Clara, Victor) avec activation en 1-clic et paramétrage de périodes d'essai temporaires (7j, 14j, 30j) répercutées instantanément sans redémarrage de conteneur.
    - Application SPA React 19 / Vite / Tailwind CSS 4 compilée dans `apps/ui-ops/dist` et servie directement par Olympe. Suite de tests unitaires validée à 100% (`test_ops_manager.py`).

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
