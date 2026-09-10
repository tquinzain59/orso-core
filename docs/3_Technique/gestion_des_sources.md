# Gestion des Sources et Dépôts Git : Écosystème Orso Agents

L'écosystème **Orso agents** ([www.orso-agents.fr](http://www.orso-agents.fr)) est articulé autour de dépôts GitHub modulaires, avec un backend unifié intégrant directement son propre moteur d'agents autonome dérivé d'Hermes Agent (licence MIT Nous Research).

---

## 1. Cartographie des Dépôts Officiels

| Projet | Rôle dans l'Écosystème | URL du Dépôt GitHub | Branche Principale |
|---|---|---|---|
| **`orso-core`** (Actif) | **Moteur Backend Unifié**, Agent Loop, Conteneurs Docker, Profils, Skills TPE/PME & SQLite | `https://github.com/tquinzain59/orso-core.git` | `main` |
| **`App_Hermes Core`** | Application Cliente Multi-Agents PWA & Actions 1-clic | `https://github.com/tquinzain59/App_Hermes-core.git` | `main` |
| **`Site_Hermes-core`** | Portail Vitrine, Vidéos Démo & Dashboard Supervision | `https://github.com/tquinzain59/hermes-core-site.git` | `main` |
| *`hermes-core` (Legacy)* | *Ancien conteneur d'orchestration (archivé au profit de `orso-core`)* | `https://github.com/tquinzain59/hermes-core.git` | `main` |

---

## 2. Organisation de l'Espace de Développement Local

Sur la machine de développement, les projets sont organisés côte-à-côte sous `/Users/tquinzain/Documents/Dev Projects/` :

```
Dev Projects/
├── orso-core/               # Backend unifié : Moteur d'agents + Skills + Profils + Docker
├── App_Hermes Core/         # Application cliente PWA (agents.js, gateway-client.js, PWA)
└── Site_Hermes-core/        # Vitrine Tailwind CSS, monitoring.html (Chart.js), admin.html
```

---

## 3. Gestion du Moteur et Synchronisation Upstream

Le dépôt `orso-core` conserve un lien direct avec le dépôt source amont (*upstream*) de Nous Research :

```bash
# Vérification des remotes dans orso-core :
git remote -v
# origin   https://github.com/tquinzain59/orso-core.git (fetch & push)
# upstream https://github.com/NousResearch/hermes-agent.git (fetch & push)

# Rapatrier les améliorations du framework en une commande :
git fetch upstream
git merge upstream/main
```

---

## 4. Politique de Sécurité et Fichiers Ignorés (`.gitignore`)

Chaque dépôt comporte des règles d'exclusion strictes pour empêcher toute fuite de données :

* **Dans `orso-core`** :
  * Fichiers d'environnement (`.env`, `.env.local`).
  * Bases SQLite locales (`*.db`, `*.db-wal`, `*.db-shm`).
  * Fichiers de clés JSON (`service_account.json`).
  * Données de cache et sessions locales (`data/`, `hermes_home_dot_hermes/`).
* **Dans `App_Hermes Core`** :
  * Dossiers de distribution de build (`dist/`).
  * Fichiers d'environnement (`.env`).
* **Dans `Site_Hermes-core`** :
  * Fichiers de configuration et secrets d'administration locaux (`Secrets/`).
