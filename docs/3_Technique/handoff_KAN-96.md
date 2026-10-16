# Handoff KAN-96 — Statut commercial OPS : règle de choix de la ligne d'abonnement, origine lisible, écarts signalés

Branche : `KAN-96-auto` (aucun push, `main` intacte).

## Étape 0 — prémisse vérifiée

Le défaut existe toujours sur `main` (`c13b03698c`). Seuls les numéros de ligne cités au ticket ont dérivé :

| Ticket | Code actuel (avant correctif) |
|---|---|
| `olympe/ops_manager.py` l.749 : jointure `subscriptions(*)` non triée | l.1092 : `tenants?select=*,profiles(*),tenant_instances(*),agent_instances(*),subscriptions(*)` |
| l.822-823 : `subs[0]` | l.1165-1166 : `subs = t.get("subscriptions", []); sb_sub = subs[0] if subs else None` |
| `TenantsView.tsx` l.218-230 : « Client résilié » dès `canceled` | l.218-230 (inchangé) : `isChurn = t.status === "churn" \|\| subStatus === "canceled"` |
| l.2007-2015 : suspension conteneur sur `canceled/unpaid/past_due` | l.2413-2418 (inchangé, non modifié ici) |

## Ce qui a été fait

- **CA1** — règle écrite dans [`olympe/subscription_status.py`](../../olympe/subscription_status.py) : la ligne retenue est la plus récente par `created_at`, puis `updated_at`, puis `id` ; date absente ou illisible = la plus ancienne. Le résultat ne dépend plus de l'ordre de la base. La requête PostgREST n'est pas modifiée : le tri est fait en Python, donc testable.
- **CA2 / CA5** — `compute_divergences` produit, côté serveur, des mentions explicites rattachées à `subscription.divergences` :
  - client `active`/`trial` avec abonnement retenu annulé ;
  - client `churn` avec abonnement actif ;
  - conteneur en ligne alors que le client est annoncé résilié ;
  - conteneur en veille sur un client `active`/`trial` dont l'abonnement est `canceled`/`unpaid`/`past_due`.

  Elles s'affichent sous le statut commercial et sous l'état du conteneur dans `TenantsView.tsx`.
- **CA3** — `subscription.origin` expose la ligne retenue : id, `created_at`, `updated_at`, présence ou absence d'identifiants Stripe, nombre de lignes et répartition par statut, règle de sélection. L'écran affiche : « Ligne X · créée le … UTC · Stripe : aucun identifiant | identifiants enregistrés (…), existence non vérifiée ». **Aucun statut ni libellé propre à la recette n'est créé** : le libellé « Client résilié » est conservé, c'est sa cause qui devient lisible.
- Aucun fichier du sanctuaire touché (**CA6**).

### Fichiers touchés

- `olympe/subscription_status.py` (nouveau)
- `olympe/ops_manager.py` (import, sélection de la ligne, appel des divergences)
- `apps/ui-ops/src/types.ts`
- `apps/ui-ops/src/components/TenantsView.tsx`
- `tests/olympe/test_kan96_subscription_status.py` (nouveau)
- `docs/3_Technique/handoff_KAN-96.md` (ce fichier)

## Vérifications mécaniques

- `scripts/run_tests.sh tests/olympe/test_kan96_subscription_status.py tests/olympe/test_ops_manager.py tests/olympe/test_kan43_kan44_acceptance.py` : 31 passés, 0 échec, code retour 0.
- Preuve de rouge : avec l'ancien `ops_manager.py` (stash), 3 des 6 tests KAN-96 échouent ; ils repassent avec le correctif.
- `ruff check .` : « All checks passed! », code retour 0.
- `tsc --noEmit` sur `apps/ui-ops` : une seule erreur, `src/main.tsx` import `./index.css` (types Vite absents de l'environnement de vérification), sans lien avec les fichiers modifiés. Les types et `TenantsView.tsx` passent.

## Écart restant (CA4) — à écrire au ticket

Avec la règle « la plus récente par création », les deux clients de test **continuent d'afficher « Client résilié »** :

- `financia-solutions` : la ligne retenue est la 3ᵉ (créée le 03/10 à 15h27, `CANCELED`, sans identifiant Stripe), et non la ligne `ACTIVE` du 28/09. Le statut du client est `active` : l'écran affiche désormais l'écart, la ligne, sa date, l'absence d'identifiant Stripe et le conteneur « En ligne » en contradiction avec le statut résilié.
- `nexis-solutions` : la ligne `CANCELED` est la seule. Le client est `trial`, le conteneur est « En veille », et l'écran signale que la veille découle de l'annulation. Les identifiants Stripe sont « enregistrés, existence non vérifiée ».

Le statut ne devient donc pas « actif » : le correctif rend le doute visible et vérifiable. Le choix de la bonne ligne quand plusieurs coexistent relève de KAN-87 (hors périmètre).

## Ce qui reste / limites

- **Non vérifié ici** : les captures OPS avant/après (CA2, CA3, CA4, CA5) et la lecture de la base de production, car ces éléments se font sur l'environnement de production. Le test E2E reproduit les données du ticket avec un `_query_supabase` simulé.
- L'existence réelle des objets Stripe n'est pas interrogée à l'affichage : l'écran indique « identifiants enregistrés, existence non vérifiée ». Une vérification en direct (appel Stripe, par client ou à la demande) est un suivi possible.
- `apps/ui-ops/dist/` n'est pas reconstruit (`node_modules` absents ici) : à rebuilder au déploiement.
- Le récepteur d'événements Stripe qui suspend le conteneur sur `canceled/unpaid/past_due` n'est pas modifié (hors périmètre : KAN-87 / causes racines des écritures).
- Aucune suppression de client Stripe ni de facture n'existe dans ce code (`grep method="DELETE"` : seules des suppressions de lignes Supabase en sandbox) ; rien n'a été ajouté dans ce sens.

## À vérifier par le PO à la recette (production)

1. Dans le cockpit OPS, `financia-solutions` : mention d'écart sous « Client résilié », ligne retenue (3ᵉ), « Stripe : aucun identifiant », conteneur « En ligne » avec sa mention.
2. `nexis-solutions` : mention d'écart, ligne unique créée le 27/09, identifiants Stripe « enregistrés, existence non vérifiée », mention sur la veille.
3. Rechargement de la page deux fois de suite : mêmes lignes retenues.
4. Comparer l'id de ligne affiché avec la table `subscriptions` en base.
