# Passation KAN-127 — politique de routage, plafonds de coût et repli par client

Date : 2026-10-22 — branche `KAN-127-modele-politique` (pas de push, `main` non touchée).

## Étape 0 — prémisse vérifiée

Le ticket affirme que routage/sélection sont couverts par Hermès et que **politique, plafond opposable, évaluation et repli ne sont portés par aucun ticket**. Vérifié sur le dépôt :

- Aucun module/doc/config de politique de modèle, de plafond par client ni d'évaluation (recherches `model_policy`, `cost_cap`, `plafond`, `politique de routage` : rien d'Orso).
- `hermes_cli/model_cost_guard.py` = simple confirmation « modèle cher » à la sélection, pas un plafond mensuel.
- Un repli existait (`fallback_model`) mais valait **`anthropic/claude-3-5-sonnet`** : non frugal, contraire à l'arbitrage. Constat aggravant, corrigé.

Prémisse vraie → traitement du ticket (pas de requalification).

## Ce qui a été fait (zone d'évolution uniquement)

| Fichier | Rôle |
|---|---|
| `config/orso_model_policy.yaml` | Politique machine : OpenRouter, pas de local, préfixes `deepseek/`+`mistralai/`, plafond 20 €/mois, alerte 80 %, secours |
| `plugins/orso-model-policy/` (`policy.py`, `ledger.py`, `__init__.py`, `plugin.yaml`) | Plafond (alerte puis blocage), registre/trace datés, repli observé + client informé |
| `config/hermes.yaml`, `config/hermes.default.yaml` | `fallback_model` → `mistralai/mistral-small-3.2-24b-instruct` ; `plugins.enabled: [orso-model-policy]` |
| `scripts/orso_model_policy_check.py` | `validate`, `simulate-cap`, `simulate-fallback`, `evaluate` |
| `tests/plugins/test_orso_model_policy.py` | 7 tests de contrat (vrai middleware, vrai transport, vrai `PluginManager`) |
| `docs/3_Technique/politique_routage_modeles_KAN-127.md` | Politique écrite et datée (CA1) |
| `docs/3_Technique/evaluation_modeles_KAN-127.md` | Protocole d'évaluation (CA4) — résultats à produire |

Aucun fichier du sanctuaire (`providers/`, `agent/turn_*`, `run_agent.py`, `conversation_loop.py`, `hermes_state*`, `tools/registry.py`) modifié. Le blocage et le repli utilisent les surfaces génériques de plugin (middleware `llm_execution`, hooks observateurs, `transform_llm_output`).

## État par critère

| CA | État | Preuve |
|---|---|---|
| CA1 | **Partiel** : document écrit/daté + `validate` vert. **Validation de Thibaut absente** (à poster en commentaire Jira). | `python scripts/orso_model_policy_check.py validate` → `CONFORME` |
| CA2 | **Prouvé en simulation** : seuil 20 €, alerte à 16,5 €, blocage à 20,5 € (requête non envoyée), codes `MODEL_POLICY_CAP_ALERT` / `MODEL_POLICY_CAP_BLOCKED`. | `... simulate-cap` → `ALERTE PUIS BLOCAGE OBSERVES` |
| CA3 | **Prouvé en simulation** (séquence de hooks) : primaire 503 → secours Mistral actif, trace datée, information client. | `... simulate-fallback` → `BASCULE TRACEE ET CLIENT INFORME` |
| CA4 | **Non clos** : protocole écrit, résultats non produits (aucune clé, dépense externe non autorisée). | `... evaluate` sans clé → code 2 `NON EXECUTE` |
| CA5 | Respecté : clé désignée par son emplacement (`OPENROUTER_API_KEY`, `.env` hôte). | recherche de motifs de clés : aucun |

## Reste à faire

1. **CA4** : lancer `evaluate` avec la clé hôte (commande dans le document), reporter le tableau, dater.
2. **CA1** : validation de Thibaut en commentaire du ticket.
3. **CA2/CA3 réels** : rejouer sur une instance de recette (coupure réelle d'OpenRouter / modèle primaire bloqué ; plafond abaissé pour provoquer le blocage).
4. Confirmer l'identifiant `mistralai/mistral-small-3.2-24b-instruct` dans le catalogue OpenRouter.

## Ce que le PO vérifie à la recette

- Déployer avec `./config` monté (la politique est lue dans `/app/config/orso_model_policy.yaml`) ; au démarrage, **aucune** ligne `MODEL_POLICY_NOT_LOADED` dans les logs (sinon le plugin est inactif — échec ouvert, signalé en `ERROR`).
- Abaisser `cost_cap.default_monthly_eur` (ex. 0,01) sur une instance de test, envoyer une requête : message `[MODEL_POLICY_CAP_BLOCKED]` côté client, ligne datée dans `<HERMES_HOME>/orso_model_policy/events.jsonl`, aucun appel facturé.
- Couper/limiter le primaire : réponse suffixée de `[MODEL_POLICY_FALLBACK_ACTIVATED]`, modèle de secours actif.

## Limites connues (non vérifiées / à connaître)

- Blocage **non testé contre la boucle réelle en streaming** : testé via la vraie chaîne middleware et le vrai transport chat-completions, pas via un tour d'agent complet. Réponse synthétique limitée à `api_mode: chat_completions`.
- Coût estimé via le barème du moteur (OpenRouter « estimé jusqu'à réconciliation ») ; modèle sans barème ⇒ coût 0 + trace `MODEL_POLICY_COST_UNKNOWN` (sous-comptage possible).
- Le cumul est par `HERMES_HOME` (un conteneur = un client) ; accès concurrents protégés par verrou fichier, pas par transaction.
- Un modèle hors politique choisi par le client (KAN-122) est tracé (`MODEL_POLICY_ROUTE_VIOLATION`), pas refusé.
- Les surfaces non liées au `fallback_model` (indisponibilité hors 429/503/529) suivent le comportement du moteur.
- Les routeurs `local_models` d'amont restent présents (non modifiables sans toucher au cœur).
- La suite complète de tests n'a pas été lancée (seul le fichier ajouté).
