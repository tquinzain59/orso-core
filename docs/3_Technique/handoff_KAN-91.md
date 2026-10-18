# Handoff KAN-91 — alerte Stripe « intégration dépréciée »

- Branche : `KAN-91-auto` (pas de `push`, `main` non touchée).
- Résultat : **requalification, aucune correction de code.** Le dépôt `orso-core` n'émet aucun appel à l'API Charges, aucun jeton, aucune source en ligne. Rapport détaillé : [requalification_KAN-91.md](requalification_KAN-91.md).
- Ticket : **reste ouvert.** L'origine de l'alerte est hors de ce dépôt.

## Ce qui a été fait

1. Prémisse rejouée au HEAD courant (complément daté du 2026-10-18 dans le rapport) : aucun écart de code depuis l'analyse initiale `c13b03698c`.
2. Inventaire complet des appels `api.stripe.com` : trois fichiers, et non un seul comme l'affirme le ticket (`olympe/ops_manager.py`, `hermes_cli/web_routers/client_ui.py`, `scripts/iam/bootstrap_stripe_products.py`). Ressources touchées : `customers`, `subscriptions`, `setup_intents`, `payment_methods`, `invoices`, `billing_portal/sessions`, `products`, `prices`. Aucune ressource héritée, aucun champ `source` ni `default_source`.
3. Le chemin d'empreinte bancaire est déjà moderne (SetupIntent, puis `payment_methods/{id}/attach`, puis abonnement avec `default_payment_method`). Rien à réinventer.
4. Aucune interface de saisie de carte dans le dépôt (aucun Stripe.js, Elements ni `createToken`). C'est la piste n°1.
5. `STRIPE_TEST_SECRET_KEY` n'existe nulle part dans le dépôt : le code et les deux fichiers compose lisent `STRIPE_SECRET_KEY`.

## Fichiers changés

- `docs/3_Technique/requalification_KAN-91.md` (complément ajouté en fin de fichier)
- `docs/3_Technique/handoff_KAN-91.md` (ce fichier)

Aucun fichier de code modifié, sanctuaire intact.

## Relecture

```bash
git show --stat HEAD
git grep -nI 'api\.stripe\.com' -- . ':!website' ':!docs' ':!tests'
git grep -nIE 'v1/(charges|tokens|sources)|stripe\.(Charge|Token|Source)|createToken\(|createSource|payment_method_data|card\[(number|cvc|exp)' -- . ':!docs' ':!tests' ':!*package-lock.json' ':!uv.lock' ':!hermes_cli/tui_dist'
source .venv/bin/activate && ruff check olympe/ops_manager.py olympe/server.py hermes_cli/web_routers/client_ui.py scripts/iam/bootstrap_stripe_products.py
```

Résultat du `ruff check` : `All checks passed!`, code retour 0 (ruff 0.15.10).

## Statut des critères d'acceptation

| CA | Statut | Motif |
|---|---|---|
| CA1 | Couvert pour ce dépôt | Liste fichier:ligne et sorties brutes dans le rapport, aucun appel hérité. |
| CA2 | Partiel | Absence prouvée dans le dépôt. Origine non trouvée. Angles morts nommés au §5 du rapport. |
| CA3 | **Non vérifié** | Exige l'accès au serveur d'exploitation, au déploiement site/tunnel et à l'API Stripe. Aucune clef disponible, aucune ne doit entrer dans le dépôt. |
| CA4 | **Non vérifié** | Exige la lecture des abonnements dans chacun des deux comptes. |
| CA5 | **Non vérifié, sans objet** | Aucune correction livrée. À jouer après identification de la vraie source. |
| CA6 | **Non vérifié** | Exige la base de production et les deux comptes. |

SHA déployé et date : **sans objet**, rien n'est déployé.

## Ce qui reste à faire (hors dépôt)

1. Thibaut lit les abonnements dans les deux comptes (lecture seule) avant toute modification du tunnel : tranche CA4, CA6 et la question de financia-solutions.
2. Inspecter le serveur d'exploitation et le déploiement du site/tunnel (nom de variable, valeur masquée, composant, date), puis `GET /v1/account` pour obtenir l'identifiant de compte. Prendre l'identifiant depuis la console Stripe, pas depuis une image (O et 0 diffèrent dans le ticket).
3. Dans le tableau de bord du compte alerté, consulter le journal des requêtes et la page des API héritées pour identifier clef, endpoint et date des appels fautifs.
4. Trancher où vit le formulaire de carte (site, tunnel, plugiciel). S'il est externe, le migrer vers Elements + SetupIntent (le `client_secret` est déjà renvoyé par `olympe/ops_manager.py`) ou contacter l'éditeur.
5. Tolérance dans les politiques d'API : non recommandée. Si activée, la dater dans le ticket avec un ticket de fermeture lié.
6. Durcissement optionnel, non appliqué : rejeter explicitement dans `olympe/server.py` tout `payment_method_id` qui ne commence pas par `pm_`. À ouvrir en sous-ticket si le PO le souhaite.

## Décisions attendues de Thibaut

Deux comptes séparés ou un seul. Tolérance ou migration immédiate. Le formulaire de carte est-il dans un dépôt détenu. Aucune écriture sur le compte de production sans décision écrite.

## À vérifier à la recette (PO)

- Qu'un rejeu de paiement de test complet crée un SetupIntent/PaymentMethod `pm_…` et que le journal Stripe du compte utilisé ne montre aucune erreur de dépréciation (CA5), une fois la vraie source identifiée.
- Que les abonnements lus en base et ceux lus dans chaque compte Stripe concordent (CA6).
