# Canaux de Communication de l'Écosystème Orso Agents

La suite Orso Agents propose une approche omnicanale unifiée, connectant les dirigeants de PME, leurs équipes opérationnelles et leurs interlocuteurs tiers (clients débiteurs, prospects, partenaires) à travers une palette de canaux adaptés à chaque contexte d'usage.

Depuis la mise en service du raccordement dynamique au backoffice Hermès (**KAN-32**), l'intégralité des données factices a été éliminée au profit d'un sondage direct des passerelles et de leurs variables de configuration réelles.

---

## 1. L'Application Cliente Unifiée : `apps/ui-client` (PWA)

L'application cliente est la **console de pilotage souveraine** mise à la disposition de l'entreprise cliente. Développée comme une Progressive Web App (PWA) moderne en React 19, TypeScript et Tailwind CSS, elle est accessible sur navigateur desktop et installable sur smartphone (iOS/Android).

L'interface s'articule autour de trois espaces de travail majeurs :

```
┌────────────────────────────────────────────────────────────────────────┐
│                        ORSO CLIENT UI (PWA)                            │
│                                                                        │
│   [ 💬 Discussion ]        [ 🔌 Interfaces & ERP ]     [ 📱 Canaux ]    │
│   ─────────────────        ───────────────────────     ─────────────    │
│   • Multi-agents (Jérôme,  • Sondage réel ERP          • Passerelles    │
│     Lucas, Clara, Victor)    (Pennylane, Sellsy,         (Telegram,     │
│   • Streaming SSE fluide     Odoo, Airtable, Jira)       WhatsApp,      │
│   • Cartes d'action        • Outils natifs (Web,         Email, Slack,  │
│   • Invariance du prompt     Playwright, Open Data)      Discord)       │
│     caching                • Serveurs MCP déclarés     • Whitelist      │
│                                                          allowedUsers   │
└────────────────────────────────────────────────────────────────────────┘
```

### A. Onglet Discussion (Console Conversationnelle Multi-Agents)
* **Sélection Multi-Agents Immédiate** : Bascule fluide entre les 4 agents spécialisés de la flotte :
  * 🔵 **Jérôme (Credit Manager)** : Trésorerie, balance âgée, relances de factures et contentieux.
  * 🟣 **Lucas (Business Developer)** : Prospection, qualification de leads entrants, synchronisation CRM.
  * 🟢 **Clara (Customer Support)** : Support client 24/7, résolution de réclamations et gestion des tickets.
  * 🟡 **Victor (Analyste Appels d'Offres)** : Veille marchés publics, décorticage de DCE et mémoires techniques.
* **Streaming Temps Réel Mot-à-Mot** : Rendu fluide via Server-Sent Events (SSE sur `/api/client/chat/stream`), visualisation des phases de réflexion et préservation absolue du cache de prompt LLM.
* **Cartes d'Action Interactives (In-Chat)** : Validation d'actions critiques en un clic (*Approuver et envoyer*, *Reporter*).
* **Actions Rapides (Quick Actions)** : Commandes contextuelles intégrées (`/balance`, `/retards`, `/leads`, `/tickets`, `/ao_list`).

### B. Onglet Interfaces & ERP (KAN-31)
* **Vérité Terrain** : Restitution en direct de l'état des connecteurs métiers (Pennylane, Sellsy, Odoo, Airtable, Jira, Supabase, Pappers, BODACC, navigateurs Playwright, serveurs MCP).
* **Statuts Transparents** : Affichage sans simulation (`Connecté`, `En attente / Libre`, `Non configuré`).
* **Modale d'Interconnexion** : Paramétrage assisté et bouton de synchronisation immédiate.

### C. Onglet Canaux (KAN-32)
* **Pilotage Omnicanal Centralisé** : Vue d'ensemble sur l'ensemble des passerelles de messagerie externes reliées au conteneur du client.
* **Détection Backoffice Automatique** : Statuts réels extraits de la passerelle Hermès Gateway.

---

## 2. Les Canaux de Messagerie Externes (Hermès Gateway)

L'écosystème s'appuie sur la passerelle native Hermès Gateway pour relayer les interactions sur les messageries tierces :

### A. Telegram (Console de Supervision Mobile)
* **Rôle** : Canal privilégié du dirigeant et des managers pour superviser l'activité en situation de mobilité.
* **Variable d'activation** : `TELEGRAM_BOT_TOKEN` (fourni via `@BotFather`).
* **Fonctionnalités** :
  * Notification instantanée sur publication BODACC (redressements, liquidations de clients).
  * Exécution de commandes slash (`/balance`, `/check <siren>`, `/status`).
  * Contrôle d'accès strict via liste blanche d'identifiants Telegram autorisés (`allowedUsers`).

### B. WhatsApp Business (Relation Clients Débiteurs & Prospects)
* **Rôle** : Dialogue direct et engageant avec les interlocuteurs externes (débiteurs pour Jérôme, prospects pour Lucas).
* **Variables d'activation** : `WHATSAPP_TOKEN` (token permanent Cloud API) et `WHATSAPP_PHONE_NUMBER_ID` (ID du numéro Meta Business).
* **Fonctionnalités** :
  * Envoi de notifications interactives et négociation cordiale d'échéanciers.
  * Taux d'ouverture supérieur à 85%, raccourcissant drastiquement les délais de règlement.

### C. Email Professionnel (Relances Officielles & Notifications)
* **Rôle** : Émission de courriels contractuels, envois de factures PDF, synthèses hebdomadaires et mises en demeure.
* **Variables d'activation** : Serveur SMTP classique (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`) ou API moderne Resend (`RESEND_API_KEY`).
* **Fonctionnalités** :
  * Génération de relances écrites avec traçabilité complète de l'historique d'envoi.

### D. Slack & Discord (Collaboration d'Équipe)
* **Slack** (`SLACK_BOT_TOKEN`) : Intégration dans les canaux internes de l'entreprise (`#finance`, `#commerce`, `#support`) pour notifier les équipes sans rupture de contexte.
* **Discord** (`DISCORD_BOT_TOKEN`) : Animation communautaire ou support étendu pour les entreprises opérant sur cette plateforme.

---

## 3. Vérité Terrain, Sécurité & Expérience d'Activation

Depuis le chantier **KAN-32**, l'expérience utilisateur répond aux exigences suivantes :

1. **Suppression des Données Factices** :
   * Disparition des anciens compteurs de messages simulés (`1 240 msgs`, `342 msgs`) et des identifiants arbitraires.
   * Restitution de métriques d'audit objectives (horodatage de dernière synchronisation, état de liaison).
2. **Indicateur d'État du Moteur Hermès Gateway** :
   * Un badge d'état temps réel en en-tête d'onglet indique la disponibilité du moteur :
     * 🟢 **Passerelle Hermès : Opérationnelle** (lorsque le moteur est actif et qu'au moins un canal est opérationnel).
     * 🟡 **Passerelle Hermès : En attente** (lorsqu'aucune variable de canal n'est injectée).
3. **Modale d'Onboarding Guidée** :
   * Chaque canal dispose d'un guide étape par étape directement accessible au clic sur *Configurer* :
     * **Telegram** : Guide de création via `@BotFather`, obtention du Token et ajout au groupe.
     * **WhatsApp** : Procédure Meta for Developers, validation du numéro et du webhook.
     * **Email** : Paramétrage SMTP ou obtention d'une clé API Resend.
   * Bouton de **Vérification de liaison** qui teste la joignabilité de l'API sans quitter la console.
4. **Contrôle d'Accès Sécurisé (Listes Blanches)** :
   * Possibilité d'ajouter et retirer des identifiants utilisateurs autorisés (`allowedUsers`) par canal afin de prévenir toute intrusion ou interaction non sollicitée.

---

## 4. Supervision & Gouvernance

* **Cockpit Orso Ops (`https://ops.orso-agents.fr` - KAN-30)** : Les administrateurs peuvent superviser l'activation des canaux de l'ensemble des tenants et contrôler l'infrastructure.
* **Sanctuaire Fork Preservé** : Conformément à la *Charte de Gouvernance du Fork*, l'ensemble de la logique de sondage et de restitution réside dans la Zone d'Évolution (`apps/ui-client` et `hermes_cli/web_routers/client_ui.py`), garantissant la pérennité du cœur upstream Hermès.
