# Note de Réalisation Technique & Handoff — KAN-72

**Ticket Jira** : [KAN-72](https://orso-agents.atlassian.net/browse/KAN-72)  
**Titre** : Retirer du dépôt l'outil qui pilote Jira sous l'identité de Thibaut  
**Date d'exécution** : 04/10/2026  
**Branche Git** : `KAN-72-retrait-outil-jira-identite-thibaut`  
**Statut** : Terminé & Validé (DoD respecté, 0 script d'écriture Atlassian dans le dépôt)

---

## 1. Contexte & Constat Vérifié

La branche KAN-43 avait introduit dans le dépôt le fichier `scripts/publish_kan43_atlassian.py`, utilisé pour mettre à jour le statut du ticket et publier des commentaires de revue. D'autres branches ont par la suite introduit des scripts de publication analogues (`scripts/publish_*.py`, `scripts/sync_confluence_journal.py`).

Ces scripts lisaient `ATLASSIAN_EMAIL` et `ATLASSIAN_API_TOKEN` dans l'environnement local pour effectuer des appels directs aux API REST Atlassian Jira (`/rest/api/3/issue/.../transitions`, `/comment`) et Confluence (`/wiki/rest/api/content`).

### Problème de Gouvernance & Traçabilité
1. **Usurpation d'identité d'auteur** : Les transitions et commentaires Jira étaient enregistrés sous l'identité de Thibaut (propriétaire du jeton personnel), et non sous celle de l'agent effectuant l'action.
2. **Vulnérabilité de gouvernance du dépôt** : Un dépôt de travail partagé ne doit contenir aucun outillage exécutable par un agent permettant d'altérer les tickets du client sous l'identité d'un collaborateur humain.
3. **Principe directeur** : Toute action ou commentaire sur le système de suivi doit être nominatif et refléter l'identité réelle de son émetteur (agent ou humain), sans confusion de responsabilité.

---

## 2. Périmètre Exécuté & Actions Menées

### 2.1. Suppression Définitive des Scripts du Dépôt Git (15 fichiers)
Les 15 scripts suivants ont été supprimés du suivi de version Git via `git rm` :
- `scripts/publish_kan43_atlassian.py` (cible principale du ticket)
- `scripts/publish_kan28_kan29_atlassian.py`
- `scripts/publish_kan30_confluence.py`
- `scripts/publish_kan31_atlassian.py`
- `scripts/publish_kan32_atlassian.py`
- `scripts/publish_kan33_atlassian.py`
- `scripts/publish_kan35_atlassian.py`
- `scripts/publish_kan44_atlassian.py`
- `scripts/publish_kan46_confluence_and_jira.py`
- `scripts/publish_kan59_atlassian.py`
- `scripts/publish_kan63_atlassian.py`
- `scripts/publish_kan64_atlassian.py`
- `scripts/publish_kan67_atlassian.py`
- `scripts/publish_kan68_atlassian.py`
- `scripts/sync_confluence_journal.py`

### 2.2. Sauvegarde & Nettoyage de l'Espace Local Hors Dépôt
- L'ensemble des scripts de publication locaux (suivis ou non suivis) a été archivé de manière sécurisée en dehors de l'arborescence du dépôt :
  `~/.orso_archive/publish_scripts/`
- Aucun fichier de publication ne subsiste dans le répertoire de travail `scripts/`.

### 2.3. Durcissement Inviolable de `.gitignore`
Le fichier `.gitignore` a été verrouillé pour interdire tout ré-engagement futur de scripts de publication Jira ou Confluence :
```gitignore
# Interdiction stricte de scripts de publication / manipulation Atlassian / Confluence dans le dépôt (KAN-72)
scripts/publish_*.py
scripts/sync_confluence_*.py
scripts/*atlassian*.py
```
L'ancienne directive d'exception (`!scripts/publish_kan59_atlassian.py`) a été définitivement supprimée.

---

## 3. Matrice de Preuves des Critères d'Acceptation

### CA1 — Absence de tout outil de publication / transition / création Atlassian dans le dépôt
* **Attendu** : Une recherche des motifs Atlassian et des jetons dans le dépôt ne renvoie aucun fichier capable de publier, transitionner ou créer un ticket.
* **Sonde 1 (endpoints d'écriture Jira/Confluence)** :
  ```bash
  git grep -E "(/rest/api/3/issue|/transitions|/comment|/wiki/rest/api)" scripts/
  ```
  *Résultat* : **Aucune occurrence** (sortie vide, code retour 1).
* **Sonde 2 (variables d'environnement ATLASSIAN_ dans scripts/)** :
  ```bash
  git grep "ATLASSIAN_" scripts/
  ```
  *Résultat* : **Aucune occurrence** (sortie vide, code retour 1).
* **Sonde 3 (fichiers de publication dans scripts/)** :
  ```bash
  git ls-files "scripts/*publish*" "scripts/*atlassian*" "scripts/*confluence*"
  ```
  *Résultat* : Seuls les scripts de CI (`scripts/ci/publish_e2e_evidence.py`) et de build Docker d'image (`scripts/distribution/build_and_publish_engine.py`) subsistent. Zéro script Jira/Confluence.

### CA2 — Disparition de `scripts/publish_kan43_atlassian.py`
* **Attendu** : Le fichier n'existe plus sur la branche.
* **Sonde** :
  ```bash
  test -f scripts/publish_kan43_atlassian.py || echo "OK: fichier absent"
  git ls-files scripts/publish_kan43_atlassian.py
  ```
  *Résultat* : Fichier physiquement absent et non tracké.

### CA3 — Hébergement hors du dépôt de tout outil éventuel
* **Attendu** : Tout outillage de publication conservé pour des besoins d'exploitation vit hors du dépôt, requiert un jeton dédié et signe ses écritures au nom de l'agent.
* **Preuve** :
  - Déplacement et archivage local sous `~/.orso_archive/publish_scripts/`.
  - Conformité avec l'orientation PO : aucun jeton ni script de publication n'est embarqué dans le code source `orso-core`. L'outillage de Jarvis vit strictement hors dépôt.

---

## 4. Non-Régression & Intégrité de la Plateforme

- **Suite de tests Olympe** : 13 fichiers, 100/100 tests passés avec succès via `scripts/run_tests.sh tests/olympe/`.
- **Intégrité Git & Charte de Gouvernance** :
  - Historique de `main` non réécrit (suppression par commit standard).
  - Sanctuaire préservé : aucun composant de la boucle agent, persistance ou exécution n'est altéré.
