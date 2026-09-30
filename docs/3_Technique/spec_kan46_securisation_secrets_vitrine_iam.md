# Spécification Technique KAN-46 : Sécurisation Vitrine, Purge des Secrets & Rotation IAM

**Ticket Jira** : [KAN-46](https://orso-agents.atlassian.net/browse/KAN-46)  
**Date d'intervention** : 30/09/2026  
**Auteur** : Équipe Plateforme & Sécurité Orso Agents  
**Statut** : LIVRÉ & VALIDÉ EN PRODUCTION  

---

## 1. Contexte & Incident Initial

Le 28/09/2026, un audit PO a révélé qu'un document interne de test, `Secrets/secrets_poc.md` (94 lignes), était servi publiquement en HTTP 200 sur la vitrine officielle de production (`https://www.orso-agents.fr/Secrets/secrets_poc.md`).

### Contenu exposé :
1. **Identifiants administrateur locaux** : `admin:admin` pour l'ancienne page `admin.html`.
2. **Endpoints de télémétrie & supervision** : `http://92.222.68.80:9120`.
3. **Mots de passe des 5 comptes de démonstration Supabase Auth** :
   - `sophie.martin@finarecee20.fr` : `TempOrso2026!Financia`
   - `claire.dubois@servicallc322.com` : `TempOrso2026!Commercia`
   - `h.bernard@recoviaa60a.fr` : `TempOrso2026!Helpdesk`
   - `julien.lefevre@batiprof38f.fr` : `TempOrso2026!Batipro`
   - `amelie.petit@ventelinkc009.com` : `TempOrso2026!EuroTech`
4. **Anciennes références Airtable révoquées** (`appZo3UIR1zxIA0sv` / `patH6WnjfLFOEnpe3...`).
5. **Page `admin.html` et `monitoring.html`** servies publiquement sur le domaine vitrine.
6. **Arborescence `docs/`** exposée en fichiers statiques.

---

## 2. Actions Correctives Réalisées

### A. Vitrine de production (`orso-site` / Vercel)
1. **Suppression définitive et purge Git** :
   - Suppression de `Secrets/secrets_poc.md` et du dossier `Secrets/`.
   - Suppression de `admin.html` et `monitoring.html`.
   - Purge de l'historique Git via `git filter-branch` pour éliminer toute trace des commits antérieurs sur GitHub (`tquinzain59/orso-site`).
2. **Durcissement Vercel (`vercel.json` & `.vercelignore`)** :
   - Configuration de redirections permanentes HTTP 308 de `/admin.html`, `/admin`, `/monitoring.html`, `/monitoring` vers le cockpit officiel d'administration `https://ops.orso-agents.fr`.
   - Blocage strict du déploiement des dossiers internes (`docs/`, `Secrets/`, `scripts/`, `*.sql`, `*.md`) via `.vercelignore`.
   - Injection d'en-têtes HTTP de sécurité : `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`.
3. **Script d'audit local (`scripts/check_no_secrets.py`)** :
   - Contrôle pré-déploiement validant l'absence de tout répertoire de secrets ou motif sensible dans les fichiers servis.

### B. Moteur et IAM (`orso-core`)
1. **Rotation immédiate des mots de passe Supabase Auth (`scripts/iam/rotate_poc_credentials.py`)** :
   - Renouvellement des mots de passe des 5 comptes démo (ainsi que `test.sansenv@orso-agents.fr`) par des chaînes aléatoires de 24 caractères cryptographiquement sécurisées.
   - Révocation de toutes les sessions actives.
   - Vérification de la non-acceptation des anciens mots de passe `TempOrso2026!...` (rejet strict HTTP 400).
2. **Nettoyage du code applicatif** :
   - Remplacement des mots de passe en clair dans `scripts/iam/migrate_poc_live.py` par une génération dynamique `secrets.token_urlsafe(16)` ou variable d'environnement `POC_DEFAULT_PASSWORD`.
   - Assainissement des données de test dans `tests/hermes_cli/test_client_environment_routing.py`.
3. **Gouvernance & Sanctuaire** :
   - Invariance absolue du cœur de l'agent (`turn_*.py`, prompt cache, `run_agent.py`) conformément à la charte.

### C. Détection Continue & Non-régression
1. **Tests automatisés dans `orso-core`** (`tests/security/test_kan46_vitrine_security.py`) :
   - Sonde HTTP live validant le statut 404/410 de `secrets_poc.md`.
   - Vérification de la redirection permanente de `admin.html`.
   - Vérification du blocage de l'arborescence `docs/`.
   - Vérification de la présence de l'inventaire de révocation.
2. **Workflows GitHub Actions quotidiens (`0 6 * * *`)** :
   - Dans `orso-core` : `.github/workflows/security_daily_leak_check.yml`.
   - Dans `orso-site` : `.github/workflows/security_daily_leak_check.yml`.

---

## 3. Matrice de Preuves & Critères d'Acceptation KAN-46

| Critère KAN-46 | Attendu | Preuve d'Exécution | Statut |
| :--- | :--- | :--- | :---: |
| **Critère 1** | L'URL du document d'identifiants répond 404 ou 410 en production. | `curl -sI https://www.orso-agents.fr/Secrets/secrets_poc.md` renvoie `HTTP/2 404` (`x-vercel-error: NOT_FOUND`). | 🟢 VALIDÉ |
| **Critère 2** | Aucun mot de passe, jeton ou clé d'API n'apparaît dans le contenu servi par le site. | `scripts/check_no_secrets.py` passe à 100% avec 0 anomalie. Les fichiers sensibles (`.sql`, `docs/`, `Secrets/`) sont ignorés par `.vercelignore`. | 🟢 VALIDÉ |
| **Critère 3** | L'inventaire des identifiants révoqués est consigné (documents 11 et 14). | Consigné dans `scripts/iam/kan46_revocation_inventory.json`, synchronisé sur Confluence Page 11 (ID 65838) et Page 14 (ID 229757). | 🟢 VALIDÉ |
| **Critère 4** | La page d'administration n'accepte plus d'identifiants par défaut. | Fichier `admin.html` supprimé du site. Requête vers `/admin.html` redirigée en `HTTP/2 308` vers `https://ops.orso-agents.fr`. | 🟢 VALIDÉ |
| **Critère 5** | Un contrôle quotidien signale toute réapparition d'un fichier de secrets dans le contenu servi. | GitHub Action programmée chaque jour à 06:00 UTC dans les deux dépôts (`orso-site` et `orso-core`). | 🟢 VALIDÉ |

---

## 4. Inventaire des Identifiants Révoqués

| Utilisateur | Organisation | Rôle | Ancien Mot de Passe | Nouveau Statut Supabase | Sessions Révoquées |
| :--- | :--- | :--- | :--- | :---: | :---: |
| `sophie.martin@finarecee20.fr` | Financia Solutions | Admin / DAF | `TempOrso2026!Financia` | 🟢 Renouvelé (24 car.) | OUI |
| `claire.dubois@servicallc322.com` | CommerciaLink | Support Client | `TempOrso2026!Commercia` | 🟢 Renouvelé (24 car.) | OUI |
| `h.bernard@recoviaa60a.fr` | HelpDesk360 | Opérateur IA | `TempOrso2026!Helpdesk` | 🟢 Renouvelé (24 car.) | OUI |
| `julien.lefevre@batiprof38f.fr` | BatiPro Services | Commercial | `TempOrso2026!Batipro` | 🟢 Renouvelé (24 car.) | OUI |
| `amelie.petit@ventelinkc009.com` | EuroTech Conseil | Direction | `TempOrso2026!EuroTech` | 🟢 Renouvelé (24 car.) | OUI |
| `test.sansenv@orso-agents.fr` | Aura Sans Env. | Testeur | `TempOrso2026!SansEnv` | 🟢 Renouvelé (24 car.) | OUI |
| Accès local `admin.html` | Vitrine locale | Administrateur | `admin:admin` | 🟢 Supprimé & Redirigé | N/A |
