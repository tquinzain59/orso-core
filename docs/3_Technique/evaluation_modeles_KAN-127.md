# Évaluation comparative des modèles frugaux autorisés — KAN-127 (CA4)

- **Protocole rédigé le** : 2026-10-22
- **Statut des résultats** : ⚠️ **NON PRODUITS** — l'exécution exige un appel réel à OpenRouter avec la clé `OPENROUTER_API_KEY` (emplacement : `.env` de l'hôte). Elle n'a pas été lancée par l'agent de développement (aucune clé fournie pour cette tâche, dépense externe non autorisée). **CA4 n'est donc pas clos** : il reste une commande à exécuter (§4).
- **Candidats** (`evaluation.candidates` de [`config/orso_model_policy.yaml`](../../config/orso_model_policy.yaml)) : `deepseek/deepseek-v4-flash` (primaire), `deepseek/deepseek-v3-0324`, `mistralai/mistral-small-3.2-24b-instruct` (secours). Seuls DeepSeek et Mistral sont éligibles (R3).

## 1. Protocole

- Route : OpenRouter, `temperature: 0`, `max_tokens: 400`, 1 exécution par cas et par modèle, mêmes prompts pour tous (définis dans `EVAL_CASES` de `scripts/orso_model_policy_check.py`).
- Cinq cas du métier recouvrement TPE/PME (français) :

| Cas | Ce qui est mesuré | Critères automatiques |
|---|---|---|
| `indemnite_recouvrement` | exactitude factuelle (indemnité forfaitaire de 40 €) | « 40 » présent, ≤ 60 mots |
| `somme_factures` | calcul (1250,40 + 480,10 + 99,50 = 1830,00) | total exact, ≤ 80 mots |
| `extraction_json` | extraction structurée | JSON valide, client/montant/échéance exacts |
| `relance_courtoise` | rédaction contrainte | n° de facture, montant, art. L.441-10 cités, ≤ 150 mots |
| `langue_francaise` | respect de la langue et de la consigne | termes anglais absents |

- Mesures par appel : score (critères réussis/total), latence, jetons, coût (`usage.cost` d'OpenRouter).
- Verdict par modèle : nombre de cas **entièrement** réussis sur 5 ; à égalité, le coût moyen le plus bas puis la latence.
- Limites assumées : échantillon de 5 cas, 1 passage (non-déterminisme résiduel malgré `temperature: 0`), critères lexicaux. Cette évaluation oriente le choix primaire/secours ; elle ne remplace pas un banc de qualité complet.

## 2. Résultats

| Modèle | Cas réussis | Coût total (USD) | Latence moy. (s) |
|---|---|---|---|
| `deepseek/deepseek-v4-flash` | _à produire_ | _à produire_ | _à produire_ |
| `deepseek/deepseek-v3-0324` | _à produire_ | _à produire_ | _à produire_ |
| `mistralai/mistral-small-3.2-24b-instruct` | _à produire_ | _à produire_ | _à produire_ |

## 3. Décision

Le couple primaire/secours posé (DeepSeek V4 Flash / Mistral Small 3.2) reprend la configuration existante et l'arbitrage du 21/10/2026 ; il reste **à confirmer** par les résultats du §2.

## 4. Exécuter l'évaluation

```bash
# La clé est lue dans l'environnement, jamais affichée ni écrite.
set -a; . ./.env; set +a     # .env hôte contenant OPENROUTER_API_KEY
python scripts/orso_model_policy_check.py evaluate
# -> docs/3_Technique/evaluation_modeles_KAN-127_resultats.json (daté, `executed_at`)
```

Reporter ensuite le tableau du §2 et dater ce document. Sans clé, la commande sort en code 2 (`NON EXECUTE`).
