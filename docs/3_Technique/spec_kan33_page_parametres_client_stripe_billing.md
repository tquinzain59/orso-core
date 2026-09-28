# Spécification Technique d'Architecture : Page Paramètres Client, Gestion de Compte, Sécurité et Synchronisation Stripe Billing

> **Ticket Jira associé** : [KAN-33](https://orso-agents.atlassian.net/browse/KAN-33)  
> **Composants** : `UI Client (apps/ui-client)`, `Routeur FastAPI Client (hermes_cli/web_routers/client_ui.py)`, `Supabase Auth (IAM)`, `Stripe Billing & Customer Portal`  
> **Statut** : Validé et Prêt pour Recette (100% tests unitaires & intégration)  
> **Auteur / Responsable d'instruction** : Antigravity (Architecte Système)  
> **Validation Métier & Décision** : Thibaut QUINZAIN (Direction Orso Agents)  
> **Date** : 28 Septembre 2026  

---

## 1. Contexte & Problématique Métier

Dans l'application cliente d'Orso Agents (`apps/ui-client`), un bouton **« Paramètres »** était présent dans le bandeau supérieur droit sans page fonctionnelle associée (simple modale de placeholder).

Le client final et le dirigeant d'entreprise avaient besoin d'une véritable interface pour :
1. **Consulter en toute transparence les informations de leur société** : Raison sociale, forme juridique, SIRET, SIREN, TVA intracommunautaire, adresse du siège, ainsi que les caractéristiques de leur hébergement souverain dédié (conteneur Docker isolé sur OVHcloud Gravelines en France) et les agents Orso déployés.
2. **Gérer leur compte collaborateur et la sécurité** : Nom, email, rôle, et un formulaire complet pour modifier leur mot de passe en autonomie (avec synchronisation sécurisée auprès de l'IAM Supabase Auth).
3. **Piloter l'Abonnement et la Facturation Stripe (Réservé aux Administrateurs)** :
   - Consultation du forfait actif (*Starter 99€, Duo 169€, Trio 229€, Flotte Complète 279€ HT/mois*), statut et date de renouvellement.
   - Consultation et mise à jour du moyen de paiement (Carte Bancaire ou Prélèvement SEPA).
   - Évolution de l'abonnement en temps réel (upgrade / downgrade de formule avec calcul de prorata automatique).
   - Accès autonome au portail officiel sécurisé [Stripe Customer Portal](https://billing.stripe.com).
   - Consultation de l'historique des factures et téléchargement direct des factures en format PDF officiel acquitté.

---

## 2. Architecture Globale du Flux

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              NAVIGATEUR CLIENT PWA                                     │
│                        (apps/ui-client - Port 9300)                                    │
│                                                                                        │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                          Page Paramètres (SettingsView)                        │   │
│   │  [Onglet 1] 🏢 Données Entreprise & Infrastructure Souveraine                  │   │
│   │  [Onglet 2] 👤 Profil Collaborateur & Changement de Mot de Passe               │   │
│   │  [Onglet 3] 💳 Abonnement & Facturation (Admin Only - Stripe Billing)          │   │
│   │      ├── Carte Forfait Actuel & Moyen de Paiement                              │   │
│   │      ├── Sélecteur de Formules (Starter 99€, Duo 169€, Trio 229€, Flotte 279€) │   │
│   │      ├── Accès Portail Client Stripe (Mise à jour CB / Coordonnées)            │   │
│   │      └── Historique des Factures avec Téléchargement direct PDF                │   │
│   └───────────────────────────────────────┬────────────────────────────────────────┘   │
└───────────────────────────────────────────┼────────────────────────────────────────────┘
                                            │ Requêtes HTTP REST Authentifiées (JWT)
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                  CONTENEUR BACKEND FASTAPI (hermes_cli/web_routers/client_ui.py)       │
│                                                                                        │
│   - GET  /api/client/settings/profile           -> Données Entreprise & Profil         │
│   - POST /api/client/settings/password          -> Mise à jour Mot de Passe Supabase   │
│   - GET  /api/client/billing                    -> État Abonnement & Factures Stripe   │
│   - POST /api/client/billing/subscription       -> Changement de Formule (Stripe Item) │
│   - POST /api/client/billing/portal-session     -> Session Stripe Customer Portal      │
│   - GET  /api/client/billing/invoices/{id}/pdf  -> Génération / Téléchargement PDF     │
└──────────────────┬───────────────────────────────────────────────┬─────────────────────┘
                   │                                               │
                   ▼                                               ▼
┌──────────────────────────────────────┐       ┌────────────────────────────────────────┐
│        SUPABASE IAM & DATABASE       │       │         STRIPE BILLING API             │
│                                      │       │                                        │
│  - PUT /auth/v1/admin/users/{id}     │       │  - GET  /v1/customers?email=...        │
│  - GET /rest/v1/tenants              │       │  - GET  /v1/subscriptions?customer=... │
│  - GET /rest/v1/tenant_instances     │       │  - POST /v1/subscriptions/{id}         │
│  - POST /rest/v1/subscriptions       │       │  - POST /v1/billing_portal/sessions    │
│                                      │       │  - GET  /v1/invoices?customer=...      │
└──────────────────────────────────────┘       └────────────────────────────────────────┘
```

---

## 3. Détail des Écrans et Fonctionnalités

### 3.1 Onglet Entreprise & Infrastructure (`company`)
- **Fiche légale** : Raison sociale, SIRET (14 chiffres), SIREN (9 chiffres), Numéro TVA, Forme juridique (SAS, SARL...), Secteur, Adresse complète et ville.
- **Badge de certification** : Confirmation de la conformité du compte client.
- **Infrastructure Souveraine** :
  - Nom du conteneur isolé (`orso_client_backend`).
  - Statut : `En ligne • Instance isolée`.
  - Localisation géographique : Datacenter Gravelines (France) • OVHcloud (100% souverain UE / zéro transfert US).
  - Flotte d'agents activés : Badges interactifs des agents déployés (`Jérôme`, `Lucas`, `Clara`, `Victor`).

### 3.2 Onglet Mon Profil & Sécurité (`profile`)
- **Fiche collaborateur** : Nom, prénom, email professionnel, fonction et statut d'habilitation (Administrateur / Collaborateur).
- **Formulaire de mise à jour du mot de passe** :
  - Champ mot de passe actuel (vérification cryptographique Supabase).
  - Champ nouveau mot de passe avec validation de complexité (>= 8 caractères) et bascule visuelle œil affiché/masqué.
  - Champ de confirmation avec contrôle d'égalité strict côté client et serveur.
  - Message de retour en temps réel (vert succès / rouge erreur).

### 3.3 Onglet Abonnement & Facturation (`billing` - Administrateurs uniquement)
- **Contrôle d'accès strict** : Si l'utilisateur n'a pas le flag `is_admin`, l'onglet est masqué dans l'UI et toute tentative d'accès via l'API renvoie `HTTP 403 Forbidden`.
- **Carte Forfait Actuel** :
  - Palier actif (Starter 99€, Duo 169€, Trio 229€ ou Flotte Complète 279€ HT).
  - Date d'échéance et de renouvellement.
  - Moyen de paiement par défaut enregistré (`Carte Bancaire (•••• 4242)` ou `Prélèvement SEPA`).
- **Bouton « Modifier mon moyen de paiement » & « Portail Stripe »** :
  - Appel à `POST /api/client/billing/portal-session`.
  - Ouvre une session sécurisée Stripe Customer Portal (`https://billing.stripe.com/p/session/...`) permettant au client de renseigner une nouvelle carte de crédit, un mandat SEPA, ou d'ajuster ses informations fiscales.
- **Grille de Changement de Forfait** :
  - Affichage comparatif des 4 formules Orso.
  - Badge « Formule actuelle » sur l'offre souscrite.
  - Bouton « Passer à cette formule » ouvrant une modale de confirmation explicite avec calcul du prorata temporis et synchronisation Stripe.
- **Historique des Factures** :
  - Numéro de facture (ex: `ORSO-2026-0001` ou numéro Stripe `in_...`).
  - Date d'émission, Montant HT, Montant TTC avec TVA 20%, Statut acquitté.
  - Bouton direct de téléchargement PDF déclenchant la génération d'un document PDF officiel conforme.

---

## 4. Spécification des Endpoints FastAPI (`client_ui.py`)

| Méthode | Route | Rôle requis | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/client/settings/profile` | Collaborateur | Récupère la fiche complète de l'entreprise et du profil utilisateur. |
| `POST` | `/api/client/settings/password` | Collaborateur | Valide et modifie le mot de passe utilisateur via Supabase Admin API. |
| `GET` | `/api/client/billing` | **Admin** | Interroge Stripe pour récupérer l'abonnement, la CB et les factures. |
| `POST` | `/api/client/billing/subscription` | **Admin** | Fait évoluer l'abonnement vers un nouveau palier (`1_agent` à `4_agents`). |
| `POST` | `/api/client/billing/portal-session` | **Admin** | Génère une session Stripe Customer Portal pour modifier la CB/TVA. |
| `GET` | `/api/client/billing/invoices/{id}/download`| **Admin** | Télécharge la facture au format PDF officiel. |

---

## 5. Synchronisation Stripe

### Mapping des Tarifs Officiels
```python
TIER_STRIPE_PRICES = {
    "1_agent": "price_1UKJ6W06XM8Z6gbS5id4Hf0s",    # 99.00 € HT / mois
    "2_agents": "price_1UKJ6W06XM8Z6gbScqwL1WI7",   # 169.00 € HT / mois
    "3_agents": "price_1UKJ6X06XM8Z6gbSI4buNHa3",   # 229.00 € HT / mois
    "4_agents": "price_1UKJ6X06XM8Z6gbSQekgaRHP",   # 279.00 € HT / mois
}
```

### Comportement de synchronisation
1. Lors du chargement de la facturation, le backend recherche le client Stripe via son adresse email (`customers?email=...`). S'il n'existe pas encore, il est automatiquement créé dans Stripe.
2. Les abonnements et factures émis dans Stripe sont fusionnés dynamiquement avec la base de données souveraine Orso.
3. Lors du changement de formule, le backend met à jour l'item de l'abonnement Stripe en appliquant la politique `proration_behavior=create_prorations`.

---

## 6. Respect Inviolable de la Charte de Gouvernance du Fork

Cette réalisation respecte rigoureusement la **Charte de Gouvernance du Fork** (`docs/3_Technique/charte_gouvernance_fork.md`) :
* **Sanctuaire (Zone A) 100% Inviolé** : Aucun fichier du cœur agent (`run_agent.py`, `conversation_loop.py`, `agent/turn_*.py`, cache de prompt) n'a été modifié.
* **Zone d'Évolution (Zone B)** : Toutes les fonctionnalités ont été implémentées aux bords du système dans `apps/ui-client/` et le routeur HTTP `hermes_cli/web_routers/client_ui.py`.

---

## 7. Validation & Tests Automatisés

Suite exécutée via `scripts/run_tests.sh tests/hermes_cli/test_client_settings_billing.py` :
- **10/10 tests passés au vert (100%)** :
  1. `test_get_settings_profile` : Résolution des profils et données d'entreprise.
  2. `test_password_update_validation` : Rejet des mots de passe trop courts ou non concordants.
  3. `test_password_update_success` : Mise à jour avec succès du mot de passe.
  4. `test_billing_forbidden_for_non_admin` : Rejet en `HTTP 403` pour les collaborateurs non admins.
  5. `test_billing_admin_access` : Accès administrateur aux forfaits et factures.
  6. `test_billing_update_subscription` : Passage dynamique au forfait Duo (169€ HT).
  7. `test_billing_update_subscription_forbidden_non_admin` : Blocage strict des modifications d'abonnements pour non-admins.
  8. `test_billing_portal_session` : Génération de session Stripe Customer Portal.
  9. `test_download_invoice_pdf` : Téléchargement d'un fichier PDF valide.
  10. `test_generate_invoice_pdf_content` : Vérification du contenu du PDF généré (RCS, TVA, montants).
