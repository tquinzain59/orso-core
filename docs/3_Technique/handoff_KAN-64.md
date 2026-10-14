# Handoff KAN-64 — amendement du 12/10/2026 (deux écarts résiduels)

Branche : `KAN-64-ecarts`. Cette passe ne porte que les deux corrections arbitrées par Thibaut le 12/10.
L'exécution réelle (CA1 à CA6) reste une passe humaine séparée : **rien n'a été exécuté contre le registre ni contre prod-fr-003**.

## Étape 0 — prémisse vérifiée (avant modification)

```
$ grep -n "d8a5f82c\|target-digest" scripts/distribution/engine_image_manager.py
618:        "--target-digest",
619:        default=os.environ.get("ORSO_TARGET_ENGINE_DIGEST", "sha256:d8a5f82c448bb95b28a9b49b43e8b0b8c6e07eb4838a1f2987a123456789abcd"),
$ grep -n "latest" .github/workflows/publish_orso_engine.yml
57:            type=raw,value=latest
```
Les deux écarts existaient sur `main` (`c13b03698c`) : prémisse vraie, correction justifiée.

## Ce qui a été fait

| Fichier | Changement |
|---|---|
| `scripts/distribution/engine_image_manager.py` | Suppression de la valeur de démonstration. Le digest est résolu après parsing : option `--target-digest`, puis `ORSO_TARGET_ENGINE_DIGEST`. S'il est absent ou vide, `parser.error` renvoie le code 2 avec un message explicite. |
| `.github/workflows/publish_orso_engine.yml` | Retrait de `type=raw,value=latest`. Restent l'étiquette humaine `<version>-<sha>` et `release-<date>`, et le digest est affiché par l'étape « Output Immutable Digest ». |
| `tests/distribution/test_kan64_amendement_ecarts.py` | 3 tests de contrat (2 invariants, plus un contrôle du chemin heureux). |

Défaut trouvé et corrigé en cours de passe : avec le parent d'arguments commun, un `--target-digest` placé avant le sous-commande était écrasé par le défaut du sous-parseur. L'ancienne valeur de démonstration masquait ce défaut. L'option utilise désormais `argparse.SUPPRESS`.

Sanctuaire non touché (aucun fichier de `agent/turn_*`, `run_agent.py`, `hermes_state*`, `providers/`, `tools/registry.py`).

## Vérifications (sorties brutes résumées)

- `scripts/run_tests.sh tests/distribution/ tests/olympe/test_lifecycle_manager.py` : `4 files, 24 tests passed, 0 failed`, code retour 0.
- `ruff check scripts/distribution/engine_image_manager.py tests/distribution/test_kan64_amendement_ecarts.py` : `All checks passed!`, code retour 0.
- Rouge sur la base : avec les deux fichiers modifiés remis à l'état de `main` (git stash), `test_cli_fails_explicitly_without_target_digest` et `test_publish_workflow_has_no_floating_tag` échouent, puis passent avec la correction.
- `ruff format --check` : le nouveau test est conforme. `engine_image_manager.py` ne l'était déjà pas avant ce changement (style historique) et n'a volontairement pas été reformaté, pour garder un diff limité aux deux corrections.

## Non fait / non vérifiable

- **CA1 à CA6** : exécution réelle non rejouée. Il faut le workflow de publication lancé sur GitHub, le jeton `read:packages` sur l'hôte et l'approbation écrite de Thibaut pour chaque commande sur prod-fr-003.
- **Workflow non exécuté** : la suppression de `latest` est vérifiée statiquement (analyse YAML), pas par un run GitHub Actions. Condition de levée : un run de `publish_orso_engine.yml` dont la liste des étiquettes ne contient pas `latest`.
- **Usages résiduels de `orso-engine:latest`** hors périmètre de cette passe : `scripts/poc/execute_kan58_poc.py`, `execute_kan59_poc.py`, `execute_kan60_poc.py` et plusieurs tests, ainsi que `docs/3_Technique/kan58/59_e2e_poc_evidence.json`. Comme `latest` n'est plus publié, ces scripts POC ne résoudront plus d'image à jour. Ils sont à aligner dans un ticket suivant.
- **ADR 2026-09-30-04 et spécification Confluence** : non modifiés. La copie `docs/3_Technique/spec_kan63_*.md` est une copie générée et Confluence reste la source. La cohérence des deux textes avec le refus du tag flottant est à confirmer côté Confluence.
- Les empreintes de démonstration restent dans l'ADR, la spécification et les tests KAN-63 (valeurs d'exemple, non utilisées par le CLI).

## À vérifier à la recette (PO)

1. `python scripts/distribution/engine_image_manager.py audit --local` sans variable : code 2 et message demandant `ORSO_TARGET_ENGINE_DIGEST`.
2. Même commande avec `ORSO_TARGET_ENGINE_DIGEST=sha256:<64 hex>` ou `--target-digest` : le contrôle de digest est franchi.
3. Après le prochain run du workflow de publication : le paquet `orso-engine` ne porte plus l'étiquette `latest` pour cette publication, et le digest figure dans le log.
