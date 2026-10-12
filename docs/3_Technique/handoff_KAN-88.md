# Handoff KAN-88 — support réel de la facturation et de l'idempotence du webhook Stripe

Branche : `KAN-88-auto` (non poussée par cette passe). Base : `c13b03698c` (= `main`).
Origine du code : `origin/KAN-88-auto` portait déjà le commit `0ba8852baf` (passe antérieure, absent de `main`) ;
cette passe l'a **récupéré par cherry-pick** (auteur préservé), relu et revalidé (voir « Revalidation »).
Le commit `fbc33bd478` (« [KAN-87][KAN-88] », Thibaut, 03/10, non fusionné) est une approche concurrente
(couplée à KAN-87 : `client_ui.py`, migration 10) : **non repris**, à arbitrer par Thibaut.
**Statut : livraison PARTIELLE.** Le code et la migration corrigée sont livrés et prouvés contre un
serveur PostgREST de test. **La production n'a pas été touchée** : aucun accès à la console Supabase
(condition d'entrée du ticket) ni aucune clé n'étaient disponibles. CA1 et CA2 ne sont donc **pas
validés en production**, et le SHA déployé ne peut pas être inscrit.

## Étape 0 — prémisse
Vérifiée dans le code (la mesure de production du PO n'est pas reproductible d'ici) :

- `scripts/iam/09_invoices_and_processed_events.sql` existe et crée les deux tables ; aucune autre migration ne les crée.
- `olympe/ops_manager.py` (`handle_stripe_webhook`) écrivait `invoices` et `processed_webhook_events` via `_query_supabase`,
  qui absorbe toute erreur et rend `None` (`except Exception … return None`), puis `except Exception: pass` /
  `_log.warning`. Un `PGRST205` ne remontait donc jamais ; la route rendait `processed`.
- La lecture d'idempotence `_query_supabase(...)` rendant `None` sur table absente, l'événement était retraité de bout en bout.

## Fichiers changés
| Fichier | Rôle |
|---|---|
| `olympe/ops_billing_store.py` (nouveau) | `supabase_request_strict` : lève `SupabaseStoreError` (statut HTTP + corps PostgREST). Sibling : `ops_manager.py` dépasse 2000 lignes. |
| `olympe/ops_manager.py` | `handle_stripe_webhook` : lecture d'idempotence, écriture facture (upsert `on_conflict=stripe_invoice_id`), écriture de la trace d'événement et persistance du compteur de rejeu passent par l'accès strict. Échec → `_fail_webhook` (log ERROR, livraison `failed`, audit `webhook:failed`, événement **non** mémorisé comme traité). |
| `olympe/server.py` | La route rend **HTTP 503** pour ces échecs (Stripe rejoue). Garde de signature inchangée. |
| `scripts/iam/09_invoices_and_processed_events.sql` | Relue : préconditions de dérive (`tenants.id` uuid, `profiles.tenant_id`), politique de lecture `TO authenticated`, `NOTIFY pgrst, 'reload schema'` (sans cela PGRST205 persiste après création). |
| `scripts/iam/09_invoices_and_processed_events_rollback.sql` (nouveau) | Retour arrière (destructif, avertissement en tête). |
| `scripts/iam/09_invoices_and_processed_events_purge_test_rows.sql` (nouveau) | Purge des seules lignes `evt_kan88_test_%` / `in_kan88_test_%`. |
| `scripts/iam/audit_supabase_write_targets.py` (nouveau) | Preuve CA4. |
| `tests/olympe/test_kan88_billing_persistence.py` (nouveau) | 5 tests d'invariants, HTTP réel contre un PostgREST de test ; 4/5 rouges sur la base, 5/5 verts après correctif. |

Aucun fichier du sanctuaire (`agent/turn_*`, `run_agent.py`, `hermes_state*`, `providers/`, `tools/registry.py`) modifié.

## Requête de relecture
1. Relire la migration 09 (préconditions, `TO authenticated`, `NOTIFY`) — **décision Thibaut** sur la question ouverte « telle quelle ou revue » : ici revue et corrigée.
2. Appliquer 09 en production (console Supabase, accès requis), puis rejouer la preuve CA1/CA2 contre la base réelle avec des lignes `evt_kan88_test_*`, puis les purger.
3. Valider que le 503 sur échec de support est le contrat voulu (Stripe rejoue ; la livraison n'est pas mémorisée).

## Preuves (serveur PostgREST de test — PAS la production)
Ruff : `ruff check olympe/ops_billing_store.py olympe/ops_manager.py olympe/server.py scripts/iam/audit_supabase_write_targets.py tests/olympe/test_kan88_billing_persistence.py` → `All checks passed!`, exit 0.

Tests : `scripts/run_tests.sh tests/olympe/test_kan88_billing_persistence.py tests/olympe/test_kan43_kan44_acceptance.py tests/olympe/test_drone_access.py tests/olympe/test_ops_manager.py` → `4 files, 40 tests passed, 0 failed`.
Sur `ops_manager.py`/`server.py` d'origine : `1 tests passed, 4 failed`.

**CA3** (tables absentes, requête signée HMAC ; sans en-tête → 400, garde intacte) :
```
503 {"status": "failed", "error": "IDEMPOTENCE_STORE_UNAVAILABLE", "event_id": "evt_kan88_test_raw1", ...,
 "detail": "Lecture de la trace d'idempotence impossible, événement non traité : GET processed_webhook_events -> HTTP 404: {\"code\": \"PGRST205\", \"message\": \"Could not find the table 'public.processed_webhook_events' in the schema cache\"}"}
ERROR:orso.olympe.ops:[WEBHOOK FAILED] IDEMPOTENCE_STORE_UNAVAILABLE : ...
```
**CA1/CA2** (tables présentes) :
```
livraison 1 -> 200 {"status": "processed", "event_id": "evt_kan88_test_raw1", "tenant_slug": "kan88-test-tenant", ...}
processed_webhook_events: [{"event_id": "evt_kan88_test_raw1", "status": "processed", "replay_count": 0, ...}]
invoices: [{"stripe_invoice_id": "in_kan88_test_raw1", "amount_ht": 100.0, "amount_ttc": 120.0, "status": "paid", ...}]
livraison 2 -> 200 {"status": "already_processed", "event_id": "evt_kan88_test_raw1", "replay_count": 1, ...}
processed_webhook_events: [{... "replay_count": 1, "last_replayed_at": "2026-10-11T23:05:40.404385+00:00"}]
```

## CA4 — NON atteint : trois autres tables absentes sont visées en écriture
`python scripts/iam/audit_supabase_write_targets.py` (exit 1), comparé aux tables servies relevées le 03/10 :
```
[ABSENTE] invoices                  olympe/ops_manager.py (webhook), scripts/iam/rollback_kan71.py:195
[ABSENTE] processed_webhook_events  olympe/ops_manager.py (webhook)
[ABSENTE] tenant_channels           hermes_cli/web_routers/client_ui.py:1089, :1141 ; rollback_kan71.py:191
[ABSENTE] tenant_integrations       hermes_cli/web_routers/client_ui.py:861 ; rollback_kan71.py:187
```
Les deux dernières sont créées par `scripts/iam/03_tenant_integrations_and_channels.sql`, également **non appliquée**
en production ; `client_ui.py` y écrit en absorbant l'erreur (`_log.debug`). Hors périmètre ici (autre migration,
autre route) : **à qualifier par un ticket dédié**, après application de 03. Les lignes `invoices`/`processed_webhook_events`
disparaîtront de la liste une fois la liste de référence mise à jour après application de 09.

Limite de l'outil : heuristique par fenêtre de texte ; il ne voit que les chemins `rest/v1/<table>`, `_query_supabase("<table>…")`
et `supabase_request_strict(...)`.

## Non vérifié
- État de production (avant/après), application de la migration, relecture PO, SHA/date de déploiement.
- Exécution réelle du SQL (aucun PostgreSQL disponible) : syntaxe relue, non jouée. Le `DO $$` et `NOTIFY` sont à valider à l'application.
- Concurrence : deux livraisons simultanées du même `event_id` — la seconde échoue sur la clé primaire (503) puis Stripe rejoue et obtient `already_processed`.

## Revalidation (passe du 2026-10-12, sur la branche `KAN-88-auto` après cherry-pick)
- `ruff check olympe/ops_billing_store.py olympe/ops_manager.py olympe/server.py scripts/iam/audit_supabase_write_targets.py tests/olympe/test_kan88_billing_persistence.py` → `All checks passed!`, exit 0.
- `scripts/run_tests.sh tests/olympe/test_kan88_billing_persistence.py tests/olympe/test_kan43_kan44_acceptance.py tests/olympe/test_drone_access.py tests/olympe/test_ops_manager.py tests/olympe/test_kan59_acceptance.py` → exit 0, 5 fichiers verts.
- `scripts/run_tests.sh tests/olympe/` → 1 rouge : `test_kan58_acceptance.py::test_kan58_dashboard_auth_strictly_required_no_fallback`
  (`FileNotFoundError: 'docker'`). **Préexistant et sans lien** : même échec sur `c13b03698c` (worktree propre), docker absent de cet hôte.
- `python scripts/iam/audit_supabase_write_targets.py` → exit 1, 4 tables visées en écriture et absentes de la liste du 03/10 :
  `invoices`, `processed_webhook_events` (couvertes par 09), `tenant_channels`, `tenant_integrations` (migration 03, hors périmètre → ticket dédié).
- Aucune clé Supabase dans l'environnement de cette passe : l'état de production (CA1 « avant », CA2 en production) n'a pas pu être relevé.
