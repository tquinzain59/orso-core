# Handoff KAN-131 — Tools : contrat par outil, authentification, permissions par rôle et dégradation

Branche : `KAN-131-tools-contrat`. Aucun `push`, `main` non touchée.

## Étape 0 — prémisse vérifiée (avant modification)

La prémisse du ticket est vraie : le catalogue Hermès existe (`tools/`, `toolsets.py`, `tools/registry.py`, `mcp_serve.py`, `optional-mcps/`) et il n'existe aucune couche de contrat, de permission par rôle/client, d'authentification imposée des outils externes ni de dégradation signalée.

```
$ grep -rIl -i "KAN-131\|tool_contract\|exposed_catalog\|catalogue expos" --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=.venv .
./cron/jobs.py ./tools/tool_search.py ./tests/...   # occurrences fortuites de « tool contract » (docstrings), aucune couche KAN-131
$ grep -n "role" hermes_cli/web_routers/client_ui.py   # rôles existants : superadmin / admin / user (l.1356-1412)
$ grep -h -A2 "^auth:" optional-mcps/*/manifest.yaml    # 54 oauth, 10 « type: none »
```

## Ce qui a été fait

| Fichier | Rôle |
|---|---|
| `plugins/orso-tool-contracts/catalog.yaml` | Catalogue exposé v1.0.0 daté du 2026-10-22 : contrat (entrées, sorties, erreurs), version, `min_role`, `clients`, repli par outil ; serveurs externes avec `secret_ref` (emplacement). |
| `plugins/orso-tool-contracts/contracts.py` | Chargement, validation (refus d'un outil système, de `auth: none`, de secret en clair), résolution, contrôle de dérive contre le registre vivant. |
| `plugins/orso-tool-contracts/secret_refs.py` | Secrets désignés par emplacement (`env:NOM`, `file:chemin` sous `HERMES_HOME`), authentification externe, détection de secret en clair (chemins rapportés, jamais les valeurs). |
| `plugins/orso-tool-contracts/guard.py` | Décision : exposition → rôle → client → authentification externe → disponibilité ; dégradation définie et trace JSONL `logs/tool_contracts.jsonl` (sans arguments d'outil). |
| `plugins/orso-tool-contracts/__init__.py`, `plugin.yaml` | Hook générique `pre_tool_call`, fail-closed. Aucun fichier du moteur modifié. |
| `hermes_cli/web_routers/tool_caller.py` | Liaison session → (rôle, client), rôle inconnu = `user` (moindre privilège). |
| `hermes_cli/web_routers/client_ui.py` | +6 lignes dans `client_chat_endpoint` : liaison du rôle (`_resolve_user_system_role_and_job_title`) et du tenant à la session. |
| `scripts/orso_tool_contracts.py` | Commandes de preuve : `catalog`, `contract`, `check`, `auth`, `secrets`, `verify`. |
| `tests/plugins/test_orso_tool_contracts.py` | 26 tests de comportement dont un parcours réel (activation par config, `PluginManager`, hook `pre_tool_call`). |

Sanctuaire non touché (`agent/turn_*`, `run_agent.py`, `hermes_state*`, `providers/`, `tools/registry.py`).

## Preuves (CA1 à CA5), sorties brutes résumées

- **CA1** — `scripts/orso_tool_contracts.py catalog` : catalogue v1.0.0 daté 2026-10-22, 7 entrées. `contract feishu_doc_read` affiche entrées/sorties/erreurs ; `contract terminal` → `TOOL_NOT_EXPOSED`, rc=3. `verify` → `outils système dans le catalogue exposé : []`, `0 erreur(s)`, rc=0.
- **CA2** — `auth --server notion` avec `mcp-tokens/notion.json` provisionné : `ACCEPTÉ OK … (secret désigné par file:mcp-tokens/notion.json)`, rc=0. Sans le fichier : `REFUSÉ AUTH_REFUSED … secret absent`, rc=3. `auth --manifest optional-mcps/wolfram/manifest.yaml` : `REFUSÉ … sans authentification`, rc=3.
- **CA3** — `check --tool messages_send --role user` : `REFUSÉ ROLE_FORBIDDEN`, rc=3 ; `--role admin` : `AUTORISÉ OK`, rc=0 ; `check --tool terminal --role superadmin` : `TOOL_NOT_EXPOSED`.
- **CA4** — avec `orso_tool_contracts.unavailable: [messages_read]` dans `config.yaml` : `REFUSÉ TOOL_UNAVAILABLE`, message de repli défini, ligne dans `logs/tool_contracts.jsonl` (`"event": "TOOL_UNAVAILABLE", "reason": "outil coupé par l'opérateur"`).
- **CA5** — `secrets` : `secret de 'notion' désigné par emplacement : file:mcp-tokens/notion.json`, `secrets en clair dans le catalogue : 0`, rc=0.

Contrôles mécaniques :
- `ruff check plugins/orso-tool-contracts hermes_cli/web_routers/tool_caller.py scripts/orso_tool_contracts.py tests/plugins/test_orso_tool_contracts.py hermes_cli/web_routers/client_ui.py` → `All checks passed!`, rc=0.
- `scripts/run_tests.sh tests/plugins/test_orso_tool_contracts.py` → `1 files, 26 tests passed, 0 failed`.
- Rouge prouvé : avec le contrôle de rôle neutralisé dans `guard.py`, `test_user_cannot_call_admin_tool_but_admin_can` et `test_hook_enforces_via_real_plugin_discovery` échouent.
- Non-régression routeur : `tests/hermes_cli/test_client_ui*.py`, `test_client_chat_*` → 44 passés, 7 échecs **identiques avec et sans ma modification** (`ModuleNotFoundError: requests` : dépendance absente de ce `.venv`). Non imputables à KAN-131.

## Non fait / à décider (honnêteté)

1. **Activation non livrée** : le plugin est opt-in. À activer par `plugins.enabled: [orso-tool-contracts]` dans la config du déploiement ; je n'ai pas modifié `config/hermes.yaml`. Tant qu'il n'est pas activé, la garde est inactive en production.
2. **Surface `mcp_serve.py` (messagerie) non gardée au runtime** : ses outils (`messages_send`, …) ne passent pas par `pre_tool_call`. Le contrat et la décision (`check`) les couvrent, mais l'enforcement runtime exigerait de toucher `mcp_serve.py` ou de l'encapsuler : à arbitrer (hors périmètre « marge »).
3. **Catégorie `calcul` : lacune réelle.** Aucun outil de calcul natif dans Hermès ; le candidat `wolfram` est anonyme (`auth: none`) donc refusé par la règle CA2. Le catalogue le signale (`[LACUNE]`). Décision PO requise (outil à authentifier ou à développer).
4. **Catégorie `documents`** : les seuls outils natifs sont Feishu/Lark. Sans Feishu configuré, `check_fn` est faux et l'appel dégrade (comportement constaté, CA4). Confirmer que Feishu est la bonne cible, sinon documents = serveurs MCP authentifiés (Notion déclaré).
5. **Outils MCP externes** : contrat au niveau serveur (schéma publié par le serveur, noms réels non figés car dépendants du serveur). Un contrat par outil MCP suppose de figer les schémas distants.
6. **Rôle** : lu depuis les claims JWT (`auth`), comme les garde-fous admin existants de `client_ui`, sans le profil Supabase. **Permissions par client** : liste `clients` par outil, valeur par défaut `*` ; aucun client restreint dans le catalogue livré. Le client = `tenant_id` de la session.
7. Test E2E avec un vrai `AIAgent` + modèle non exécuté (aucune clé, dépendances manquantes). Le parcours réel testé s'arrête au hook `pre_tool_call` du moteur.
8. `ruff --select F` sur `client_ui.py` signale 9 avertissements préexistants (identiques avant/après).

## À vérifier à la recette (PO)

1. `python scripts/orso_tool_contracts.py catalog` puis `contract <outil>` : le sous-ensemble métier retenu (documents, messagerie) est-il le bon ? Arbitrer calcul (point 3) et documents (point 4).
2. Rôles : `messages_send` et `feishu_drive_add_comment` réservés à `admin` ; les autres entrées à `user`. Valider ce partage.
3. Activer le plugin sur un environnement de recette, appeler `/api/client/chat` avec un compte `user`, déclencher un outil admin : réponse `ROLE_FORBIDDEN`, trace dans `logs/tool_contracts.jsonl`.
4. Décider de l'enforcement de `mcp_serve` (point 2).
