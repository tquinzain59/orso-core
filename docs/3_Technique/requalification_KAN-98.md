# Requalification KAN-98 — la porte d'entrée est fermée, la campagne ne peut pas s'ouvrir

Date du constat : 17/10/2026. Branche : `KAN-98-auto`, au même commit que `main` (`d4557974fd`).
Aucune réinitialisation, aucune suppression et aucun accès à la base ou à Stripe n'ont été faits.

## Ce que le ticket affirme

1. La réinitialisation ne s'ouvre qu'une fois KAN-87, KAN-88 et KAN-96 fermés et vérifiés (verdicts signés).
2. Les causes sont encore là : lignes d'abonnement créées en local avant tout objet Stripe, statut commercial contradictoire.
3. Un contrat reste à écrire par le PO avant l'exécution : « une ligne d'abonnement naît d'un objet Stripe, ou elle ne naît pas ».

## Ce que le code fait réellement

### A. Les trois tickets de la porte ne sont pas sur HEAD

```
$ for c in fbc33bd478 0ba8852baf 58b6f26bbd a4d8367594; do git branch -a --contains $c; git merge-base --is-ancestor $c HEAD && echo "ANCESTOR OF HEAD" || echo "NOT in HEAD"; done
== fbc33bd478  (KAN-87 + KAN-88, feat)
  remotes/origin/KAN-87-88-abonnements-facturation
NOT in HEAD
== 0ba8852baf  (KAN-88)
  KAN-88-auto   remotes/origin/KAN-88-auto
NOT in HEAD
== 58b6f26bbd  (KAN-88, handoff)
  KAN-88-auto   remotes/origin/KAN-88-auto
NOT in HEAD
== a4d8367594  (KAN-96)
  KAN-96-auto   remotes/origin/KAN-96-auto
NOT in HEAD
```

Les correctifs existent sur des branches, aucun n'est fusionné. `git log --oneline main..KAN-96-auto` ne renvoie que `a4d8367594`. `main..KAN-88-auto` ne renvoie que `0ba8852baf` et `58b6f26bbd`. La branche `origin/KAN-87-88-abonnements-facturation` n'est pas fusionnable telle quelle : son diff contre `main` est `77 files changed, 1579 insertions(+), 11058 deletions(-)`, c'est-à-dire une base ancienne qui supprimerait des travaux récents. `KAN-88-auto` en est la reprise sélective (message de `58b6f26bbd` : « origine du cherry-pick »).

### B. Le correctif de KAN-87 (unicité de la ligne d'abonnement) est absent de HEAD

```
$ ls scripts/iam | grep -E "^1[0-9]_|rollback_10"
(aucune sortie)
$ git ls-tree -r --name-only origin/KAN-87-88-abonnements-facturation scripts/iam | grep rollback_10
scripts/iam/rollback_10_subscriptions_unique_active_and_audit.sql
$ grep -n -i unique scripts/iam/*.sql | grep -i -E "subscr|active"
(aucune sortie)
```

Sur HEAD, la dernière migration est `09_invoices_and_processed_events.sql`. Aucune contrainte d'unicité sur l'abonnement actif d'un client.

### C. Le défaut « local d'abord » est toujours présent

```
$ sed -n 2074,2079p olympe/ops_manager.py
                self._query_supabase("subscriptions", method="POST", payload={
                    "tenant_id": tenant_id,
                    "tier_id": "1_agent",
                    "status": "active" if is_container_ready else "pending_validation",
                    "stripe_customer_id": stripe_customer_id or f"cus_test_{tenant_slug}",
                    "stripe_subscription_id": f"sub_test_{tenant_slug}",
$ sed -n 2686,2691p olympe/ops_manager.py
                self._query_supabase("subscriptions", method="POST", payload={
                    "tenant_id": pending_tenant["id"],
                    "tier_id": "1_agent",
                    "status": "pending_validation",
                    "trial_days": 30,
```

`olympe/ops_manager.py` crée la ligne d'abonnement avant tout objet Stripe : avec un identifiant fabriqué (`sub_test_<slug>`) à la ligne 2074, avec un essai de 30 jours et sans identifiant à la ligne 2686. C'est exactement ce que le ticket décrit. Réinitialiser maintenant reproduirait le désordre.

### D. Les verdicts signés ne sont pas dans le dépôt

```
$ grep -rIl -E "KAN-(87|88|96)" docs | head
(aucune sortie : aucun document du dépôt ne mentionne ces tickets, donc aucun verdict)
```

CA1 repose sur Jira (statut des tickets, verdicts du PO selon le document 19 section 6). Ce n'est pas vérifiable depuis le dépôt.

## Conclusion

Porte fermée. La procédure du ticket interdit toute réinitialisation dans cet état. Par ailleurs, le contrat « une ligne naît d'un objet Stripe » n'est pas écrit (il revient au PO). Aucune correction de code n'a été produite : le périmètre de KAN-98 exclut la réparation des causes.

## Ce qui reste à faire (ordre imposé)

1. Fusionner `KAN-88-auto` et `KAN-96-auto` dans `main`. Pour KAN-87, reprendre `fbc33bd478` et `68bf4c59ab` par cherry-pick (pas de merge de la branche ancienne). Chaque ticket doit avoir son verdict signé.
2. Le PO écrit le contrat « une ligne d'abonnement naît d'un objet Stripe », l'architecte choisit le mécanisme. Cela touche `olympe/ops_manager.py` (lignes 2074 et 2686 ci-dessus) : il faut un ticket de réparation, il n'est pas dans KAN-98.
3. Le PO tranche le moment de la rotation vers l'architecte (question ouverte du 07/10).
4. Alors seulement : exécuter la procédure `docs/3_Technique/procedure_reinitialisation_base_client.md` (projet à valider).
