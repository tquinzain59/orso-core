# Canaux de Communication de l'Écosystème Hermès

La suite Hermès propose une approche véritablement omnicanale, connectant les dirigeants de PME, leurs équipes opérationnelles et leurs clients tiers à travers quatre canaux adaptés à chaque contexte d'usage.

---

## 1. L'Application Cliente Native : `App_Hermes Core` (PWA)

L'application `App_Hermes Core` est le **canal de pilotage principal** mis à la disposition de l'entreprise cliente. Développée comme une Progressive Web App (PWA) moderne, elle est accessible via navigateur desktop et installable sur smartphone (iOS/Android).

### Fonctionnalités Clés du Canal App
* **Sélection Multi-Agents Immédiate** : La barre latérale permet de basculer instantanément entre les 4 agents de l'entreprise (🔵 Jérôme, 🟣 Lucas, 🟢 Clara, 🟡 Victor).
* **Streaming Temps Réel Mot-à-Mot** : Les réponses des agents s'affichent de façon fluide en direct grâce à la connexion WebSocket (`ws://localhost:9229/ws`), avec visualisation du temps de réflexion.
* **Cartes d'Action Interactives (In-Chat)** : Les propositions critiques des agents (ex: relance de facture, proposition commerciale, escalade ticket) s'affichent sous forme de cartes d'action interactives munies de boutons d'arbitrage en un clic (*Approuver et envoyer*, *Reporter*).
* **Boutons d'Actions Rapides (Quick Actions)** : Des raccourcis contextuels permettent de déclencher les requêtes les plus fréquentes (`/balance`, `/retards`, `/leads`, `/tickets`, `/ao_list`).
* **Mode Hors-Ligne & Simulation** : Si les conteneurs backend sont en cours de maintenance, l'application bascule automatiquement en mode de simulation fluide pour permettre la formation des équipes.

---

## 2. Le Canal Telegram (Console de Pilotage Nomade)

Le canal Telegram est réservé au **gestionnaire interne (Credit Manager / Direction)** pour assurer une surveillance en temps réel sans ouvrir l'application complète.

### Fonctionnalités
* **Alertes Prioritaires Immédiates** : Notification instantanée dès qu'une procédure collective (redressement, liquidation) est publiée au BODACC sur un client de l'entreprise.
* **Commandes Slash Directes** :
  * `/balance` : Renvoie la synthèse chiffrée de la balance âgée.
  * `/check <siren>` : Génère la fiche crédit et le scoring d'un tiers.
  * `/status` : Affiche l'état des conteneurs et les coûts LLM de la journée.
* **Indicateur Dynamique** : Affiche le statut réel de l'agent (`"🟢 En ligne — Credit Manager"`).

---

## 3. Le Canal WhatsApp Business (Relation Clients Débiteurs & Prospects)

WhatsApp est le canal dédié à l'**interaction directe avec les tiers extérieurs** (clients débiteurs pour Jérôme, prospects pour Lucas).

### Caractéristiques
* **Numéro WhatsApp Business ID** : `1080843988243985`.
* **Mode Bot Dédié** : Jérôme dialogue de manière autonome et courtoise pour négocier des échéanciers, accuser réception des preuves de virement ou orienter les contestations.
* **Taux d'Engagement Maximal** : Taux d'ouverture supérieur à 85%, garantissant une réactivité bien plus forte que les courriels traditionnels.

---

## 4. Le Portail Web & Espace Supervision (`Site_Hermes-core`)

Le dépôt `Site_Hermes-core` sert de portail d'accueil public et de centre d'administration :
* **Site Vitrine** : Présentation pédagogique des agents avec vidéos de démonstration dédiées par cas d'usage.
* **Console de Supervision (`monitoring.html`)** : Vue globale sur les consommations d'APIs, les tokens consommés et la répartition des coûts en dollars pour chaque agent de la flotte.
* **Espace Admin (`admin.html`)** : Gestion des accès sécurisés et des paramètres de l'organisation.
