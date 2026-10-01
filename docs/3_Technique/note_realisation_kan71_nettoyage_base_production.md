# Note de Réalisation Technique & Handoff — KAN-71

**Ticket Jira** : [KAN-71](https://orso-agents.atlassian.net/browse/KAN-71)  
**Titre** : Base de production : retirer les clients fictifs amorcés par les scripts du POC, conserver financia-solutions et nexis-solutions  
**Date d'exécution** : 01/10/2026  
**Branche Git** : `KAN-71-nettoyage-base-production`  
**Base cible** : PostgreSQL / Supabase Production (`nyntmjorcqgbzaxszekk`)  
**Statut** : Terminé & Validé (68/68 tests automatisés, conformité Charte de Gouvernance)

---

## 1. Contexte & Problématique

Lors de la mise en place initiale du POC Orso Agents, des scripts d'amorçage (`scripts/iam/01_init_supabase_complete.sql`, `scripts/iam/02_add_target_environment_and_alerts.sql`, `scripts/iam/migrate_poc_live.py`) ont injecté dans la base PostgreSQL de production des organisations clientes de démonstration issues du POC.

Le Cockpit OPS lisant la base de production, ces organisations apparaissaient dans l'annuaire et faussaient les indicateurs de flotte et de facturation. Par ailleurs, l'organisation `aura-sans-env` faisait l'objet d'un filtrage en dur dans `olympe/ops_manager.py` (ligne 746).

L'intervention KAN-71 a pour objectifs :
1. **Assainissement de la base** : Purger définitivement les organisations de POC tout en préservant strictement les clients réels et qualifiés (`financia-solutions` et `nexis-solutions`).
2. **Cantonnement inviolable des scripts** : Sécuriser tous les scripts sous `scripts/iam/` pour interdire tout réamorçage intempestif en production (gardes multi-variables d'environnement, exigence de flags explicites, exclusion des sauvegardes du dépôt git).
3. **Suppression du contournement en dur** : Nettoyer `olympe/ops_manager.py` de toute référence à `aura-sans-env` (CA6).
4. **Anonymisation et hygiène de sécurité** : Garantir l'absence totale de données personnelles (PII) et d'extraits de base bruts dans le dépôt public.

---

## 2. Inventaire Préalable & Croisement (CA1)

L'inventaire de la table `public.tenants` a recensé 7 organisations avant purge :

| Organisation | Slug | SIRET | Rapprochement Scripts | Décision |
|---|---|---|---|---|
| **Financia Solutions** | `financia-solutions` | 83214567800012 | Organisation réelle (PROD-FR-002) | **CONSERVÉE** |
| **Nexis Solutions** | `nexis-solutions` | 45754525474 | Organisation réelle/qualifiée (PROD-FR-003) | **CONSERVÉE** |
| **CommerciaLink** | `commercialink` | 78451236900021 | Amorçage POC (`01_init_supabase_complete.sql`) | **PURGÉE** |
| **HelpDesk360** | `helpdesk360` | 88997766500033 | Amorçage POC (`01_init_supabase_complete.sql`) | **PURGÉE** |
| **BatiPro Services** | `batipro-services` | 90123456700038 | Amorçage POC (`01_init_supabase_complete.sql`) | **PURGÉE** |
| **EuroTech Conseil** | `eurotech-conseil` | 55566677700044 | Amorçage POC (`01_init_supabase_complete.sql`) | **PURGÉE** |
| **Aura Sans Environnement** | `aura-sans-env` | 99988877700011 | Test alerte (`02_add_target_environment_and_alerts.sql`) | **PURGÉE** |

---

## 3. Sauvegarde & Procédure de Rollback (CA5)

### 3.1. Hygiène des Dépôts et Sécurité
Le dépôt étant public, les sauvegardes et données brutes de production ne doivent **en aucun cas** être suivies par Git :
- Ajout strict de `scripts/iam/backups/`, `*.dump` et `*.backup` dans `.gitignore`.
- Aucune donnée nominative (noms, téléphones, courriels réels) n'est consignée dans la documentation.

### 3.2. Sauvegarde Exhaustive Pre-Purge
Avant la suppression en production, une sauvegarde JSON exhaustive a été générée localement :
- **Tables couvertes** : `tenants`, `profiles`, `tenant_instances`, `agent_instances`, `subscriptions`, `tenant_integrations`, `tenant_channels`, `invoices`, `audit_logs`, `processed_events`, et `auth.users`.
- **Emplacement local (non tracké)** : `scripts/iam/backups/backup_kan71_pre_purge_*.json`.

### 3.3. Script de Restauration d'Urgence (Rollback)
Le script `scripts/iam/rollback_kan71.py` prend en charge l'ensemble des tables en cascade :
- **Mode simulation par défaut** (`--dry-run`).
- **Exécution contrôlée** nécessitant les drapeaux `--execute` et `--confirm-rollback` :
  ```bash
  .venv/bin/python scripts/iam/rollback_kan71.py --execute --confirm-rollback scripts/iam/backups/<fichier_backup>.json
  ```

---

## 4. Exécution de la Purge & Preuves de Contrôle (CA2 & CA3)

### 4.1. Double Verrouillage du Script de Purge
Le script `scripts/iam/clean_production_database_kan71.py` intègre un verrouillage strict :
- Exécution par défaut en **simulation passive** (`--dry-run`).
- L'exécution réelle exige `--execute` ET `--confirm-purge-production`.

### 4.2. Bilan de la Purge
- **Organisations supprimées** : 5 (`commercialink`, `helpdesk360`, `batipro-services`, `eurotech-conseil`, `aura-sans-env`).
- **Profils associés supprimés** : 5.
- **Instances conteneurs supprimées** : 4.
- **Comptes Auth associés purgés** : 5.
- **Organisations conservées intactes** : 2 (`financia-solutions`, `nexis-solutions`).

### 4.3. Vérification CA2 (Absence des Slugs Purgés)
La requête de contrôle sur les 5 slugs purgés renvoie **0 ligne** :
```sql
SELECT count(*) FROM public.tenants
WHERE slug IN ('commercialink', 'helpdesk360', 'batipro-services', 'eurotech-conseil', 'aura-sans-env');
-- Résultat : 0
```

### 4.4. Vérification CA3 (Intégrité des Clients Conservés)
- `financia-solutions` : 1 profil utilisateur, 1 instance conteneur (`PROD-FR-002`), 1 abonnement actif (Forfait Trio - 3 agents).
- `nexis-solutions` : 1 profil utilisateur, 1 instance conteneur (`PROD-FR-003`), 1 abonnement actif (Forfait Starter - 1 agent).

---

## 5. Métriques du Cockpit OPS (CA4)

Relecture directe des indicateurs calculés par `OpsManager.get_stats()` :
- **Total clients** : 2
- **Abonnements actifs** : 2
- **MRR HT** : 328,00 € (229,00 € pour Financia Solutions + 99,00 € pour Nexis Solutions)
- **MRR TTC** : 393,60 €
- **ARR HT** : 3 936,00 €

Corroboré fidèlement par la sonde publique du Cockpit OPS en ligne.

---

## 6. Retrait du Filtrage en Dur (CA6)

Le filtrage conditionnel qui excluait artificiellement `aura-sans-env` dans `olympe/ops_manager.py` (ligne 746) a été supprimé.
L'analyse de l'arborescence confirme qu'aucune référence résiduelle n'existe :
```bash
grep -rn "aura-sans-env" olympe/
# Résultat : 0 occurrence
```

---

## 7. Cantonnement des Scripts d'Amorçage (scripts/iam)

Pour prévenir tout risque de réintroduction ou d'exécution accidentelle en production :
1. **`scripts/iam/migrate_poc_live.py`** :
   - Vérification multi-variables : teste `ORSO_ENV`, `APP_ENV`, `ENVIRONMENT`, `ENV`. L'exécution est immédiatement bloquée avec une erreur si l'une d'entre elles vaut `production` ou `prod`.
   - Blocage formel si l'URL Supabase contient l'identifiant du projet de production (`nyntmjorcqgbzaxszekk`).
   - Aucune URL de production par défaut (`SUPABASE_URL` obligatoire).
   - Exigence obligatoire du drapeau `--allow-dev-seed`.
2. **`scripts/iam/01_init_supabase_complete.sql`** :
   - Section 8 épurée : seules les structures nécessaires sont conservées, les 4 organisations POC ont été retirées.
3. **`scripts/iam/02_add_target_environment_and_alerts.sql`** :
   - Section 5 (création d'`aura-sans-env`) supprimée.
4. **`scripts/iam/05_consistency_locks_and_reality_alignment.sql`** :
   - Suppression du ciblage par slug des 5 organisations purgées ; application générique des verrous de cohérence.

---

## 8. Validation des Tests & Respect du Sanctuaire

- **Exécution de la suite de tests automatisés** :
  ```bash
  scripts/run_tests.sh tests/olympe/
  # Résultat : 68 tests exécutés, 68 validés (100% au vert)
  ```
- **Respect absolu du Sanctuaire** :
  - Aucun fichier du Sanctuaire (`agent/turn_*.py`, `run_agent.py`, `conversation_loop.py`, `hermes_state*.py`, prompt caching, `providers/`) n'a été modifié.
  - Toutes les modifications sont strictement cantonnées aux interfaces Olympe (`olympe/ops_manager.py`), aux scripts d'administration (`scripts/iam/`), à la configuration Git (`.gitignore`) et à la documentation (`docs/3_Technique/`).
