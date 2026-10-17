# Requalification KAN-108 — programme partenaire cabinets d'expertise comptable

Date de la passe : 17/10/2026. Branche : `KAN-108-auto` (base `main` à `d4557974fd`).
Résultat : aucune modification de code. Le ticket n'est pas exécutable en l'état. Ce rapport remplace le handoff.

## Ce que le ticket affirme

- La page `https://www.orso-agents.fr/experts-comptables.html` répond 404 (constat du 07/10/2026).
- Une page de ce nom avait été créée le 08/09 puis supprimée par un revert.
- Le sujet est hors du POC d'architecture (document 27, épique KAN-62) et ne doit consommer aucune ressource avant la validation de l'architecture.
- Taux de commission, assiette, durée, exclusivité, remise ou marque blanche relèvent de la politique commerciale : décision de Thibaut, jamais du PO.
- Le ticket est volontairement « pas prêt » (étiquette prêt absente) et trois arbitrages restent ouverts.
- Aucune prise de contact avec les cabinets avant l'arbitrage de Thibaut.

## Ce que le code et l'environnement montrent

La prémisse factuelle est encore vraie, mais elle ne rend pas le ticket actionnable.

Commande :

```
curl -s -o /dev/null -m 15 -w "%{http_code}\n" https://www.orso-agents.fr/experts-comptables.html
```

Sortie brute :

```
404
```

En-têtes (`curl -sI`), début de sortie : `HTTP/2 404`, `content-type: text/plain; charset=utf-8`, `server: Vercel`.

Dans le dépôt :

- `git log --all -S"experts-comptables"` ne retourne qu'un commit, `bca02bd6ae` (KAN-26 et KAN-27, IAM Supabase). Il ne porte pas de page partenaire.
- Le journal des réalisations (`docs/21_journal_realisations_orso.md`, ligne 180) confirme que `experts-comptables.html` a été créée sans validation formelle du dirigeant, puis annulée. La section 7.3 impose de ne pas la reprendre à l'identique.
- Le site vitrine n'est pas dans `orso-core`. Aucun fichier de la page, aucun gabarit et aucun mécanisme de déploiement de la vitrine n'y figurent. CA2 ne peut pas être traité depuis ce dépôt.
- Les documents 12, 13, 14, 15 et 27 cités par le ticket ne sont pas dans le dépôt (seuls `feuille_de_route.md` et `vision_et_objectifs.md` y sont). Ils sont sur Confluence. Je n'y ai pas accès.
- Aucun routeur de `hermes_cli/web_routers/` ni aucun module ne porte de notion de cabinet ou de partenaire. CA4 demanderait un nouveau modèle de données, qui serait spéculatif sans l'assiette et le mode de versement arrêtés.
- L'architecture n'est pas validée : la spec KAN-64 est amendée (écarts du 12/10), et son handoff indique que l'exécution réelle (CA1 à CA6) reste une passe humaine séparée, jamais rejouée à ce jour.

## Pourquoi je n'ai pas produit de livrable

Chaque critère d'acceptation touche à un point que le ticket réserve explicitement.

- CA1 (offre chiffrée) : taux, assiette, durée et versement sont des décisions de Thibaut. Les écrire reviendrait à inventer la politique commerciale. La fourchette de 15 à 20 % du document 12 est une hypothèse de travail, pas une décision.
- CA2 (page publique) : hors dépôt, et la publier avant l'arbitrage reproduirait l'incident du 08/09 qui a justifié les reverts.
- CA3 (convention type relue par un tiers) : la relecture par un tiers ne peut pas être produite par un agent. Un texte non relu ne satisfait pas le critère.
- CA4 (rattachement mesurable sur un client de test) : dépend de l'assiette de commission, donc de CA1. Il faudrait aussi ne pas toucher à la persistance du sanctuaire, ce qui impose de passer par un routeur ou un profil dont la forme dépend de l'arbitrage.
- Contrainte de calendrier : le ticket reste en attente tant que l'architecture n'est pas validée (KAN-62 à KAN-66).

## Ce qui reste à faire (ordre proposé)

1. Valider l'architecture (KAN-62 à KAN-66), puis lever l'attente du ticket.
2. Thibaut arbitre : forme (commission sur abonnement, remise ou marque blanche), taux, durée, assiette, versement, exclusivité, calendrier. Tenir compte de l'avance de GetBill et INNEST (document 13, alerte 2).
3. Rédiger l'offre sur Confluence, datée, avec la validation de Thibaut en commentaire du ticket (CA1).
4. Faire rédiger puis relire par un tiers la convention type, avec les exigences d'indépendance et de transparence propres à la profession (CA3).
5. Définir où vit la page publique (dépôt de la vitrine, hors `orso-core`), la publier avec un contact dédié, et prouver le 200 par curl plus lecture du code servi (CA2).
6. Concevoir le rattachement client vers cabinet dans la Zone d'Évolution (routeur `hermes_cli/web_routers/` ou module de profils), lisible par l'exploitation. Le mesurer sur un client de test (CA4).
7. Ajouter l'entrée au journal des réalisations (document 21) uniquement quand les quatre critères sont tenus.

## Passation au PO

- Aucune action n'a été menée vers des cabinets, aucun fichier de page ou de convention n'a été créé.
- Ne pas passer le ticket à « prêt » tant que les trois arbitrages ne sont pas rendus.
- Aucune vérification `ruff` n'est applicable : aucun fichier Python n'a été modifié.
- Sanctuaire non touché. Pas de `git push`, `main` non touchée.
