# Requalification KAN-64 — la prémisse du ticket n'est plus vraie pour le code

Date de relevé : 12/10/2026. Branche : `KAN-64-auto`, HEAD = `main` (`c13b03698c`). Aucune modification de code n'a été faite.

## 1. Ce que le ticket affirme (constat du 30/09/2026 sur `KAN-63-distribution-image-moteur`, c01e92a6)

| # | Affirmation | État sur `main` au 12/10/2026 |
|---|---|---|
| a | Aucun workflow/script ne construit ni ne publie `ghcr.io/tquinzain59/orso-engine` | **Faux** — `.github/workflows/publish_orso_engine.yml` et `scripts/distribution/build_and_publish_engine.py` existent |
| b | `audit_hosts_drift` reçoit un inventaire en paramètre, aucun démon interrogé, aucune connexion distante | **Faux** — `probe_docker_host` + `run_remote_or_local_cmd` (ssh `BatchMode=yes`) interrogent `docker ps` / `docker inspect` |
| c | `execute_host_update` / `execute_host_rollback` ne modifient qu'une structure en mémoire | **Faux** — exécutent `docker pull`, `stop`, `rm`, `run` et une sonde de santé via `run_remote_or_local_cmd` (l. 294-416) |
| d | Compteur de données client = 0 en dur (audit, l. 151) | **Faux** — `client_data_count = len(client_data_violations)` (l. 391), alimenté aussi par l'inspection de l'image (`audit_docker_image_for_secrets_and_client_data`) |
| e | `lifecycle_manager.py` n'a aucune branche de refus | **Faux** — `ERR_DIGEST_REQUIRED` et `ERR_INVALID_DIGEST` (l. 1080-1112) |
| f | Variable de digest divergente spec / code | **Faux** — `ORSO_TARGET_ENGINE_DIGEST` canonique, repli sur `ORSO_BACKEND_IMAGE_DIGEST` ; spec (l. 61, 150) et ADR (§4.3) alignés |
| g | Empreintes de démonstration dans ADR, spec, tests | **Partiellement vrai** — voir §4 (ADR et spec ne contiennent plus de `sha256:` ; reste une valeur par défaut de démonstration dans le code) |

L'historique montre que ce travail est déjà livré : `d8e4e65060 [KAN-64] POC : execution reelle de la distribution…` (01/10/2026) et ses commits `50fbe801c9`, `c91a966be5`, `8aa50cc0f6`, `d0c099e21d`, `53b791bcb5`, `0986522e78`, tous ancêtres de `main`
(`git merge-base --is-ancestor d8e4e65060 HEAD` → `yes`).

## 2. Commandes et sorties brutes

```
$ ruff check scripts/distribution scripts/security/audit_zero_secrets_and_client_data.py olympe/lifecycle_manager.py tests/distribution
All checks passed!
rc=0

$ scripts/run_tests.sh tests/distribution tests/olympe/test_kan74_acceptance.py tests/olympe/test_kan43_kan44_acceptance.py
Discovered 4 test files (~29 tests) …
✓ tests/olympe/test_kan74_acceptance.py (5✓)
✓ tests/olympe/test_kan43_kan44_acceptance.py (13✓)
✓ tests/distribution/test_kan63_engine_distribution.py (5✓)
✓ tests/distribution/test_kan64_execution_reelle_distribution.py (6✓)
=== Summary: 4 files, 29 tests passed, 0 failed ===
rc=0

$ python scripts/security/audit_zero_secrets_and_client_data.py        # sans référence d'image
✗ Erreur CA5 : Référence d'image Docker obligatoire en paramètre (ex: ghcr.io/tquinzain59/orso-engine@sha256:... ou via ORSO_TARGET_ENGINE_DIGEST).
rc=1   (comportement attendu : l'audit refuse de ne scanner que l'arbre de travail ; un traceback s'ensuit faute de Docker local)
```

`which docker gh` ne retourne rien sur cette machine : l'inspection d'image (CA5) et la publication (CA1) ne peuvent pas être rejouées ici.

## 3. Ce qui reste réellement à faire (non faisable depuis cette passe)

Le code et l'outillage sont en place ; ce qui manque est l'**exécution réelle et ses preuves brutes** (CA1 à CA6 « en conditions réelles »). Conditions exactes qui lèvent chaque point :

- **CA1** : déclencher le workflow `publish_orso_engine.yml` (`workflow_dispatch`) sur GitHub, relever l'empreinte dans la sortie du job, relire le manifeste par cette empreinte (`docker buildx imagetools inspect ghcr.io/tquinzain59/orso-engine@sha256:…`), écrire l'empreinte dans Jira. Nécessite accès GitHub Actions (hors de portée de cet agent).
- **CA2/CA3/CA4** : jeton classique `read:packages` posé dans un fichier `0600` sur chaque hôte, puis exécution de `engine_image_manager.py` (probe, update, rollback) sur `prod-fr-003` (57.131.196.106) **avec l'approbation écrite de Thibaut à chaque commande** (décision du 30/09). Aucune commande distante n'a été lancée ici, faute de cette approbation.
- **CA5** : Docker local ou accès à `prod-fr-003`, puis `audit_zero_secrets_and_client_data.py ghcr.io/tquinzain59/orso-engine@sha256:<empreinte publiée>` pour obtenir le compteur calculé sur l'image réelle.
- **CA6** : couvert par tests (`ERR_DIGEST_REQUIRED` / acceptation avec digest) ; preuve brute sur hôte réel à rejouer avec CA4.
- **Corrections documentaires Confluence** (spec 5472268, ADR) : la copie du dépôt est déjà corrigée ; Confluence reste la source et doit être vérifiée par le PO (non accessible ici).

## 4. Écarts résiduels constatés (non corrigés : requalification, pas de commit de correction)

1. `scripts/distribution/engine_image_manager.py` l. 619 : `--target-digest` a pour valeur par défaut une empreinte de démonstration (`sha256:d8a5f82c…abcd`, 64 hex fantaisistes). Un appel sans variable d'environnement comparerait donc les hôtes à une référence fictive ; à remplacer par un échec explicite lorsque `ORSO_TARGET_ENGINE_DIGEST` est absent.
2. `.github/workflows/publish_orso_engine.yml` : déclenché sur `push` vers `main` et publie l'étiquette flottante `latest` ; le déclencheur de branche cite encore `KAN-64-execution-reelle-distribution`. À arbitrer par le PO (publication à chaque merge ? étiquette `latest` cohérente avec le refus du tag flottant ?).
3. Le test des empreintes de démonstration subsiste dans `tests/distribution/test_kan63_*` et `tests/olympe/test_lifecycle_manager.py` (usage de fixtures, sans impact production).

## 5. Recommandation

Requalifier KAN-64 : **le périmètre « code » est livré et vert ; le ticket se réduit à une passe d'exécution opérée par un humain** (workflow GitHub + commandes approuvées sur `prod-fr-003`), plus les deux écarts du §4. Aucune zone sanctuaire n'est concernée.
