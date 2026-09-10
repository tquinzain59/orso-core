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

---

## 2. Jalons Futurs (Roadmap Court & Moyen Terme)

### 🚀 Jalon 7 : Industrialisation Multi-Conteneurs de la Flotte
* Déploiement des 3 conteneurs d'agents additionnels : `hermes_commercial_agent` (port 9231), `hermes_support_agent` (port 9232), `hermes_ao_agent` (port 9233).
* Orchestration unifiée via Docker Compose interconnectant les agents au superviseur `olympe-core` (port 9230).

### 🚀 Jalon 8 : Synchronisation Bidirectionnelle ERP (Writeback)
* Lettrage comptable automatique dans les ERP (Pennylane, Sellsy, Odoo) dès confirmation d'un règlement.
* Génération automatique d'avoirs/notes de crédit après accord du gestionnaire.

### 🚀 Jalon 9 : Paiement Immédiat & Recouvrement par LRAR
* Intégration d'un module de paiement par carte bancaire (Stripe / Payplug) directement dans les liens de relance WhatsApp/Chat.
* Envoi automatisé de Lettres Recommandées Électroniques (LRE) avec valeur légale (via API AR24 / Maileva) lors du passage en contentieux.
