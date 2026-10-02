# Spécification Technique KAN-60 : Artefact d'Espace Client (Construction, Empreinte et Montage)

- **Date** : 02 octobre 2026
- **Auteurs** : Thibaut (Lead / PO), Antigravity (Architecte Projet & Développeur)
- **Ticket Jira** : [KAN-60](https://orso-agents.atlassian.net/browse/KAN-60) (Statut : Validé / Prêt pour Revue)
- **Épique associée** : [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62) (POC d'architecture : deux artefacts)
- **Documents sources** : Confluence Document 27 (sections 2, 5 et 6), ADR 2026-10-02-06 (Mécanique de montage), ADR 2026-09-30-04 (Distribution moteur), Ticket KAN-58 (Espaces propres), Ticket KAN-59 (Quotas physiques), Ticket KAN-33 (Intégrité des personas).

---

## 1. Contexte & Problématique (POC 3 - Cœur de l'Épique KAN-62)

La décision d'architecture du 30/09/2026 (Document 27) formalise le découpage du système en **Deux Artefacts** :
1. **L'artefact moteur** : Socle commun immuable, identique pour tous les clients, référencé exclusivement par son digest SHA-256 (`ghcr.io/tquinzain59/orso-engine@sha256:...`).
2. **L'artefact d'espace client** : Contient l'ensemble des données, configurations et personnalisations propres à une entreprise cliente.

Jusqu'alors, l'espace d'agents d'un client n'existait pas comme un artefact autonome : il s'agissait de répertoires copiés ou montés depuis l'hôte.
Sans artefact d'espace client versionné et scellé :
- Aucune des trois questions fondamentales du POC d'architecture (spécialisation, étanchéité, reproductibilité des retours arrière) ne pouvait recevoir de réponse formelle.
- Les mises à jour de configuration risquaient des altérations silencieuses non versionnées.

L'objectif de **KAN-60 (POC 3)** est de concevoir, implémenter, éprouver et documenter la chaîne complète de production, de scellement par empreinte, d'audit de sécurité, de montage en lecture seule et de retour arrière de l'artefact d'espace client, sans modifier le moteur commun.

---

## 2. Architecture Technique de l'Artefact d'Espace Client

### 2.1 Contenu de l'Artefact Scellé
L'artefact d'espace client regroupe exclusivement les composants métier propres au client :
- `config/hermes.yaml` : Configuration Hermès personnalisée, calibration d'invite système et paramètres d'exécution.
- `skills/` : Compétences et connecteurs métiers sur-mesure (ex: `reconciliation_poc-alpha.py`).
- `profiles/` : Personnalités d'agents (`SOUL.md`), profils métiers et manifeste de conformité cryptographique (`personas.lock.json` avec signatures HMAC KAN-33).
- `manifest.json` : Métadonnées d'intégrité, horodatage, empreinte canonique globale et inventaire unitaire des fichiers.

### 2.2 Format d'Archive et Calcul de l'Empreinte (Digest SHA-256)
L'artefact est généré sous forme d'archive déterministe `client-space-{tenant_slug}-{version}.tar.gz` :
- Propriétaires normalisés : `uid=0, gid=0, orso:orso`.
- Horodatage des membres calé sur un epoch déterministe (`1700000000`).
- Ordre des fichiers strictement trié lexicographiquement.
- L'empreinte d'identification officielle est le digest SHA-256 de l'archive scellée :
  $$\text{fingerprint} = \text{sha256:}\langle 64\text{ caractères hexadécimaux}\rangle$$
- Un digest d'arbre de contenu (*Content Merkle Tree*) garantit la traçabilité byte-for-byte du contenu indépendamment de l'archive.

### 2.3 Mécanique de Montage (ADR 2026-10-02-06)
Conformément à la contrainte du ticket KAN-60, l'**Option B (Extraction Contrôlée & Vérification Cryptographique)** a été retenue et justifiée par écrit :
1. Le superviseur `ClientSpaceArtifactManager` contrôle l'empreinte avant toute extraction (Fail-Closed en cas de mismatch).
2. L'extraction est réalisée avec protection anti-Zip Slip (rejet des chemins `..` ou absolus).
3. Les permissions hôte sont scellées (`0555` pour les répertoires, `0444` pour les fichiers).
4. Le conteneur moteur monte les dossiers en lecture seule stricte (`:ro`) :
   - `/app/config:ro`
   - `/app/skills:ro`
   - `/app/profiles:ro`, `/app/data/hermes_home/profiles:ro`, `/home/orso/.hermes/profiles:ro`
5. Les labels d'audit sont injectés dans le conteneur :
   - `com.orso.artifact.version={version}`
   - `com.orso.artifact.digest={fingerprint}`
   - `com.orso.artifact.mounted_ro=true`

---

## 3. Déclinaison des 4 Critères d'Acceptation et Preuves Réelles

Toutes les preuves ci-dessous ont été produites en direct lors de l'exécution du harnais officiel (`scripts/poc/execute_kan60_poc.py`) sur trois conteneurs réels en service (`orso_client_poc_alpha`, `orso_client_poc_beta`, `orso_client_poc_gamma`) :

### CA1 : Chaque espace client est produit depuis un artefact versionné et identifiable par une empreinte
- **Règle** : Les 3 espaces clients du POC doivent être construits sous forme d'artefacts versionnés et posséder des empreintes SHA-256 distinctes et reproductibles.
- **Preuve factuelle issue du rapport `kan60_e2e_poc_evidence.json`** :
  - **Espace `poc-alpha` (v1.0.0)** :
    - Empreinte : `sha256:f0c1226bd0d7f58e488c24329922b29b8dd4b9823016cf69f45fa553117f196f`
    - Fichiers : 4 fichiers (`config/hermes.yaml`, `profiles/jerome/SOUL.md`, `profiles/personas.lock.json`, `skills/reconciliation_poc-alpha.py`)
    - Taille archive : 664 octets
  - **Espace `poc-beta` (v1.0.0)** :
    - Empreinte : `sha256:46dc4d60d63dfa7cb9f62a1fa02b66736c4544aa6a4c79cd4f40ac3a678bdffe`
    - Fichiers : 4 fichiers
    - Taille archive : 661 octets
  - **Espace `poc-gamma` (v1.0.0)** :
    - Empreinte : `sha256:68174b4d59f5e64e701898c30fac1bd8da5fc6870addc37eebe6601a0c58d4c7`
    - Fichiers : 4 fichiers
    - Taille archive : 664 octets
  - Les 3 empreintes sont 100 % uniques, vérifiées cryptographiquement avec intégrité validée.
- **Résultat** : **CONFORME & PROUVÉ (100%)**.

### CA2 : L'artefact est monté en lecture seule dans le conteneur du client et de personne d'autre
- **Règle** : L'espace est monté exclusivement en `:ro` dans le conteneur du client concerné. Toute tentative d'écriture dans `/app/config/` ou `/app/skills/` doit échouer avec l'erreur système `Read-only file system`.
- **Preuve factuelle par `docker inspect` et `docker exec`** :
  - `docker inspect orso_client_poc_alpha` : `RW: false` sur les 4 montages d'espace.
  - `docker exec orso_client_poc_alpha touch /app/config/illegal_write_test.txt` :
    `touch: cannot touch '/app/config/illegal_write_test.txt': Read-only file system` (Code sortie != 0).
  - `docker exec orso_client_poc_alpha touch /app/skills/illegal_skill_test.txt` :
    `touch: cannot touch '/app/skills/illegal_skill_test.txt': Read-only file system` (Code sortie != 0).
  - Mêmes résultats validés à l'identique sur `orso_client_poc_beta` et `orso_client_poc_gamma`.
- **Résultat** : **CONFORME & PROUVÉ (100%)**.

### CA3 : Une modification d'espace produit une nouvelle version, et le retour arrière est possible et rejoué
- **Règle** : Une modification entraîne la construction d'une nouvelle version (v2.0.0) avec son empreinte propre. Le retour à la v1.0.0 restaure fidèlement l'état initial, redémarre le conteneur et purge la v2.
- **Preuve factuelle** :
  1. Construction de `poc-alpha` v2.0.0 : nouvelle empreinte `sha256:d7e6054d631395a5acd3bda11ddf0e71ee24addfe4c2ffa6b85b719e2a998ffb`.
  2. Déploiement de la v2.0.0 et redémarrage conteneur : `CALIBRATION V2 UPGRADE` active dans `/app/config/hermes.yaml`.
  3. Déclenchement du retour arrière : `manager.rollback_tenant_artifact("poc-alpha", "1.0.0")`.
  4. Redémarrage conteneur validé (`container_restarted: true, container_healthy: true`).
  5. Vérification post-rollback en direct : `/app/config/hermes.yaml` a retrouvé la calibration initiale v1.0.0 (`Calibration exclusive pour poc-alpha`), et toute trace de la v2 a disparu.
- **Résultat** : **CONFORME & PROUVÉ (100%)**.

### CA4 : Aucun secret ne figure dans un artefact
- **Règle** : Compteur de secrets strictement nul dans les artefacts légitimes. Rejet immédiat (Fail-Closed) à la moindre détection de clé API ou token lors de la construction.
- **Preuve factuelle** :
  1. Audit récursif des 3 artefacts produits : `total_secrets_detected: 0` (bilan vierge).
  2. Test d'injection volontaire d'une fausse clé `sk-proj-...` dans `test-secret-injection/config/leak.yaml` :
     - Rejet immédiat par `ClientSpaceArtifactManager.build_artifact` avec exception `ERR_SECRET_DETECTED_IN_ARTIFACT`.
     - Message d'erreur : `1 violation(s) de secrets détectée(s) (CA4). Détails: [{"file": "config/leak.yaml", "type": "OpenAI Project API Key (sk-proj-)", "count": 1}]`.
     - Zéro fichier d'artefact persisté sur le disque.
- **Résultat** : **CONFORME & PROUVÉ (100%)**.

---

## 4. Points de Terminaison API Olympe (Supervision & Cockpit)

Les points d'entrée suivants sont intégrés dans l'API Olympe (`olympe/server.py`) pour la gestion des artefacts par le Cockpit Ops et les automates :

- `GET /api/olympe/ops/tenants/{slug}/artifacts` : Liste les versions disponibles avec leurs empreintes SHA-256.
- `GET /api/olympe/ops/tenants/{slug}/artifacts/{version}` : Inspecte le manifeste et vérifie l'intégrité de l'archive.
- `POST /api/olympe/ops/tenants/{slug}/artifacts/build` : Déclenche la construction d'une nouvelle version d'artefact.
- `POST /api/olympe/ops/tenants/{slug}/artifacts/deploy` : Déploie une version d'artefact dans l'espace client et redémarre le conteneur.
- `POST /api/olympe/ops/tenants/{slug}/artifacts/rollback` : Réexécute un retour arrière vers une version d'artefact antérieure.

---

## 5. Respect de la Charte de Gouvernance du Fork (Sanctuaire Intact)

- **Sanctuaire Orso (Zone A)** : `agent/turn_*.py`, `run_agent.py`, `conversation_loop.py`, `hermes_state*.py`, `providers/`, `tools/registry.py` -> **0 modification**.
- **Zone d'Évolution (Zone B)** : Toute l'architecture d'artefacts d'espace client réside dans `olympe/artifact_manager.py`, `olympe/lifecycle_manager.py` et `olympe/server.py`.
- **Suite de tests** : 13 fichiers de tests, 100 tests unitaires et d'acceptation validés à 100% (`tests/olympe/test_kan60_acceptance.py`).
