# Spécification Technique d'Architecture : Accès Drone Machine de Test & Périmètre OPS (KAN-35)

> **Ticket Jira associé** : [KAN-35](https://orso-agents.atlassian.net/browse/KAN-35)  
> **Composants** : `Olympe Ops Core (olympe/)`, `Supabase Auth IAM`, `Docker Lifecycle Manager`, `Stripe Webhooks`  
> **Statut** : Validé et Testé (Conformité CA1 à CA8 100% validée)  
> **Auteur / Responsable technique** : Antigravity (Architecte Projet)  
> **Destinataire & Mandat** : Jarvis (PO), sur mandat de Thibaut QUINZAIN (Direction Orso Agents)  
> **Date** : 28 Septembre 2026  

---

## 1. Contexte & Objectif Métier

Pour automatiser la qualification et l'exercice du parcours client de bout en bout (inscription, abonnement, provisioning, espace client connecté, canaux de communication), un drone de test automatisé piloté par le PO (Jarvis) nécessite un accès machine au cockpit **Orso Ops** (`ops.orso-agents.fr`).

### Principe Fondateur de Sécurité (Least Privilege)
Le drone doit pouvoir **créer, vérifier et détruire** le tenant de test, et **rien d'autre**. Toute capacité qui dépasse ce périmètre est un défaut de conception, et non un confort.
- **Surface OPS (`ops.orso-agents.fr`)** : Accès machine dédié via jeton Bearer à portées limitées.
- **Surface Vitrine (`www.orso-agents.fr`)** : Aucun accès drone nécessaire (surface publique).
- **Surface Client (`app.orso-agents.fr`)** : Accès client standard rattaché au tenant de test, avec interdiction absolue et vérifiée d'accès au cockpit OPS.

---

## 2. Matrice d'Habilitation & Portées du Drone (RBAC)

### 2.1 Identité Machine Dédiée (L1 & CA7)
- **Rôle IAM** : `drone` (distinct du rôle `superadmin` humain et du rôle `user`/`admin` client).
- **Identifiant d'acteur dans les journaux** : `drone-clientx` (distinguable dans les logs d'audit `[OPS_AUDIT] [DRONE]`).
- **Authentification** : Jeton d'API à en-tête (`Authorization: Bearer <jeton>`), révocable immédiatement.

### 2.2 Portées Autorisées (L2)
| Portée (Scope) | Description | Endpoints OPS Associés |
| :--- | :--- | :--- |
| `tenants:read` | Lecture de l'état de la flotte et du tenant de test | `GET /api/olympe/ops/tenants`, `GET /api/olympe/ops/stats`, `GET /api/olympe/ops/tenants/clientx-orso` |
| `tenants:provision:sandbox` | Création et instanciation du tenant de test uniquement | `POST /api/olympe/ops/tenants` (restreint à `clientx-orso`) |
| `tenants:teardown:sandbox` | Destruction idempotente du tenant de test uniquement | `DELETE /api/olympe/ops/tenants/clientx-orso` |
| `agents:write:sandbox` | Activation/désactivation d'agents sur le tenant de test | `POST /api/olympe/ops/tenants/clientx-orso/agents` |
| `billing:read` | Consultation des factures et du statut d'abonnement | `GET /api/olympe/ops/invoices` |
| `webhooks:read` | Consultation du journal de livraison des événements Stripe | `GET /api/olympe/ops/webhooks/deliveries` |

### 2.3 Interdits Absolus (Refus Serveur HTTP 403 / 401)
1. **Accès hors whitelist sandbox** : Tout appel visant un tenant en dehors de la whitelist `clientx-orso` (ex: `financia-solutions`) est rejeté en **HTTP 403 Forbidden**.
2. **IAM & Gestion des comptes** : Refus formel de `POST /api/olympe/ops/tenants/{id}/users` et `DELETE .../users/{id}` (réservés au superadmin).
3. **Clés & Configuration Stripe** : Refus de toute modification de prix ou d'abonnement structurel (`POST /api/olympe/ops/tenants/{id}/subscription`).
4. **Infrastructure & Hôte** : Aucun accès Docker direct ni endpoints OVH (`POST /api/olympe/ops/ovh/credential-request` et `GET /api/olympe/ops/ovh/status` rejetés en 403).
5. **Révocation immédiate (CA4)** : Tout jeton révoqué via `revoke_token` est immédiatement rejeté en **HTTP 401 Unauthorized**.

---

## 3. Architecture Technique des Composants

```
                    ┌────────────────────────────────────────────────────────┐
                    │               DRONE AUTOMATISÉ (JARVIS)                │
                    │         Identité: drone-clientx (Rôle: drone)          │
                    └───────────────────────────┬────────────────────────────┘
                                                │
                                                ▼  Authorization: Bearer <jeton_drone>
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 SUPERVISEUR OLYMPE (Port 9230)                                  │
│                                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                              GARDE DE SÉCURITÉ IAM (olympe/auth.py)                       │  │
│  │  - verify_ops_token : Validation de session & vérification du registre de révocation      │  │
│  │  - require_ops_actor(scope) : Validation des portées autorisées                           │  │
│  │  - check_sandbox_tenant_access : Whitelist stricte {'clientx-orso'}                       │  │
│  └────────────────────────────────────────────┬──────────────────────────────────────────────┘  │
│                                               │                                                 │
│                                               ▼                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                          ENDPOINTS OPS SÉCURISÉS (olympe/server.py)                       │  │
│  │  - POST   /api/olympe/ops/tenants                (tenants:provision:sandbox)              │  │
│  │  - DELETE /api/olympe/ops/tenants/{id}           (tenants:teardown:sandbox)               │  │
│  │  - GET    /api/olympe/ops/tenants                (tenants:read)                           │  │
│  │  - GET    /api/olympe/ops/tenants/clientx-orso   (tenants:read + check_sandbox)           │  │
│  │  - POST   /api/olympe/ops/tenants/.../agents     (agents:write:sandbox + check_sandbox)   │  │
│  │  - GET    /api/olympe/ops/webhooks/deliveries    (webhooks:read)                          │  │
│  │  - GET    /api/olympe/ops/audit-log              (tenants:read)                           │  │
│  └────────────────────────────────────────────┬──────────────────────────────────────────────┘  │
│                                               │                                                 │
│                      ┌────────────────────────┴────────────────────────┐                        │
│                      ▼                                                 ▼                        │
│     ┌─────────────────────────────────┐               ┌─────────────────────────────────┐       │
│     │ DOCKER LIFECYCLE (olympe/)      │               │ STRIPE WEBHOOKS & AUDIT         │       │
│     │ - Quotas CPU (0.5), RAM (512m)  │               │ - POST /webhooks/stripe         │       │
│     │ - teardown_tenant idempotent    │               │ - Journal _webhook_deliveries   │       │
│     │ - Zéro conteneur / volume résidu│               │ - Journal d'audit _audit_log    │       │
│     └─────────────────────────────────┘               └─────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Tenant de Test & Cycle de Vie Idempotent (L3 & CA2)

- **Identifiant** : `clientx-orso`  
- **Nom affiché dans le Cockpit** : `CLIENTX-ORSO (TEST)` (filtrable immédiatement)
- **Quotas explicites imposés côté Docker** :
  - CPU : `0.5` vCPU (`--cpus=0.5`)
  - Mémoire RAM : `512 Mo` (`--memory=512m`, `--memory-swap=512m`)
  - Limite de processus : `100 PIDs` (`--pids-limit=100`)
  - Labels Docker : `com.orso.sandbox=true`, `com.orso.quotas.cpus=0.5`, `com.orso.quotas.memory=512m`
- **Destruction idempotente (`DELETE /api/olympe/ops/tenants/{tenant_id}`)** :
  - Arrêt forcé et suppression du conteneur (`docker rm -f orso_client_clientx_orso`)
  - Suppression de l'arborescence de données (`data/tenants/clientx-orso`)
  - Suppression de l'enregistrement `tenant_instances` Supabase
  - Deux exécutions successives renvoient `HTTP 200` avec `status: destroyed` sans lever d'erreur ni laisser de résidu.

---

## 5. Webhooks Stripe & Journal de Livraison (L5 & CA6)

- **Récepteur** : `POST /api/olympe/ops/webhooks/stripe`
- **Vérification de signature** : Valide l'en-tête `Stripe-Signature` (`t=...,v1=...`) par HMAC-SHA256 avec tolérance d'horloge (300s) si `STRIPE_WEBHOOK_SECRET` est défini.
- **Journal de livraison** : Chaque événement (`customer.subscription.created`, `invoice.payment_succeeded`, etc.) est consigné avec son horodatage ISO, identifiant `evt_...`, client Stripe et état de synchronisation du tenant.
- **Consultation autorisée** : Accessible via `GET /api/olympe/ops/webhooks/deliveries` avec la portée `webhooks:read`.

---

## 6. Modalité de Remise des Secrets (L6 & CA8)

Conformément à la règle de vigilance inviolable, **aucun secret ne transite par les commits, tickets ou fils de messagerie**.
Les identifiants et jetons sont remis sur l'hôte sous forme d'un fichier d'environnement restreint :
- **Chemin** : `~/.hermes/secrets/orso_drone.env`
- **Droits système** : `chmod 600` (lecture/écriture propriétaire strict, rejet immédiat si accessible aux tiers).
- **Structure type** :
```bash
# Configuration Drone de Test Orso (Client-X-Orso) - KAN-35
ORSO_OPS_BASE_URL=https://ops.orso-agents.fr
ORSO_DRONE_API_TOKEN=<token_machine_révocable>
ORSO_DRONE_ACTOR=drone-clientx
ORSO_TEST_TENANT_SLUG=clientx-orso
ORSO_TEST_CLIENT_EMAIL=dirigeant.clientx@test.orso-agents.fr
ORSO_TEST_CLIENT_PASSWORD=<mot_de_passe_client>
```

---

## 7. Preuves et Validation des Critères d'Acceptation (CA1 à CA8)

Suite de tests automatisée exécutée via `scripts/run_tests.sh tests/olympe/test_drone_access.py` : **8/8 tests au vert (100%)** :

- [x] **CA1** : Lecture flotte OK (`200`) et rejet systématique de `financia-solutions` (`403`).
- [x] **CA2** : Provisioning puis destruction de `clientx-orso` validés 2 fois consécutives sans résidu.
- [x] **CA3** : Rejet `403` prouvé sur création/suppression IAM, OVH et modifications Stripe.
- [x] **CA4** : Révocation immédiate validée (`401`) avec rejet de toute tentative d'auto-attribution.
- [x] **CA5** : Compte client de test isolé et formellement interdit d'accès au Cockpit OPS (`403`).
- [x] **CA6** : Événement Webhook Stripe reçu, journalisé et vérifiable via `webhooks:read`.
- [x] **CA7** : Actions enregistrées dans `_audit_log` sous l'acteur `drone-clientx`.
- [x] **CA8** : Fichier `~/.hermes/secrets/orso_drone.env` vérifié en permissions `0600` et hors git.

---

## 8. Clôture des Réserves de Sécurité PO (KAN-39 & KAN-40)

Lors de la première revue, le PO Jarvis a soulevé deux vulnérabilités critiques immédiatement colmatées :

1. **KAN-39 (Vérification Stripe obligatoire)** :
   - *Problème identifié* : En cas d'omission du header `Stripe-Signature`, la requête webhook retournait 200 sans vérification.
   - *Correction* : Rejet strict `HTTP 400 Bad Request` dès que `Stripe-Signature` est manquant ou que le HMAC SHA-256 ne correspond pas. Enregistrement actif de l'endpoint webhook sur le compte Stripe réel (`we_1UKbAc06XM8Z6gbSXgK53MPa`).
2. **KAN-40 (Sécurisation des routes legacy)** :
   - *Problème identifié* : Les routes directes `/api/olympe/tenants/provision`, `/status`, `/wake`, `/suspend` étaient non authentifiées.
   - *Correction* : Provisioning strictement réservé au rôle `superadmin` ; status/wake/suspend soumis au RBAC OPS (`require_ops_actor`) avec validation de la sandbox whitelistée. Purge immédiate du tenant résiduel `x` créé lors du test PO (DB et disque propres).

---

## 9. Déploiement en Production & Pull Request

- **Pull Request GitHub** : [PR #1 (KAN-35-access-drone-ops -> feature/ops-admin-cockpit)](https://github.com/tquinzain59/orso-core/pull/1)
- **Déploiement VPS (`92.222.68.80`)** : Branche déployée, conteneur `olympe_core` redémarré avec variables d'environnement actives (`STRIPE_WEBHOOK_SECRET`, `ORSO_DRONE_API_TOKEN`).
- **Preuves curl directes en production (`ops.orso-agents.fr`)** :
  - `GET /api/olympe/ops/webhooks/deliveries` (sans jeton) : **HTTP 401** (route existante et sécurisée)
  - `POST /api/olympe/tenants/provision` (sans jeton) : **HTTP 401** (faille KAN-40 close)
  - `POST /api/olympe/ops/webhooks/stripe` (sans signature) : **HTTP 400** (faille KAN-39 close)
  - `GET /api/olympe/ops/tenants` (avec jeton drone) : **HTTP 200** (6 tenants retournés)
  - `GET /api/olympe/ops/tenants/financia-solutions` (avec jeton drone) : **HTTP 403** (isolation sandbox garantie)
- **Récupération runner drone (CA8)** :
  ```bash
  scp -p ubuntu@92.222.68.80:~/.hermes/secrets/orso_drone.env ~/.hermes/secrets/orso_drone.env
  chmod 600 ~/.hermes/secrets/orso_drone.env
  ```

