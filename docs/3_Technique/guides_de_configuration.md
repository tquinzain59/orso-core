# Guides de Configuration et de Déploiement

Ce document fournit l'ensemble des instructions pour configurer et déployer les trois composantes de l'écosystème : le moteur d'agents backend, l'application cliente PWA et le portail de supervision.

---

## 1. Déploiement du Moteur Backend (`hermes-core`)

### Fichier `config/hermes.yaml`
```yaml
model:
  provider: openrouter
  default: deepseek/deepseek-v4-flash
agent:
  name: Hermes_Recouvrement
  role: Assistant ADV spécialisé dans le recouvrement pour les TPE/PME.
dashboard:
  basic_auth:
    username: ${HERMES_DASHBOARD_BASIC_AUTH_USERNAME}
    password_hash: ${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH}
tools:
  - path: /app/skills/check_overdue.py
  - path: /app/skills/credit_management/balance_agee.py
  - path: /app/skills/credit_management/import_csv.py
  - path: /app/skills/credit_management/veille_bodacc.py
  - path: /app/skills/credit_management/fiche_credit.py
  - path: /app/skills/telemetry.py
gateway:
  platforms:
    telegram:
      extra:
        status_indicator: true
        status_online: "🟢 En ligne — Credit Manager"
        status_offline: "🔴 Hors ligne"
```


### Lancement Docker
```bash
cd "/Users/tquinzain/Documents/Dev Projects/hermes-core"
docker compose up -d --build
```
L'API et le dashboard d'administration deviennent accessibles sur `http://localhost:9229`.

---

## 2. Déploiement de l'Application Cliente (`App_Hermes Core`)

L'application cliente peut être exécutée selon trois modes en fonction de l'environnement :

### Mode A : Lancement Local Immédiat
```bash
cd "/Users/tquinzain/Documents/Dev Projects/App_Hermes Core"
python3 -m http.server 9300
```
Accédez ensuite à `http://localhost:9300` dans votre navigateur.

### Mode B : Déploiement Dockerisé
```bash
cd "/Users/tquinzain/Documents/Dev Projects/App_Hermes Core"
docker compose up -d --build
```
Le conteneur `app_hermes_core` est rattaché au réseau `hermes_network` et expose le port `9300`.

### Mode C : Déploiement Cloud Vercel
Le fichier `vercel.json` est préconfiguré pour router toutes les requêtes vers `index.html` (SPA) :
```bash
vercel --prod
```

### Paramètres de Configuration (`js/config.js`)
* `DEFAULT_GATEWAY_WS` : URL WebSocket de l'agent (défaut : `ws://localhost:9229/ws`).
* `DEFAULT_GATEWAY_HTTP` : URL HTTP REST de l'agent (défaut : `http://localhost:9229`).
* `SUPERVISOR_HTTP` : URL du superviseur Olympe (défaut : `http://localhost:9230`).
* `ENABLE_SIMULATION_FALLBACK` : Activé à `true` par défaut pour permettre les démonstrations même si les conteneurs backend sont éteints.

---

## 3. Déploiement du Portail Vitrine & Supervision (`Site_Hermes-core`)

Le portail statique est directement consultable en ouvrant les fichiers dans un navigateur ou via un hébergement web classique :
* `index.html` : Site vitrine avec vidéos de démonstration locales (`videos/`).
* `monitoring.html` : Tableau de bord de télémétrie. Configuré pour interroger l'API locale/distante (`http://localhost:9120` ou URL personnalisée) avec bascule automatique sur données simulées si l'API est injoignable.
* `admin.html` : Espace d'administration avec authentification locale.

---

## 4. Sécurité et Variables d'Environnement

Variables à exporter sur la machine hôte :
```bash
# Backend Hermès
export OPENROUTER_API_KEY="sk-or-v1-..."
export HERMES_DASHBOARD_BASIC_AUTH_USERNAME="admin"
export HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH="scrypt$$16384$$..."

# Données & Messageries
export PAPPERS_API_TOKEN="votre_cle_pappers"
export TELEGRAM_BOT_TOKEN="votre_token_telegram_ici"
```

Le filtre **Tirith** inspecte automatiquement tous les scripts dans `skills/` avant exécution, et la fonctionnalité **Secret Redaction** masque automatiquement les tokens et clés privées dans les logs de l'agent.

---

## 5. Configuration des Connecteurs Métiers (Interfaces & ERP)

L'onglet **Interfaces & ERP** de l'UI Client (`/api/client/integrations`) sonde dynamiquement les variables d'environnement et la configuration Hermès pour refléter en direct l'état opérationnel des connecteurs :

### Variables d'environnement pour ERP & Données Métiers (`.env`)
```bash
# Facturation & ERP
PENNYLANE_API_KEY="votre_cle_api_pennylane"
SELLSY_TOKEN="votre_jeton_sellsy"
ODOO_URL="https://votre-instance.odoo.com"
ODOO_DB="votre_base"
ODOO_USERNAME="agent@entreprise.com"
ODOO_PASSWORD="votre_mot_de_passe_ou_api_key"

# CRM & Collaboration
AIRTABLE_API_KEY="pat..."
ATLASSIAN_DOMAIN="votre-domaine"
JIRA_API_TOKEN="votre_token_jira"

# Données Légales & Solvabilité
PAPPERS_API_KEY="votre_cle_pappers"
# Note : BODACC / DILA fonctionne en Open Data direct ou via la compétence 'consulter-bodacc-creditsafe'

# Messageries & Bureautique
GOOGLE_WORKSPACE_CREDENTIALS='{"client_id": "...", ...}'
MICROSOFT_365_TOKEN="votre_token_graph_api"
```

### Serveurs MCP & Outils dans `config/hermes.yaml`
Pour activer des serveurs MCP personnalisés ou des outils avancés :
```yaml
mcp_servers:
  mon_erp_custom:
    command: npx
    args: ["-y", "@company/mcp-erp-server"]
    env:
      ERP_SECRET: "..."
```
Dès qu'une clé est injectée dans le conteneur ou que le serveur MCP est déclaré, l'interface client passe automatiquement le connecteur au statut **Connecté (Backoffice)** (🟢).

---

## 6. Configuration des Canaux de Communication (Messageries & Omnicanal - KAN-32)

L'onglet **Canaux** de l'UI Client (`/api/client/channels`) sonde en temps réel la configuration des passerelles externes du conteneur Hermès.

### Variables d'environnement des Canaux (`.env`)
```bash
# 1. Telegram Bot
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"

# 2. WhatsApp Business Cloud API
WHATSAPP_TOKEN="EAA..."
WHATSAPP_PHONE_NUMBER_ID="1080843988243985"

# 3. Email (SMTP standard ou Resend API)
# Option A : SMTP
SMTP_HOST="smtp.monentreprise.fr"
SMTP_PORT="587"
SMTP_USER="relances@monentreprise.fr"
SMTP_PASSWORD="mot_de_passe_securise"
SMTP_FROM="Jérôme - Credit Manager <relances@monentreprise.fr>"

# Option B : Resend
RESEND_API_KEY="re_..."

# 4. Collaboration d'Équipe (Slack & Discord)
SLACK_BOT_TOKEN="xoxb-..."
DISCORD_BOT_TOKEN="MTE..."
```

### Contrôle d'Accès et Filtrage d'Identifiants (`allowedUsers`)
Pour sécuriser les canaux interactifs (Telegram, Slack, WhatsApp), l'agent n'autorise que les identifiants déclarés dans sa liste blanche. Cette liste peut être gérée directement depuis l'UI Client dans la modale du canal, et persistée dans l'instance du client.

