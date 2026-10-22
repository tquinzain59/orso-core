# Note de passation — KAN-128 : observabilité et reprise de l'exécution exposées au client

Branche : `KAN-128-harness-observabilite` (non poussée, `main` non touchée).

## Étape 0 — Prémisse vérifiée (elle tient, donc pas de requalification)

| Affirmation du ticket | Constat sur le dépôt | Commande |
|---|---|---|
| 28 phases `agent/turn_*.py` | 28 fichiers | `ls agent/turn_*.py \| wc -l` → `28` |
| `run_agent.py`, `conversation_loop.py` | `run_agent.py` à la racine ; `conversation_loop.py` est dans `agent/` | `ls run_agent.py agent/conversation_loop.py` |
| Aucune observabilité client des exécutions | Aucun module de trace ni de rejeu côté client | `grep -rIl -i -E "KAN-107\|execution_trace\|client_trace\|run_trace" .` → seul `olympe/ops_manager.py` (simple mention du « journal d'activité » dans un prompt) |
| KAN-107 (journal métier) | Aucun code KAN-107 dans ce dépôt | idem |

## Ce qui a été fait (zone d'évolution uniquement)

- `hermes_cli/web_routers/client_run_traces.py` (nouveau) : stockage SQLite (`client_run_traces.db`, à côté de `client_chat_sessions.db`), `RunRecorder`, vue client en liste blanche, routes `GET /api/client/runs`, `/api/client/runs/{trace_id}`, `/api/client/runs/{trace_id}/artifacts/{name}`, rétention 30 j + purge, `scrub_secrets`, `read_internal_diagnostics` (cockpit).
- `hermes_cli/web_routers/client_run_replay.py` (nouveau) : `run_with_replay` — 2 rejeux automatiques max (3 tentatives), pauses 1 s puis 3 s.
- `hermes_cli/web_routers/client_ui.py` (modifié) : le générateur SSE accepte une `trace` ; l'appel `AIAgent` passe par `run_with_replay` ; événements SSE `run_retry` et `run_failed` ; `trace_id` ajouté aux événements `start` et `done` ; montage du routeur.
- `tests/hermes_cli/test_client_run_traces_kan128.py` : 16 tests, un ou plusieurs par critère.
- Aucun fichier du sanctuaire modifié (`agent/turn_*`, `run_agent.py`, `hermes_state*`, `providers/`, `tools/registry.py`).

## Frontière client / cockpit (CA3)

- **Client** : `trace_id` (poignée opaque), agent, statut, dates ISO UTC, nombre de rejeux, message d'échec, étapes (libellés d'un **catalogue fermé** de 6 étapes ; une étape hors catalogue lève `ValueError`), artefacts (`reponse.txt`, `carte_action.json`).
- **Cockpit uniquement** (table `client_run_internal`, jamais lue par le routeur) : classe et message d'erreur par tentative. Lecture par `read_internal_diagnostics(trace_id)`.
- **Jamais dans une trace client** : tenant, utilisateur, session, modèle/fournisseur, outils, erreurs techniques.
- **Frontière KAN-107** : ces traces décrivent le déroulé technique de haut niveau ; le journal métier (actions à effet visible) reste à KAN-107. Le texte miroir côté KAN-107 reste à écrire.

## Preuves (commande → sortie brute)

```
$ ruff check hermes_cli/web_routers/client_ui.py hermes_cli/web_routers/client_run_traces.py hermes_cli/web_routers/client_run_replay.py tests/hermes_cli/test_client_run_traces_kan128.py
All checks passed!
rc ruff=0
$ ruff check .
All checks passed!
rc ruff .=0
$ scripts/run_tests.sh tests/hermes_cli/test_client_run_traces_kan128.py -v
=== Summary: 1 files, 16 tests passed, 0 failed (100% complete) in 7.4s (8 workers) ===
```

| CA | Tests |
|---|---|
| CA1 | `test_ca1_run_produces_dated_high_level_trace_with_artifacts`, `test_ca1_action_card_is_an_artifact` |
| CA2 | `test_ca2_transient_failure_is_replayed_without_client_alert`, `test_ca2_persistent_failure_is_replayed_then_reported_to_client`, `test_ca2_failed_runs_filterable_by_status`, `test_replay_*` |
| CA3 | `test_ca3_client_trace_contains_nothing_internal`, `..._closed_whitelist`, `..._step_outside_client_catalog_is_refused`, `..._isolated_per_user_and_tenant` |
| CA4 | `test_ca4_trace_readable_before_30_days_absent_after`, `test_ca4_purge_physically_deletes_every_table` |
| CA5 | `test_ca5_secrets_are_designated_by_location_never_in_clear` (inclut une recherche dans les octets du fichier `.db`), `..._internal_diagnostics_are_scrubbed_too` |

Rebase (cherry-pick sur `origin/main` incluant KAN-127 et KAN-131) : conflit unique dans `client_ui.py`, `client_chat_endpoint`. Les deux ajouts sont indépendants et ont été conservés : `bind_tool_caller` (KAN-131), puis `RunRecorder` (KAN-128). Après résolution : `ruff check .` rc=0 ; 16 tests KAN-128 et 26 tests `test_orso_tool_contracts.py` passent. Sur les tests client voisins (`test_client_ui`, `kan83`, `kan84`, `kan85`, `kan86`), les mêmes 8 tests échouent sur la base `HEAD` sans KAN-128 (83 passés) et avec KAN-128 (99 passés dont 16 nouveaux et 26 du plugin) : cause d'environnement (`requests` absent du `.venv`).

Non-régression (avant rebase) : sur les 8 fichiers de tests client voisins (`test_client_*`), **8 tests échouent à l'identique avant et après** ce ticket (70 passés dans les deux cas). Ils échouent pour une cause d'environnement (`httpx`/`requests` absents du `.venv`), pas pour une cause liée à KAN-128.

## Ce qui reste / limites connues

1. **Moteur simulé.** Les tests simulent `run_agent.AIAgent` (le `.venv` n'a pas `httpx`) : le rejeu n'a pas été exercé contre le vrai moteur ni un vrai fournisseur.
2. **Doublons dans `state.db` possibles au rejeu.** Une tentative échouée peut déjà avoir écrit des messages dans `SessionDB` ; le rejeu repart de l'historique chargé avant la 1re tentative (contexte modèle propre) mais la base peut contenir des doublons. Le corriger demanderait de toucher au sanctuaire : **non fait**.
3. **Mode résilient conservé.** Après un échec persistant, le comportement existant (réponses de repli scénarisées) s'exécute toujours, après l'événement `run_failed`. À arbitrer : afficher ces réponses de repli après un signalement d'échec est ambigu pour le client.
4. **Interface client non branchée.** `apps/ui-client` n'écoute pas encore `run_retry`/`run_failed` ni ne consomme `/api/client/runs` (aucune modification front dans ce ticket).
5. **Trace « running » orpheline** si le client coupe la connexion en plein flux (pas de clôture) ; elle sera purgée à 30 jours.
6. **Cockpit** : `read_internal_diagnostics` existe mais n'est pas encore exposé dans `ops.py`.
7. **Hors périmètre non couvert** : échecs hors chemin chat client (cron, gateway messagerie).

## À vérifier à la recette (PO)

- Nombre de rejeux (2) et pauses (1 s / 3 s) : valeurs de produit proposées, non arbitrées par le ticket (`client_run_replay.py`).
- Libellés des 6 étapes et message d'échec (`STEP_CATALOG`, `FAILURE_NOTICE`) : validation rédactionnelle.
- Avec le vrai moteur : couper le fournisseur de modèle, envoyer un message, constater 2 `run_retry` puis `run_failed`, puis consulter `GET /api/client/runs/{trace_id}` avec le jeton du client.
- Contrôler qu'un autre utilisateur obtient `404` sur cette trace.
- Aucun secret : inspecter `client_run_traces.db` (`strings`) après un échec réel.
