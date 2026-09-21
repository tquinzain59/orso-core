# Spécification Technique d'Architecture : Ingress Dynamique & Gestion du Cycle de Vie Olympe (Option B)

> **Ticket Jira associé** : [KAN-28](https://orso-agents.atlassian.net/browse/KAN-28)  
> **Composants** : `Orso Ingress`, `Olympe Supervisor`, `Orso UI Client`  
> **Statut** : Validé (En cours de déploiement)  
> **Auteur / Responsable d'instruction** : Antigravity (Architecte Projet)  
> **Validation Métier & Décision** : Thibaut QUINZAIN (Direction Orso Agents)  
> **Date** : 20 Septembre 2026  

---

## 1. Contexte & Problématique Industrielle

Dans la phase initiale de prototypage, chaque client devait potentiellement disposer d'une URL ou d'un port dédié (ex: `:9229`, `prod-fr-002.orso-agents.fr`). 

Pour industrialiser l'onboarding de dizaines ou centaines de clients :
1. **Élimination des frictions DNS** : Créer manuellement un sous-domaine (`client.orso-agents.fr`) et renouveler des certificats SSL pour chaque nouvel arrivant est incompatible avec un onboarding automatisé en quelques secondes.
2. **URL unique et souveraine** : Tous les clients accèdent à leurs agents via une porte d'entrée universelle : `https://app.orso-agents.fr`.
3. **Optimisation des ressources serveur (RAM)** : Maintenir des centaines de conteneurs allumés 24/7 est coûteux. Le superviseur **Olympe** doit pouvoir suspendre les conteneurs inactifs et les réveiller instantanément à la connexion (*Wake-on-Demand*).

L'arbitrage retenu par la direction est l'**Option B : Routage dynamique transparent par chemin avec Ingress Zero-Reload et orchestration par Olympe**.

---

## 2. Architecture Cible Globale

```
                            ┌──────────────────────────────────────────────┐
                            │               CLIENT WEB / PWA               │
                            │         (https://app.orso-agents.fr)         │
                            └──────────────────────┬───────────────────────┘
                                                   │
                1. Authentification Supabase       │ 2. Requêtes API & WebSockets
                (JWT avec tenant_slug)             │    /t/{tenant_slug}/api/...
                                                   ▼
                ┌──────────────────────────────────────────────────────────┐
                │          INGRESS REVERSE PROXY DYNAMIQUE (Nginx)         │
                │     Résolveur Docker DNS 127.0.0.11 (Zéro Reload)        │
                └──────────────┬────────────────────────────┬──────────────┘
                               │                            │
             /t/financia/api/* │          /api/olympe/*     │
                               ▼                            ▼
                 ┌───────────────────────────┐ ┌───────────────────────────┐
                 │     CONTENEUR CLIENT      │ │     SUPERVISEUR OLYMPE    │
                 │   orso_client_financia    │ │        olympe-core        │
                 │   - Port interne: 9119    │ │   - Port interne: 9230    │
                 │   - Guard JWT (KAN-27)    │ │   - Docker SDK / API      │
                 │   - SQLite state.db isolé │ │   - Provisioning & Wake   │
                 └───────────────────────────┘ └───────────────────────────┘
```

---

## 3. Spécifications des Composants

### 3.1 Passerelle Ingress Dynamique (`docker/ingress/nginx.ingress.conf`)
* **Résolution Docker DNS à chaud** : Utilisation du serveur DNS interne Docker (`resolver 127.0.0.11 valid=10s ipv6=off;`). Dès qu'un nouveau conteneur `orso_client_{slug}` est démarré sur le réseau `orso_network`, Nginx est capable de le joindre sans recharger sa configuration.
* **Aiguillage des APIs** :
  ```nginx
  location ~ ^/t/(?<tenant>[a-zA-Z0-9_-]+)/api/(.*)$ {
      set $target_backend http://orso_client_$tenant:9119;
      proxy_pass $target_backend/api/$2$is_args$args;
      proxy_buffering off;
      proxy_read_timeout 3600s;
  }
  ```
* **Support complet WebSockets** :
  ```nginx
  location ~ ^/t/(?<tenant>[a-zA-Z0-9_-]+)/ws/?$ {
      set $target_backend http://orso_client_$tenant:9119;
      proxy_pass $target_backend/ws;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "Upgrade";
  }
  ```
* **Interception des conteneurs en veille** : Si le conteneur client est éteint (502/504), Nginx renvoie un code `503 Service Unavailable` enrichi d'un payload JSON clair invitant la PWA à solliciter le réveil Olympe.

### 3.2 Superviseur Olympe (`olympe/`)
* **Port d'écoute** : 9230.
* **Rôle** : Tour de contrôle de la flotte d'agents Orso.
* **Endpoints exposés** :
  * `GET /api/olympe/health` : État de santé d'Olympe et disponibilité du daemon Docker.
  * `GET /api/olympe/tenants/status/{tenant_slug}` : Retourne l'état de l'environnement (`ready`, `sleeping`, `starting`, `not_found`).
  * `POST /api/olympe/tenants/wake/{tenant_slug}` : Réveille le conteneur (`docker start`), attend sa disponibilité et renvoie le statut.
  * `POST /api/olympe/tenants/suspend/{tenant_slug}` : Met en veille le conteneur (`docker stop`).
  * `POST /api/olympe/tenants/provision` : Crée le volume `/data/tenants/{slug}`, lance le conteneur sur `orso_network` et synchronise Supabase `tenant_instances`.
  * `GET /api/olympe/telemetry/summary` : Agrège la consommation de tokens et les dépenses USD de tous les conteneurs actifs.

### 3.3 Adaptation PWA Frontend (`apps/ui-client/src/lib/api.ts`)
* **Résolution automatique du préfixe** : Dès qu'un utilisateur est authentifié, son `tenant_slug` est injecté pour former l'URL `/t/{tenant_slug}/api/...`.
* **Support du Wake-on-Demand** : La fonction `wakeTenantEnvironment(slug)` est exposée pour permettre à l'UI d'afficher un écran de chargement élégant (*« Démarrage de votre espace sécurisé... »*) en cas de premier accès après mise en veille.

---

## 4. Sécurité & Défense en Profondeur

Le partage d'une URL unique (`https://app.orso-agents.fr`) ne compromet en rien l'étanchéité absolue des données clients grâce à **deux verrous indépendants** :

1. **Verrou 1 (Routage Physique)** :
   Nginx achemine le trafic vers le conteneur physique `orso_client_{tenant_slug}` identifié dans le chemin URL.
2. **Verrou 2 (Guard Cryptographique JWT - KAN-27)** :
   Même si un utilisateur malveillant modifie son URL pour frapper `/t/autre-client/api/client/chat` :
   * Le conteneur cible reçoit la requête avec le Bearer JWT.
   * Le guard `verify_client_token` décode le JWT et compare le claim `tenant_slug` ("financia") avec sa variable locale `ORSO_CLIENT_SLUG` ("autre-client").
   * **Rejet immédiat en HTTP 403 Forbidden**. Aucune donnée n'est accessible.

---

## 5. Critères d'Acceptation (Definition of Done)

- [x] **CA 1** : La configuration Nginx Ingress permet de router dynamiquement les requêtes `/t/{slug}/api/*` et `/t/{slug}/ws` vers `http://orso_client_{slug}:9119` sans recharger Nginx.
- [x] **CA 2** : Le serveur Olympe (port 9230) implémente les routes d'état, de réveil (wake), de mise en veille (suspend) et de provisioning.
- [x] **CA 3** : L'UI cliente (`apps/ui-client`) préfixe ses requêtes d'API et WebSocket avec le slug du tenant stocké en session.
- [x] **CA 4** : Tous les tests unitaires et d'intégration d'Olympe et du routeur s'exécutent avec succès via `scripts/run_tests.sh`.
- [x] **CA 5** : Le build TypeScript de l'UI cliente (`npm run build`) est valide sans erreur.
