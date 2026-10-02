# Spécification Technique KAN-58 : Espace d'Agents Propre à Chaque Client (Fin des Dossiers Partagés)

- **Date** : 02 octobre 2026
- **Auteurs** : Thibaut (Lead / PO), Antigravity (Architecte Projet)
- **Ticket Jira** : [KAN-58](https://orso-agents.atlassian.net/browse/KAN-58) (Statut : Validé / Prêt pour Revue)
- **Épique associée** : [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62) (POC d'architecture : deux artefacts)
- **Documents sources** : Confluence Document 27 (sections 2, 5, 6, 7), ADR 2026-09-30-04, ADR 2026-10-01-05 (KAN-74), Ticket KAN-33 (intégrité des personas).

---

## 1. Contexte & Problématique (Constat P1 de Document 27)

Le 30/09/2026, l'audit du superviseur Olympe (`olympe/lifecycle_manager.py`) a révélé un constat critique pour l'isolation multi-tenant :
- Dans la fonction `provision_tenant`, tous les conteneurs clients recevaient en montage direct les mêmes dossiers de l'hôte : `config`, `skills` et `profiles`, en lecture seule mais partagés entre toute la flotte.
- Seul le répertoire `/app/data` (base SQLite et mémoires) était propre à chaque client.

### Conséquences majeures identifiées :
1. **Absence d'étanchéité de configuration et de compétences** : Toute personnalisation d'un skill ou d'un profil réalisée pour un client était automatiquement montée et visible par tous les autres conteneurs.
2. **Blocage du POC d'Architecture à Deux Artefacts (Document 27)** : Aucun artefact d'espace client (KAN-60) ne pouvait produire d'effet d'isolation tant que ces montages partagés persistaient sur l'hôte.
3. **Multiplication désordonnée des points de montage de profils** : Pour satisfaire les différents chemins de découverte d'Hermes (`/app/profiles`, `/app/data/hermes_home/profiles`, `/home/orso/.hermes/profiles`), `docker-compose.orso.yml` montait trois fois le même dossier hôte partagé.

L'objectif de **KAN-58 (POC 1)** est d'éliminer définitivement ces montages partagés au profit d'un espace d'agents hermétique, propre et isolé pour chaque client, et de converger les trois points de montage de profils vers une seule source client.

---

## 2. Architecture de l'Espace Propre Client

L'infrastructure distingue désormais formellement deux racines de stockage par client :
1. **Volume de données isolé (`data_root / {tenant_slug}`)** : Monté en lecture/écriture (`RW`) sur `/app/data` (base SQLite `state.db`, mémoires, rapports, télémétrie).
2. **Espace d'agents propre (`spaces_root / {tenant_slug}`)** : Monté en lecture seule stricte (`:ro`) dans le conteneur du client, comprenant :
   - `config/` : Configuration `hermes.yaml` propre au client monté sur `/app/config:ro`.
   - `skills/` : Compétences et connecteurs métiers sur-mesure du client montés sur `/app/skills:ro`.
   - `profiles/` : Profils d'agents et `SOUL.md` du client, montés en convergence sur les 3 chemins d'exécution.

```
Hôte (Docker Engine)
├── data/tenants/
│   ├── poc-alpha/ (RW -> /app/data)
│   ├── poc-beta/  (RW -> /app/data)
│   └── poc-gamma/ (RW -> /app/data)
└── data/spaces/
    ├── poc-alpha/
    │   ├── config/   (:ro -> /app/config)
    │   ├── skills/   (:ro -> /app/skills)
    │   └── profiles/ (:ro -> /app/profiles, /app/data/hermes_home/profiles, /home/orso/.hermes/profiles)
    ├── poc-beta/
    │   ├── config/   (:ro -> /app/config)
    │   ├── skills/   (:ro -> /app/skills)
    │   └── profiles/ (:ro -> /app/profiles, /app/data/hermes_home/profiles, /home/orso/.hermes/profiles)
    └── poc-gamma/
        ├── config/   (:ro -> /app/config)
        ├── skills/   (:ro -> /app/skills)
        └── profiles/ (:ro -> /app/profiles, /app/data/hermes_home/profiles, /home/orso/.hermes/profiles)
```

---

## 3. Déclinaison des 4 Critères d'Acceptation et Preuves Réelles

Conformément à la Definition of Done du ticket KAN-58, toutes les preuves ci-dessous ont été produites sur **trois conteneurs réels en fonctionnement** (`orso_client_poc_alpha`, `orso_client_poc_beta`, `orso_client_poc_gamma`) orchestrés par `scripts/poc/execute_kan58_poc.py`.

### CA1 : Aucun conteneur client ne monte un dossier partagé avec un autre client
- **Règle** : L'intersection des points de montage hôte entre deux conteneurs quelconques doit être un ensemble strictement vide (`∅`). Aucun conteneur ne doit monter les dossiers racines partagés du projet (`./config`, `./skills`, `./profiles`).
- **Preuve par inspection Docker Inspect** :
  ```json
  Intersection A ∩ B = 0 chemin partagé
  Intersection A ∩ C = 0 chemin partagé
  Intersection B ∩ C = 0 chemin partagé
  Chemins racines partagés montés = 0
  ```
- **Résultat** : **CONFORME & PROUVÉ**.

### CA2 : Un fichier déposé dans l'espace d'un client n'est visible dans aucun autre
- **Protocole** : Dépôt du fichier témoin secret `witness_secret_alpha_kan58.txt` dans l'espace physique de `poc-alpha` (`data/spaces/poc-alpha/skills/`).
- **Vérification croisée en direct via `docker exec`** :
  - `docker exec orso_client_poc_alpha cat /app/skills/witness_secret_alpha_kan58.txt` : **TROUVÉ (200 OK, contenu vérifié)**.
  - `docker exec orso_client_poc_beta cat /app/skills/witness_secret_alpha_kan58.txt` : **ABSENT (No such file or directory, returncode != 0)**.
  - `docker exec orso_client_poc_gamma cat /app/skills/witness_secret_alpha_kan58.txt` : **ABSENT (No such file or directory, returncode != 0)**.
- **Résultat** : **CONFORME & PROUVÉ (Étanchéité absolue)**.

### CA3 : Convergence des trois points de montage de profils vers une seule source par client
- **Règle** : Les 3 destinations requises par le runtime Hermès et Orso pointent vers le même et unique répertoire `profiles/` du client dans son espace propre :
  1. `/app/profiles`
  2. `/app/data/hermes_home/profiles`
  3. `/home/orso/.hermes/profiles`
- **Preuve par inspection des montages** :
  Chacune des 3 destinations reçoit la source immuable `:ro` :
  `Source: /path/to/spaces/poc-alpha/profiles`
  La lecture de `/app/profiles/personas.lock.json` par le conteneur réussit avec intégrité validée.
- **Résultat** : **CONFORME & PROUVÉ**.

### CA4 : Procédure de retour arrière écrite, rejouée et état vérifié
- **Protocole de test** :
  1. Sauvegarde horodatée v1 créée via `manager.backup_tenant_space("poc-alpha", "v1_clean")`.
  2. Altération volontaire de l'espace client par injection d'un fichier corrompu `corrupted_config.yaml`.
  3. Vérification de la présence de l'altération dans le conteneur en direct.
  4. Exécution du retour arrière via `manager.rollback_tenant_space("poc-alpha", backup_path=backup_v1, restart_container=True)`.
  5. Vérification post-rollback : le fichier corrompu a disparu du conteneur, les fichiers essentiels (`personas.lock.json`) sont intègres, et le conteneur redémarre sainement.
- **Résultat** : **CONFORME & PROUVÉ**.

---

## 4. Préservation du Sanctuaire (Zone A) & Gouvernance

Conformément à la Charte de Gouvernance du Fork Orso :
- **Zone A (Sanctuaire)** : Aucune modification effectuée dans les moteurs d'inférence (`agent/turn_*.py`, `run_agent.py`, `conversation_loop.py`, `hermes_state*.py`, prompt caching, `providers/`, `tools/registry.py`).
- **Zone B (Évolution & Orchestration)** : Modifications circonscrites à `olympe/lifecycle_manager.py`, `olympe/server.py` et aux tests d'acceptation dans `tests/olympe/`.
- **Rétro-compatibilité** : Le mode déprécié de montages partagés legacy reste accessible sur option explicite (`use_dedicated_space=False` ou variable `ORSO_LEGACY_SHARED_MOUNTS=1`) pour tout besoin de comparaison ou de secours immédiat.
