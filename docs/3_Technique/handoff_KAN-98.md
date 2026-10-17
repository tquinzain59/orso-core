# Handoff KAN-98 — campagne de réinitialisation : bloquée à la porte d'entrée

Branche : `KAN-98-auto`. Passe documentaire uniquement : **rien n'a été exécuté contre la base client, Stripe ou un hôte**. Aucun code n'a changé.

## Étape 0 — prémisse vérifiée

La porte d'entrée n'est pas ouverte (détail brut dans [requalification_KAN-98.md](requalification_KAN-98.md)) :

```
$ git merge-base --is-ancestor <commit KAN-87/88/96> HEAD
fbc33bd478 (KAN-87+88) NOT in HEAD
0ba8852baf (KAN-88)    NOT in HEAD
a4d8367594 (KAN-96)    NOT in HEAD
```

`olympe/ops_manager.py` écrit toujours la ligne d'abonnement avant l'objet Stripe (lignes 2074 et 2686). La campagne ne peut donc pas s'ouvrir : la procédure du ticket l'interdit.

## Ce qui a été fait

| Fichier | Rôle |
|---|---|
| `docs/3_Technique/requalification_KAN-98.md` | Constat daté, commandes et sorties brutes, reste à faire. |
| `docs/3_Technique/procedure_reinitialisation_base_client.md` | Procédure avec la borne (interdiction dès la première facture de valeur comptable), archivage d'abord, grille d'acceptation. Projet à valider par le PO. |
| `docs/3_Technique/handoff_KAN-98.md` | Cette note. |

Fichiers touchés au total : ces trois fichiers de documentation. Aucun fichier du sanctuaire n'est modifié (CA6).

## Critères d'acceptation

- [ ] **CA1** — Non satisfait. KAN-87, KAN-88 et KAN-96 ne sont pas fusionnés dans `main`. Les verdicts signés sont dans Jira, non vérifiables depuis le dépôt.
- [ ] **CA2** — Non fait. Aucune archive n'a été produite, faute de porte ouverte et d'accès à la base.
- [ ] **CA3** — Non fait. Aucun client n'a été créé par le tunnel.
- [ ] **CA4** — Non fait. La grille n'est pas rejouée (grille vide dans la procédure, §5).
- [x] **CA5** — Borne écrite dans `procedure_reinitialisation_base_client.md` §1, statut « projet » en attente de validation du PO.
- [x] **CA6** — Aucun fichier du sanctuaire modifié ; liste des fichiers touchés ci-dessus.

## Vérification

- `ruff check scripts/iam` : `All checks passed!`, code retour 0. Cette commande n'est qu'une base de référence : aucun fichier Python n'a été modifié, donc `ruff` n'a rien de plus à contrôler.
- Aucun test lancé : aucun code n'a changé.

## Ce qui reste à faire

1. Fusionner KAN-88 (`KAN-88-auto`) et KAN-96 (`KAN-96-auto`). Pour KAN-87, reprendre `fbc33bd478` et `68bf4c59ab` par cherry-pick : la branche `origin/KAN-87-88-abonnements-facturation` repose sur une base ancienne (`77 files changed, 1579 insertions(+), 11058 deletions(-)` contre `main`) et supprimerait des travaux récents si on la fusionnait telle quelle. Obtenir les trois verdicts signés.
2. Le PO écrit le contrat « une ligne naît d'un objet Stripe » ; l'architecte décide du mécanisme. Cela demande un ticket de réparation sur `olympe/ops_manager.py`, hors KAN-98.
3. Thibaut tranche le moment de la rotation vers l'architecte (question ouverte du 07/10).
4. Exécuter la procédure, en passe humaine séparée, avec l'approbation écrite de Thibaut.

## À vérifier par le PO à la recette

- Valider ou amender le texte de la borne (§1 de la procédure), notamment la manière de distinguer un client de test d'un client réel.
- Confirmer que le périmètre du §3 est complet (par exemple les `auth.users` liés aux clients) et que la liste des tables archivées convient.
- Ne pas passer KAN-98 à Terminé : CA1 à CA4 sont ouverts.

## Non vérifiable ici

L'état réel de la base de production, les objets Stripe, le statut Jira des trois tickets et les verdicts signés.
