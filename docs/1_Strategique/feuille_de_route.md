# Feuille de Route : Hermès Core & Écosystème

Ce document présente l'historique exhaustif des jalons de développement franchis à ce jour, incluant le développement du site vitrine et de l'application cliente multi-agents, ainsi que les prochaines étapes stratégiques.

---

## 1. Jalons Réalisés (Historique des travaux)

### 📌 Jalon 1 : Socle Technique Backend (2026-08-20)
* **Description** : Infrastructure Docker pour l'exécution conteneurisée de l'agent de recouvrement.
* **Livrables** : 
  * Dockerfile et `docker-compose.yml` avec volumes persistants (`/app/config`, `/app/skills`, `/app/data`).
  * Dashboard de contrôle sécurisé par mot de passe chiffré (`scrypt`).

### 📌 Jalon 2 : Cartographie et Connecteurs ERP (2026-08-24 - 2026-08-26)
* **Description** : Interfaçage avec les solutions de facturation et comptabilité des TPE/PME françaises.
* **Livrables** :
  * Analyse de 13 solutions (Pennylane, Sellsy, Sage, Evoliz, QuickBooks, Odoo, Dynamics 365, Cegid, etc.).
  * Développements Python : `balance_agee.py` (calcul des tranches de retard) et `import_csv.py` (normalisation des exports manuels).

### 📌 Jalon 3 : Intégration Open Data & Scoring Pappers (2026-08-27 - 2026-08-28)
* **Description** : Collecte des signaux légaux et financiers des entreprises françaises.
* **Livrables** :
  * Intégration de l'API Pappers via `fiche_credit.py` (scoring financier, représentants, comptes annuels).
  * Veille automatisée des annonces BODACC via `veille_bodacc.py` (alertes sur procédures collectives, redressements et radiations).

### 📌 Jalon 4 : Canaux Messagerie Telegram & WhatsApp (2026-08-29)
* **Description** : Déploiement des premières passerelles de dialogue pour le credit manager et les débiteurs.
* **Livrables** :
  * Passerelle Telegram Bot avec statut dynamique (`"🟢 En ligne — Credit Manager"`).
  * Canal WhatsApp Business (ID `1080843988243985`) en mode Bot conversationnel.

### 📌 Jalon 5 : Portail Vitrine & Supervision Télémétrique (2026-08-30 - 2026-08-31)
* **Description** : Création du dépôt `Site_Hermes-core` pour présenter l'offre et surveiller l'infrastructure.
* **Livrables** :
  * `index.html` : Site vitrine avec design sombre soigné, effets visuels glow, et intégration des vidéos de démonstration de chaque agent.
  * `monitoring.html` : Tableau de bord de télémétrie en temps réel avec graphiques Chart.js (consommation de tokens, coûts USD par serveur d'agent, filtres et pagination).
  * `admin.html` : Espace d'administration sécurisé pour la gestion des accès et de la configuration.
  * Dépôt GitHub : `https://github.com/tquinzain59/hermes-core-site.git`.

### 📌 Jalon 6 : Application Cliente Multi-Agents PWA (2026-09-01)
* **Description** : Développement de `App_Hermes Core`, l'application cliente officielle permettant aux dirigeants de piloter l'ensemble de leurs agents IA.
* **Livrables** :
  * Interface PWA (Progressive Web App) installable sur mobile et desktop avec Service Worker (`sw.js`).
  * 4 canaux de discussion cloisonnés pour la flotte :
    * 🔵 **Hermès Recouvrement (Jérôme)** : Trésorerie & relances.
    * 🟣 **Hermès Commercial (Lucas)** : Pipeline de vente & leads.
    * 🟢 **Hermès Support Client (Clara)** : SAV 24/7 & gestion de tickets.
    * 🟡 **Hermès Appel d’Offre (Victor)** : Analyse DCE & mémoires techniques.
  * **Cartes d'Action Interactives** intégrées dans le chat (*"Approuver et envoyer"*, *"Reporter 48h"*).
  * Streaming mot à mot en temps réel via WebSocket/REST (Port 9300), avec affichage de la réflexion de l'agent.
  * Déploiement conteneurisé Docker (`docker-compose.yml`) et configuration Vercel SPA (`vercel.json`).
  * Dépôt GitHub : `https://github.com/tquinzain59/App_Hermes-core.git`.

### 📌 Jalon 7 : Architecture IAM Supabase Auth & Ingress Multi-Tenant (2026-09-16 - 2026-09-20)
* **Description** : Refonte de la sécurité avec fournisseur d'identité souverain (Supabase Auth - KAN-26), guard JWT cryptographique sur le backend (`orso-core` - KAN-27), et routage ingress dynamique Nginx sans rechargement sous URL unique `app.orso-agents.fr` (KAN-28).
* **Livrables** :
  * Schéma PostgreSQL Supabase (`tenants`, `profiles`, `tenant_instances` avec RLS étanche).
  * Reverse proxy Ingress résolvant à chaud les conteneurs clients (`127.0.0.11`) avec support complet SSE/WebSockets.
  * Superviseur Olympe (port 9230) avec cycle de vie *Wake-on-Demand* et mise en veille *Scale-to-Zero*.

### 📌 Jalon 8 : Cockpit Orso Ops & IAM Superadmin (2026-09-21 - 2026-09-23)
* **Description** : Console d'exploitation et d'administration commerciale déployée en direct sur `https://ops.orso-agents.fr` (KAN-30).
* **Livrables** :
  * Interface React 19 / Tailwind 4 (`apps/ui-ops`) avec authentification IAM Superadmin Supabase (`olympe/auth.py`).
  * Résolution automatique des emails réels des clients via l'API Admin Supabase.
  * Grille tarifaire (Starter 99 € HT, Duo 169 € HT, Flotte Complète 279 € HT), réconciliation Stripe Billing et feature toggling des 4 agents avec périodes d'essai à chaud.

### 📌 Jalon 9 : Raccordement dynamique des Interfaces & ERP au Backoffice Hermès (2026-09-25)
* **Description** : Suppression totale des données factices de l'onglet *Interfaces & ERP* de l'UI Client et sondage en temps réel du conteneur Hermès (KAN-31).
* **Livrables** :
  * Routeur de détection `_probe_hermes_backoffice_integrations` dans `hermes_cli/web_routers/client_ui.py` (Pennylane, Sellsy, Odoo, Airtable, Jira, Supabase, Pappers, BODACC Open Data, outils natifs Playwright/Web, serveurs MCP).
  * Statuts réels (Connecté, En attente/Libre, Non configuré) et modale de synchronisation / test en direct.
  * Déploiement en production sur `prod-fr-002.orso-agents.fr` et publication Confluence Page 3964930.

### 📌 Jalon 10 : Raccordement dynamique des Canaux de Messagerie & Omnicanal (2026-09-25)
* **Description** : Raccordement transparent de l'onglet *Canaux* au backoffice Hermès Gateway et purge des métriques simulées (KAN-32).
* **Livrables** :
  * Routeur de détection `_probe_hermes_backoffice_channels` sondant les variables réelles (`TELEGRAM_BOT_TOKEN`, `WHATSAPP_TOKEN`, `SMTP_HOST`/`RESEND_API_KEY`, `SLACK_BOT_TOKEN`, `DISCORD_BOT_TOKEN`).
  * Modale guidée d'activation étape par étape (@BotFather, Cloud API, SMTP) avec bouton de vérification de liaison.
  * Badge d'état de la passerelle Hermès Gateway et contrôle d'accès persistant par listes blanches (`allowedUsers`).
  * Déploiement en direct sur `prod-fr-002.orso-agents.fr`, test automatisé de non-régression et publication Confluence Page 3997698.

---

## 2. Jalons Futurs (Roadmap Court & Moyen Terme)

### 🚀 Jalon 11 : Synchronisation Bidirectionnelle ERP (Writeback)
* Lettrage comptable automatique dans les ERP (Pennylane, Sellsy, Odoo) dès confirmation d'un règlement.
* Génération automatique d'avoirs/notes de crédit après accord du gestionnaire.

### 🚀 Jalon 12 : Paiement Immédiat & Recouvrement par LRAR
* Intégration d'un module de paiement par carte bancaire (Stripe / Payplug) directement dans les liens de relance WhatsApp/Chat.
* Envoi automatisé de Lettres Recommandées Électroniques (LRE) avec valeur légale (via API AR24 / Maileva) lors du passage en contentieux.

