# Politique de routage, plafonds de coût et repli par client — KAN-127

- **Rédigé le** : 2026-10-22 (arbitrages rendus le 2026-10-21 par Thibaut)
- **Statut** : rédigé et mécaniquement contrôlé ; **validation de Thibaut à porter en commentaire du ticket Jira KAN-127** (preuve CA1 — non produite par l'agent de développement).
- **Source de vérité machine** : [`config/orso_model_policy.yaml`](../../config/orso_model_policy.yaml)
- **Contrôle** : `python scripts/orso_model_policy_check.py validate`

## 1. Règles opposables

| # | Règle | Arbitrage | Où elle est tenue |
|---|---|---|---|
| R1 | Tout appel modèle passe par **OpenRouter** (`provider: openrouter`). | 21/10/2026 | `validate` sur `config/hermes*.yaml` ; écart de route tracé à l'exécution (`MODEL_POLICY_ROUTE_VIOLATION`) |
| R2 | **Aucun modèle local** (ollama, lmstudio, llama.cpp, vllm, `custom`, hôtes loopback/`host.docker.internal`). | 21/10/2026 | idem (`forbid_local`) |
| R3 | **Frugaux uniquement** : préfixes `deepseek/` et `mistralai/`. | 21/10/2026 | idem (`allowed_model_prefixes`) |
| R4 | Plafond **20 € / mois civil (UTC) / client**, configurable, surcharge par client. Alerte à 80 %, **blocage** à 100 %. | 21/10/2026 | plugin `orso-model-policy` |
| R5 | Indisponibilité du primaire ⇒ **bascule automatique** sur le frugal de secours, **client informé**. | 21/10/2026 | `fallback_model` (config) + plugin (trace + information) |

Clé d'API : désignée par son **emplacement** — variable `OPENROUTER_API_KEY`, déclarée dans `docker-compose.orso.yml`, valeur dans le `.env` de l'hôte. Aucune valeur n'apparaît dans le dépôt, le ticket ou ce document.

## 2. Modèles

| Rôle | Modèle OpenRouter |
|---|---|
| Primaire | `deepseek/deepseek-v4-flash` (inchangé, déjà dans `config/hermes.yaml`) |
| Secours | `mistralai/mistral-small-3.2-24b-instruct` |

> Constat de l'étape 0 : `fallback_model` valait `anthropic/claude-3-5-sonnet`, **non frugal et contraire à R3** ; il est corrigé dans `config/hermes.yaml` et `config/hermes.default.yaml`. L'identifiant exact du secours est à confirmer dans le catalogue OpenRouter à la recette (non vérifiable hors ligne).

## 3. Plafond de coût (R4)

- Coût de chaque appel estimé par le barème du moteur (`agent.usage_pricing`), cumulé en euros dans `<HERMES_HOME>/orso_model_policy/state.json`, trace datée dans `events.jsonl`.
- `usd_to_eur: 1.0` : borne haute prudente (1 USD compté 1 €) — on bloque plutôt trop tôt que trop tard. Barème inconnu pour un modèle ⇒ coût compté 0 et trace `MODEL_POLICY_COST_UNKNOWN` (voir limites).
- Surcharge par client : `cost_cap.clients.<ORSO_CLIENT_ID>.monthly_eur`.

| Seuil | Code | Effet observable |
|---|---|---|
| ≥ 80 % | `MODEL_POLICY_CAP_ALERT` | événement tracé + avertissement ajouté **une fois** à la réponse du client |
| ≥ 100 % | `MODEL_POLICY_CAP_BLOCKED` | la requête **n'est pas envoyée** au fournisseur ; le client reçoit un message portant le code ; événement tracé à chaque refus |

Le blocage passe par le middleware générique `llm_execution` (réponse synthétique chat-completions) : aucune modification de `providers/` ni de la boucle.

## 4. Repli (R5)

| Étape | Code | Trace / information |
|---|---|---|
| Erreur du primaire | `MODEL_POLICY_PRIMARY_UNAVAILABLE` | événement daté (code HTTP, motif) |
| Secours actif | `MODEL_POLICY_FALLBACK_ACTIVATED` | événement daté + avertissement dans le journal |
| Client informé | `MODEL_POLICY_CLIENT_INFORMED` | message ajouté à la réponse (`transform_llm_output`), une fois par session |

La bascule est exécutée par le mécanisme `fallback_model` du moteur (429/503/529) ; le plugin l'observe et l'annonce sans le réimplémenter.

## 5. Périmètre et limites connues

- Hors périmètre : sélection client (KAN-122), onglet consommation (KAN-123), token OpenRouter dédié (KAN-116), rotation des clés (KAN-53), chaîne interne, sandbox, observabilité de la boucle.
- Les appels **auxiliaires** (compression, titres…) sont aussi comptés et bloqués (ils passent par `llm_execution`).
- Un `api_mode` autre que `chat_completions` n'est pas bloquable sans toucher au moteur : il est laissé passer et tracé (il constitue de toute façon un écart R1).
- La route client (KAN-122) n'est pas contrainte par ce ticket : un modèle hors politique est **tracé** (`MODEL_POLICY_ROUTE_VIOLATION`), pas refusé.
- Les routeurs `hermes_cli/web_routers/local_models.py` (amont Hermès) existent encore ; R2 est tenue par la validation de config et la trace d'écart, pas par leur retrait (ce serait toucher au cœur).
