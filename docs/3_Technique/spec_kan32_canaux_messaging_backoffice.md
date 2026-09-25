# Spécification Technique d'Architecture : Raccordement Dynamique des Canaux de Discussion au Backoffice Hermès

> **Ticket Jira associé** : [KAN-32](https://orso-agents.atlassian.net/browse/KAN-32)  
> **Page Confluence de référence** : [Confluence Orso-agents (Page 3997698)](https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/3997698)  
> **Composants** : `UI Client (apps/ui-client)`, `Routeur FastAPI Client (hermes_cli/web_routers/client_ui.py)`, `Passerelles Gateway Hermès (Telegram, WhatsApp, Email, Slack, Discord)`  
> **Statut** : Validé et Déployé en Production (`https://prod-fr-002.orso-agents.fr` / VPS OVH `92.222.68.80`)  
> **Auteur / Responsable d'instruction** : Antigravity (Architecte Projet)  
> **Validation Métier & Décision** : Thibaut QUINZAIN (Direction Orso Agents)  
> **Date** : 25 Septembre 2026  

---

## 1. Contexte & Problématique Métier

Dans l'application cliente PWA d'Orso Agents (`apps/ui-client`), l'onglet **Canaux** permet aux dirigeants et aux équipes de configurer les passerelles de messagerie instantanée (Telegram, WhatsApp, Email) reliant les agents autonomes à leurs interlocuteurs humains.

### Constat initial
L'écran reposait sur des données factices et des interactions simulées :
- Numéros et adresses inventés : `+33 6 42 00 12 34`, `@OrsoDirigeantBot`, `recouvrement@finarecee20.fr`.
- Faux compteurs de trafic : `messagesToday: 12`, `messagesToday: 26`, etc.
- Statuts verts `connected` affichés par défaut même sans aucun paramétrage dans l'environnement.
- Faux parcours d'appairage : génération d'un QR code factice avec chaîne locale bidon (`2@OrsoAgents-...`) et simples `alert()` navigateurs.

### Objectif d'alignement & de transparence
1. **Élimination complète des données factices** : suppression des numéros, emails et compteurs inventés.
2. **Sondage dynamique de l'environnement réel du conteneur Hermès** (`_probe_hermes_backoffice_channels`) :
   - **Telegram** : détection de `TELEGRAM_BOT_TOKEN`.
   - **WhatsApp Business** : détection de `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` ou `WHATSAPP_API_KEY`.
   - **Passerelle Email** : détection de `SMTP_HOST`, `RESEND_API_KEY`, `MAILGUN_API_KEY` ou `SMTP_USER`.
   - **Canaux optionnels** : détection automatique de `SLACK_BOT_TOKEN` ou `DISCORD_BOT_TOKEN`.
3. **Statuts honnêtes et exploitables** :
   - `Connecté (Backoffice)` (🟢) si la passerelle est configurée avec des identifiants valides.
   - `Non configuré` (⚪) si les variables d'environnement requises sont absentes.
4. **Modale de Détails & Paramétrage** : guide pas-à-pas pour chaque canal indiquant la variable requise, l'emplacement cible (`.env` ou `config/hermes.yaml`), et un bouton pour vérifier la liaison en direct.

---

## 2. Architecture Globale

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                NAVIGATEUR CLIENT PWA                                   │
│                        (https://prod-fr-002.orso-agents.fr)                            │
│                                                                                        │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                         Onglet 'Canaux de Discussion'                          │   │
│   │  - Cartouche état Moteur Hermès : Connecté (Instance client)                   │   │
│   │  - Badges réels : Connecté (Backoffice) | Non configuré                        │   │
│   │  - Modale de paramétrage : Instructions @BotFather, SMTP, WhatsApp Cloud       │   │
│   │  - Gestion des accès autorisés par canal (Allowed Users)                       │   │
│   └───────────────────────────────────────┬────────────────────────────────────────┘   │
└───────────────────────────────────────────┼────────────────────────────────────────────┘
                                            │ Requêtes HTTP REST
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                    CONTENEUR BACKEND HERMES (orso_client_backend)                      │
│                                                                                        │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │       FastAPI Routeur Client UI (hermes_cli/web_routers/client_ui.py)           │   │
│   │       - GET /api/client/channels                                               │   │
│   │       - POST /api/client/channels/{channel_id}/users                           │   │
│   │       - DELETE /api/client/channels/{channel_id}/users/{user}                  │   │
│   └───────────────────────┬────────────────────────────────────────────────────────┘   │
│                           │                                                            │
│                           ▼                                                            │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │         Sondeur Canaux Hermès (_probe_hermes_backoffice_channels)              │   │
│   │                                                                                │   │
│   │   ├── Telegram : TELEGRAM_BOT_TOKEN                                            │   │
│   │   ├── WhatsApp : WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID                     │   │
│   │   ├── Email    : SMTP_HOST / RESEND_API_KEY / MAILGUN_API_KEY                  │   │
│   │   └── Extensions: SLACK_BOT_TOKEN, DISCORD_BOT_TOKEN                           │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Détails d'Implémentation

### 3.1 Backend FastAPI (`hermes_cli/web_routers/client_ui.py`)
- Fonction `_probe_hermes_backoffice_channels` : inspecte l'environnement sans exposer les tokens en clair.
- Persistance en mémoire `_CHANNEL_ALLOWED_USERS` pour conserver les utilisateurs autorisés par tenant/canal, couplée à Supabase si provisionné.
- Suppression des faux numéros et compteurs dans `_SEED_CHANNELS`.
- Maintien du contrat REST `/api/client/channels` et `/users`.

### 3.2 Frontend PWA (`apps/ui-client`)
- `src/types/index.ts` : ajout de `configKey`, `metrics` et `syncStatus` sur `MessagingChannel`.
- `src/lib/data.ts` : nettoyage des fausses métriques dans `SAMPLE_CHANNELS`.
- `src/pages/ChannelsView.tsx` :
  - Intégration du bandeau d'état du moteur Hermès.
  - Badges transparents (Connecté vs Non configuré).
  - Modale d'instructions détaillées et diagnostic en remplacement des alertes factices.

---

## 4. Conformité Gouvernance Fork Orso

- **Le Sanctuaire (Zone A)** : aucun fichier de la boucle centrale (`agent/`, `run_agent.py`, `conversation_loop.py`, prompt caching) n'a été modifié.
- **La Zone d'Évolution (Zone B)** : 100% des modifications sont circonscrites à `apps/ui-client` et `hermes_cli/web_routers/client_ui.py`.

---

## 5. Recette & Déploiement

- **Tests unitaires** : 19/19 tests passés avec succès via `./scripts/run_tests.sh tests/hermes_cli/test_client_ui.py` (incluant `test_client_channels_backoffice_real_detection`).
- **Compilation Frontend** : `npm run build` dans `apps/ui-client` réussi en 180ms sans erreur.
- **Déploiement VPS** : Synchronisation sur `prod-fr-002.orso-agents.fr` (VPS OVH `92.222.68.80`).
