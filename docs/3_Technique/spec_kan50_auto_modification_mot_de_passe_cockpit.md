# Spécification Technique & Sécurité : Auto-modification du Mot de Passe Cockpit OPS (KAN-50)

> **Projet** : Orso Agents  
> **Composant** : Cockpit OPS (`apps/ui-ops`), Superviseur Olympe (`olympe/`) & IAM Supabase Auth  
> **Ticket Jira associé** : [KAN-50](https://orso-agents.atlassian.net/browse/KAN-50)  
> **Date de réalisation** : 30/09/2026  
> **Auteur** : Antigravity (Architecte Projet Orso Agents)  
> **Statut** : Validé & Conforme aux critères d'acceptation CA1 à CA10  

---

## 1. Contexte & Objectifs

Dans le cadre du durcissement de la sécurité d'Orso Agents suite aux tickets KAN-46 et KAN-49, l'administrateur unique de la plateforme (**Thibaut Quinzain**) devait pouvoir modifier son mot de passe superadmin en toute autonomie et de manière récurrente directement depuis le Cockpit OPS (`https://ops.orso-agents.fr`), sans avoir à se connecter en SSH au serveur VPS OVH ni manipuler de console SQL.

Le ticket KAN-50 a été articulé en deux temps :
1. **Lot 1 (Urgent)** : Rotation d'urgence immédiate du mot de passe superadmin actuel avec les outils existants, horodatage consigné dans le ticket.
2. **Lot 2 (Fonctionnalité pérenne)** : Implémentation du libre-service d'auto-modification dans le Cockpit OPS, assorti d'une politique de sécurité stricte, d'un anti-bruteforce, d'une invalidation de session, d'un journal d'audit et d'une procédure de secours d'urgence CLI.

---

## 2. Matrice de Conformité aux Critères d'Acceptation

| Critère | Description | Statut | Preuve d'implémentation |
| :--- | :--- | :---: | :--- |
| **CA1** | Interface libre-service dans Cockpit OPS | ✅ Conforme | Composant `AccountSecurityModal.tsx` accessible via icône `KeyRound` dans la `Navbar.tsx` |
| **CA2** | Contexte d'administrateur unique & procédure de secours | ✅ Conforme | Contexte Thibaut Quinzain (`admin@orso-agents.fr`), secours via `scripts/iam/reset_superadmin_password.py` |
| **CA3** | Formulaire strict à 3 champs (Ancien, Nouveau, Confirmation) | ✅ Conforme | Modèle `ChangePasswordRequest`, vérification obligatoire de l'ancien mot de passe via Supabase Auth |
| **CA4** | Politique de complexité stricte | ✅ Conforme | Longueur ≥ 12, majuscule, minuscule, chiffre, symbole, rejet des termes triviaux (`admin`, `orso`...) et de l'identique |
| **CA5** | Stockage 100% hashé & prise d'effet immédiate (0ms) | ✅ Conforme | Mise à jour via API Admin Supabase Auth (`PUT /auth/v1/admin/users/{id}`), 0ms, sans redémarrage de conteneur |
| **CA6** | Invalidation de session et révocation des jetons | ✅ Conforme | Appel `revoke_token(token)` et `clear_token_cache()`, déconnexion automatique côté front |
| **CA7** | Protection anti-bruteforce / rate limiting | ✅ Conforme | Registre `_FAILED_ATTEMPTS` limitant à max 5 tentatives consécutives échouées / 15 min par IP et compte |
| **CA8** | Procédure de secours d'urgence CLI | ✅ Conforme | Script autonome `scripts/iam/reset_superadmin_password.py` avec génération aléatoire et validation de flux |
| **CA9** | Journal d'audit sans secret en clair ni condensat | ✅ Conforme | Fichier `ops_auth_audit.json`, endpoint `GET /api/olympe/ops/auth/audit-log`, affichage dans la modale |
| **CA10** | Préservation absolue du Sanctuaire Orso | ✅ Conforme | 0 modification dans `agent/turn_*.py`, `run_agent.py`, `hermes_state*.py`, `providers/`, `tools/` |

---

## 3. Architecture Technique

### 3.1 Backend Olympe (`olympe/auth.py` & `olympe/server.py`)

1. **`change_superadmin_password(...)`** :
   - Vérifie le rate limiting de l'IP et du compte appelant (`check_rate_limit`).
   - Valide la conformité du mot de passe avec `validate_password_policy`.
   - Vérifie l'ancien mot de passe en réalisant une requête vers Supabase Auth `POST /auth/v1/token?grant_type=password`. En cas d'échec, enregistre une tentative infructueuse (`record_failed_attempt`) et lève une exception HTTP 400.
   - Met à jour le mot de passe via l'API Admin de Supabase (`PUT /auth/v1/admin/users/{user_id}`).
   - Révoque immédiatement le jeton Bearer actif (`revoke_token`) et vide le cache mémoire TTL (`clear_token_cache`).
   - Enregistre un événement de succès dans le journal d'audit (`append_auth_audit_event`).

2. **Endpoints FastAPI exposés** :
   - `POST /api/olympe/ops/auth/change-password` : Protégé par `require_superadmin`. Accepte `current_password`, `new_password` et `confirm_password`.
   - `GET /api/olympe/ops/auth/audit-log` : Protégé par `require_superadmin`. Renvoie les 50 derniers événements d'audit sans secret.
   - `POST /api/olympe/ops/auth/logout` : Amélioré pour révoquer explicitement le jeton d'authentification transmis.

### 3.2 Frontend Cockpit OPS (`apps/ui-ops`)

1. **`AccountSecurityModal.tsx`** :
   - Onglet 1 : **Formulaire de modification** avec masquage/démasquage des mots de passe (icônes œil), indicateurs visuels des exigences de sécurité en temps réel (vert/gris), alerte de confirmation d'invalidation de session.
   - Onglet 2 : **Journal d'audit** affichant l'historique des modifications (date UTC, IP, action, statut vert/rouge).
   - Onglet 3 : **Procédure de secours CLI** documentant les commandes d'urgence pour l'administrateur.
2. **`Navbar.tsx`** :
   - Ajout d'un bouton d'accès direct `KeyRound` dans le bandeau supérieur à côté du profil utilisateur.
3. **`App.tsx` & `api.ts`** :
   - Fonctions `changeSuperadminPassword` et `fetchAuthAuditLog`. Déconnexion automatique et redirection vers l'écran de connexion dès modification réussie.

---

## 4. Procédure de Secours d'Urgence CLI (CA8)

En cas d'oubli ou d'indisponibilité du mot de passe superadmin, l'administrateur unique dispose du script `scripts/iam/reset_superadmin_password.py`.

### Génération automatique d'un mot de passe fort
```bash
python3 scripts/iam/reset_superadmin_password.py --email admin@orso-agents.fr --generate
```

### Définition manuelle d'un mot de passe
```bash
python3 scripts/iam/reset_superadmin_password.py --email admin@orso-agents.fr --password "VotreMotDePasseComplexe123!"
```

**Garanties de sécurité du script CLI** :
- Lit `SUPABASE_URL` et `SUPABASE_SERVICE_ROLE_KEY` depuis l'environnement ou le fichier `.env`.
- Valide immédiatement la politique de sécurité (longueur ≥ 12, caractères variés, non-trivial).
- Met à jour le compte dans `auth.users` via l'API Admin de Supabase.
- Teste immédiatement l'authentification avec `grant_type=password` pour certifier l'accès.
- Consigne l'opération dans `ops_auth_audit.json` sans exposer le mot de passe.

---

## 5. Journal d'Audit & Protection des Secrets (CA9)

Le journal d'audit est stocké localement dans `get_hermes_home() / "ops_auth_audit.json"` (profile-aware et container-aware).

### Format d'enregistrement :
```json
{
  "timestamp": "2026-09-30T08:11:16.166407+00:00",
  "action": "reset_cli",
  "account": "admin@orso-agents.fr",
  "ip": "127.0.0.1",
  "result": "success",
  "reason": null
}
```

**Règle absolue d'hygiène** : Aucun mot de passe en clair, condensat (hash), clé d'API ou secret n'est jamais consigné dans ce fichier.
