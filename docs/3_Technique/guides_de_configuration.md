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
